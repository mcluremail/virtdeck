"""QRunnable workers for PBS operations (B17 stage 2).

A single generic worker: builds a fresh PbsProvider per run, calls one
provider method, emits ``result`` or ``failed``. Long-lived objects
(panels, tree) connect to the signals; workers are tracked by callers.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from .provider import PbsProvider

logger = logging.getLogger(__name__)


class _Signals(QObject):
    done = Signal(object, object)   # tag, result
    failed = Signal(object, str)    # tag, error message
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
