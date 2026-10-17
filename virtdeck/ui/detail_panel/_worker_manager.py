import logging
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QThreadPool

from ._constants import _MAX_WORKERS_DP

logger = logging.getLogger(__name__)

# Bounded queue for workers that arrive while the pool is at capacity.
# Prevents the old behaviour of silently dropping fetches (which left
# tabs stuck on "Loading…") while still bounding memory under spam.
_MAX_PENDING = _MAX_WORKERS_DP * 2


class WorkerManager:
    def __init__(self):
        self._workers = set()
        self._pending = deque()
        self.current_worker = None
        self.current_config_worker = None
        self.current_hist_worker = None
        self.current_snap_worker = None
        self.current_host_workers = set()
        # Set by the owning panel (audit 6.3.2a D8): called when a worker
        # is dropped because both the pool and the queue are full, so the
        # user learns the request was not accepted instead of staring at
        # an eternal "Loading…".
        self.on_overload: Callable[[], None] | None = None

    def run_worker(self, worker) -> bool:
        """True — started or queued; False — dropped (never will run)."""
        started = self._try_start(worker, host=False)
        self._pump()
        return started

    def run_host_worker(self, worker) -> bool:
        """Run a host-detail worker that is tracked for cancellation on tab switch."""
        started = self._try_start(worker, host=True)
        self._pump()
        return started

    def _try_start(self, worker, host) -> bool:
        if len(self._workers) >= _MAX_WORKERS_DP:
            if len(self._pending) >= _MAX_PENDING:
                logger.warning(
                    "worker pool and queue full (%d+%d), dropping worker",
                    len(self._workers), len(self._pending),
                )
                if self.on_overload is not None:
                    try:
                        self.on_overload()
                    except Exception:
                        logger.exception("on_overload callback failed")
                return False
            self._pending.append((worker, host))
            return True
        self._workers.add(worker)
        if host:
            self.current_host_workers.add(worker)
            worker.signals.finished.connect(
                lambda w=worker: (self.discard_worker(w), self.current_host_workers.discard(w))
            )
        else:
            worker.signals.finished.connect(lambda w=worker: self.discard_worker(w))
        QThreadPool.globalInstance().start(worker)
        return True

    def _pump(self):
        """Start queued workers as pool slots free up."""
        while self._pending and len(self._workers) < _MAX_WORKERS_DP:
            worker, host = self._pending.popleft()
            self._try_start(worker, host)

    def discard_worker(self, worker):
        self._workers.discard(worker)
        self._pump()

    def shutdown(self):
        """Disconnect every tracked worker's signals (panel teardown).

        A worker keeps polling its task for up to 600 s. If the window
        closes mid-flight, the connection lambdas keep the (deleted)
        panel wrapper alive in a collectable cycle, and a later cyclic
        GC run segfaults collecting it (PySide6 6.11.2, CI 2026-10-17).
        After the shutdown every late emission is a no-op."""
        import warnings

        self._pending.clear()
        singles = [w for w in (self.current_worker,
                               self.current_config_worker,
                               self.current_hist_worker,
                               self.current_snap_worker) if w is not None]
        for w in (list(self._workers)
                  + list(self.current_host_workers) + singles):
            sigs = getattr(w, "signals", None)
            if sigs is None:
                continue
            for attr in dir(sigs):
                sig = getattr(sigs, attr, None)
                if not hasattr(sig, "disconnect"):
                    continue
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
        self._workers.clear()
        self.current_host_workers.clear()
        self.current_worker = None
        self.current_config_worker = None
        self.current_hist_worker = None
        self.current_snap_worker = None

    def cancel_detail_worker(self):
        if self.current_worker:
            self.discard_worker(self.current_worker)
            try: self.current_worker.signals.detail_ready.disconnect()
            except RuntimeError: pass
            self.current_worker = None

    def cancel_config_worker(self):
        if self.current_config_worker:
            self.discard_worker(self.current_config_worker)
            try: self.current_config_worker.signals.config_ready.disconnect()
            except RuntimeError: pass
            try: self.current_config_worker.signals.config_error.disconnect()
            except RuntimeError: pass
            self.current_config_worker = None

    def cancel_history_worker(self):
        if self.current_hist_worker:
            self.discard_worker(self.current_hist_worker)
            try: self.current_hist_worker.signals.tasks_ready.disconnect()
            except RuntimeError: pass
            try: self.current_hist_worker.signals.tasks_error.disconnect()
            except RuntimeError: pass
            self.current_hist_worker = None

    def cancel_snapshots_worker(self):
        if self.current_snap_worker:
            self.discard_worker(self.current_snap_worker)
            try: self.current_snap_worker.signals.snapshots_ready.disconnect()
            except RuntimeError: pass
            try: self.current_snap_worker.signals.snapshots_error.disconnect()
            except RuntimeError: pass
            self.current_snap_worker = None

    def cancel_host_workers(self):
        """Discard all host-detail workers from the pool tracking so new
        workers can be scheduled.  Running workers keep going but their
        results are dropped by the tab-type guard in the result slots."""
        self._pending.clear()
        for w in list(self.current_host_workers):
            self.discard_worker(w)
        self.current_host_workers.clear()

    def cancel_general_workers(self):
        """Discard all general workers (run_worker) from pool tracking
        so new workers can be scheduled.  Running workers keep going
        but their results are dropped by generation/tab guards."""
        self._pending.clear()
        for w in list(self._workers):
            # Don't touch current_worker etc. — they have dedicated cancel methods
            if w not in (self.current_worker, self.current_config_worker,
                         self.current_hist_worker, self.current_snap_worker):
                self.discard_worker(w)
