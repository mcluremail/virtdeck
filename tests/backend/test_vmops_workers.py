"""VM ops worker lifecycle tests (external audit, stage 2).

Every worker path must emit ``finished`` exactly once and close the
provider; write-op outcomes must be honest (task awaited, failed tasks
surfaced). Runs against the fake PVE with write routes + task
simulation (audit batch 1).
"""

from __future__ import annotations

from PySide6.QtCore import QThreadPool

from tests.harness.install import fake_pve_cfg, install_fake_pve
from tests.harness.scenarios import make_pve_cluster
from virtdeck.backend import (
    BulkVmActionWorker,
    CloneVmWorker,
    CreateVmWorker,
    DeleteVmWorker,
    MigrateVmWorker,
    VmActionWorker,
    VmDiskMoveWorker,
    VmDiskResizeWorker,
)
from virtdeck.backend import vmops as vmops_mod
from virtdeck.backend.core import _await_task, _is_vmid_conflict
from virtdeck.provider import ProxmoxProvider

# ── helpers ──────────────────────────────────────────────────────────


def run_worker(qtbot, worker) -> list:
    """Start the worker; return the list of finished emissions
    (assert ``len == 1`` for "exactly once")."""
    done: list = []
    worker.signals.finished.connect(lambda: done.append(1))
    with qtbot.waitSignal(worker.signals.finished, timeout=5000):
        QThreadPool.globalInstance().start(worker)
    return done


def migrate_calls(api) -> list[tuple]:
    return [c for c in api.calls
            if c[0] == "POST" and c[1].endswith("/migrate")]


# ── batch 1: fake write routes + task simulation ─────────────────────


