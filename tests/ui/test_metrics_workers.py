"""Audit 6.3.1 — honesty of the raw metrics workers (D2/D3), no real PVE.

D2: HealthCheckWorker must not report "healthy" when a mandatory check
    (services / subscription / updates) could not be read; an unreadable
    check is surfaced, successful parts are kept, and "unknown" is not
    turned into a broken service.
D3: HostSnapshotsWorker / StorageDisksWorker must not swallow per-VM
    failures — a failed guest is unverified, not "has no snapshots /
    disks", and neighbouring results survive.
"""
from __future__ import annotations

from types import SimpleNamespace

from virtdeck.ui.api import metrics as m

_CFG = {"host": "10.0.0.1", "user": "u@pam", "token_name": "t",
        "token_value": "s", "proxy": ""}


class _Resp:
    def __init__(self, data, status=200, omit_data=False):
        self._data = data
        self._omit = omit_data
        self.status_code = status
        self.reason = "OK" if status < 400 else "Error"
        self.ok = status < 400

    def json(self):
        if self._omit:
            return {}
        return {"data": self._data}


def _fail(status=500):
    return _Resp({"message": "boom"}, status=status)


class _FakeSession:
    verify = None

    def __init__(self, handler):
        self._handler = handler

    def get(self, url, **kw):
        out = self._handler(url)
        if isinstance(out, Exception):
            raise out
        return out

    def close(self):
        pass


def _install(monkeypatch, handler):
    monkeypatch.setattr(
        m, "build_requests_session", lambda cfg: _FakeSession(handler))


def _collect(signal, worker):
    out = []
    signal.connect(lambda *args: out.append(args))
    worker.run()
    return out


def _vm(vmid):
    return SimpleNamespace(vmid=vmid, node="n1", name=f"vm{vmid}",
                           vm_type=SimpleNamespace(value="qemu"),
                           host_name="h1")


# ----------------------------------------------------------------------
# D2 — HealthCheckWorker
# ----------------------------------------------------------------------

def _health_handler(services=None, subscription=None, updates=None):
    def handler(url):
        if url.endswith("/services"):
            out = services if services is not None else _Resp([])
        elif url.endswith("/subscription"):
            out = subscription if subscription is not None else _Resp({})
        elif url.endswith("/apt/update"):
            out = updates if updates is not None else _Resp([])
        else:
            out = _Resp([])
        if isinstance(out, Exception):
            raise out
        return out
    return handler


def _run_health(monkeypatch, **checks):
    _install(monkeypatch, _health_handler(**checks))
    worker = m.HealthCheckWorker(_CFG, "n1")
    out = _collect(worker.signals.health_ready, worker)
    assert len(out) == 1
    return out[0][1]  # health dict


