import logging
import sys
import traceback

from PySide6.QtWidgets import QApplication

from .config import load_config, load_ui_state

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    force=True
)


def _excepthook(exc_type, exc_value, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, tb)
        return
    logger.error(
        "Unhandled exception: %s: %s\n%s",
        exc_type.__name__,
        exc_value,
        "".join(traceback.format_exception(exc_type, exc_value, tb)),
    )


def main():
    sys.excepthook = _excepthook
    app = QApplication(sys.argv)

    # PM_SmallIconSize = base_size() before widgets are created: otherwise
    # all places without setIconSize (detail panel, tabs) draw 16px icons
    from .ui.theme import install_base_icon_style
    install_base_icon_style()

    from .ui.i18n import set_language
    lang = load_ui_state("language") or "en"
    set_language(lang)

    nodes_cfg = load_config()

    from .ui.mainwindow import MainWindow
    window = MainWindow(nodes_cfg)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
