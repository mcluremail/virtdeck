"""Columns must be draggable in all tables and trees.

In Qt6 QHeaderView is created with sectionsMovable=False for QTableWidget,
so every table site calls enable_column_reorder() explicitly.
Also: ResizeToContents/Fixed columns cannot be dragged, so they
switch to Interactive with content-based width fitting.
"""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPointingDevice
from PySide6.QtWidgets import QApplication, QHeaderView, QTableWidgetItem

from virtdeck.ui.detail_panel._table_utils import make_table


class TestMakeTable:
    def test_columns_movable(self, qtbot):
        t = make_table(
            ["A", "B"],
            [(QHeaderView.Interactive, 80), (QHeaderView.Stretch, None)],
        )
        qtbot.addWidget(t)
        assert t.horizontalHeader().sectionsMovable()

    def test_resize_to_contents_becomes_interactive(self, qtbot):
        t = make_table(
            ["A", "B"],
            [(QHeaderView.ResizeToContents, None), (QHeaderView.Stretch, None)],
        )
        qtbot.addWidget(t)
        assert t.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive

    def test_stretch_becomes_interactive(self, qtbot):
        """Stretch cannot be dragged either — all columns Interactive, the last
        becomes the filler (stretchLastSection)."""
        t = make_table(
            ["A", "B", "C"],
            [(QHeaderView.Stretch, None), (QHeaderView.Stretch, None),
             (QHeaderView.Stretch, None)],
        )
        qtbot.addWidget(t)
        h = t.horizontalHeader()
        for col in range(3):
            assert h.sectionResizeMode(col) == QHeaderView.Interactive, col
        assert h.stretchLastSection()
        assert t.property("_pve_autofit_cols") == {0, 1}

    def test_autofit_capped(self, qtbot):
        t = make_table(
            ["A", "B"],
            [(QHeaderView.Stretch, None), (QHeaderView.Stretch, None)],
        )
        qtbot.addWidget(t)
        t.setRowCount(1)
        t.setItem(0, 0, QTableWidgetItem("x" * 300))
        qtbot.wait(150)
        assert t.columnWidth(0) <= 480


class TestTableAutofit:
    """RTC/Fixed -> Interactive + content-based width until manual resize."""

    def test_autofit_after_fill(self, qtbot):
        t = make_table(
            ["A", "B"],
            [(QHeaderView.ResizeToContents, None), (QHeaderView.Stretch, None)],
        )
        qtbot.addWidget(t)
        default = t.columnWidth(0)
        t.setRowCount(1)
        t.setItem(0, 0, QTableWidgetItem("x" * 60))
        qtbot.wait(150)  # debounce 60ms
        assert t.columnWidth(0) > default

    def test_user_press_disables_autofit(self, qtbot):
        t = make_table(
            ["A", "B"],
            [(QHeaderView.ResizeToContents, None), (QHeaderView.Stretch, None)],
        )
        qtbot.addWidget(t)
        header = t.horizontalHeader()
        x = header.sectionViewportPosition(0) + 5
        QApplication.sendEvent(header.viewport(), QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(x, 5), QPointF(x, 5),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPointingDevice.primaryPointingDevice()))
        t.setRowCount(1)
        t.setItem(0, 0, QTableWidgetItem("x" * 60))
        qtbot.wait(150)
        assert 0 not in t.property("_pve_autofit_cols")


class TestDirectTables:
    """Widgets with hand-rolled tables (bypassing make_table)."""

    @pytest.mark.parametrize(
        "factory",
        [
            lambda: _mk("virtdeck.ui.widgets.vm_options_widget",
                        "VmOptionsWidget"),
            lambda: _mk("virtdeck.ui.widgets.vm_hardware_widget",
                        "VmHardwareWidget"),
            lambda: _mk("virtdeck.ui.widgets.vm_pool_widget",
                        "VmPoolWidget"),
            lambda: _mk("virtdeck.ui.widgets.vm_task_history_widget",
                        "VmTaskHistoryWidget"),
            lambda: _mk("virtdeck.ui.widgets.cluster_tasks_widget",
                        "ClusterTasksWidget"),
        ],
        ids=["options", "hardware", "pool", "task_history", "cluster_tasks"],
    )
    def test_table_columns_movable(self, qtbot, factory):
        w = factory()
        qtbot.addWidget(w)
        assert w.table.horizontalHeader().sectionsMovable()

    @pytest.mark.parametrize(
        "factory, resizable_cols",
        [
            (lambda: _mk("virtdeck.ui.widgets.vm_options_widget",
                         "VmOptionsWidget"), [0]),
            (lambda: _mk("virtdeck.ui.widgets.vm_hardware_widget",
                         "VmHardwareWidget"), [0]),
            (lambda: _mk("virtdeck.ui.widgets.vm_pool_widget",
                         "VmPoolWidget"), [1, 2, 3, 4, 5]),
            (lambda: _mk("virtdeck.ui.widgets.vm_task_history_widget",
                         "VmTaskHistoryWidget"), [0, 1, 2, 3]),
            (lambda: _mk("virtdeck.ui.widgets.cluster_tasks_widget",
                         "ClusterTasksWidget"), [2, 3]),
        ],
        ids=["options", "hardware", "pool", "task_history", "cluster_tasks"],
    )
    def test_no_resize_to_contents(self, qtbot, factory, resizable_cols):
        """Former RTC/Stretch columns must be Interactive (mouse-draggable);
        the last column is the filler."""
        w = factory()
        qtbot.addWidget(w)
        header = w.table.horizontalHeader()
        for col in range(w.table.columnCount()):
            mode = header.sectionResizeMode(col)
            if col in resizable_cols:
                assert mode == QHeaderView.Interactive, (col, mode)
            else:
                assert mode != QHeaderView.ResizeToContents, (col, mode)
                assert mode != QHeaderView.Stretch, (col, mode)
        assert header.stretchLastSection()

    def test_pbs_panel_tables_movable(self, qtbot):
        from virtdeck.ui.pbs_panel import PbsPanel
        panel = PbsPanel()
        qtbot.addWidget(panel)
        for name in ("_ds_table", "_snap_table", "_jobs_table"):
            table = getattr(panel, name)
            header = table.horizontalHeader()
            assert header.sectionsMovable(), name
            assert header.stretchLastSection(), name
            for col in range(table.columnCount()):
                assert header.sectionResizeMode(
                    col) != QHeaderView.Stretch, (name, col)

    def test_search_dialog_tree_movable(self, qtbot):
        from virtdeck.ui.search_dialog import GlobalSearchDialog
        dlg = GlobalSearchDialog(lambda: (object(), object(), object(), object()))
        qtbot.addWidget(dlg)
        assert dlg._tree.header().sectionsMovable()


class TestTreePanelHeader:
    def test_single_column_header_hidden(self, qtbot):
        """2026-10-08 redesign: single column, header hidden, the info line
        is drawn by the delegate from INFO_ROLE; column-width persistence removed."""
        from virtdeck.ui.tree_panel import TreePanel, _TwoLineDelegate
        tp = TreePanel([])
        qtbot.addWidget(tp)
        assert tp.tree.isHeaderHidden()
        assert tp.tree.columnCount() == 1
        assert isinstance(tp.tree.itemDelegate(), _TwoLineDelegate)
        assert not hasattr(tp, "_save_tree_columns")


def _mk(module_name, class_name):
    """Import and create the widget (keeps parameterization terse)."""
    import importlib
    mod = importlib.import_module(module_name)
    return getattr(mod, class_name)()
