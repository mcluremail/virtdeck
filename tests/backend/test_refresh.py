"""RefreshCoordinator tests: generations, pending, guards, timeouts."""

from virtdeck.backend.refresh import RefreshCoordinator


class TestHard:
    def test_begin_hard_bumps_generation_and_clears_pending(self):
        c = RefreshCoordinator()
        g1 = c.begin_hard()
        w = object()
        c.track_hard(w)
        assert c.hard_pending_count == 1
        g2 = c.begin_hard()
        assert g2 == g1 + 1
        assert c.hard_pending_count == 0

    def test_stale_result_ignored(self):
        c = RefreshCoordinator()
        g1 = c.begin_hard()
        c.begin_hard()
        assert not c.hard_result_current(g1)
        assert c.hard_result_current(c.hard_gen)
        # gen == 0 — legacy call without a generation, always current
        assert c.hard_result_current(0)

    def test_hard_done_discards_only_current_gen(self):
        c = RefreshCoordinator()
        g = c.begin_hard()
        w = object()
        c.track_hard(w)
        c.hard_done(w, g + 5)  # worker from a stale generation
        assert c.hard_pending_count == 1
        c.hard_done(w, g)
        assert c.hard_pending_count == 0

    def test_hard_does_not_touch_soft(self):
        c = RefreshCoordinator()
        sg = c.begin_soft(2, now=100.0)
        c.begin_hard()
        # the soft generation is not invalidated by begin_hard itself
        assert c.soft_result_current(sg)
        assert c.soft_running


class TestSoft:
    def test_begin_soft_claims_and_bumps(self):
        c = RefreshCoordinator()
        g1 = c.begin_soft(3, now=10.0)
        assert c.soft_running
        g2 = c.begin_soft(1, now=20.0)
        assert g2 == g1 + 1
        assert c.soft_expected == 1

    def test_soft_result_counts_to_expected(self):
        c = RefreshCoordinator()
        g = c.begin_soft(2, now=0.0)
        assert not c.soft_result(g)
        assert c.soft_result(g)

    def test_stale_soft_result_ignored(self):
        c = RefreshCoordinator()
        g1 = c.begin_soft(1, now=0.0)
        c.reset_soft()
        g2 = c.begin_soft(1, now=1.0)
        assert g2 != g1
        assert not c.soft_result(g1)
        assert c.soft_result_current(g2)
        assert not c.soft_result_current(g1)

    def test_reset_soft_stops_running(self):
        c = RefreshCoordinator()
        c.begin_soft(5, now=0.0)
        c.reset_soft()
        assert not c.soft_running
        assert c.soft_expected == 0

    def test_finish_soft_keeps_generation(self):
        c = RefreshCoordinator()
        g = c.begin_soft(1, now=0.0)
        c.finish_soft()
        assert not c.soft_running
        assert c.soft_result_current(g)

    def test_timeout(self):
        c = RefreshCoordinator(soft_timeout=90)
        c.begin_soft(3, now=100.0)
        assert not c.soft_timed_out(100.0 + 90)
        assert not c.soft_timed_out(189.9)
        assert c.soft_timed_out(190.1)
        # a non-running loop does not "expire"
        c.reset_soft()
        assert not c.soft_timed_out(9999.0)