class TestHealthHonestyD2:
    def test_all_checks_ok_is_healthy(self, monkeypatch):
        health = _run_health(
            monkeypatch,
            services=_Resp([{"name": "pvedaemon", "state": "running"}]),
            subscription=_Resp({"status": "active"}),
            updates=_Resp([]),
        )
        assert health["status"] == "healthy"
        assert health["issues"] == []
        assert health["warnings"] == []
        assert health["unavailable"] == []

    def test_broken_service_is_critical(self, monkeypatch):
        health = _run_health(
            monkeypatch,
            services=_Resp([{"name": "pveproxy", "state": "stopped"}]),
        )
        assert health["status"] == "critical"
        assert health["issues"]
        assert health["unavailable"] == []

    def test_expired_subscription_is_critical(self, monkeypatch):
        health = _run_health(
            monkeypatch, subscription=_Resp({"status": "expired"}))
        assert health["status"] == "critical"
        assert any("expired" in i for i in health["issues"])

    def test_services_unreadable_is_not_healthy(self, monkeypatch):
        health = _run_health(monkeypatch, services=_fail())
        assert health["status"] != "healthy"
        assert health["issues"] == []  # unknown ≠ broken service
        assert health["unavailable"] == ["services"]
        assert any("services" in w for w in health["warnings"])

    def test_subscription_unreadable_is_not_healthy(self, monkeypatch):
        health = _run_health(monkeypatch, subscription=_fail())
        assert health["status"] != "healthy"
        assert health["unavailable"] == ["subscription"]
        assert any("subscription" in w for w in health["warnings"])

    def test_updates_unreadable_is_not_healthy(self, monkeypatch):
        health = _run_health(monkeypatch, updates=_fail())
        assert health["status"] != "healthy"
        assert health["unavailable"] == ["updates"]

    def test_malformed_services_structure_is_unavailable(self, monkeypatch):
        # data present but not a list — cannot be interpreted
        health = _run_health(monkeypatch, services=_Resp({"oops": 1}))
        assert health["unavailable"] == ["services"]
        assert health["status"] != "healthy"

    def test_malformed_subscription_structure_is_unavailable(self, monkeypatch):
        health = _run_health(monkeypatch, subscription=_Resp([1, 2]))
        assert health["unavailable"] == ["subscription"]
        assert health["status"] != "healthy"

    def test_missing_data_field_is_not_an_error(self, monkeypatch):
        # contract allows the field to be absent: empty is a valid result
        health = _run_health(
            monkeypatch,
            services=_Resp(None, omit_data=True),
            subscription=_Resp({}),
            updates=_Resp([]),
        )
        assert health["status"] == "healthy"
        assert health["unavailable"] == []

    def test_partial_failure_keeps_successful_results(self, monkeypatch):
        # services readable and unhealthy + subscription unreadable:
        # the issue must survive, healthy must not appear
        health = _run_health(
            monkeypatch,
            services=_Resp([{"name": "pvestatd", "state": "stopped"}]),
            subscription=_fail(),
        )
        assert health["status"] == "critical"
        assert health["issues"]  # kept
        assert health["unavailable"] == ["subscription"]
        assert any("subscription" in w for w in health["warnings"])

    def test_all_checks_unreadable_is_not_healthy(self, monkeypatch):
        health = _run_health(
            monkeypatch, services=_fail(), subscription=_fail(),
            updates=_fail())
        assert health["status"] != "healthy"
        assert sorted(health["unavailable"]) == ["services", "subscription",
                                                 "updates"]
        assert health["issues"] == []


# ----------------------------------------------------------------------
# D3 — HostSnapshotsWorker / StorageDisksWorker
# ----------------------------------------------------------------------

def _snap_handler(per_vmid):
    """Route by vmid: GET .../qemu/{vmid}/snapshot (and size configs)."""
    def handler(url):
        if url.endswith("/snapshot"):
            vmid = int(url.split("/")[-2])
            out = per_vmid.get(vmid, _Resp([]))
            if isinstance(out, Exception):
                raise out
            return out
        if url.endswith("/config"):  # snapshot size config — best effort
            return _Resp({})
        return _Resp([])
    return handler


class TestHostSnapshotsD3:
    def test_success_collects_all_and_no_failures(self, monkeypatch):
        _install(monkeypatch, _snap_handler({
            100: _Resp([{"name": "s1", "snaptime": 123}]),
            101: _Resp([{"name": "s2", "snaptime": 456}]),
        }))
        worker = m.HostSnapshotsWorker(_CFG, "n1", [_vm(100), _vm(101)])
        out = _collect(worker.signals.snapshots_ready, worker)
        assert len(out) == 1
        node, snaps, failed = out[0]
        assert node == "n1"
        assert {s["vmid"] for s in snaps} == {100, 101}
        assert failed == []

    def test_per_vm_failure_is_reported_not_hidden(self, monkeypatch):
        _install(monkeypatch, _snap_handler({
            100: _Resp([{"name": "s1", "snaptime": 123}]),
            101: _fail(),  # this guest is unreadable
        }))
        worker = m.HostSnapshotsWorker(_CFG, "n1", [_vm(100), _vm(101)])
        node, snaps, failed = _collect(
            worker.signals.snapshots_ready, worker)[0]
        # 100's result survives; 101 is explicitly unverified
        assert {s["vmid"] for s in snaps} == {100}
        assert len(failed) == 1
        assert failed[0]["vmid"] == 101
        assert failed[0]["error"]

    def test_confirmed_empty_is_not_a_failure(self, monkeypatch):
        _install(monkeypatch, _snap_handler({102: _Resp([])}))
        worker = m.HostSnapshotsWorker(_CFG, "n1", [_vm(102)])
        _, snaps, failed = _collect(
            worker.signals.snapshots_ready, worker)[0]
        assert snaps == []
        assert failed == []

    def test_multiple_failures_all_reported(self, monkeypatch):
        _install(monkeypatch, _snap_handler({
            100: _fail(),
            101: _fail(),
            102: _Resp([{"name": "s", "snaptime": 1}]),
        }))
        worker = m.HostSnapshotsWorker(_CFG, "n1",
                                       [_vm(100), _vm(101), _vm(102)])
        _, snaps, failed = _collect(
            worker.signals.snapshots_ready, worker)[0]
        assert {s["vmid"] for s in snaps} == {102}
        assert sorted(f["vmid"] for f in failed) == [100, 101]


