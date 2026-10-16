"""Audit 6.3.2a: mainwindow-level gates.

D6 — the optimistic VM status (and the bulk progress dialog) must be
undone when _run_worker refuses the worker (pool full): the worker never
starts and never reports.

D13 — API-token deletion for removed hosts runs off the GUI thread, one
removal at a time, and the configuration cleanup happens only after the
worker reports back.

D15 — a backup-job creation error must not be reported as "HA error".
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from PySide6.QtCore import QThreadPool

import virtdeck.ui.mainwindow as mainwindow_mod
from virtdeck.backend import tokens as tokens_mod
from virtdeck.backend.tokens import HostTokenDeleteWorker
from virtdeck.ui.detail_panel._host_tabs import HostTabs


class _SignalStub:
    """Minimal Qt-signal double: connect() stores, emit() fires."""

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


def _action_signals():
    return SimpleNamespace(action_result=_SignalStub(),
                           action_error=_SignalStub())


class _OptimisticRecorder:
    def __init__(self):
        self.calls = []

    def apply(self, *a):
        self.calls.append(("apply", *a))

    def rollback(self, *a):
        self.calls.append(("rollback", *a))

    def confirm(self, *a):
        self.calls.append(("confirm", *a))

    def pending_action(self, host_name, vmid):
        # Real API: returns the in-flight action or None. The recorder
        # never leaves anything pending.
        return None


def _patch_action_worker(monkeypatch, workers):
    def _make(*a, **kw):
        w = SimpleNamespace(signals=_action_signals())
        workers.append(w)
        return w

    monkeypatch.setattr("virtdeck.backend.VmActionWorker", _make)


# --- D6: optimistic status only after the worker is accepted ---------------


class TestOptimisticOnWorkerAcceptance:
    def _seed(self, mw):
        mw._cfg_by_name = {"h1": {"name": "h1"}}

    def test_rejected_start_rolls_optimistic_back(self, main_window,
                                                  monkeypatch):
        mw = main_window
        self._seed(mw)
        opt = _OptimisticRecorder()
        mw._optimistic = opt
        monkeypatch.setattr(mw, "_run_worker", lambda w: False)
        monkeypatch.setattr(mainwindow_mod, "confirm_vm_action",
                            lambda *a, **kw: True)
        _patch_action_worker(monkeypatch, [])
        mw._on_vm_action_from_tree("h1", "pve1", 100, "start")
        assert ("apply", "h1", 100, "start") in opt.calls
        assert ("rollback", "h1", 100) in opt.calls
        assert not any(c[0] == "confirm" for c in opt.calls)

    def test_accepted_start_confirms_on_result(self, main_window,
                                               monkeypatch):
        mw = main_window
        self._seed(mw)
        opt = _OptimisticRecorder()
        mw._optimistic = opt
        monkeypatch.setattr(mw, "_run_worker", lambda w: True)
        monkeypatch.setattr(mainwindow_mod, "confirm_vm_action",
                            lambda *a, **kw: True)
        workers = []
        _patch_action_worker(monkeypatch, workers)
        mw._on_vm_action_from_tree("h1", "pve1", 100, "start")
        assert ("rollback", "h1", 100) not in opt.calls
        workers[0].signals.action_result.emit("Started: 100")
        assert ("confirm", "h1", 100) in opt.calls

    def test_worker_error_rolls_back(self, main_window, monkeypatch):
        mw = main_window
        self._seed(mw)
        opt = _OptimisticRecorder()
        mw._optimistic = opt
        monkeypatch.setattr(mw, "_run_worker", lambda w: True)
        monkeypatch.setattr(mainwindow_mod, "confirm_vm_action",
                            lambda *a, **kw: True)
        workers = []
        _patch_action_worker(monkeypatch, workers)
        mw._on_vm_action_from_tree("h1", "pve1", 100, "start")
        workers[0].signals.action_error.emit("timeout")
        assert ("rollback", "h1", 100) in opt.calls
        assert not any(c[0] == "confirm" for c in opt.calls)

    def test_rejected_bulk_closes_progress_dialog(self, main_window,
                                                  monkeypatch):
        mw = main_window
        plan = SimpleNamespace(skipped_count=0, targets=[
            SimpleNamespace(host_name="h1", node="pve1", vmid=100,
                            vm_type="qemu")])
        monkeypatch.setattr(mainwindow_mod, "plan_bulk_action",
                            lambda *a, **kw: plan)
        mw._cfg_by_name = {"h1": {"name": "h1"}}
        yes = object()

        class _StubBox:
            Warning = 1
            Question = 2
            YesRole = 3
            NoRole = 4

            def __init__(self, *a, **kw):
                pass

            def setIcon(self, *a):
                pass

            setWindowTitle = setText = setInformativeText = setIcon

            def addButton(self, *a, **kw):
                return yes

            def exec(self):
                return 0

            def clickedButton(self):
                return yes

        monkeypatch.setattr(mainwindow_mod, "QMessageBox", _StubBox)

        class _StubProgress:
            def __init__(self, *a, **kw):
                self.cancel_calls = 0
                self._canceled = _SignalStub()

            def setWindowTitle(self, *a):
                pass

            def setWindowModality(self, *a):
                pass

            def setMinimumDuration(self, *a):
                pass

            @property
            def canceled(self):
                return self._canceled

            def cancel(self):
                self.cancel_calls += 1

        prog = _StubProgress()
        monkeypatch.setattr(mainwindow_mod, "QProgressDialog",
                            lambda *a, **kw: prog)
        monkeypatch.setattr(mw, "_run_worker", lambda w: False)
        mw._on_bulk_vm_action([("h1", 100)], "start")
        assert prog.cancel_calls == 1


# --- D13: host token deletion off the GUI thread ---------------------------


class TestHostTokenDeleteWorker:
    def test_delete_call_runs_off_main_thread(self, qtbot, monkeypatch):
        threads = []

        def fake_create_provider(cfg, timeout=10):
            threads.append(threading.current_thread())
            return SimpleNamespace(
                access=SimpleNamespace(delete_token=lambda u, t: None),
                close=lambda: None)

        monkeypatch.setattr(tokens_mod, "create_provider",
                            fake_create_provider)
        got = []
        w = HostTokenDeleteWorker([{"name": "h1", "host": "h1.local",
                                    "user": "root@pam",
                                    "token_name": "app"}])
        w.signals.delete_result.connect(lambda failed: got.append(list(failed)))
        with qtbot.waitSignal(w.signals.delete_result, timeout=5000):
            QThreadPool.globalInstance().start(w)
        assert threads and threads[0] is not threading.main_thread()
        assert got == [[]]

    def test_failed_hosts_are_reported(self, monkeypatch):
        def fake_create_provider(cfg, timeout=10):
            raise RuntimeError("no network")

        monkeypatch.setattr(tokens_mod, "create_provider",
                            fake_create_provider)
        got = []
        w = HostTokenDeleteWorker([
            {"name": "h1", "host": "h1.local", "user": "u",
             "token_name": "t"},
            {"name": "h2", "host": "h2.local", "user": "u",
             "token_name": "t"},
        ])
        w.signals.delete_result.connect(lambda failed: got.append(list(failed)))
        w.run()  # direct call: the worker itself must survive the errors
        assert got == [["h1", "h2"]]


class TestHostRemovalFlow:
    def test_removal_is_async_and_applies_on_report(self, main_window,
                                                    monkeypatch):
        mw = main_window
        monkeypatch.setattr(mw, "_confirm_delete", lambda text: True)
        cfg1 = {"name": "h1", "host": "h1.local"}
        cfg2 = {"name": "h2", "host": "h2.local"}
        mw.nodes_cfg = [dict(cfg1), dict(cfg2)]
        mw._rebuild_cfg_indexes()
        mw._on_host_remove("host", "h1")
        assert mw._host_token_del_active is True
        assert len(mw._workers) == 1
        w = next(iter(mw._workers))
        w.signals.delete_result.emit([])
        # the report alone already applies the removal...
        assert [c["name"] for c in mw.nodes_cfg] == ["h2"]
        # ...the flag clears only when the worker is fully finished
        assert mw._host_token_del_active is True
        w.signals.finished.emit()
        assert mw._host_token_del_active is False

    def test_failed_deletion_names_shown_and_config_cleared(
            self, main_window, monkeypatch):
        mw = main_window
        monkeypatch.setattr(mw, "_confirm_delete", lambda text: True)
        shown = []
        monkeypatch.setattr(mw._notifications, "show",
                            lambda text, error=False: shown.append(text))
        mw.nodes_cfg = [{"name": "h1", "host": "h1.local"},
                        {"name": "h2", "host": "h2.local"}]
        mw._rebuild_cfg_indexes()
        mw._on_host_remove("host", "h1")
        w = next(iter(mw._workers))
        w.signals.delete_result.emit(["h1"])
        w.signals.finished.emit()
        assert [c["name"] for c in mw.nodes_cfg] == ["h2"]
        assert any("Failed to delete tokens: h1" in t for t in shown)

    def test_second_removal_blocked_while_active(self, main_window,
                                                 monkeypatch):
        mw = main_window
        mw._host_token_del_active = True
        monkeypatch.setattr(mw, "_confirm_delete", lambda text: True)
        mw._on_host_remove("host", "h1")
        assert mw._workers == set()

    def test_pool_rejection_keeps_configuration(self, main_window,
                                                monkeypatch):
        mw = main_window
        monkeypatch.setattr(mw, "_run_worker", lambda w: False)
        monkeypatch.setattr(mw, "_confirm_delete", lambda text: True)
        mw.nodes_cfg = [{"name": "h1", "host": "h1.local"}]
        mw._rebuild_cfg_indexes()
        mw._on_host_remove("host", "h1")
        assert [c["name"] for c in mw.nodes_cfg] == ["h1"]
        assert mw._host_token_del_active is False


# --- D15: backup-job errors are not HA errors ------------------------------


class TestBackupJobErrorText:
    def test_create_error_reported_as_job_error(self, monkeypatch):
        messages = []
        started = []
        panel = SimpleNamespace(
            _backup_jobs_cfg={"name": "h1"},
            _backup_jobs_pve_major=7,
            _backup_jobs_context="h1",
            _backup_jobs_host_cfg="h1",
            current_obj_type="host",
            all_storages=[],
            all_pools=[],
            config_update_result=SimpleNamespace(emit=messages.append),
            _workers_mgr=SimpleNamespace(
                run_host_worker=lambda w: started.append(w),
                discard_worker=lambda w: None),
        )

        class _Dlg:
            Accepted = 1

            def __init__(self, parent, storages=None, pools=None):
                pass

            def exec(self):
                return _Dlg.Accepted

            def get_params(self):
                return {"id": "job1"}

        monkeypatch.setattr("virtdeck.ui.backup_job_dialog.BackupJobDialog",
                            _Dlg)
        monkeypatch.setattr(
            "virtdeck.backend.ClusterJobCreateWorker",
            lambda *a, **kw: SimpleNamespace(signals=SimpleNamespace(
                result=_SignalStub(), error=_SignalStub())))
        HostTabs._on_add_backup_job(SimpleNamespace(
            panel=panel,
            _get_backup_jobs_storages=lambda: [],
            _get_pool_ids=lambda: []))
        assert len(started) == 1
        started[0].signals.error.emit("quota exceeded")
        assert messages == ["Job error: quota exceeded"]
