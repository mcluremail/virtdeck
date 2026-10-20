"""Каталог сверки: встроенные токен-иконки vs внешний пак (light + graphite).

Usage:
    .venv/bin/python scripts/icon_pack_preview.py [pack_dir] [out.png]

Defaults: пак из бандла (virtdeck/ui/icons_pack), вывод ~/virtdeck-icon-preview.png.

Обе полосы — база 24 px (размер иконок во всех темах): light и graphite
(тёмный вариант пака), плюс обе семьи на 48 px. Полный пак v2: все 49
имён _PACK_MAP плюс встроенные restore/app/loading и статус-точки.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from virtdeck.plugins._themes import GraphiteTheme
from virtdeck.ui import icons, theme

PACK_DIR = sys.argv[1] if len(sys.argv) > 1 else icons._BUNDLED_PACK_ROOT
OUT = sys.argv[2] if len(sys.argv) > 2 else \
    os.path.expanduser("~/virtdeck-icon-preview.png")

MARGIN = 24
LABEL_W = 250
CELL = 64
ROW_H = 54
TITLE_H = 30
COLHEAD_H = 20
SECTION_H = 44
GAP = 18

# вне пака остаются только бренд, спиннер и restore (в паке нет пары)
OURS_ONLY = ["restore", "app", "loading"]

OURS_RU = {
    "restore": "Восстановление",
    "start": "Запустить", "shutdown": "Выключить", "reboot": "Перезагрузить",
    "reset": "Сбросить", "stop": "Остановить", "resume": "Продолжить",
    "add": "Добавить", "remove": "Удалить", "upload": "Загрузить",
    "download": "Скачать", "export": "Экспорт", "import": "Импорт",
    "search": "Поиск", "expand": "Развернуть", "collapse": "Свернуть",
    "clone": "Клонировать", "migrate": "Мигрировать", "disk": "Диск",
    "usb": "USB", "pci": "PCI-плата", "serial": "COM-порт",
    "services": "Службы", "tpm": "TPM-чип", "hardware": "Оборудование",
    "group": "Группа", "role": "Роль", "acl": "ACL-доступ",
    "app": "Бренд VirtDeck", "loading": "Спиннер (анимация)",
}

_PACK_RU = {}


def _pack_labels():
    try:
        with open(os.path.join(PACK_DIR, "manifest.json"),
                  encoding="utf-8") as fh:
            for entry in json.load(fh):
                _PACK_RU[entry["id"]] = entry.get("label_ru", entry["id"])
    except (OSError, ValueError, KeyError):
        pass


_PACK_SVGS: dict = {}


def _pack_svg(pack_id, variant):
    key = (variant, pack_id)
    if key not in _PACK_SVGS:
        path = os.path.join(PACK_DIR, variant, pack_id + ".svg")
        try:
            with open(path, encoding="utf-8") as fh:
                _PACK_SVGS[key] = fh.read()
        except OSError:
            _PACK_SVGS[key] = None
    return _PACK_SVGS[key]


def _blank(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    return pm


def _pack_pm(pack_id, variant, size):
    svg = _pack_svg(pack_id, variant)
    if svg is None:
        return None
    renderer = QSvgRenderer(svg.encode("utf-8"))
    if not renderer.isValid():
        return None
    pm = _blank(size)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def _ours_pm(name, size):
    """Встроенная иконка токенами АКТИВНОЙ темы (Color уже переключён)."""
    if name == "loading":
        return icons._make_loading_icon(0).pixmap(size, size)
    tmpl = icons._BUILTINS.get(name)
    if tmpl is None:
        return None
    return icons._render_svg_pixmap(icons._fmt(tmpl), size, 1.0)


def _dot_pm(name, tmpl, size):
    icon = icons._make_icon_with_dot(tmpl, "online")
    return icon.pixmap(size, size)


def _strip_lines():
    """Единый список строк полосы: ("section", t) | ("row", label, ours, pack).

    ours — имя builtin или None (только в паке); pack — id пака или None
    (только у нас).
    """
    lines = []
    for ours_name, pack_id in icons._PACK_MAP.items():
        lines.append(("row", f"{ours_name} · {_PACK_RU.get(pack_id, pack_id)}",
                      ours_name, pack_id))
    lines.append(("section", "Только у нас (в паке нет)"))
    for name in OURS_ONLY:
        lines.append(("row", f"{name} · {OURS_RU[name]}", name, None))
    lines.append(("section", "Статус-точка (host/vm online)"))
    for name in ("host", "vm"):
        lines.append(("row", f"{name} · online", name,
                      icons._PACK_MAP[name]))
    return lines


def _strip_height(lines):
    return (TITLE_H + COLHEAD_H
            + sum(SECTION_H if kind == "section" else ROW_H
                  for kind, *_ in lines))


def _draw_cell(p, pm, cx, cy, color_dim):
    if pm is None:
        p.setPen(QColor(color_dim))
        p.drawText(cx - CELL // 2, cy - 10, CELL, 20, Qt.AlignCenter, "—")
        return
    p.drawPixmap(cx - pm.width() // 2, cy - pm.height() // 2, pm)


def _draw_strip(p, rect, lines, *, variant, base, bg, text, text_sec, title):
    p.fillRect(rect, QColor(bg))
    y = rect.top()

    f = p.font()
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(text))
    p.drawText(rect.left() + MARGIN, y, rect.width() - 2 * MARGIN, TITLE_H,
               Qt.AlignVCenter, title)
    y += TITLE_H

    f.setBold(False)
    p.setFont(f)
    x0 = rect.left() + MARGIN + LABEL_W
    p.setPen(QColor(text_sec))
    for i, head in enumerate([f"наш {base}px", f"пак {variant} {base}px",
                              "наш 48px", "пак 48px"]):
        p.drawText(x0 + i * CELL, y, CELL, COLHEAD_H, Qt.AlignCenter, head)
    y += COLHEAD_H

    for kind, *rest in lines:
        if kind == "section":
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(text))
            p.drawText(rect.left() + MARGIN, y, rect.width() - 2 * MARGIN,
                       SECTION_H, Qt.AlignVCenter, rest[0])
            f.setBold(False)
            p.setFont(f)
            y += SECTION_H
            continue

        label, ours_name, pack_id = rest
        cy = y + ROW_H // 2
        p.setPen(QColor(text))
        p.drawText(rect.left() + MARGIN, y, LABEL_W - 10, ROW_H,
                   Qt.AlignVCenter, label)

        if kind == "row" and label.endswith("online"):
            # статус-точка: наша механика поверх обоих семейств
            _draw_cell(p, _dot_pm(ours_name, icons._BUILTINS[ours_name], base),
                       x0 + CELL // 2, cy, text_sec)
            svg = _pack_svg(pack_id, variant)
            pack_dot = (icons._make_icon_with_dot(svg, "online").pixmap(base, base)
                        if svg else None)
            _draw_cell(p, pack_dot, x0 + CELL + CELL // 2, cy, text_sec)
            _draw_cell(p, None, x0 + 2 * CELL + CELL // 2, cy, text_sec)
            _draw_cell(p, None, x0 + 3 * CELL + CELL // 2, cy, text_sec)
            y += ROW_H
            continue

        _draw_cell(p, _ours_pm(ours_name, base) if ours_name else None,
                   x0 + CELL // 2, cy, text_sec)
        _draw_cell(p, _pack_pm(pack_id, variant, base) if pack_id else None,
                   x0 + CELL + CELL // 2, cy, text_sec)
        _draw_cell(p, _ours_pm(ours_name, 48) if ours_name else None,
                   x0 + 2 * CELL + CELL // 2, cy, text_sec)
        _draw_cell(p, _pack_pm(pack_id, variant, 48) if pack_id else None,
                   x0 + 3 * CELL + CELL // 2, cy, text_sec)
        y += ROW_H


def main():
    _pack_labels()
    QGuiApplication([])  # offscreen-платформа для растеризации
    lines = _strip_lines()

    strips = [
        {"variant": "light", "base": 24, "bg": theme.Color.BG,
         "text": theme.Color.TEXT, "text_sec": theme.Color.TEXT_SEC,
         "title": "Светлые темы (light / breeze / oxygen) — база 24 px",
         "tokens": None},
        {"variant": "dark", "base": 24, "bg": GraphiteTheme._TOKENS["BG"],
         "text": GraphiteTheme._TOKENS["TEXT"],
         "text_sec": GraphiteTheme._TOKENS["TEXT_SEC"],
         "title": "Graphite — база 24 px (тёмный вариант пака)",
         "tokens": GraphiteTheme._TOKENS},
    ]

    W = MARGIN * 2 + LABEL_W + 4 * CELL
    H = GAP + sum(_strip_height(lines) + GAP for _ in strips)
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor("#d8dade"))

    p = QPainter(img)
    y = GAP
    for strip in strips:
        if strip["tokens"]:
            theme.apply_tokens(strip["tokens"])  # наши — токенами темы
        h = _strip_height(lines)
        _draw_strip(p, QRect(0, int(y), W, int(h)), lines,
                    variant=strip["variant"], base=strip["base"],
                    bg=strip["bg"], text=strip["text"],
                    text_sec=strip["text_sec"], title=strip["title"])
        y += h + GAP
    p.end()
    img.save(OUT)
    print(f"OK: {OUT}  ({W}x{int(H)})")


if __name__ == "__main__":
    main()
