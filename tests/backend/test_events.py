"""Event Bus tests (seed v3.0)."""

import threading

import pytest

from virtdeck.backend.events import Event, EventBus


class TestSubscribe:
    def test_publish_delivers_to_subscriber(self):
        bus = EventBus()
        seen = []
        bus.subscribe("t", seen.append)
        n = bus.publish(Event("t", {"x": 1}))
        assert n == 1
        assert len(seen) == 1
        assert seen[0].topic == "t"
        assert seen[0].payload == {"x": 1}

    def test_no_subscribers_returns_zero(self):
        bus = EventBus()
        assert bus.publish(Event("t")) == 0

    def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        seen = []
        off = bus.subscribe("t", seen.append)
        assert off() is None
        assert bus.publish(Event("t")) == 0
        off()  # idempotent

    def test_multiple_subscribers_all_delivered(self):
        bus = EventBus()
        a, b = [], []
        bus.subscribe("t", a.append)
        bus.subscribe("t", b.append)
        assert bus.publish(Event("t")) == 2
        assert a and b

    def test_topics_isolated(self):
        bus = EventBus()
        seen = []
        bus.subscribe("a", seen.append)
        bus.publish(Event("b"))
        assert seen == []

    def test_subscriber_count_and_clear(self):
        bus = EventBus()
        bus.subscribe("t", lambda e: None)
        assert bus.subscriber_count("t") == 1
        bus.clear()
        assert bus.subscriber_count("t") == 0


class TestIsolation:
    def test_handler_exception_does_not_break_others(self):
        bus = EventBus()
        seen = []

        def bad(_):
            raise RuntimeError("boom")

        bus.subscribe("t", bad)
        bus.subscribe("t", seen.append)
        assert bus.publish(Event("t")) == 1
        assert len(seen) == 1

    def test_event_frozen(self):
        import dataclasses

        e = Event("t", 1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.topic = "x"

    def test_threaded_publish(self):
        bus = EventBus()
        seen = []
        bus.subscribe("t", lambda e: seen.append(e.payload))

        def worker():
            for i in range(50):
                bus.publish(Event("t", i))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(seen) == sorted(list(range(50)) * 4)
