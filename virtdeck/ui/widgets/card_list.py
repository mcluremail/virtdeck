"""CardList — list of card rows (replaces QTableWidget for list views).

Each row is a horizontal card: optional status dot, optional icon,
title, and a flexible set of field slots. Supports filtering and
a double-click signal for future editing.

Rows accept either dicts (``.get(key, default)``) or arbitrary objects
(accessed via ``getattr``).  This allows passing domain dataclasses
directly without converting to dict.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..theme import Color

_DOT_COLORS = {
    "ok": Color.STATUS_OK,
    "warn": Color.STATUS_WARN,
    "err": Color.STATUS_ERR,
    "off": Color.TEXT_DIM,
}


def _status_dot(status):
    s = (status or "").lower() if isinstance(status, str) else ""
    if s in ("running", "online", "ok"):
        return "ok"
    if s in ("stopped", "offline"):
        return "off"
    if s in ("error", "unknown", "warning", "critical"):
        return "err" if s in ("error", "critical") else "warn"
    if status in ("ok", "err", "warn", "off"):
        return status
    return None


def _get_field(obj, key, default=""):
    """Read a field from a dict or arbitrary object.

    Dicts use ``.get(key, default)``; other objects use ``getattr``.
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    val = getattr(obj, key, default)
    return val if val is not None else default


def _make_dict(obj):
    """Convert obj to dict if it's not already one (for update_fields)."""
    if isinstance(obj, dict):
        return obj
    return {}


class CardRow(QFrame):
    """Single card row in a CardList."""

    doubleClicked = Signal(object)  # emits the row's data dict

    def __init__(self, data, columns, parent=None):
        super().__init__(parent)
        self.setObjectName("cardRow")
        self._data = data
        self._columns = columns
        self._dot_label = None
        self._field_labels = []
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        dot_color_key = self._columns.get("dot")
        if dot_color_key:
            self._dot_label = QLabel("●")
            self._dot_label.setFixedWidth(14)
            self._dot_label.setAlignment(Qt.AlignCenter)
            dot_val = _get_field(self._data, dot_color_key, "")
            color_key = _status_dot(dot_val) or dot_val
            self._dot_label.setStyleSheet(f"color: {_DOT_COLORS.get(color_key, Color.TEXT_DIM)}; font-size: 10px;")
            layout.addWidget(self._dot_label)

        title_key = self._columns.get("title")
        if title_key:
            val = _get_field(self._data, title_key, "")
            self._title_label = QLabel(str(val))
            self._title_label.setStyleSheet(f"font-weight: 500; color: {Color.TEXT};")
            title_width = self._columns.get("title_width", 0)
            if title_width:
                self._title_label.setFixedWidth(title_width)
            else:
                self._title_label.setMinimumWidth(120)
            if val:
                # the fixed-width column clips long values silently —
                # the full name is available in the tooltip
                self._title_label.setToolTip(str(val))
            layout.addWidget(self._title_label)

        fields = self._columns.get("fields", [])
        for fkey, fwidth in fields:
            val = _get_field(self._data, fkey, "")
            lbl = QLabel(str(val) if val is not None and val != "" else "—")
            lbl.setStyleSheet(f"color: {Color.TEXT_SEC};")
            if fwidth:
                lbl.setFixedWidth(fwidth)
                if val:
                    lbl.setToolTip(str(val))
            self._field_labels.append((fkey, lbl))
            layout.addWidget(lbl)

        layout.addStretch()

    def update_fields(self, data):
        if isinstance(self._data, dict):
            self._data.update(data)
            if self._dot_label:
                dot_key = self._columns.get("dot", "status")
                dot_val = self._data.get(dot_key, "")
                color_key = _status_dot(dot_val) or dot_val
                self._dot_label.setStyleSheet(f"color: {_DOT_COLORS.get(color_key, Color.TEXT_DIM)}; font-size: 10px;")
            title_key = self._columns.get("title")
            if title_key and self._title_label:
                self._title_label.setText(str(self._data.get(title_key, "")))
            for fkey, lbl in self._field_labels:
                val = self._data.get(fkey, "")
                lbl.setText(str(val) if val is not None and val != "" else "—")
        else:
            # Object mode: replace data and rebuild
            self._data = data
            if self._dot_label:
                dot_key = self._columns.get("dot", "status")
                dot_val = _get_field(self._data, dot_key, "")
                color_key = _status_dot(dot_val) or dot_val
                self._dot_label.setStyleSheet(f"color: {_DOT_COLORS.get(color_key, Color.TEXT_DIM)}; font-size: 10px;")
            title_key = self._columns.get("title")
            if title_key and self._title_label:
                val = _get_field(self._data, title_key, "")
                self._title_label.setText(str(val))
            for fkey, lbl in self._field_labels:
                val = _get_field(self._data, fkey, "")
                lbl.setText(str(val) if val is not None and val != "" else "—")

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self._data)
        super().mouseDoubleClickEvent(event)