def _disk_handler(per_vmid):
    """Route by vmid: GET .../qemu/{vmid}/config."""
    def handler(url):
        if url.endswith("/config"):
            vmid = int(url.split("/")[-2])
            out = per_vmid.get(vmid)
            if out is None:
                return _Resp({})
            if isinstance(out, Exception):
                raise out
            return out
        return _Resp([])
    return handler


class TestStorageDisksD3:
    def test_success_collects_disks_no_failures(self, monkeypatch):
        _install(monkeypatch, _disk_handler({
            100: _Resp({"scsi0": "local-lvm:vm-100-disk-0,size=8G"}),
        }))
        worker = m.StorageDisksWorker(_CFG, "n1", "local-lvm", [_vm(100)])
        out = _collect(worker.signals.disks_ready, worker)
        storage, disks, failed = out[0]
        assert storage == "local-lvm"
        assert len(disks) == 1
        assert disks[0]["vmid"] == 100
        assert failed == []

    def test_per_vm_failure_is_reported_not_hidden(self, monkeypatch):
        _install(monkeypatch, _disk_handler({
            100: _Resp({"scsi0": "local-lvm:vm-100-disk-0,size=8G"}),
            101: _fail(),
        }))
        worker = m.StorageDisksWorker(_CFG, "n1", "local-lvm",
                                      [_vm(100), _vm(101)])
        _, disks, failed = _collect(worker.signals.disks_ready, worker)[0]
        assert [d["vmid"] for d in disks] == [100]  # neighbour survives
        assert len(failed) == 1
        assert failed[0]["vmid"] == 101
        assert failed[0]["error"]

    def test_confirmed_no_volumes_is_not_a_failure(self, monkeypatch):
        _install(monkeypatch, _disk_handler({
            102: _Resp({"ide0": "none,media=cdrom"}),
            103: _Resp({"net0": "virtio=AA:BB,bridge=vmbr0"}),
        }))
        worker = m.StorageDisksWorker(_CFG, "n1", "local-lvm",
                                      [_vm(102), _vm(103)])
        _, disks, failed = _collect(worker.signals.disks_ready, worker)[0]
        assert disks == []
        assert failed == []


# ----------------------------------------------------------------------
# D3 — UI representation of unverified guests
# ----------------------------------------------------------------------

class TestUnreadMarkerUI:
    """The unread-guests marker must be visible in the snapshots tree."""

    def test_marker_added_with_error_details(self, qtbot):
        from PySide6.QtWidgets import QTreeWidget

        from virtdeck.ui.detail_panel._host_tabs import HostTabs

        tree = QTreeWidget()
        qtbot.addWidget(tree)
        failed = [{"vmid": 101, "error": "HTTP 500: boom"},
                  {"vmid": 102, "error": "read timed out"}]
        HostTabs._add_unread_snapshots_marker(tree, failed)
        assert tree.topLevelItemCount() == 1
        marker = tree.topLevelItem(0)
        assert "2" in marker.text(0)  # count is part of the label
        assert "HTTP 500: boom" in marker.toolTip(0)
        assert "read timed out" in marker.toolTip(0)

    def test_no_marker_when_everything_was_read(self, qtbot):
        from PySide6.QtWidgets import QTreeWidget

        from virtdeck.ui.detail_panel._host_tabs import HostTabs

        tree = QTreeWidget()
        qtbot.addWidget(tree)
        HostTabs._add_unread_snapshots_marker(tree, [])
        assert tree.topLevelItemCount() == 0
