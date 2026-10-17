import sys
import weakref

from PySide6.QtCore import QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QLabel,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .theme import Color


class FadeToast(QWidget):
    """Fading notification in the top-right corner of the parent."""

    def __init__(self, parent, text, color=Color.TOAST_BG, offset_y=12):
        super().__init__(parent)
        self._text = text
        self._bg_color = color

        flags = Qt.FramelessWindowHint | Qt.ToolTip | Qt.WindowStaysOnTopHint
        if sys.platform.startswith("linux"):
            flags |= Qt.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        self.label = QLabel(text)
        self.label.setStyleSheet(self._toast_style())
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(320)
        self.label.setCursor(Qt.PointingHandCursor)
        self.label.mousePressEvent = lambda e: self._copy_to_clipboard()
        layout.addWidget(self.label)

        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.setInterval(4000)
        self._fade_timer.timeout.connect(self._start_fade)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(600)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self.deleteLater)

        self.adjustSize()

        p = self.parent()
        if p:
            parent_pos = p.mapToGlobal(QPoint(0, 0))
            self.move(parent_pos.x() + p.width() - self.width() - 20, parent_pos.y() + offset_y)

        self.show()
        self._fade_timer.start()

    def _toast_style(self, fg=None):
        """A2: the sheet is re-rendered from tokens (no string surgery).

        The copy-feedback used to flip the color by replacing substrings
        in styleSheet() — brittle against any QSS rewording.
        """
        return f"""
            color: {fg or Color.ON_ACCENT};
            font-size: 12px;
            font-weight: 500;
            background: {self._bg_color};
            border-radius: 6px;
            padding: 8px 16px;
        """

    def _copy_to_clipboard(self):
        try:
            QApplication.clipboard().setText(self._text)
        except RuntimeError:
            return
        try:
            self.label.setStyleSheet(self._toast_style(Color.SUCCESS_LIGHT))
        except RuntimeError:
            return
        QTimer.singleShot(400, self._restore_color)

    def _restore_color(self):
        try:
            self.label.setStyleSheet(self._toast_style())
        except RuntimeError:
            pass

    def _start_fade(self):
        try:
            self._fade_anim.start()
        except RuntimeError:
            pass


class NotificationManager:
    """Shows notifications about status changes. Deduplicates identical ones."""

    def __init__(self, parent):
        self.parent = parent
        self._active = {}

    def host_status_changed(self, host_name, old_status, new_status):
        key = f"host:{host_name}"
        if new_status == "error" or new_status == "offline":
            text = tr("is unavailable ❌ {}").format(host_name)
            color = Color.DANGER
        elif old_status in ("error", "offline", "unknown") and new_status == "online":
            text = tr("is back online ✅ {}").format(host_name)
            color = Color.SUCCESS
        elif new_status != "online" and old_status != new_status:
            text = f"🟡 {host_name} — {new_status}"
            color = Color.WARNING
        else:
            return
        self._show(key, text, color)

    def vm_status_changed(self, vm_name, host_name, new_status):
        key = f"vm:{host_name}:{vm_name}"
        status_labels = {"running": tr("Running"), "stopped": tr("Stopped"), "paused": tr("Paused")}
        ru = status_labels.get(new_status, new_status)
        status_icon = "🟢" if new_status == "running" else "🔴" if new_status == "stopped" else "🟡"
        color = Color.SUCCESS if new_status == "running" else Color.DANGER if new_status == "stopped" else Color.WARNING
        self._show(key, f"{status_icon} {vm_name} — {ru}", color)

    def _show(self, key, text, color):
        if self.parent and not self.parent.isVisible():
            tray = getattr(self.parent, "_tray", None)
            if tray and tray.isVisible():
                tray.showMessage("VirtDeck", text.replace("❌", "").replace("✅", "").strip(),
                                 QSystemTrayIcon.Information, 4000)
                return
        existing = self._active.pop(key, None)
        if existing is not None:
            ref = existing()
            if ref is not None:
                try:
                    ref._fade_timer.stop()
                except RuntimeError:
                    pass
                try:
                    ref._fade_anim.stop()
                except RuntimeError:
                    pass
                try:
                    ref.deleteLater()
                except RuntimeError:
                    pass
        offset_y = 12
        dead_keys = []
        for k, t_ref in list(self._active.items()):
            t = t_ref()
            if t is None:
                dead_keys.append(k)
                continue
            try:
                if t.isVisible():
                    offset_y += t.height() + 8
            except RuntimeError:
                dead_keys.append(k)
        for k in dead_keys:
            self._active.pop(k, None)
        toast = FadeToast(self.parent, text, color, offset_y=offset_y)
        self._active[key] = weakref.ref(toast)

    def show(self, text, error=False):
        color = Color.DANGER if error else Color.TOAST_BG
        self._show(text, text, color)
