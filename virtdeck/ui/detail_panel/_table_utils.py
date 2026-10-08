from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...domain._format import (
    format_volsize,  # noqa: F401  (re-export)
    safe_pct,  # noqa: F401  (re-export)
)
from ..hover import enable_row_hover
from ..i18n import tr
from ..theme import Color, enable_column_reorder, enable_table_autofit
from ..widgets.spinner import SpinnerWidget
from ._constants import _HEADER_STYLE

_FILTER_TEXT_ROLE = Qt.UserRole + 42

_LOADING_STYLE = f"color: {Color.TEXT_DIM}; font-size: 14px;"


class LoadingPage(QWidget):
    """Loading page: spinner + caption.

    Drop-in replacement for the former static "Loading..." QLabel:
    setText()/text() are proxied to the caption (error and empty-state
    call sites keep working). Any text other than the initial
    "Loading..." is treated as a final state and stops the spinner;
    setting the loading text again re-arms it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        self._spinner = SpinnerWidget(28)
        self._spinner.start()
        layout.addWidget(self._spinner, 0, Qt.AlignCenter)
        self._caption = QLabel(tr("Loading..."))
        self._caption.setAlignment(Qt.AlignCenter)
        self._caption.setStyleSheet(_LOADING_STYLE)
        layout.addWidget(self._caption)
        self._loading_text = self._caption.text()

    def setText(self, text):
        self._caption.setText(text)
        if text == self._loading_text:
            self._spinner.start()
        else:
            self._spinner.stop()

    def text(self):
        return self._caption.text()


def loading_label():
    """Animated loading page: spinner + caption (see LoadingPage)."""
    return LoadingPage()


def make_loading_stack(content_widget, text=None):
    """Stack with an animated spinner page (index 0) and content (index 1)."""
    stack = QStackedWidget()
    stack.addWidget(loading_label())
    stack.addWidget(content_widget)
    return stack


def fit_table_height(table, max_h: int = 260) -> None:
    """Fit table height to content: header + rows (+2px frame).

    Unconstrained, a QTableWidget in a stretched layout takes its own
    sizeHint (~256px or more) regardless of the row count — with a couple
    of rows dead space is left under the table and neighboring widgets
    get squeezed out. If rows exceed max_h, an internal vertical
    scrollbar kicks in.
    """
    rows = sum(table.rowHeight(r) for r in range(table.rowCount()))
    h = table.horizontalHeader().height() + rows + 2
    table.setFixedHeight(min(max(h, 40), max_h))


def make_table(headers, col_specs, sortable=False):
    table = QTableWidget()
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.verticalHeader().hide()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    autofit_cols = []
    for col, (mode, width) in enumerate(col_specs):
        if mode in (QHeaderView.ResizeToContents, QHeaderView.Fixed):
            # Auto modes do not allow dragging the column with the mouse —
            # Interactive + autofit.
            mode = QHeaderView.Interactive
            autofit_cols.append(col)
        elif mode == QHeaderView.Stretch:
            mode = QHeaderView.Interactive
            if col != len(col_specs) - 1:
                # Middle Stretch columns are sized by content; the last one
                # becomes the filler (stretchLastSection).
                autofit_cols.append(col)
        table.horizontalHeader().setSectionResizeMode(col, mode)
        if width is not None:
            table.setColumnWidth(col, width)
    # The table always fills the panel width: the last column stretches.
    table.horizontalHeader().setStretchLastSection(True)
    enable_column_reorder(table.horizontalHeader())
    if autofit_cols:
        enable_table_autofit(table, autofit_cols, max_width=480)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.horizontalHeader().setStyleSheet(_HEADER_STYLE)
    table.setAlternatingRowColors(True)
    if sortable:
        table.setSortingEnabled(True)
    enable_row_hover(table)
    return table


def filter_table(table, text):
    needle = text.lower()
    sort_was = table.isSortingEnabled()
    if sort_was:
        table.setSortingEnabled(False)
    table.blockSignals(True)
    try:
        for row in range(table.rowCount()):
            visible = False
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if not item:
                    continue
                cached = item.data(_FILTER_TEXT_ROLE)
                if cached is None:
                    cached = item.text().lower()
                    item.setData(_FILTER_TEXT_ROLE, cached)
                if needle in cached:
                    visible = True
                    break
            table.setRowHidden(row, not visible)
    finally:
        table.blockSignals(False)
        if sort_was:
            table.setSortingEnabled(True)


def compact_table(table, max_height=22):
    for r in range(table.rowCount()):
        if table.rowHeight(r) > max_height:
            table.setRowHeight(r, max_height)


def set_cell_text(table, row, col, text, fg_color=None):
    item = table.item(row, col)
    if item is None:
        item = QTableWidgetItem(text)
        table.setItem(row, col, item)
    else:
        item.setText(text)
    if fg_color:
        item.setForeground(QBrush(QColor(fg_color)))


def update_progress_bar(bar, value, fmt):
    from ._constants import _progress_style
    bar.setValue(value)
    bar.setFormat(fmt)
    bar.setStyleSheet(_progress_style(value))


def make_filterable_table(table):
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    search = QLineEdit()
    search.setPlaceholderText(tr("Filter"))
    search.setStyleSheet(
        f"QLineEdit {{ font-size: 12px; padding: 4px 8px; border: 1px solid {Color.BORDER_STRONG}; "
        f"border-radius: 3px; margin: 4px 4px 0 4px; }}"
    )
    debounce = QTimer(container)
    debounce.setSingleShot(True)
    debounce.setInterval(200)
    debounce.timeout.connect(lambda: filter_table(table, search.text()))
    search.textChanged.connect(debounce.start)
    layout.addWidget(search)
    layout.addWidget(table)
    container._filter_debounce = debounce
    return container


def set_empty_placeholder(table, col_count, text=None):
    if text is None:
        text = tr("No data")
    table.setRowCount(1)
    for c in range(col_count):
        item = QTableWidgetItem(text if c == col_count // 2 else "")
        item.setFlags(Qt.NoItemFlags)
        item.setTextAlignment(Qt.AlignCenter)
        if c == col_count // 2:
            item.setForeground(QBrush(QColor(Color.TEXT_DIM)))
        table.setItem(0, c, item)
