"""M2.2: тесты командной палитры (Ctrl+K).

Реестр собирается из фейковых ActionSpec — палитра не должна знать о
конкретных действиях; проверяются фильтрация по выделению, поиск,
клавиатура (Enter/Esc/стрелки) и подсветка опасных действий.
"""
from PySide6.QtCore import Qt

from virtdeck.ui.action_registry import (
    SCOPE_GLOBAL,
    SCOPE_HOST,
    SCOPE_VM,
    ActionRegistry,
    ActionSpec,
    Selection,
)
from virtdeck.ui.action_specs import register_tree_actions
from virtdeck.ui.command_palette import CommandPalette
from virtdeck.ui.theme import Color


def _registry(invoked):
    reg = ActionRegistry()
    reg.register(ActionSpec(
        action_id="global.refresh", label="Refresh data", icon="refresh",
        scopes=frozenset({SCOPE_GLOBAL}),
        invoke=lambda sel: invoked.append("refresh"),
    ))
    reg.register(ActionSpec(
        action_id="vm.start", label="Start", icon="start",
        scopes=frozenset({SCOPE_VM}),
        enabled=lambda sel: (sel.vm is not None and not sel.vm.template
                             and sel.vm.status_value != "running"),
        invoke=lambda sel: invoked.append("start"),
    ))
    reg.register(ActionSpec(
        action_id="global.quit", label="Quit", dangerous=True,
        scopes=frozenset({SCOPE_GLOBAL}),
        invoke=lambda sel: invoked.append("quit"),
    ))
    return reg


class _FakeVm:
    template = False
    status_value = "stopped"


def _labels(pal):
    return [pal._list.topLevelItem(i).text(0)
            for i in range(pal._list.topLevelItemCount())]


