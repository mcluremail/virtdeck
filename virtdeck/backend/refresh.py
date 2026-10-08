"""Hard/soft refresh cycle state — pure logic, no Qt.

RefreshCoordinator keeps generations, pending sets and guards that
MainWindow uses to decide which worker results are current, when a cycle
is complete and when a stuck soft refresh should be reset by timeout.
"""

from __future__ import annotations

from typing import Any


class RefreshCoordinator:
    """Hard and soft refresh cycle state.

    Invariants:
    - a worker's result is current only if its generation matches the
      current one (gen == 0 is treated as a legacy call without a generation);
    - the hard cycle completes once all workers of the generation reported;
    - the soft cycle is reset by timeout or by a new hard refresh.
    """

    def __init__(self, soft_timeout: float = 90.0) -> None:
        self.soft_timeout = soft_timeout
        self._hard_gen = 0
        self._hard_pending: set[Any] = set()
        self._soft_gen = 0
        self._soft_running = False
        self._soft_start = 0.0
        self._soft_done = 0
        self._soft_expected = 0

    # -- hard refresh ---------------------------------------------------

    @property
    def hard_gen(self) -> int:
        return self._hard_gen

    def begin_hard(self) -> int:
        """Start a hard refresh: reset pending. Returns the new generation."""
        self._hard_gen += 1
        self._hard_pending = set()
        return self._hard_gen

    def track_hard(self, worker: Any) -> None:
        self._hard_pending.add(worker)

    def hard_done(self, worker: Any, gen: int) -> None:
        if gen == self._hard_gen:
            self._hard_pending.discard(worker)

    def hard_result_current(self, gen: int) -> bool:
        """Whether a hard worker's result is current (gen == 0 — legacy call)."""
        return gen == 0 or gen == self._hard_gen

    @property
    def hard_pending_count(self) -> int:
        return len(self._hard_pending)

    # -- soft refresh ---------------------------------------------------

    @property
    def soft_gen(self) -> int:
        return self._soft_gen

    @property
    def soft_running(self) -> bool:
        return self._soft_running

    @property
    def soft_expected(self) -> int:
        return self._soft_expected

    def reset_soft(self) -> None:
        """Invalidate the running soft cycle (new hard refresh / timeout)."""
        self._soft_gen += 1
        self._soft_running = False
        self._soft_done = 0
        self._soft_expected = 0

    def finish_soft(self) -> None:
        """Clear the running flag without invalidating the generation."""
        self._soft_running = False

    def soft_timed_out(self, now: float) -> bool:
        return self._soft_running and (now - self._soft_start > self.soft_timeout)

    def begin_soft(self, expected: int, now: float) -> int:
        """Claim ownership of a new soft cycle. Returns the generation."""
        self._soft_running = True
        self._soft_start = now
        self._soft_done = 0
        self._soft_expected = expected
        self._soft_gen += 1
        return self._soft_gen

    def soft_result_current(self, gen: int) -> bool:
        return gen == self._soft_gen

    def soft_result(self, gen: int) -> bool:
        """Account for a soft worker's result; True if it was the last one."""
        if gen != self._soft_gen:
            return False
        self._soft_done += 1
        return self._soft_done >= self._soft_expected
