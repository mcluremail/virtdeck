"""M2.2: command palette (Ctrl+K).

A modeless frameless overlay above the main window: a query line +
fuzzy output from ActionRegistry. Actions are filtered by the current
tree selection (Selection from TreePanel.current_selection);
Enter/click runs the invoke closure. The palette knows nothing about
specific actions — specs are supplied by
action_specs.build_registry(mainwindow).
"""

import logging

from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .action_registry import Selection
from .i18n import tr
from .icons import base_size, get_icon
from .theme import Color

logger = logging.getLogger(__name__)

_SPEC_ROLE = Qt.UserRole + 1
_PALETTE_WIDTH = 520
_LIST_MAX_HEIGHT = 400


class CommandPalette(QDialog):
    """Fuzzy palette of actions applicable to the selected tree object."""

    def __init__(self, registry, selection_provider, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._selection_provider = selection_provider
        self._selection = Selection()
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._frame = QFrame(objectName="paletteFrame")
        root.addWidget(self._frame)
        lay = QVBoxLayout(self._frame)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Context: name of the selected object ("actions on ...")
        self._header = QLabel("")
        self._header.hide()
        lay.addWidget(self._header)

        self._input = QLineEdit()
        self._input.setPlaceholderText(tr("Type a command..."))
        self._input.setClearButtonEnabled(True)
        self._input.textChanged.connect(self._refresh)
        self._input.installEventFilter(self)
        lay.addWidget(self._input)

        self._list = QTreeWidget()
        self._list.setColumnCount(2)
        self._list.setHeaderHidden(True)
        self._list.setRootIsDecorated(False)
        self._list.setUniformRowHeights(True)
        self._list.setAllColumnsShowFocus(True)
        self._list.setFocusPolicy(Qt.NoFocus)   # navigation via arrows from the input
        self._list.setIconSize(QSize(base_size(), base_size()))
        # label takes the full width, shortcut — resize-to-content on the right
        header = self._list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionsClickable(False)
        self._list.itemClicked.connect(self._invoke_item)
        lay.addWidget(self._list)

        self.retheme()

    # ── Public API ──────────────────────────────────────────────────

    def open_for(self):
        """Open the palette over the current tree selection."""
        try:
            self._selection = self._selection_provider() or Selection()
        except Exception:
            logger.exception("palette selection provider failed")
            self._selection = Selection()
        label = "" if self._selection.is_empty else self._selection.label
        self._header.setText(label)
        self._header.setVisible(bool(label))
        self._input.clear()
        self._refresh("")
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus()
        self._reposition()

    def retheme(self):
        """Restyle on theme change (skeleton; content is rebuilt on the
        next open from fresh tokens)."""
        self._list.setIconSize(QSize(base_size(), base_size()))
        self._frame.setStyleSheet(
            f"QFrame#paletteFrame {{ background: {Color.RAISED};"
            f" border: 1px solid {Color.BORDER_STRONG}; border-radius: 10px; }}"
        )
        self._input.setStyleSheet(
            f"QLineEdit {{ background: {Color.PANEL}; color: {Color.TEXT};"
            f" border: 1px solid {Color.BORDER}; border-radius: 6px;"
            " padding: 6px 10px; font-size: 14px;"
            f" selection-background-color: {Color.ACCENT}; }}"
            f"QLineEdit:focus {{ border: 1px solid {Color.ACCENT}; }}"
        )
        self._header.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 12px;")
        self._list.setStyleSheet(
            f"QTreeWidget {{ background: transparent; color: {Color.TEXT};"
            " border: none; font-size: 13px; outline: 0; }"
            "QTreeWidget::item { padding: 3px; border-radius: 4px; }"
            f"QTreeWidget::item:selected {{ background: {Color.ACCENT};"
            f" color: {Color.ON_ACCENT}; }}"
        )

    # ── Internal ────────────────────────────────────────────────────

    def _refresh(self, query):
        self._list.clear()
        specs = self._registry.search(query, self._selection)
        if not specs:
            empty = QTreeWidgetItem([tr("No matching actions"), ""])
            empty.setFlags(Qt.NoItemFlags)
            empty.setForeground(0, QBrush(QColor(Color.DISABLED)))
            self._list.addTopLevelItem(empty)
        for spec in specs:
            item = QTreeWidgetItem([spec.label, spec.shortcut])
            item.setIcon(0, get_icon(spec.icon) if spec.icon else QIcon())
            item.setData(0, _SPEC_ROLE, spec)
            if spec.dangerous:
                item.setForeground(0, QBrush(QColor(Color.DANGER)))
            if spec.shortcut:
                item.setTextAlignment(1, int(Qt.AlignRight | Qt.AlignVCenter))
                item.setForeground(1, QBrush(QColor(Color.TEXT_SEC)))
            self._list.addTopLevelItem(item)
        if specs:
            self._list.setCurrentItem(self._list.topLevelItem(0))
        row_h = self._list.sizeHintForRow(0) or (base_size() + 14)
        rows = max(self._list.topLevelItemCount(), 1)
        self._list.setFixedHeight(min(rows * row_h + 10, _LIST_MAX_HEIGHT))
        if self.isVisible():
            self.adjustSize()
            self._reposition()

    def _invoke_item(self, item):
        spec = item.data(0, _SPEC_ROLE) if item is not None else None
        if spec is None or spec.invoke is None:
            return
        try:
            spec.invoke(self._selection)
        except Exception:
            logger.exception("palette action %s failed", spec.action_id)
        self.accept()

    def _invoke_current(self):
        self._invoke_item(self._list.currentItem())

    def _reposition(self):
        """Horizontally centered on the parent, near the top edge (below the toolbar)."""
        parent = self.parent()
        if parent is None or not parent.isVisible():
            return
        top_left = parent.mapToGlobal(QPoint(0, 0))
        x = top_left.x() + (parent.width() - self.width()) // 2
        y = top_left.y() + min(100, max(24, parent.height() // 8))
        self.move(x, y)

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up):
                count = self._list.topLevelItemCount()
                if count:
                    current = self._list.indexOfTopLevelItem(self._list.currentItem())
                    step = 1 if key == Qt.Key_Down else -1
                    row = max(0, min(count - 1, current + step))
                    self._list.setCurrentItem(self._list.topLevelItem(row))
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._invoke_current()
                return True
            if key == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        # Clicking outside the palette (into the main window) closes it — popup behavior.
        if event.type() == QEvent.WindowDeactivate and self.isVisible():
            self.close()
        super().changeEvent(event)
