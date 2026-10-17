from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QBrush, QColor

from .theme import Color

WARN_ROLE = Qt.UserRole + 10

# The filter object is parented to the table (C++-owned), but its Python
# wrapper must outlive the eventFilter registration: a GC pass that
# collects the dropped wrapper leaves the filter registered on the living
# viewport — a later event reaches a dead Python override (CI segfault
# class, 2026-10-17). Pin the wrapper until destroyed releases it.
_LIVE_HOVERS: set = set()


class _RowHoverFilter(QObject):
    def __init__(self, table):
        super().__init__(table)
        self.table = table
        self._prev_row = -1
        self._orig_colors = {}
        table.setMouseTracking(True)
        table.viewport().setMouseTracking(True)
        table.cellEntered.connect(self._on_cell_entered)
        table.viewport().installEventFilter(self)

    def _on_cell_entered(self, row, col):
        self._clear_row(self._prev_row)
        self._highlight_row(row)
        self._prev_row = row

    def _highlight_row(self, row):
        self._save_orig_colors(row)
        for c in range(self.table.columnCount()):
            item = self.table.item(row, c)
            if item and not item.isSelected():
                item.setBackground(QBrush(Color.HOVER))

    def _clear_row(self, row):
        if row < 0:
            return
        if row in self._orig_colors:
            orig = self._orig_colors.pop(row)
            for c, brush in enumerate(orig):
                item = self.table.item(row, c)
                if item:
                    item.setBackground(brush)
        elif row < self.table.rowCount():
            for c in range(self.table.columnCount()):
                item = self.table.item(row, c)
                if item:
                    if item.data(WARN_ROLE):
                        item.setBackground(QBrush(QColor(Color.ROW_WARN)))
                    elif row % 2 == 1:
                        item.setBackground(QBrush(QColor(Color.ALT_ROW)))
                    else:
                        item.setBackground(QBrush())

    def _save_orig_colors(self, row):
        orig = []
        for c in range(self.table.columnCount()):
            item = self.table.item(row, c)
            if item:
                orig.append(item.background())
            else:
                orig.append(QBrush())
        self._orig_colors[row] = orig

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Leave:
            self._clear_row(self._prev_row)
            self._prev_row = -1
            self._orig_colors.clear()
        return super().eventFilter(obj, event)


def enable_row_hover(table):
    f = _RowHoverFilter(table)
    _LIVE_HOVERS.add(f)
    f.destroyed.connect(lambda *_: _LIVE_HOVERS.discard(f))
    return f
