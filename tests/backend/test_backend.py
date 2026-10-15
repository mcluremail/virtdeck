"""Tests for virtdeck/backend.py — pure helpers and token-creation flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from virtdeck import backend


class FakeProvider:
    """Stands in for the plugin-dispatched provider factory: facade attrs + close()."""

    def __init__(self, cfg=None, timeout=10):
        self.cfg = cfg
        self.timeout = timeout
        self.closed = False
        self.nodes = MagicMock()
        self.vms = MagicMock()
        self.cluster = MagicMock()
        self.storage = MagicMock()
        self.tasks = MagicMock()
        self.pools = MagicMock()
        self.access = MagicMock()
        self.rrd = MagicMock()
        # Part of the provider contract (M0.5 compat matrix)
        self.report_version = MagicMock()

    def close(self):
        self.closed = True


class FakePveApi:
    """Provider facade whose API objects answer with real (empty by
    default) lists: a confirmed absence of resources, not a failure."""

    def __init__(self, *, nodes=None, vms=None, storages=None,
                 resources=None, pools=None, ha=None, iso=None):
        self._nodes = nodes if nodes is not None else []
        self._vms = vms if vms is not None else []
        self._storages = storages if storages is not None else []
        self._resources = resources if resources is not None else []
        self._pools = pools if pools is not None else []
        self._ha = ha if ha is not None else []
        self._iso = iso if iso is not None else []
        self.report_version = MagicMock()
        self.nodes = SimpleNamespace(
            list=lambda: list(self._nodes),
            get_status=lambda n: {"pveversion": "8.2.4", "memory": {},
                                  "rootfs": {}, "cpuinfo": {}},
            get_version=lambda n: {},
            list_storage=lambda n: list(self._storages),
        )
        self.vms = SimpleNamespace(
            list_qemu=lambda n: [v for v in self._vms if v.get("type") == "qemu"],
            list_lxc=lambda n: [v for v in self._vms if v.get("type") == "lxc"],
        )
        self.cluster = SimpleNamespace(
            list_ha_groups=lambda: list(self._ha),
            list_resources=lambda: list(self._resources),
        )
        self.pools = SimpleNamespace(
            list=lambda: list(self._pools),
            get=lambda p: {},
        )
        self.storage = SimpleNamespace(
            list_content=lambda n, s, content="iso": list(self._iso),
        )

# --- _verify_ssl ---


class TestVerifySsl:
    def test_default_strict(self):
        assert backend._verify_ssl({}) is True

    def test_explicit_false(self):
        assert backend._verify_ssl({"trust_ssl": False}) is True

    def test_trusted(self):
        assert backend._verify_ssl({"trust_ssl": True}) is False

    def test_truthy_string(self):
        assert backend._verify_ssl({"trust_ssl": "1"}) is False


# --- _q ---


class TestQ:
    def test_space(self):
        assert backend._q("a b") == "a%20b"

    def test_slash_and_at(self):
        assert backend._q("user@pam") == "user%40pam"
        assert backend._q("a/b") == "a%2Fb"

    def test_non_string(self):
        assert backend._q(100) == "100"

    def test_safe_chars_kept(self):
        assert backend._q("a.b-c_d") == "a.b-c_d"


# --- _sanitize_error ---


class TestSanitizeError:
    def test_strips_url(self):
        msg = backend._sanitize_error(Exception("GET https://10.0.0.1:8006/api2/json failed"))
        assert "10.0.0.1" not in msg.replace("[host]", "")
        assert "https://" not in msg

    def test_strips_host_port(self):
        msg = backend._sanitize_error(Exception("connect to 192.168.1.10:8006"))
        assert "192.168.1.10" not in msg
        assert "[host]" in msg

    def test_truncates_long(self):
        msg = backend._sanitize_error(Exception("x" * 500))
        assert len(msg) == 153  # 150 + "..."
        assert msg.endswith("...")

    def test_short_preserved(self):
        assert backend._sanitize_error(Exception("boom")) == "boom"


class TestSanitizeErrorHostnames:
    """D6: bare hostnames from requests/proxmoxer exceptions must not leak."""

    def test_requests_quoted_host(self):
        exc = Exception("HTTPSConnectionPool(host='pve1.lan', port=8006): "
                        "Max retries exceeded")
        msg = backend._sanitize_error(exc)
        assert "pve1.lan" not in msg
        assert "[host]" in msg
        assert "Max retries exceeded" in msg  # diagnostic value kept

    def test_fqdn_with_port(self):
        msg = backend._sanitize_error(
            Exception("connection to pve1.lan:8006 failed"))
        assert "pve1.lan" not in msg
        assert "[host]" in msg
        assert "connection" in msg and "failed" in msg

    def test_ipv4_port_still_stripped(self):
        msg = backend._sanitize_error(
            Exception("connect to 192.168.1.10:8006 refused"))
        assert "192.168.1.10" not in msg

    def test_timestamps_not_masked(self):
        # timestamps and volid-ish text must survive sanitization
        text = "TASK ERROR: backup 2026-01-01T00:00:00Z volume local:iso/x"
        assert backend._sanitize_error(Exception(text)) == text

    def test_task_error_text_preserved(self):
        text = "TASK ERROR: volume 'local-zfs:subvol-101-disk-0' is full"
        assert backend._sanitize_error(Exception(text)) == text

    def test_credential_like_fragment_stripped(self):
        # URLs may carry credentials — the URL pattern removes them whole
        msg = backend._sanitize_error(
            Exception("auth failed for https://root:secret@pve1.lan:8006/x"))
        assert "root" not in msg and "secret" not in msg and "pve1.lan" not in msg


class TestAwaitTask:
    """D2: poll outcomes must be distinguished; D6: texts sanitized."""

    @staticmethod
    def _provider(poll_return):
        p = FakeProvider()
        p.tasks.poll = MagicMock(return_value=poll_return)
        return p

    def test_non_upid_result_is_synchronous(self):
        ok, err = backend._await_task(FakeProvider(), "n1", {"data": None})
        assert ok is True and err == ""

    def test_stopped_ok(self):
        p = self._provider(("stopped", "OK"))
        assert backend._await_task(p, "n1", "UPID:x") == (True, "")

    def test_stopped_failed_carries_task_error(self):
        p = self._provider(("stopped", "TASK ERROR: volume full"))
        ok, err = backend._await_task(p, "n1", "UPID:x")
        assert ok is False
        assert err == "TASK ERROR: volume full"

    def test_stopped_failed_sanitized(self):
        p = self._provider(("stopped",
                            "TASK ERROR: see https://pve1.lan:8006/docs"))
        ok, err = backend._await_task(p, "n1", "UPID:x")
        assert ok is False
        assert "pve1.lan" not in err and "https://" not in err

    def test_poll_failed_means_unknown_outcome(self):
        p = self._provider(("poll_failed",
                            "HTTPSConnectionPool(host='pve1.lan', port=8006)"))
        ok, err = backend._await_task(p, "n1", "UPID:x")
        assert ok is False
        assert "outcome unknown" in err
        assert "pve1.lan" not in err  # D6: sanitized

    def test_timeout_is_not_a_failure_claim(self):
        p = self._provider(("timeout", ""))
        ok, err = backend._await_task(p, "n1", "UPID:x", timeout=120)
        assert ok is False
        assert err == "still running after 120 s"

    def test_unknown_status_defensive(self):
        p = self._provider(("weird", ""))
        ok, err = backend._await_task(p, "n1", "UPID:x")
        assert ok is False
        assert "weird" in err

    def test_poll_args_forwarded(self):
        p = self._provider(("stopped", "OK"))
        backend._await_task(p, "n1", "UPID:x", timeout=300)
        p.tasks.poll.assert_called_once_with("n1", "UPID:x",
                                             timeout=300, interval=1.0)


# --- _cleanup_vv ---


class TestCloseAndCleanup:
    def test_cleanup_vv_removes_file(self, tmp_path):
        f = tmp_path / "spice.vv"
        f.write_text("[virt-viewer]")
        backend._cleanup_vv(str(f))
        assert not f.exists()

    def test_cleanup_vv_missing_file(self, tmp_path):
        backend._cleanup_vv(str(tmp_path / "gone.vv"))

    def test_cleanup_vv_falsy(self):
        backend._cleanup_vv("")
        backend._cleanup_vv(None)


# --- _parse_disk_size ---


class TestParseDiskSize:
    def test_simple_gigabytes(self):
        assert backend._parse_disk_size("local-lvm:vm-100-disk-0,size=32G") == 32 * 1024**3

    def test_terabytes(self):
        assert backend._parse_disk_size("size=1T") == 1024**4

    def test_megabytes_and_kilobytes(self):
        assert backend._parse_disk_size("size=512M") == 512 * 1024**2
        assert backend._parse_disk_size("size=1024K") == 1024 * 1024  # 1 MiB

    def test_fractional(self):
        assert backend._parse_disk_size("size=1.5G") == int(1.5 * 1024**3)

    def test_multiple_sizes_summed(self):
        val = "scsi0,size=10G,scsi1,size=5G"
        assert backend._parse_disk_size(val) == 15 * 1024**3

    def test_no_size_key(self):
        assert backend._parse_disk_size("local-lvm:vm-100-disk-0") == 0

    def test_invalid_value(self):
        assert backend._parse_disk_size("size=abc") == 0

    def test_empty_value(self):
        assert backend._parse_disk_size("size=") == 0

    def test_non_string(self):
        assert backend._parse_disk_size(None) == 0
        assert backend._parse_disk_size(42) == 0


# --- create_admin_token ---


def _resp(status=200, payload=None):
    def raise_for_status():
        if status >= 400:
            # real requests.HTTPError always carries its response
            raise requests.HTTPError(
                f"{status} Error", response=SimpleNamespace(status_code=status))
        return None
    return SimpleNamespace(
        status_code=status,
        json=lambda: payload if payload is not None else {"data": {}},
        raise_for_status=raise_for_status,
    )


class FakeSession:
    def __init__(self, responses):
        self.verify = None
        self.headers = {}
        self.responses = list(responses)
        self.closed = False

    def post(self, url, **kwargs):
        return self.responses.pop(0)

    def put(self, url, **kwargs):
        return self.responses.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def ticket_ok(monkeypatch):
    """Ticket endpoint returns valid ticket/csrf."""
    monkeypatch.setattr(
        requests, "post",
        lambda url, **kw: _resp(200, {"data": {"ticket": "TICKET",
                                               "CSRFPreventionToken": "CSRF"}}),
    )


class TestCreateAdminToken:
    def test_success(self, ticket_ok, monkeypatch):
        fake = FakeSession([_resp(200, {"data": {"value": "UUID-123"}})])
        monkeypatch.setattr(requests, "Session", lambda: fake)
        monkeypatch.setattr(requests, "get", lambda url, **kw: _resp(200, {}))
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert "error" not in result
        assert result["token_value"] == "UUID-123"
        assert result["user"] == "root@pam"
        assert result["token_name"].startswith("virtdeck-")
        assert fake.closed

    def test_post_and_put_both_fail(self, ticket_ok, monkeypatch):
        fake = FakeSession([_resp(400), _resp(400)])
        monkeypatch.setattr(requests, "Session", lambda: fake)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert "error" in result
        assert "token_name" not in result

    def test_empty_token_value(self, ticket_ok, monkeypatch):
        fake = FakeSession([_resp(200, {"data": {}})])
        monkeypatch.setattr(requests, "Session", lambda: fake)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert "error" in result

    def test_verify_fails(self, ticket_ok, monkeypatch):
        fake = FakeSession([_resp(200, {"data": {"value": "UUID"}})])
        monkeypatch.setattr(requests, "Session", lambda: fake)
        monkeypatch.setattr(requests, "get", lambda url, **kw: _resp(403))
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert "error" in result
        assert "not working" in result["error"]

    def test_cluster_detected(self, ticket_ok, monkeypatch):
        """cluster/status with a type=cluster entry — cluster_info in the result."""
        fake = FakeSession([_resp(200, {"data": {"value": "UUID"}})])
        monkeypatch.setattr(requests, "Session", lambda: fake)

        def fake_get(url, **kw):
            if "/cluster/status" in url:
                return _resp(200, {"data": [
                    {"type": "cluster", "name": "ros", "quorate": 1},
                    {"type": "node", "name": "pve01"},
                    {"type": "node", "name": "pve02"},
                    {"type": "node", "name": "pve03"},
                ]})
            return _resp(200, {})
        monkeypatch.setattr(requests, "get", fake_get)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert result["cluster"] == {"name": "ros", "nodes": 3}

    def test_standalone_no_cluster_entry(self, ticket_ok, monkeypatch):
        fake = FakeSession([_resp(200, {"data": {"value": "UUID"}})])
        monkeypatch.setattr(requests, "Session", lambda: fake)

        def fake_get(url, **kw):
            if "/cluster/status" in url:
                return _resp(200, {"data": [{"type": "node", "name": "pve01"}]})
            return _resp(200, {})
        monkeypatch.setattr(requests, "get", fake_get)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert result["cluster"] is None

    def test_cluster_status_error_is_tolerated(self, ticket_ok, monkeypatch):
        fake = FakeSession([_resp(200, {"data": {"value": "UUID"}})])
        monkeypatch.setattr(requests, "Session", lambda: fake)

        def fake_get(url, **kw):
            if "/cluster/status" in url:
                return _resp(500)
            return _resp(200, {})
        monkeypatch.setattr(requests, "get", fake_get)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert "error" not in result
        assert result["cluster"] is None

    def test_bad_credentials(self, monkeypatch):
        monkeypatch.setattr(
            requests, "post",
            lambda url, **kw: _resp(401),
        )
        result = backend.create_admin_token("pve.local", "root@pam", "wrong")
        assert result == {"error": backend.tr("Invalid login or password")}

    def test_connection_error(self, monkeypatch):
        def boom(url, **kw):
            raise requests.ConnectionError("connection refused")

        monkeypatch.setattr(requests, "post", boom)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert result == {"error": backend.tr("Cannot connect to {}").format("pve.local")}

    def test_generic_error(self, monkeypatch):
        def boom(url, **kw):
            raise ValueError("weird")

        monkeypatch.setattr(requests, "post", boom)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert "error" in result

    # -- audit D4: transport errors must not be classified by numbers
    #    inside the message text --

    def test_dns_error_with_vmid_url_is_not_auth(self, monkeypatch):
        def boom(url, **kw):
            raise requests.ConnectionError(
                "Max retries exceeded with url: "
                "/api2/json/nodes/pve1/qemu/401/status/current "
                "(Caused by NameResolutionError(\"Failed to resolve 'pve1'\"))")

        monkeypatch.setattr(requests, "post", boom)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert result == {"error": backend.tr("Cannot connect to {}").format("pve.local")}

    def test_timeout_is_not_auth(self, monkeypatch):
        def boom(url, **kw):
            raise requests.Timeout("timed out (url: /api2/json/nodes/x/401/...)")

        monkeypatch.setattr(requests, "post", boom)
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert result == {"error": backend.tr("Cannot connect to {}").format("pve.local")}

    def test_http_403_is_not_invalid_login(self, monkeypatch):
        """403 from raise_for_status: forbidden ≠ wrong password (kept as a
        generic failure, as before the fix)."""
        monkeypatch.setattr(
            requests, "post",
            lambda url, **kw: _resp(403),
        )
        result = backend.create_admin_token("pve.local", "root@pam", "pass")
        assert result == {"error": backend.tr(
            "Token creation failed. Check host, user, and password.")}


# --- delete_host_token ---


class TestDeleteHostToken:
    def test_success(self, monkeypatch):
        fake = FakeProvider()
        monkeypatch.setattr(backend.tokens, "create_provider", lambda cfg, timeout=10: fake)
        cfg = {"host": "10.0.0.1", "user": "root@pam", "token_name": "virtdeck-x"}
        assert backend.delete_host_token(cfg) is True
        fake.access.delete_token.assert_called_once_with("root@pam", "virtdeck-x")
        assert fake.closed

    def test_failure_returns_false(self, monkeypatch):
        fake = FakeProvider()
        fake.access.delete_token.side_effect = RuntimeError("nope")
        monkeypatch.setattr(backend.tokens, "create_provider", lambda cfg, timeout=10: fake)
        assert backend.delete_host_token({"user": "u", "token_name": "t"}) is False
        assert fake.closed


# --- BulkVmActionWorker ---


class TestBulkVmActionWorker:
    @staticmethod
    def _make_worker(monkeypatch, failures=None):
        """Build a bulk worker with a plugin-dispatched provider stub.

        failures: dict {vmid: exception} — those VMs raise in perform_action.
        Returns (worker, recorded) where recorded collects signal emissions.
        """
        providers = []
        calls = []

        def fake_perform(node, vmid, vm_type, action):
            calls.append((node, vmid, vm_type, action))
            if failures and vmid in failures:
                raise failures[vmid]

        class ActionProvider(FakeProvider):
            def __init__(self, cfg, timeout=10):
                super().__init__(cfg, timeout)
                providers.append(self)
                self.vms = SimpleNamespace(perform_action=fake_perform)

        monkeypatch.setattr(backend.vm, "create_provider", ActionProvider)

        targets = [
            {"host_cfg": {"name": "h1"}, "node": "n1", "vmid": v, "vm_type": "qemu"}
            for v in (100, 101, 102)
        ]
        worker = backend.BulkVmActionWorker(targets, "start")
        recorded = {"progress": [], "vm_done": [], "finished": []}
        worker.signals.progress.connect(
            lambda d, t, v: recorded["progress"].append((d, t, v)))
        worker.signals.vm_done.connect(
            lambda v, ok, m: recorded["vm_done"].append((v, ok, m)))
        worker.signals.finished.connect(lambda: recorded["finished"].append(True))
        return worker, recorded, calls, providers

    def test_all_success(self, monkeypatch):
        worker, recorded, calls, providers = self._make_worker(monkeypatch)
        worker.run()
        assert [c[1] for c in calls] == [100, 101, 102]
        assert all(c[3] == "start" for c in calls)
        assert all(ok for _v, ok, _m in recorded["vm_done"])
        assert recorded["finished"] == [True]
        assert recorded["progress"] == [(0, 3, 100), (1, 3, 101), (2, 3, 102)]
        assert all(p.closed for p in providers)
        assert not worker.was_cancelled

    def test_partial_failure_continues(self, monkeypatch):
        failures = {101: RuntimeError("vm locked")}
        worker, recorded, calls, _providers = self._make_worker(
            monkeypatch, failures=failures)
        worker.run()
        assert [c[1] for c in calls] == [100, 101, 102]  # loop continues
        results = {v: ok for v, ok, _m in recorded["vm_done"]}
        assert results == {100: True, 101: False, 102: True}
        _v, ok, msg = next(r for r in recorded["vm_done"] if not r[1])
        assert "locked" in msg

    def test_cancel_stops_loop(self, monkeypatch):
        worker, recorded, calls, _providers = self._make_worker(monkeypatch)
        worker.cancel()
        worker.run()
        assert calls == []
        assert recorded["vm_done"] == []
        assert worker.was_cancelled
        assert recorded["finished"] == [True]

    def test_cancel_midway(self, monkeypatch):
        state = {"count": 0}
        calls = []

        def fake_perform(node, vmid, vm_type, action):
            state["count"] += 1
            if state["count"] >= 2:
                worker.cancel()
            calls.append((node, vmid, vm_type, action))

        class MidwayProvider(FakeProvider):
            def __init__(self, cfg, timeout=10):
                super().__init__(cfg, timeout)
                self.vms = SimpleNamespace(perform_action=fake_perform)

        monkeypatch.setattr(backend.vm, "create_provider", MidwayProvider)
        worker = backend.BulkVmActionWorker(
            [{"host_cfg": {"name": "h1"}, "node": "n1", "vmid": v, "vm_type": "qemu"}
             for v in (100, 101, 102)], "start")
        recorded = {"vm_done": [], "finished": []}
        worker.signals.vm_done.connect(
            lambda v, ok, m: recorded["vm_done"].append((v, ok, m)))
        worker.signals.finished.connect(lambda: recorded["finished"].append(True))
        worker.run()
        # VM 100 done, VM 101 triggers cancel mid-run but still completes it;
        # VM 102 skipped
        assert [c[1] for c in calls] == [100, 101]
        assert worker.was_cancelled
        assert recorded["finished"] == [True]

    def test_empty_targets(self, monkeypatch):
        worker = backend.BulkVmActionWorker([], "start")
        recorded = {"finished": []}
        worker.signals.finished.connect(lambda: recorded["finished"].append(True))
        worker.run()
        assert recorded["finished"] == [True]
        assert not worker.was_cancelled


class TestTaskWorkers:
    """Task flow emits domain Task objects (dict→domain migration)."""

    @staticmethod
    def _patch_task_api(monkeypatch, list_result=None, list_for_vm_result=None):
        calls = {}

        class TaskProvider(FakeProvider):
            def __init__(self, cfg, timeout=10):
                super().__init__(cfg, timeout)
                self.tasks = SimpleNamespace(
                    list=lambda node_name, limit=100: (
                        calls.setdefault("list", []).append(node_name)
                        or list_result or []),
                    list_for_vm=lambda node_name, vmid, limit=50: (
                        calls.setdefault("list_for_vm", []).append((node_name, vmid))
                        or list_for_vm_result or []),
                )

        monkeypatch.setattr(backend.vm, "create_provider", TaskProvider)
        return calls

    def test_vm_task_history_emits_domain_objects(self, monkeypatch):
        self._patch_task_api(monkeypatch, list_for_vm_result=[
            {"upid": "UPID:n1:1:2:1700000000:qmstart:100:root@pam:",
             "node": "n1", "type": "qmstart", "status": "OK",
             "starttime": 1700000000, "endtime": 1700000010},
        ])
        worker = backend.VmTaskHistoryWorker({"name": "h1"}, "n1", 100)
        recorded = {"ready": [], "finished": []}
        worker.signals.tasks_ready.connect(lambda v, t: recorded["ready"].append((v, t)))
        worker.signals.finished.connect(lambda: recorded["finished"].append(True))
        worker.run()
        vmid, tasks = recorded["ready"][0]
        assert vmid == 100
        assert len(tasks) == 1
        task = tasks[0]
        assert isinstance(task, backend.Task)
        assert task.task_type == "qmstart"
        assert task.vmid == 100
        assert task.is_ok
        assert recorded["finished"] == [True]

    def test_cluster_tasks_merge_dedup_sort(self, monkeypatch):
        results = {
            "n1": [
                {"upid": "UPID:n1:1:2:200:qmstart:100:root@pam:",
                 "node": "n1", "type": "qmstart", "status": "OK",
                 "starttime": 200, "endtime": 210},
                {"upid": "UPID:n1:1:2:100:qmstop:100:root@pam:",
                 "node": "n1", "type": "qmstop", "status": "OK",
                 "starttime": 100, "endtime": 150},
            ],
            "n2": [
                # duplicate of n1's task with the same UPID — must dedup
                {"upid": "UPID:n1:1:2:200:qmstart:100:root@pam:",
                 "node": "n1", "type": "qmstart", "status": "OK",
                 "starttime": 200, "endtime": 210},
            ],
        }

        class ClusterTaskProvider(FakeProvider):
            def __init__(self, cfg, timeout=10):
                super().__init__(cfg, timeout)
                self.tasks = SimpleNamespace(
                    list=lambda node_name, limit=100: results.get(node_name, []))

        monkeypatch.setattr(backend.cluster, "create_provider", ClusterTaskProvider)

        worker = backend.ClusterTasksWorker([({"name": "h1"}, "n1"),
                                             ({"name": "h2"}, "n2")])
        recorded = {"ready": [], "error": [], "finished": []}
        worker.signals.tasks_ready.connect(lambda t: recorded["ready"].append(t))
        worker.signals.tasks_error.connect(lambda e: recorded["error"].append(e))
        worker.signals.finished.connect(lambda: recorded["finished"].append(True))
        worker.run()

        assert recorded["error"] == []
        tasks = recorded["ready"][0]
        assert all(isinstance(t, backend.Task) for t in tasks)
        # dedup by UPID + sorted by starttime desc
        assert [t.starttime for t in tasks] == [200, 100]
        assert tasks[0].task_type == "qmstart"
        assert tasks[1].task_type == "qmstop"
        assert recorded["finished"] == [True]


class TestVmSnapshotsWorker:
    """Snapshot flow emits domain Snapshot objects (dict→domain migration)."""

    @staticmethod
    def _make_worker(monkeypatch, snaps, cfgs=None):
        def no_cfg(name):
            raise RuntimeError(f"no cfg for {name}")

        class SnapshotProvider(FakeProvider):
            def __init__(self, cfg, timeout=10):
                super().__init__(cfg, timeout)
                self.vms = SimpleNamespace(
                    list_snapshots=lambda node, vmid, vm_type: snaps,
                    get_snapshot_config=lambda node, vmid, vm_type, name: (
                        cfgs[name] if cfgs and name in cfgs else no_cfg(name)),
                )

        monkeypatch.setattr(backend.vm, "create_provider", SnapshotProvider)
        worker = backend.VmSnapshotsWorker({"name": "h1"}, "n1", 100)
        recorded = {"ready": [], "error": [], "finished": []}
        worker.signals.snapshots_ready.connect(
            lambda v, s: recorded["ready"].append((v, s)))
        worker.signals.snapshots_error.connect(
            lambda v, e: recorded["error"].append(e))
        worker.signals.finished.connect(lambda: recorded["finished"].append(True))
        return worker, recorded

    def test_emits_domain_snapshots(self, monkeypatch):
        worker, recorded = self._make_worker(
            monkeypatch,
            snaps=[
                {"name": "current", "description": "You are here!"},
                {"name": "base", "description": "clean",
                 "snaptime": 1700000000, "parent": "", "vmstate": 1},
                {"name": "work", "description": "after edits",
                 "snaptime": 1700000100, "parent": "base"},
            ],
            cfgs={"base": {"scsi0": "local-lvm:vm-100-disk-0,size=32G",
                           "memory": 2048},
                  "work": {"scsi0": "local-lvm:vm-100-disk-0,size=1T"}},
        )
        worker.run()
        vmid, snapshots = recorded["ready"][0]
        assert vmid == 100
        assert recorded["error"] == []
        assert all(isinstance(s, backend.Snapshot) for s in snapshots)
        assert [s.name for s in snapshots] == ["base", "work"]  # sorted by time
        base, work = snapshots
        assert base.size_bytes == 32 * 1024**3
        assert base.vmstate is True
        assert base.is_root is True
        assert work.parent == "base"
        assert work.is_root is False
        assert work.size_bytes == 1024**4
        assert recorded["finished"] == [True]

    def test_config_error_yields_zero_size(self, monkeypatch):
        worker, recorded = self._make_worker(
            monkeypatch,
            snaps=[{"name": "s1", "description": "", "snaptime": 5}],
        )
        worker.run()
        _, snapshots = recorded["ready"][0]
        assert snapshots[0].size_bytes == 0
        assert snapshots[0].size_str == "—"


class TestHaResourcesWorker:
    """HA resources flow emits domain HaResource objects."""

    def test_emits_domain_ha_resources(self, monkeypatch):
        class HaProvider(FakeProvider):
            def __init__(self, cfg, timeout=10):
                super().__init__(cfg, timeout)
                self.cluster = SimpleNamespace(
                    list_ha_resources=lambda: [
                        {"sid": "vm:100", "group": "g1", "state": "started",
                         "max_restart": 2, "max_relocate": 1, "comment": "db"},
                        {"sid": "vm:200", "group": "g2", "state": "stopped"},
                    ])

        monkeypatch.setattr(backend.ha, "create_provider", HaProvider)

        worker = backend.HaResourcesWorker({"name": "h1"})
        recorded = {"ready": [], "error": [], "finished": []}
        worker.signals.ha_resources_ready.connect(
            lambda r: recorded["ready"].append(r))
        worker.signals.ha_resources_error.connect(
            lambda e: recorded["error"].append(e))
        worker.signals.finished.connect(lambda: recorded["finished"].append(True))
        worker.run()

        assert recorded["error"] == []
        resources = recorded["ready"][0]
        assert all(isinstance(r, backend.HaResource) for r in resources)
        assert resources[0].sid == "vm:100"
        assert resources[0].vmid == 100
        assert resources[0].max_restart == 2
        assert resources[0].comment == "db"
        assert resources[1].max_restart == 1  # PVE omits defaults
        assert recorded["finished"] == [True]


class TestBuildVvLines:
    """VNC .vv file: password field preferred (PSA-2026-00014-1), ticket as fallback."""

    def test_prefers_password_field(self):
        config = {"port": 5900, "host": "n1", "password": "pwd", "ticket": "old"}
        lines = backend.VmConsoleWorker._build_vv_lines(config, "fallback")
        assert lines[0] == "[virt-viewer]"
        assert "type=vnc" in lines
        assert "port=5900" in lines
        assert "host=n1" in lines
        assert "password=pwd" in lines
        assert not any(line.startswith("password=old") for line in lines)

    def test_falls_back_to_ticket(self):
        # Old PVE (< 8.4.19 / < 9.1.9) responses have only the ticket field.
        config = {"port": 5901, "host": "n2", "ticket": "old"}
        lines = backend.VmConsoleWorker._build_vv_lines(config, "fallback")
        assert "password=old" in lines

    def test_no_auth_fields(self):
        lines = backend.VmConsoleWorker._build_vv_lines({}, "fallback")
        assert lines == ["[virt-viewer]", "type=vnc", "host=fallback"]

    def test_delete_this_file_flag(self):
        config = {"port": 5900, "ticket": "t", "delete-this-file": 1}
        lines = backend.VmConsoleWorker._build_vv_lines(config, "fb")
        assert "delete-this-file=1" in lines
