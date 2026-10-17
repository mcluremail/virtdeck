"""State primitives (Д6/Д7, DELIGHT-10/11 — stage 5 of the 3.1.0 plan).

EmptyState — one empty-state component for every surface (palette,
search, tasks dock, Fleet, PBS, tree): icon + title + hint + optional
action. Replaces the six ad-hoc solutions (U3/U6/U7/U11/U12/L10).

SkeletonDetail — the detail-panel skeleton (Д7/DELIGHT-10): stripes of
the future layout instead of a text label + a central spinner (S4
double indicator).

Both primitives resolve colors at render time: the labels are styled
by the global theme QSS via objectName (re-polished on every theme
switch), the skeleton paints from Color tokens per frame — no frozen
hexes anywhere (A7/Д4 rule).
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..icons import base_size, get_icon
from ..theme import RADIUS, font_px
from ..i18n import tr


class EmptyState(QWidget):
    """Icon + title + hint + optional action button (Д6)."""

    def __init__(self, icon_name, title, hint="",
                 action_text=None, on_action=None, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._title = title

        lay = QVBoxLayout(self)
        lay.setContentsMargins(base_size() * 3, base_size() * 3,
                               base_size() * 3, base_size() * 3)
        lay.setSpacing(base_size())

        icon_lbl = QLabel()
        icon_lbl.setObjectName("emptyStateIcon")
        icon = get_icon(icon_name)
        if icon is not None and not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(base_size() * 3, base_size() * 3))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(icon_lbl)

        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("emptyStateTitle")
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._title_lbl.setWordWrap(True)
        lay.addWidget(self._title_lbl)

        self._hint_lbl = None
        if hint:
            self._hint_lbl = QLabel(hint)
            self._hint_lbl.setObjectName("emptyStateHint")
            self._hint_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._hint_lbl.setWordWrap(True)
            lay.addWidget(self._hint_lbl)

        self._action_btn = None
        if action_text:
            self._action_btn = QPushButton(action_text)
            self._action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if on_action is not None:
                self._action_btn.clicked.connect(on_action)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(self._action_btn)
            row.addStretch(1)
            lay.addLayout(row)

        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    # ── live theming ────────────────────────────────────────────────
    def reapply(self):
        """Re-resolve the icon (labels follow the global QSS).

        Call from the owning surface's reapply_theme; showEvent also
        re-fetches, covering most lifecycles.
        """
        icon = get_icon(self._icon_name)
        if icon is not None and not icon.isNull() and self._icon_name:
            for child in self.findChildren(QLabel):
                if child.objectName() == "emptyStateIcon":
                    child.setPixmap(icon.pixmap(base_size() * 3,
                                                base_size() * 3))

    def showEvent(self, ev):
        super().showEvent(ev)
        self.reapply()

    # ── live content ────────────────────────────────────────────────
    def set_state(self, title, hint=""):
        """Swap title/hint without rebuilding (e.g. typing → no results)."""
        self._title = title
        self._title_lbl.setText(title)
        if self._hint_lbl is not None:
            self._hint_lbl.setText(hint)
            self._hint_lbl.setVisible(bool(hint))


class SkeletonDetail(QWidget):
    """Detail-panel skeleton (Д7/DELIGHT-10).

    Paints the structure of the future page: a title stripe, a row of
    metric-card placeholders and content rows — read from Color tokens
    at every paint, so themes are followed live. Static (no timer): the
    point is to show structure immediately, not to animate.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(base_size() * 12)

    def paintEvent(self, ev):
        from PySide6.QtGui import QColor, QPainter, QPainterPath

        from ..theme import Color

        w = self.width()
        m = base_size() * 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QColor(Color.PANEL)
        stripe = QColor(Color.ALT_ROW)
        edge = QColor(Color.BORDER_LIGHT)
        y = m
        r = float(RADIUS["MD"])

        def bar(x, yy, bw, bh, color):
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, yy, bw, bh), r, r)
            painter.fillPath(path, color)

        # title + caption line
        bar(m, y, w * 0.28, font_px("DISPLAY"), card)
        painter.setPen(edge)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        y += font_px("DISPLAY") + base_size()
        bar(m, y, w * 0.16, font_px("SM"), stripe)
        y += font_px("SM") + base_size() * 2

        # metric cards row
        card_w = (w - 2 * m - 3 * base_size()) / 4.0
        for i in range(4):
            x = m + i * (card_w + base_size())
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, y, card_w, base_size() * 5),
                                float(RADIUS["LG"]), float(RADIUS["LG"]))
            painter.fillPath(path, QColor(Color.PANEL))
            painter.setPen(edge)
            painter.drawPath(path)
            bar(x + base_size() * 0.75, y + base_size() * 0.75,
                card_w * 0.55, font_px("SM"), stripe)
            bar(x + base_size() * 0.75, y + base_size() * 2.25,
                card_w * 0.4, font_px("LG"), card)
        y += base_size() * 5 + base_size() * 2

        # content rows
        while y + base_size() * 2 < self.height() - m:
            bar(m, y, w - 2 * m, base_size() * 2, stripe)
            y += base_size() * 2 + base_size() * 0.75
        painter.end()
