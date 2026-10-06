"""M2.1: тесты ядра реестра действий (чистый Python, без Qt).

fuzzy_score — ранжирование совпадений; ActionRegistry — фильтрация по
scope/enabled и поиск; ActionSpec — декларативное описание действия.
"""
from virtdeck.ui.action_registry import (
    SCOPE_GLOBAL,
    SCOPE_HOST,
    SCOPE_VM,
    ActionRegistry,
    ActionSpec,
    Selection,
    fuzzy_score,
)


def _spec(action_id="a", label="Start", scopes=frozenset({SCOPE_GLOBAL}), **kw):
    return ActionSpec(action_id=action_id, label=label, scopes=scopes, **kw)


class TestFuzzyScore:
    def test_empty_query_matches_weakly(self):
        assert fuzzy_score("", "Start") == 1

    def test_prefix_beats_word_start_beats_substring(self):
        assert fuzzy_score("start", "Start VM") == 100
        # «start» внутри «Restart» — не с границы слова
        assert fuzzy_score("start", "Restart") == 60
        # «IO» после границы слова («Network IO»)
        assert fuzzy_score("io", "Network IO") == 80

    def test_subsequence_with_gap_penalty(self):
        # подпоследовательность совпадает, но ценится ниже подстроки
        score = fuzzy_score("svm", "Start VM")
        assert 0 < score < 60
        # больше «дырок» — ниже счёт: a..c..e (2 дырки) против a..de (1)
        assert fuzzy_score("ace", "abcde") == 30
        assert fuzzy_score("ade", "abcde") == 35

    def test_no_match(self):
        assert fuzzy_score("xyz", "Start VM") == 0
        assert fuzzy_score("sm", "Start") == 0  # m нет после s

    def test_case_insensitive(self):
        assert fuzzy_score("ST", "start") == 100
        assert fuzzy_score("vm", "VM 101") == 100


class TestSelection:
    def test_empty_selection(self):
        assert Selection().is_empty
        assert not Selection(kind=SCOPE_VM).is_empty


class TestRegistry:
    def test_registration_order_preserved(self):
        reg = ActionRegistry()
        reg.register(_spec("b", "Backup"))
        reg.register(_spec("a", "Add server"))
        assert [s.action_id for s in reg.all()] == ["b", "a"]

    def test_actions_for_filters_by_scope(self):
        reg = ActionRegistry()
        reg.register(_spec("g", "Refresh", scopes=frozenset({SCOPE_GLOBAL})))
        reg.register(_spec("v", "Start", scopes=frozenset({SCOPE_VM})))
        reg.register(_spec("h", "Reboot node", scopes=frozenset({SCOPE_HOST})))
        assert [s.action_id for s in reg.actions_for(Selection())] == ["g"]
        assert [s.action_id for s in reg.actions_for(Selection(kind=SCOPE_VM))] == ["g", "v"]

    def test_global_scope_always_applicable(self):
        reg = ActionRegistry()
        reg.register(_spec("g", "Refresh", scopes=frozenset({SCOPE_GLOBAL})))
        # глобальные действия видны и когда выделена ВМ
        assert [s.action_id for s in reg.actions_for(Selection(kind=SCOPE_VM))] == ["g"]

    def test_actions_for_applies_enabled_predicate(self):
        reg = ActionRegistry()
        reg.register(_spec("v", "Start", scopes=frozenset({SCOPE_VM}),
                           enabled=lambda sel: not sel.is_empty and sel.vmid > 100))
        assert reg.actions_for(Selection(kind=SCOPE_VM, vmid=50)) == []
        assert len(reg.actions_for(Selection(kind=SCOPE_VM, vmid=101))) == 1


class TestSearch:
    def test_empty_query_returns_all_applicable_in_order(self):
        reg = ActionRegistry()
        reg.register(_spec("v", "Start", scopes=frozenset({SCOPE_VM})))
        reg.register(_spec("g", "Refresh"))
        assert [s.action_id for s in reg.search("", Selection(kind=SCOPE_VM))] == ["v", "g"]

    def test_ranking_prefix_first(self):
        reg = ActionRegistry()
        reg.register(_spec("r", "Restart"))
        reg.register(_spec("s", "Start VM"))
        assert [s.action_id for s in reg.search("start", Selection())] == ["s", "r"]

    def test_keywords_match(self):
        reg = ActionRegistry()
        reg.register(_spec("q", "Quit", keywords=("exit", "shutdown app")))
        assert reg.search("exit", Selection())[0].action_id == "q"

    def test_keywords_rank_below_direct_label(self):
        reg = ActionRegistry()
        reg.register(_spec("k", "Reboot all", keywords=("start",)))
        reg.register(_spec("l", "Start"))
        assert [s.action_id for s in reg.search("start", Selection())] == ["l", "k"]

    def test_limit(self):
        reg = ActionRegistry()
        for i in range(10):
            reg.register(_spec(f"a{i}", f"Action {i:02} prefix"))
        assert len(reg.search("action", Selection(), limit=3)) == 3
        # лучшие (по порядку регистрации при равном счёте) остаются
        assert [s.action_id for s in reg.search("action", Selection(), limit=3)] == [
            "a0", "a1", "a2",
        ]

    def test_no_results(self):
        reg = ActionRegistry()
        reg.register(_spec("g", "Refresh"))
        assert reg.search("zzz", Selection()) == []

    def test_scope_filter_applies_to_search(self):
        reg = ActionRegistry()
        reg.register(_spec("v", "Start VM", scopes=frozenset({SCOPE_VM})))
        assert reg.search("start", Selection()) == []
        assert len(reg.search("start", Selection(kind=SCOPE_VM))) == 1
