import weakref

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout

from ..theme import TOKENS, Color
from .spinner import SpinnerWidget

# Live cards: inline styles are baked in at creation time, so they must be
# restyled on theme change (see retheme_metric_cards).
_LIVE_CARDS: weakref.WeakSet | None = None


def retheme_metric_cards():
    """Recolor all live MetricCards to the active theme."""
    global _LIVE_CARDS
    if _LIVE_CARDS is None:
        return
    for card in list(_LIVE_CARDS):
        try:
            card.retheme()
        except RuntimeError:
            _LIVE_CARDS.discard(card)  # C++ object already deleted


def _token_for(color):
    """Canonical token name by value (for recoloring on theme change)."""
    for name in TOKENS:
        if getattr(Color, name, None) == color:
            return name
    return None


class MetricCard(QFrame):
    def __init__(self, title="", value="", subtitle="", show_progress=False, parent=None):
        super().__init__(parent)
        self._show_progress = show_progress
        self._progress = 0
        self._bar_color = None        # custom chunk color (hex)
        self._value_color_token = None
        self.setObjectName("metricCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(2)

        self._title_label = QLabel(title)
        layout.addWidget(self._title_label)

        layout.addSpacing(4)

        self._value_label = QLabel(value)
        self._value_font = QFont()
        self._value_font.setPointSize(18)
        self._value_font.setBold(True)
        self._value_font.setLetterSpacing(QFont.AbsoluteSpacing, -0.5)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(4)
        value_row.addWidget(self._value_label)
        value_row.addStretch()
        # Shown instead of the value while async data is loading.
        self._spinner = SpinnerWidget(18)
        self._spinner.hide()
        value_row.addWidget(self._spinner, 0, Qt.AlignVCenter)
        layout.addLayout(value_row)

        self._subtitle_label = QLabel(subtitle)
        if subtitle:
            self._subtitle_label.show()
        else:
            self._subtitle_label.hide()
        layout.addWidget(self._subtitle_label)

        if show_progress:
            self._bar = QProgressBar()
            self._bar.setRange(0, 100)
            self._bar.setFixedHeight(6)
            self._bar.setTextVisible(False)
            layout.addSpacing(8)
            layout.addWidget(self._bar)
        else:
            self._bar = None

        # Content-driven height: a fixed height clipped the values
        # (18pt digits did not fit). In a grid layout, cards of one row
        # still align to the tallest one (Minimum).
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        self._restyle()

        global _LIVE_CARDS
        if _LIVE_CARDS is None:
            _LIVE_CARDS = weakref.WeakSet()
        _LIVE_CARDS.add(self)

    def _restyle(self):
        """Inline styles from current tokens (creation + theme change)."""
        self._title_label.setStyleSheet(
            f"color: {Color.TEXT_DIM}; font-size: 11px; font-weight: 600;"
            " text-transform: uppercase; letter-spacing: 0.05em;"
        )
        value_color = Color.TEXT
        extra = ""
        if self._value_color_token:
            value_color = getattr(Color, self._value_color_token)
            extra = " font-weight: 600;"
        self._value_label.setFont(self._value_font)
        self._value_label.setStyleSheet(f"color: {value_color};{extra}")
        self._subtitle_label.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 12px;")
        self._apply_bar_style()

    def retheme(self):
        """Recolor on theme change: fresh tokens into inline styles."""
        self._restyle()

    def _apply_bar_style(self):
        if self._bar is None:
            return
        pct = self._progress
        if self._bar_color:
            bar_color = self._bar_color
        elif pct >= 80:
            bar_color = Color.STATUS_ERR
        elif pct >= 50:
            bar_color = Color.STATUS_WARN
        else:
            bar_color = Color.ACCENT
        self._bar.setStyleSheet(
            f"QProgressBar {{ background: {Color.TRACK}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {bar_color}; border-radius: 3px; }}"
        )

    def set_title(self, title):
        self._title_label.setText(title)

    def start_loading(self):
        """Hide the value and spin until the next set_value/stop_loading."""
        self._value_label.hide()
        self._spinner.start()

    def stop_loading(self):
        self._spinner.stop()
        self._value_label.show()

    def set_value(self, value, subtitle=None):
        self.stop_loading()
        self._value_label.setText(str(value))
        if subtitle is not None:
            self.set_subtitle(subtitle)

    def set_subtitle(self, subtitle):
        self._subtitle_label.setText(str(subtitle))
        self._subtitle_label.show() if subtitle else self._subtitle_label.hide()

    def set_progress(self, pct, color=None):
        if not self._bar:
            return
        self._progress = max(0, min(100, int(pct)))
        self._bar_color = color
        self._bar.setValue(self._progress)
        self._apply_bar_style()

    def set_value_color(self, color):
        self._value_color_token = _token_for(color)
        self._value_label.setStyleSheet(f"color: {color}; font-weight: 600;")