class TestFakeWriteRoutes:
    def test_post_migrate_forks_task_ok(self, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        with ProxmoxProvider(fake_pve_cfg()) as provider:
            # proxmoxer unwraps the {"data": ...} envelope itself
            upid = provider.vms.migrate("pve01", 101, "qemu", "pve02")
            assert isinstance(upid, str) and upid.startswith("UPID:")
            assert api.task_results[upid] == "OK"
            status = provider.tasks.get_status("pve01", upid)
            assert status == {"status": "stopped", "exitstatus": "OK"}

    def test_next_task_result_failure_then_reset(self, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result("migration aborted")
        install_fake_pve(monkeypatch, api)
        with ProxmoxProvider(fake_pve_cfg()) as provider:
            first = provider.vms.migrate("pve01", 101, "qemu", "pve02")
            assert api.task_results[first] == "migration aborted"
            # "next task only": the one after is OK again
            second = provider.vms.migrate("pve01", 102, "qemu", "pve02")
            assert api.task_results[second] == "OK"

    def test_unregistered_task_stays_running(self, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result(None)
        install_fake_pve(monkeypatch, api)
        with ProxmoxProvider(fake_pve_cfg()) as provider:
            upid = provider.vms.migrate("pve01", 101, "qemu", "pve02")
            assert upid not in api.task_results
            assert provider.tasks.get_status("pve01", upid) \
                == {"status": "running"}

    def test_cluster_nextid(self, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        with ProxmoxProvider(fake_pve_cfg()) as provider:
            assert provider.cluster.next_vmid() == 302


# ── batch 2: MigrateVmWorker (D1/D2/D3/D7) ───────────────────────────


class TestMigrateWorker:
    def test_qemu_stopped_no_online(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        migrated: list = []
        worker = MigrateVmWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                                 "pve02", running=False)
        worker.signals.vm_migrated.connect(migrated.append)
        run_worker(qtbot, worker)
        calls = migrate_calls(api)
        assert len(calls) == 1
        _method, path, params = calls[0]
        assert path == "/nodes/pve01/qemu/101/migrate"
        assert params["target"] == "pve02"
        assert str(params.get("with-local-disks")) == "1"
        assert "online" not in params and "restart" not in params
        # task awaited: honest completion message, not "started"
        assert len(migrated) == 1
        assert "migrated to pve02" in migrated[0]

    def test_qemu_running_sends_online(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        worker = MigrateVmWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                                 "pve02", running=True)
        run_worker(qtbot, worker)
        _method, _path, params = migrate_calls(api)[0]
        assert str(params.get("online")) == "1"
        assert "restart" not in params

    def test_lxc_stopped_no_restart(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        worker = MigrateVmWorker(fake_pve_cfg(), "pve02", 301, "lxc",
                                 "pve01", running=False)
        run_worker(qtbot, worker)
        calls = migrate_calls(api)
        assert len(calls) == 1
        assert calls[0][1] == "/nodes/pve02/lxc/301/migrate"
        assert "online" not in calls[0][2] and "restart" not in calls[0][2]

    def test_lxc_running_sends_restart(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        worker = MigrateVmWorker(fake_pve_cfg(), "pve02", 301, "lxc",
                                 "pve01", running=True)
        run_worker(qtbot, worker)
        _method, _path, params = migrate_calls(api)[0]
        assert str(params.get("restart")) == "1"
        assert "online" not in params

    def test_failed_task_surfaced(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result("migration aborted: storage not shared")
        install_fake_pve(monkeypatch, api)
        errors: list = []
        worker = MigrateVmWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                                 "pve02", running=False)
        worker.signals.vm_error.connect(errors.append)
        done = run_worker(qtbot, worker)
        assert len(errors) == 1
        assert "migration aborted: storage not shared" in errors[0]
        assert len(done) == 1  # finished exactly once

    def test_provider_crash_still_finished(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        errors: list = []

        def boom(*_a, **_kw):
            raise RuntimeError("auth failed")

        monkeypatch.setattr(vmops_mod, "create_provider", boom)
        worker = MigrateVmWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                                 "pve02", running=False)
        worker.signals.vm_error.connect(errors.append)
        done = run_worker(qtbot, worker)
        assert len(errors) == 1
        assert len(done) == 1

    def test_provider_closed_on_all_paths(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        closed: list = []
        real_create = vmops_mod.create_provider

        def spy_create(cfg, timeout=None):
            p = real_create(cfg, timeout=timeout)

            real_close = p.close

            def close():
                closed.append(1)
                real_close()

            p.close = close
            return p

        monkeypatch.setattr(vmops_mod, "create_provider", spy_create)
        # success path
        run_worker(qtbot, MigrateVmWorker(fake_pve_cfg(), "pve01", 101,
                                          "qemu", "pve02"))
        assert len(closed) == 1
        # failure path
        api.set_next_task_result("aborted")
        run_worker(qtbot, MigrateVmWorker(fake_pve_cfg(), "pve01", 101,
                                          "qemu", "pve02"))
        assert len(closed) == 2


# ── batch 3: honest task outcomes (D4/D5) ────────────────────────────


class TestAwaitTaskTimeout:
    def test_timeout_is_distinguishable(self, monkeypatch):
        """A still-running task is not a failure: the message must say
        "still running", not "timeout"/"OK"."""
        import virtdeck.provider._tasks as tasks_mod

        monkeypatch.setattr(tasks_mod.time, "sleep", lambda _s: None)
        api = make_pve_cluster("fake1")
        api.set_next_task_result(None)  # never finishes
        install_fake_pve(monkeypatch, api)
        with ProxmoxProvider(fake_pve_cfg()) as provider:
            upid = provider.vms.migrate("pve01", 101, "qemu", "pve02")
            ok, err = _await_task(provider, "pve01", upid, timeout=0.2)
        assert ok is False
        assert "still running" in err

    def test_failed_task_returns_exitstatus(self, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result("task aborted")
        install_fake_pve(monkeypatch, api)
        with ProxmoxProvider(fake_pve_cfg()) as provider:
            upid = provider.vms.migrate("pve01", 101, "qemu", "pve02")
            ok, err = _await_task(provider, "pve01", upid, timeout=5)
        assert ok is False
        assert err == "task aborted"


class TestVmActionWorker:
    def test_completed_after_task_ok(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        results: list = []
        worker = VmActionWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                                "start")
        worker.signals.action_result.connect(results.append)
        run_worker(qtbot, worker)
        assert len(results) == 1
        assert "completed" in results[0]
        # the action POST actually happened
        assert any(c[1] == "/nodes/pve01/qemu/101/status/start"
                   for c in api.calls)

    def test_failed_task_is_an_error(self, qtbot, monkeypatch):
        """A failed start task must surface, not report "completed"."""
        api = make_pve_cluster("fake1")
        api.set_next_task_result("start failed: no boot disk")
        install_fake_pve(monkeypatch, api)
        errors: list = []
        worker = VmActionWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                                "start")
        worker.signals.action_error.connect(errors.append)
        run_worker(qtbot, worker)
        assert len(errors) == 1
        assert "start failed: no boot disk" in errors[0]

    def test_finished_exactly_once_on_error(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result("boom")
        install_fake_pve(monkeypatch, api)
        worker = VmActionWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                                "stop")
        done = run_worker(qtbot, worker)
        assert len(done) == 1


class TestBulkVmActionWorker:
    def test_mixed_outcomes_per_vm(self, qtbot, monkeypatch):
        """One failed VM must not fake successes for the others."""
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        done_vms: list = []
        worker = BulkVmActionWorker([
            {"host_cfg": fake_pve_cfg(), "node": "pve01", "vmid": 101,
             "vm_type": "qemu"},
            {"host_cfg": fake_pve_cfg(), "node": "pve01", "vmid": 102,
             "vm_type": "qemu"},
        ], "start")
        # first task fails, the next one succeeds ("next task only")
        api.set_next_task_result("start failed: locked")
        worker.signals.vm_done.connect(
            lambda vmid, ok, msg: done_vms.append((vmid, ok, msg)))
        run_worker(qtbot, worker)
        assert len(done_vms) == 2
        first, second = done_vms
        assert first[0] == 101 and first[1] is False
        assert "start failed: locked" in first[2]
        assert second[0] == 102 and second[1] is True
        assert "completed" in second[2]

    def test_finished_exactly_once(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        worker = BulkVmActionWorker([
            {"host_cfg": fake_pve_cfg(), "node": "pve01", "vmid": 101,
             "vm_type": "qemu"},
        ], "stop")
        done = run_worker(qtbot, worker)
        assert len(done) == 1


class TestDiskWorkers:
    def test_resize_failed_task_surfaced(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result("resizing failed: no space left")
        install_fake_pve(monkeypatch, api)
        errors: list = []
        worker = VmDiskResizeWorker(fake_pve_cfg(), "pve01", 101, "scsi0",
                                    "+10G", "qemu")
        worker.signals.disk_resize_error.connect(
            lambda vid, err: errors.append((vid, err)))
        run_worker(qtbot, worker)
        assert errors == [(101, "resizing failed: no space left")]

    def test_resize_success_after_task(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        resized: list = []
        worker = VmDiskResizeWorker(fake_pve_cfg(), "pve01", 101, "scsi0",
                                    "+10G", "qemu")
        worker.signals.disk_resized.connect(
            lambda vid, _r: resized.append(vid))
        run_worker(qtbot, worker)
        assert resized == [101]
        assert any(c[0] == "PUT" and c[1] == "/nodes/pve01/qemu/101/resize"
                   for c in api.calls)

    def test_move_failed_task_surfaced(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result("move failed: storage full")
        install_fake_pve(monkeypatch, api)
        errors: list = []
        worker = VmDiskMoveWorker(fake_pve_cfg(), "pve01", 101, "scsi0",
                                  "nfs1", "qemu")
        worker.signals.disk_move_error.connect(
            lambda vid, err: errors.append((vid, err)))
        run_worker(qtbot, worker)
        assert errors == [(101, "move failed: storage full")]

    def test_move_success_after_task(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        moved: list = []
        worker = VmDiskMoveWorker(fake_pve_cfg(), "pve01", 101, "scsi0",
                                  "nfs1", "qemu")
        worker.signals.disk_moved.connect(lambda vid, _r: moved.append(vid))
        run_worker(qtbot, worker)
        assert moved == [101]
        assert any(c[0] == "POST"
                   and c[1] == "/nodes/pve01/qemu/101/move_disk"
                   for c in api.calls)


# ── batch 4: nextid retry, purge, vmid-conflict guard (D6/D8/D9) ─────


class TestVmidRetry:
    def test_is_vmid_conflict(self):
        assert _is_vmid_conflict("guest with ID 102 already exists")
        assert _is_vmid_conflict("VM 102 already in use")
        assert not _is_vmid_conflict("authentication failure")

    def test_clone_retries_with_fresh_vmid(self, qtbot, monkeypatch):
        """The dialog-supplied id is already taken (nextid race): the
        worker must refetch a fresh id and succeed."""
        api = make_pve_cluster("fake1")
        api.set_next_task_result("guest with ID 301 already exists")
        install_fake_pve(monkeypatch, api)
        cloned: list = []
        worker = CloneVmWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                               {"newid": 301, "name": "copy"})
        worker.signals.vm_cloned.connect(cloned.append)
        run_worker(qtbot, worker)
        assert len(cloned) == 1
        newids = [str(c[2].get("newid")) for c in api.calls
                  if c[1] == "/nodes/pve01/qemu/101/clone"]
        assert newids == ["301", "302"]

    def test_clone_non_conflict_error_not_retried(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result("authentication failure")
        install_fake_pve(monkeypatch, api)
        errors: list = []
        worker = CloneVmWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                               {"newid": 301, "name": "copy"})
        worker.signals.vm_error.connect(errors.append)
        run_worker(qtbot, worker)
        assert len(errors) == 1
        clone_calls = [c for c in api.calls
                       if c[1] == "/nodes/pve01/qemu/101/clone"]
        assert len(clone_calls) == 1  # no retry on a non-conflict error

    def test_create_retries_with_fresh_vmid(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        api.set_next_task_result("guest with ID 301 already exists")
        install_fake_pve(monkeypatch, api)
        errors: list = []
        created: list = []
        worker = CreateVmWorker(fake_pve_cfg(), "pve01",
                                {"vmid": 301, "name": "newvm"})
        worker.signals.vm_error.connect(errors.append)
        worker.signals.vm_created.connect(created.append)
        run_worker(qtbot, worker)
        assert errors == []
        assert len(created) == 1
        vmids = [str(c[2].get("vmid")) for c in api.calls
                 if c[0] == "POST" and c[1] == "/nodes/pve01/qemu"]
        assert vmids == ["301", "302"]


class TestDeletePurge:
    def test_purge_default_on(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        deleted: list = []
        worker = DeleteVmWorker(fake_pve_cfg(), "pve01", 101, "qemu")
        worker.signals.vm_deleted.connect(deleted.append)
        run_worker(qtbot, worker)
        assert len(deleted) == 1
        call = [c for c in api.calls
                if c[0] == "DELETE" and c[1] == "/nodes/pve01/qemu/101"]
        assert len(call) == 1
        assert str(call[0][2].get("purge")) == "1"

    def test_purge_off_not_sent(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        deleted: list = []
        worker = DeleteVmWorker(fake_pve_cfg(), "pve01", 101, "qemu",
                                purge=False)
        worker.signals.vm_deleted.connect(deleted.append)
        run_worker(qtbot, worker)
        assert len(deleted) == 1
        call = [c for c in api.calls
                if c[0] == "DELETE" and c[1] == "/nodes/pve01/qemu/101"]
        assert "purge" not in call[0][2]


class TestBulkProviderReuse:
    def test_one_provider_per_host(self, qtbot, monkeypatch):
        api = make_pve_cluster("fake1")
        install_fake_pve(monkeypatch, api)
        logins: list = []
        real_create = vmops_mod.create_provider

        def counting_create(cfg, timeout=None):
            logins.append(cfg.get("name"))
            return real_create(cfg, timeout=timeout)

        # BulkVmActionWorker imports create_provider from vm.py namespace
        import virtdeck.backend.vm as vm_mod
        monkeypatch.setattr(vm_mod, "create_provider", counting_create)
        done_vms: list = []
        worker = BulkVmActionWorker([
            {"host_cfg": fake_pve_cfg(), "node": "pve01", "vmid": 101,
             "vm_type": "qemu"},
            {"host_cfg": fake_pve_cfg(), "node": "pve01", "vmid": 102,
             "vm_type": "qemu"},
        ], "start")
        worker.signals.vm_done.connect(
            lambda vmid, ok, msg: done_vms.append((vmid, ok)))
        run_worker(qtbot, worker)
        assert len(done_vms) == 2
        assert all(ok for _vmid, ok in done_vms)
        assert len(logins) == 1  # one login for both VMs