class CardList(QWidget):
    """Scrollable list of CardRow widgets with optional filter."""

    cardDoubleClicked = Signal(object)

    def __init__(self, columns, filterable=False, parent=None):
        super().__init__(parent)
        self._columns = columns
        self._rows = []
        self._key_field = columns.get("key", "name")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if filterable:
            self._filter = QLineEdit()
            self._filter.setPlaceholderText(tr("Filter"))
            self._filter.textChanged.connect(self._apply_filter)
            layout.addWidget(self._filter)
        else:
            self._filter = None

        header_labels = columns.get("header_labels")
        if header_labels:
            header = QFrame()
            header.setObjectName("cardListHeader")
            h_layout = QHBoxLayout(header)
            h_layout.setContentsMargins(14, 6, 14, 6)
            h_layout.setSpacing(10)
            if columns.get("dot"):
                dot_placeholder = QLabel("")
                dot_placeholder.setFixedWidth(14)
                h_layout.addWidget(dot_placeholder)
            for label_text, width in header_labels:
                lbl = QLabel(label_text)
                lbl.setStyleSheet(f"color: {Color.TEXT_DIM}; font-size: 11px; text-transform: uppercase;")
                if width:
                    lbl.setFixedWidth(width)
                h_layout.addWidget(lbl)
            h_layout.addStretch()
            layout.addWidget(header)

        self._container = QFrame()
        self._container.setObjectName("cardList")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)
        self._container_layout.addStretch()

        layout.addWidget(self._container)

        self._empty_label = QLabel(tr("No data"))
        self._empty_label.setStyleSheet(f"color: {Color.TEXT_DIM}; padding: 40px; font-size: 13px;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._container_layout.insertWidget(0, self._empty_label)

    def set_items(self, items):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []

        if not items:
            self._empty_label.show()
            return
        self._empty_label.hide()

        for item in items:
            row = CardRow(item, self._columns)
            row.doubleClicked.connect(self._on_row_double_click)
            self._container_layout.insertWidget(self._container_layout.count() - 1, row)
            self._rows.append(row)

    def update_item(self, key, data):
        for row in self._rows:
            row_key = _get_field(row._data, self._key_field, "")
            if str(row_key) == str(key):
                row.update_fields(data)
                return

    def update_all(self, items):
        key_to_data = {str(_get_field(it, self._key_field, "")): it for it in items}
        for row in self._rows:
            key = str(_get_field(row._data, self._key_field, ""))
            if key in key_to_data:
                row.update_fields(key_to_data[key])

    def clear(self):
        self.set_items([])

    def _apply_filter(self, text):
        text = text.strip().lower()
        for row in self._rows:
            visible = not text
            if not visible:
                field_keys = [(self._columns.get("title", ""), None)] + self._columns.get("fields", [])
                for fkey, _ in field_keys:
                    val = str(_get_field(row._data, fkey, "")).lower()
                    if text in val:
                        visible = True
                        break
            row.setVisible(visible)

    def _on_row_double_click(self, data):
        self.cardDoubleClicked.emit(data)
