"""QRunnable workers for PBS operations (B17 stage 2).

A single generic worker: builds a fresh PbsProvider per run, calls one
provider method, emits ``result`` or ``failed``. Long-lived objects
(panels, tree) connect to the signals; workers are tracked by callers.
"""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, QRunnable, Signal

from .provider import PbsProvider

logger = logging.getLogger(__name__)

# Task states a tracker reports (mirror of provider.task_status plus
# the client-side deadline state "timeout").  These are data states for
# the panel, not a new task-management system: the tracker is just one
# more QRunnable consumer of the existing PBS worker infrastructure.
TRACKER_TERMINAL = ("success", "failed", "unknown", "timeout")


class _Signals(QObject):
    done = Signal(object, object)   # tag, result
    failed = Signal(object, str)    # tag, error message
    finished = Signal()


class _TrackerSignals(QObject):
    update = Signal(object, object)  # key (server, upid), (state, detail)
    finished = Signal()


class PbsApiWorker(QRunnable):
    """Call ``PbsProvider.<method>(*args)`` off the UI thread.

    ``tag`` echoes back the request (e.g. server name or (server, store)).
    ``signals`` is per instance (audit 6.3.2a D9): completion tracking
    connects ``finished`` per worker, and a class-level signals object
    would keep every such connection (with the worker it closes over)
    alive for the whole session.
    """

    def __init__(self, cfg: dict, method: str, *args,
                 timeout: float = 15, tag=None, **kwargs):
        super().__init__()
        self.cfg = cfg
        self.method = method
        self.args = args
        self.kwargs = kwargs
        self.timeout = timeout
        self.tag = tag
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self):
        provider: PbsProvider | None = None
        try:
            provider = PbsProvider(self.cfg, timeout=self.timeout)
            result = getattr(provider, self.method)(*self.args, **self.kwargs)
            try:
                self.signals.done.emit(self.tag, result)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("pbs worker error (%s)", self.method, exc_info=True)
            try:
                self.signals.failed.emit(self.tag, str(e))
            except RuntimeError:
                pass
        finally:
            if provider is not None:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class PbsTaskTracker(QRunnable):
    """Watch one started PBS task (UPID) until a terminal outcome.

    Audit 6.3.3 D16.  Mirrors the PVE poll taxonomy
    (``provider/_tasks.py``) without sharing its transport:

    - ``running`` — PBS confirms the task is working;
    - ``success`` / ``failed`` — a confirmed terminal exit status;
    - ``unknown`` — the outcome could not be established (unreadable
      status, missing rights, odd response, stopped without exit
      status): never reported as the task's own failure;
    - ``timeout`` — this client's watch deadline expired; the task may
      still be running on PBS.

    Polls live in this worker (never the GUI thread).  ``interval`` and
    ``deadline`` are injectable so tests run with zero real waiting.
    Consecutive transient read errors are tolerated up to
    ``max_read_failures``; 401/403 will not heal and report unknown
    immediately.  Signals are per instance (audit 6.3.2a D9) and
    connect-before-start, so a fast completion cannot race the wiring.
    ``stop_event`` lets a closing panel end the watch between ticks.
    """

    def __init__(self, cfg: dict, upid: str, *, interval: float = 3.0,
                 deadline: float = 900.0, max_read_failures: int = 5,
                 timeout: float = 15, tag=None,
                 stop_event: threading.Event | None = None):
        super().__init__()
        self.cfg = cfg
        self.upid = upid
        self.interval = interval
        self.deadline = deadline
        self.max_read_failures = max_read_failures
        self.timeout = timeout
        self.tag = tag
        self._stop = stop_event if stop_event is not None \
            else threading.Event()
        self.signals = _TrackerSignals()
        self.setAutoDelete(True)

    def run(self):
        provider: PbsProvider | None = None
        result: tuple[str, str] | None = None
        try:
            provider = PbsProvider(self.cfg, timeout=self.timeout)
            result = self._poll(provider)
        except Exception as e:  # noqa: BLE001 — worker boundary
            logger.debug("pbs task tracker error", exc_info=True)
            result = ("unknown", _short(str(e)))
        finally:
            if provider is not None:
                provider.close()
            if result is not None:
                try:
                    self.signals.update.emit(self.tag, result)
                except RuntimeError:
                    pass
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

    def _poll(self, provider: PbsProvider) -> tuple[str, str] | None:
        deadline = time.monotonic() + self.deadline
        failures = 0
        state, detail = "running", ""
        while not self._stop.is_set():
            try:
                state, detail = provider.task_status(self.upid)
                failures = 0
            except Exception as e:  # noqa: BLE001 — read failures only
                if isinstance(e, PermissionError) or \
                        getattr(e, "status_code", 0) in (401, 403):
                    # will not heal by polling; and it is NOT the task
                    # failing — the state is just unreadable
                    return ("unknown",
                            "status not readable (authentication or "
                            f"rights): {_short(str(e))}")
                failures += 1
                if failures >= self.max_read_failures:
                    return ("unknown",
                            "status unreadable: " + _short(str(e)))
                state = "running"  # transient — keep watching
            else:
                if state != "running":
                    return state, detail
            if time.monotonic() >= deadline:
                return ("timeout",
                        "watch deadline reached — the task may still "
                        "be running on the server")
            if self.interval > 0:
                time.sleep(self.interval)
        return None  # stopped by the closing panel: nothing to report

    @property
    def stop_event(self) -> threading.Event:
        return self._stop


def _short(text: str, limit: int = 300) -> str:
    """One-line, bounded detail — safe for status lines and logs."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
