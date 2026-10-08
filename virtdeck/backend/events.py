"""Lightweight event bus — seed for ROADMAP v3.0 (Event Bus).

Minimalist pub/sub with no Qt dependencies. Thread safety: subscription
mutations are under a lock; handlers run in the publisher's thread —
publish from worker threads via QueuedConnection/InvokeMethod.

Usage:
    bus = EventBus()
    off = bus.subscribe("node.status_changed", lambda e: ...)
    bus.publish(Event("node.status_changed", {"node": "n1", "status": "online"}))
    off()  # unsubscribe
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    """Immutable bus event: topic + arbitrary payload."""

    topic: str
    payload: Any = None


Handler = Callable[[Event], None]


class EventBus:
    """Registry of subscribers by topic with isolated delivery.

    An exception in one handler is logged and does not prevent delivery
    to the remaining subscribers of the same event.
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = {}
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        """Subscribe; returns an unsubscribe function (idempotent)."""
        with self._lock:
            self._subs.setdefault(topic, []).append(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._subs.get(topic)
                if handlers is not None and handler in handlers:
                    handlers.remove(handler)
                    if not handlers:
                        del self._subs[topic]

        return unsubscribe

    def publish(self, event: Event) -> int:
        """Deliver an event to the topic's subscribers. Returns delivery count."""
        with self._lock:
            handlers = list(self._subs.get(event.topic, ()))
        delivered = 0
        for handler in handlers:
            try:
                handler(event)
                delivered += 1
            except Exception:
                logger.exception("event handler failed: topic=%s", event.topic)
        return delivered

    def subscriber_count(self, topic: str) -> int:
        with self._lock:
            return len(self._subs.get(topic, ()))

    def clear(self) -> None:
        """Drop all subscriptions (for tests)."""
        with self._lock:
            self._subs.clear()