class TestCommandPalette:
    def test_open_shows_applicable_actions(self, qtbot):
        pal = CommandPalette(_registry([]), lambda: Selection())
        qtbot.addWidget(pal)
        pal.open_for()
        assert pal.isVisible()
        # пустое выделение: только глобальные действия
        assert _labels(pal) == ["Refresh data", "Quit"]

    def test_enter_invokes_first_match_and_closes(self, qtbot):
        invoked = []
        pal = CommandPalette(_registry(invoked), lambda: Selection())
        qtbot.addWidget(pal)
        pal.open_for()
        qtbot.keyClick(pal._input, Qt.Key_Return)
        assert invoked == ["refresh"]
        assert not pal.isVisible()

    def test_query_filters_and_invokes(self, qtbot):
        invoked = []
        pal = CommandPalette(_registry(invoked), lambda: Selection())
        qtbot.addWidget(pal)
        pal.open_for()
        qtbot.keyClicks(pal._input, "quit")
        assert _labels(pal) == ["Quit"]
        qtbot.keyClick(pal._input, Qt.Key_Return)
        assert invoked == ["quit"]

    def test_arrow_navigation_before_enter(self, qtbot):
        invoked = []
        pal = CommandPalette(_registry(invoked), lambda: Selection())
        qtbot.addWidget(pal)
        pal.open_for()
        qtbot.keyClick(pal._input, Qt.Key_Down)   # Refresh -> Quit
        qtbot.keyClick(pal._input, Qt.Key_Return)
        assert invoked == ["quit"]

    def test_escape_closes(self, qtbot):
        invoked = []
        pal = CommandPalette(_registry(invoked), lambda: Selection())
        qtbot.addWidget(pal)
        pal.open_for()
        qtbot.keyClick(pal._input, Qt.Key_Escape)
        assert not pal.isVisible()
        assert invoked == []

    def test_no_matching_actions_row(self, qtbot):
        pal = CommandPalette(_registry([]), lambda: Selection())
        qtbot.addWidget(pal)
        pal.open_for()
        qtbot.keyClicks(pal._input, "zzz")
        assert _labels(pal) == ["No matching actions"]
        # пустышка не выполняется
        qtbot.keyClick(pal._input, Qt.Key_Return)

    def test_selection_filters_and_vm_actions(self, qtbot):
        invoked = []
        sel = Selection(kind=SCOPE_VM, label="web-01", host_name="h",
                        node="n1", vmid=101, vm=_FakeVm())
        pal = CommandPalette(_registry(invoked), lambda: sel)
        qtbot.addWidget(pal)
        pal.open_for()
        # остановленная ВМ: Start доступен, глобальные тоже
        assert _labels(pal) == ["Refresh data", "Start", "Quit"]
        assert pal._header.text() == "web-01"
        pal._input.clear()
        qtbot.keyClicks(pal._input, "start")
        qtbot.keyClick(pal._input, Qt.Key_Return)
        assert invoked == ["start"]

    def test_running_vm_disables_unavailable_actions(self, qtbot):
        vm = _FakeVm()
        vm.status_value = "running"
        sel = Selection(kind=SCOPE_VM, label="web-01", vm=vm)
        pal = CommandPalette(_registry([]), lambda: sel)
        qtbot.addWidget(pal)
        pal.open_for()
        # Start запрещён для работающей ВМ → остаются только глобальные
        assert _labels(pal) == ["Refresh data", "Quit"]

    def test_multi_selection_shows_bulk_not_singles(self, qtbot):
        """Мульти-выделение: массовые действия вместо одиночных."""
        class _Sig:
            def __init__(self):
                self.log = []

            def emit(self, *a):
                self.log.append(a)

        class _Tree:
            def __init__(self):
                self.vm_action_requested = _Sig()
                self.bulk_vm_action_requested = _Sig()
                self.console_requested = _Sig()

        tree = _Tree()
        reg = ActionRegistry()
        register_tree_actions(reg, tree)
        reg.register(ActionSpec(
            action_id="global.refresh", label="Refresh data",
            scopes=frozenset({SCOPE_GLOBAL}), invoke=lambda s: None,
        ))
        vm = _FakeVm()
        keys = (("h1", 100, "pve01"), ("h1", 101, "pve01"))
        sel = Selection(kind=SCOPE_VM, label="alpha", host_name="h1",
                        node="pve01", vmid=100, vm=vm, vm_keys=keys)
        pal = CommandPalette(reg, lambda: sel)
        qtbot.addWidget(pal)
        pal.open_for()
        labels = _labels(pal)
        assert "Start" not in labels          # одиночное скрыто
        assert "Stop" not in labels
        assert "Start all" in labels          # массовые доступны
        assert "Stop all" in labels
        for i in range(pal._list.topLevelItemCount()):
            item = pal._list.topLevelItem(i)
            if item.text(0) == "Stop all":
                pal._list.setCurrentItem(item)
                qtbot.keyClick(pal._input, Qt.Key_Return)
                break
        assert tree.bulk_vm_action_requested.log == [
            (list(keys), "stop"),
        ]

    def test_dangerous_highlighted(self, qtbot):
        pal = CommandPalette(_registry([]), lambda: Selection())
        qtbot.addWidget(pal)
        pal.open_for()
        for i in range(pal._list.topLevelItemCount()):
            item = pal._list.topLevelItem(i)
            if item.text(0) == "Quit":
                assert item.foreground(0).color().name() == Color.DANGER
                break
        else:
            raise AssertionError("Quit not in list")

    def test_host_selection_shows_host_actions(self, qtbot):
        """Выделен хост: палитра предлагает host-действия реестра."""
        from virtdeck.ui.action_specs import register_tree_actions

        class _Tree:
            pass

        reg = ActionRegistry()
        register_tree_actions(reg, _Tree())
        reg.register(ActionSpec(
            action_id="global.refresh", label="Refresh data",
            scopes=frozenset({SCOPE_GLOBAL}), invoke=lambda s: None,
        ))
        sel = Selection(kind=SCOPE_HOST, label="pve01", host_name="h1",
                        node="pve01", key=("host", "pve01", "h1"))
        pal = CommandPalette(reg, lambda: sel)
        qtbot.addWidget(pal)
        pal.open_for()
        labels = _labels(pal)
        assert "Create VM" in labels
        assert "Delete host" in labels
        assert "Refresh token" in labels
        assert "Create cluster…" in labels
        assert "Start" not in labels            # VM-действия скрыты

    def test_retheme_updates_icon_size(self, qtbot):
        """E2 (аудит 2026-10-06): смена темы с другим icon_size (Breeze 24px)
        обновляет размер иконок списка палитры, созданной ранее."""
        from virtdeck.ui import icons as icons_mod

        pal = CommandPalette(ActionRegistry(), lambda: Selection())
        qtbot.addWidget(pal)
        old = icons_mod.base_size()
        try:
            icons_mod.set_base_size(24)
            pal.retheme()
            assert pal._list.iconSize().height() == 24
        finally:
            icons_mod.set_base_size(old)
