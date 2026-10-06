"""Built-in themes (ThemePlugin v1).

Точечные значения палитр взяты из схем KDE: breeze (colors/BreezeLight.
colors, BreezeDark.colors) и oxygen (color-schemes/Oxygen.colors).
Значения с комментарием «derived» в схемах отсутствуют — выведены из
базовых цветов схем (Breeze рисует disabled через ColorEffects, бордеров
в схемах нет). Graphite — собственная нейтральная тема.
"""

from __future__ import annotations

from ..ui.theme import LIGHT_TOKENS
from .base import ThemePlugin


class LightTheme:
    """Светлая тема — встроенный плагин поверх дефолтной палитры."""

    _tokens: dict[str, str] | None = None

    @property
    def id(self) -> str:
        return "light"

    @property
    def name(self) -> str:
        return "Light"

    def tokens(self) -> dict[str, str]:
        # Снимок делается лениво при первом tokens(): к этому моменту
        # Color ещё держит дефолтную (светлую) палитру, а повторные
        # активации не должны наследовать значения чужих тем.
        if LightTheme._tokens is None:
            LightTheme._tokens = dict(LIGHT_TOKENS)
        return dict(LightTheme._tokens)

    def extra_qss(self) -> str:
        return ""

    def icons(self) -> dict[str, str] | None:
        return None

    @property
    def icon_size(self) -> int:
        return 16


# ── Breeze — фирменный filled-цветной набор (фиксированные цвета, как бренд) ──

BREEZE_ICONS = {
    'about': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.6" fill="#3D8BFD"/><circle cx="12" cy="7.7" r="1.35" fill="#FFFFFF"/><path d="M12 10.8v5.6" fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'acl': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2.4l7.6 3.2v5.7c0 4.6-3.1 8.5-7.6 10.3-4.5-1.8-7.6-5.7-7.6-10.3V5.6z" fill="#2563EB"/><circle cx="12" cy="10.6" r="1.8" fill="#FFFFFF"/><path d="M12 12.2v3" fill="none" stroke="#FFFFFF" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'add': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 4.6v14.8M4.6 12h14.8" fill="none" stroke="#22C55E" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'backup': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 6v8c0 1.45 2.24 2.6 5 2.6s5-1.15 5-2.6V6z" fill="#2563EB"/><ellipse cx="10" cy="6" rx="5" ry="2.1" fill="#3D8BFD"/><circle cx="17.3" cy="16.8" r="4.6" fill="#22C55E"/><path d="M17.3 19.2v-4.6M15.5 16.3l1.8-1.8 1.8 1.8" fill="none" stroke="#FFFFFF" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'clone': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="8.6" y="3.4" width="11.4" height="11.4" rx="2.2" fill="#93C5FD"/><rect x="4" y="9.2" width="11.4" height="11.4" rx="2.2" fill="#3D8BFD"/><path d="M9.7 14.9v4M7.7 16.9h4" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'cluster': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M6.5 11v3h11v-3" fill="none" stroke="#2563EB" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><path d="M12 14v3.2" fill="none" stroke="#2563EB" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><rect x="3" y="3.5" width="7" height="7" rx="2" fill="#3D8BFD"/><rect x="14" y="3.5" width="7" height="7" rx="2" fill="#3D8BFD"/><rect x="8.5" y="13.5" width="7" height="7" rx="2" fill="#2563EB"/></svg>',
    'collapse': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M20 4l-6.3 6.3M13.7 10.3h4.6M13.7 10.3V5.7" fill="none" stroke="#3D8BFD" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M4 20l6.3-6.3M10.3 13.7H5.7M10.3 13.7v4.6" fill="none" stroke="#3D8BFD" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'console': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="14.5" rx="2.6" fill="#1E3A8A"/><path d="M7 9.3l3.3 2.7L7 14.7" fill="none" stroke="#FFFFFF" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" /><path d="M12.7 14.7h4.5" fill="none" stroke="#FFFFFF" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" /><path d="M12 18.5v2.5M8 21h8" fill="none" stroke="#3D8BFD" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'disk': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3.4" y="7.3" width="17.2" height="9.6" rx="2.1" fill="#2563EB"/><circle cx="10.4" cy="12.1" r="3.1" fill="#FFFFFF"/><circle cx="10.4" cy="12.1" r="1.25" fill="#2563EB"/><circle cx="17.5" cy="14.6" r="1.05" fill="#22C55E"/></svg>',
    'download': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 4.2v10.3" fill="none" stroke="#22C55E" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M8.2 10.7L12 14.5l3.8-3.8" fill="none" stroke="#22C55E" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M5 13.8v3.9a2.3 2.3 0 002.3 2.3h9.4a2.3 2.3 0 002.3-2.3v-3.9" fill="none" stroke="#3D8BFD" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'expand': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M13.7 10.3L20 4M20 4h-5M20 4v5" fill="none" stroke="#3D8BFD" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M10.3 13.7L4 20M4 20h5M4 20v-5" fill="none" stroke="#3D8BFD" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'export': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="4.6" y="10.4" width="14.8" height="9.6" rx="2.1" fill="#3D8BFD"/><path d="M12 14.8V3.8" fill="none" stroke="#F59E0B" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M8.7 7.1L12 3.8l3.3 3.3" fill="none" stroke="#F59E0B" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'folder': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M3.5 6.7a2 2 0 012-2h3.9l2 2.3h9.1a2 2 0 012 2v9.5a2 2 0 01-2 2h-15a2 2 0 01-2-2z" fill="#3D8BFD"/><path d="M3.5 9.8h17" fill="none" stroke="#2563EB" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/><path d="M3.5 6.7v-.9" fill="none" stroke="#3D8BFD" stroke-width="0" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'group': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="6.8" cy="9" r="2.5" fill="#3D8BFD"/><path d="M2.8 18.3c.4-2.6 1.9-4 4-4s3.6 1.4 4 4z" fill="#3D8BFD"/><circle cx="17.2" cy="9" r="2.5" fill="#3D8BFD"/><path d="M13.2 18.3c.4-2.6 1.9-4 4-4s3.6 1.4 4 4z" fill="#3D8BFD"/><circle cx="12" cy="10" r="3" fill="#2563EB"/><path d="M7.4 19.6c.5-3.3 2.2-5 4.6-5s4.1 1.7 4.6 5z" fill="#2563EB"/></svg>',
    'ha': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2.4l7.6 3.2v5.7c0 4.6-3.1 8.5-7.6 10.3-4.5-1.8-7.6-5.7-7.6-10.3V5.6z" fill="#2563EB"/><path d="M7.4 12h2.7l1.3-2.7 2.1 5.2 1.4-2.5h1.7" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'hardware': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M9.6 6.4V2.8M14.4 6.4V2.8M9.6 17.6v3.6M14.4 17.6v3.6M6.4 9.6H2.8M6.4 14.4H2.8M17.6 9.6h3.6M17.6 14.4h3.6" fill="none" stroke="#2563EB" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><rect x="6.4" y="6.4" width="11.2" height="11.2" rx="2.1" fill="#3D8BFD"/><rect x="9.4" y="9.4" width="5.2" height="5.2" rx="1.1" fill="#FFFFFF"/></svg>',
    'history': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4.4 9.9A8.1 8.1 0 116.6 17.8" fill="none" stroke="#3D8BFD" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" /><path d="M3 6.3l1.65 4.4 4-2.6z" fill="#3D8BFD"/><circle cx="12.6" cy="12.4" r="5.7" fill="#2563EB"/><path d="M12.6 9.4v3.2l2.3 1.4" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'host': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="5" y="2.5" width="14" height="19" rx="2.5" fill="#2563EB"/><path d="M8 7.5h8M8 11.5h8M8 15.5h5" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><circle cx="16" cy="18" r="1.3" fill="#22C55E"/></svg>',
    'import': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="4.6" y="10.4" width="14.8" height="9.6" rx="2.1" fill="#3D8BFD"/><path d="M12 3.8v11" fill="none" stroke="#F59E0B" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M8.7 11.5l3.3 3.3 3.3-3.3" fill="none" stroke="#F59E0B" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'iso': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.4" fill="#3D8BFD"/><circle cx="12" cy="12" r="4.7" fill="none" stroke="#FFFFFF" stroke-width="1.7" opacity=".8"/><circle cx="12" cy="12" r="2.1" fill="#FFFFFF"/><circle cx="12" cy="12" r=".95" fill="#2563EB"/><path d="M6.2 8.4a7 7 0 014.2-3" fill="none" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" opacity=".6"/></svg>',
    'lock': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8 10.4V7.8a4 4 0 018 0v2.6" fill="none" stroke="#2563EB" stroke-width="2.6"/><rect x="5.4" y="10.4" width="13.2" height="10" rx="2.6" fill="#3D8BFD"/><circle cx="12" cy="14.7" r="1.75" fill="#FFFFFF"/><path d="M12 16.2v2" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'migrate': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="2.8" y="6.2" width="6.9" height="9" rx="1.8" fill="#2563EB"/><path d="M4.6 8.8h3.3M4.6 11.3h3.3" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><rect x="14.3" y="6.2" width="6.9" height="9" rx="1.8" fill="#3D8BFD"/><path d="M16.1 8.8h3.3M16.1 11.3h3.3" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M10.3 10.7l3 0" fill="none" stroke="#22C55E" stroke-width="0" stroke-linecap="round" stroke-linejoin="round" /><path d="M13.9 10.7l-3-2.1v4.2z" fill="#22C55E"/></svg>',
    'monitor': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13.4" rx="2.6" fill="#2563EB"/><path d="M6.4 13.4l3-3.1 2.3 2.3 3.3-4.3 2.6 2.1" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><circle cx="17.2" cy="7" r="1.1" fill="#F59E0B"/><path d="M12 17.4v3M8 20.4h8" fill="none" stroke="#2563EB" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'network': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 9.6h2M2 14.4h2" fill="none" stroke="#2563EB" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><rect x="4" y="5.8" width="16" height="12.4" rx="2.1" fill="#3D8BFD"/><rect x="7.6" y="9.2" width="8.8" height="5" rx="1.1" fill="#FFFFFF"/><path d="M9.4 14.2v2.4M11.8 14.2v2.4M14.2 14.2v2.4" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M9.4 11.7h5.2" fill="none" stroke="#93C5FD" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'options': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 6.6h14M5 12h14M5 17.4h14" fill="none" stroke="#2563EB" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /><circle cx="9.2" cy="6.6" r="2.7" fill="#22C55E"/><circle cx="15.6" cy="12" r="2.7" fill="#F59E0B"/><circle cx="10.6" cy="17.4" r="2.7" fill="#8B5CF6"/><circle cx="9.2" cy="6.6" r="1" fill="#FFFFFF"/><circle cx="15.6" cy="12" r="1" fill="#FFFFFF"/><circle cx="10.6" cy="17.4" r="1" fill="#FFFFFF"/></svg>',
    'pci': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2.6 8.6h2.2M2.6 12h2.2M2.6 15.4h2.2" fill="none" stroke="#F59E0B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><rect x="4.8" y="4.4" width="14.6" height="15.2" rx="2" fill="#2563EB"/><path d="M7.6 8.2h9M7.6 12h5.6M7.6 15.8h7" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><rect x="15.4" y="13.6" width="2" height="4" rx="0.8" fill="#22C55E"/></svg>',
    'pool': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M3.5 6.7a2 2 0 012-2h3.9l2 2.3h9.1a2 2 0 012 2v9.5a2 2 0 01-2 2h-15a2 2 0 01-2-2z" fill="#8B5CF6"/><path d="M3.5 9.8h17" fill="none" stroke="#6D28D9" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/></svg>',
    'reboot': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19.3 8.2A7.9 7.9 0 1112 4.1" fill="none" stroke="#3D8BFD" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /><path d="M21 3.3l-.65 5.1-4.65-1.95z" fill="#3D8BFD"/></svg>',
    'refresh': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5.6 11.6a6.6 6.6 0 0111-4.4" fill="none" stroke="#3D8BFD" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" /><path d="M17.2 3.3l-.4 4.2-4-1.2z" fill="#3D8BFD"/><path d="M18.4 12.4a6.6 6.6 0 01-11 4.4" fill="none" stroke="#22C55E" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" /><path d="M6.8 20.7l.4-4.2 4 1.2z" fill="#22C55E"/></svg>',
    'remove': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4.6 12h14.8" fill="none" stroke="#EF4444" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'reset': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19.3 8.2A7.9 7.9 0 1112 4.1" fill="none" stroke="#EF4444" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /><path d="M21 3.3l-.65 5.1-4.65-1.95z" fill="#EF4444"/><path d="M17.3 15.2l.65 1.75 1.75.65-1.75.65-.65 1.75-.65-1.75-1.75-.65 1.75-.65z" fill="#F59E0B"/></svg>',
    'restore': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4.6 9.8A8.2 8.2 0 117 18.4" fill="none" stroke="#3D8BFD" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" /><path d="M3.2 6.2l1.7 4.5 4.1-2.7z" fill="#3D8BFD"/><circle cx="13" cy="13" r="6" fill="#1E3A8A"/><path d="M13 9.8v3.4l2.4 1.5" fill="none" stroke="#FFFFFF" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'resume': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M6.7 6.3l7.8 4.85c.9.56.9 1.86 0 2.42l-7.8 4.85c-.93.58-2.1-.08-2.1-1.2V7.5c0-1.12 1.17-1.78 2.1-1.2z" fill="#3D8BFD"/><rect x="17.4" y="5.4" width="2.7" height="13.2" rx="1.35" fill="#2563EB"/></svg>',
    'role': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="4.4" y="3.8" width="15.2" height="16.4" rx="2.2" fill="#3D8BFD"/><circle cx="12" cy="9.7" r="2.5" fill="#FFFFFF"/><path d="M8.3 15.8c.4-2.3 1.8-3.5 3.7-3.5s3.3 1.2 3.7 3.5z" fill="#FFFFFF"/></svg>',
    'search': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="10.4" cy="10.4" r="6.2" fill="#BFDBFE"/><circle cx="10.4" cy="10.4" r="6.2" fill="none" stroke="#2563EB" stroke-width="2.6"/><path d="M15.3 15.3L20.4 20.4" fill="none" stroke="#2563EB" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'serial': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3.8" y="6.8" width="16.4" height="10.4" rx="2.1" fill="#1E3A8A"/><circle cx="7.2" cy="10.2" r=".85" fill="#FFFFFF"/><circle cx="9.9" cy="10.2" r=".85" fill="#FFFFFF"/><circle cx="12.6" cy="10.2" r=".85" fill="#FFFFFF"/><circle cx="15.3" cy="10.2" r=".85" fill="#FFFFFF"/><circle cx="18" cy="10.2" r=".85" fill="#FFFFFF"/><path d="M7.4 14.2h2.4M11 14.2h2.4M14.6 14.2h2.4" fill="none" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'services': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="9" r="5.7" fill="none" stroke="#3D8BFD" stroke-width="2.7" stroke-dasharray="2.55 2.6"/><circle cx="12" cy="9" r="4.4" fill="#3D8BFD"/><circle cx="12" cy="9" r="1.9" fill="#FFFFFF"/><path d="M6.8 17.6h10.4M6.8 20.6h6.4" fill="none" stroke="#2563EB" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'shutdown': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M7.4 5.9a8.1 8.1 0 109.2 0" fill="none" stroke="#F59E0B" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /><path d="M12 3v8" fill="none" stroke="#F59E0B" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'snapshot': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8.2 6.8l1.3-2.3h5l1.3 2.3z" fill="#2563EB"/><rect x="3.4" y="6.8" width="17.2" height="12.8" rx="2.6" fill="#3D8BFD"/><circle cx="12" cy="13" r="3.5" fill="#FFFFFF"/><circle cx="12" cy="13" r="1.9" fill="#2563EB"/><circle cx="17.6" cy="9.6" r=".95" fill="#FFFFFF" opacity=".85"/></svg>',
    'start': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8.2 5.1l9.6 6.35c.83.55.83 1.75 0 2.3L8.2 20.1c-.92.6-2.1-.06-2.1-1.17V6.27c0-1.1 1.18-1.77 2.1-1.17z" fill="#22C55E"/></svg>',
    'stop': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2.6" fill="#EF4444"/></svg>',
    'storage': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 5.5v13c0 1.55 3.13 2.8 7 2.8s7-1.25 7-2.8v-13z" fill="#2563EB"/><ellipse cx="12" cy="5.5" rx="7" ry="2.8" fill="#3D8BFD"/><path d="M5 9.3c1.35 1.05 3.95 1.7 7 1.7s5.65-.65 7-1.7" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/></svg>',
    'template': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3.5" width="18" height="13.5" rx="2.8" fill="#2563EB"/><rect x="5.4" y="5.9" width="13.2" height="8.7" rx="1.6" fill="#FFFFFF"/><path d="M7.6 8.6h5M7.6 11.6h3" fill="none" stroke="#93C5FD" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><circle cx="18.5" cy="6.5" r="4" fill="#F59E0B"/><path d="M18.5 4.9v3.2M16.9 6.5h3.2" fill="none" stroke="#FFFFFF" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M12 17v3.5M8 20.5h8" fill="none" stroke="#2563EB" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'token': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="6.8" y="3.4" width="10.4" height="17.2" rx="2.2" fill="#2563EB"/><path d="M9.8 7.8h4.4M9.8 10.8h4.4" fill="none" stroke="#93C5FD" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><circle cx="12" cy="15.8" r="2.7" fill="#F59E0B"/><path d="M12 14.9v1.9M11.1 16.8h1.8" fill="none" stroke="#FFFFFF" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'tpm': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8 6.8V4.2M12 6.8V4.2M16 6.8V4.2M8 17.2v2.6M12 17.2v2.6M16 17.2v2.6" fill="none" stroke="#CBD5E1" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" /><rect x="5" y="6.8" width="14" height="10.4" rx="1.8" fill="#1E3A8A"/><rect x="8.4" y="9.6" width="7.2" height="4.8" rx="1" fill="#FFFFFF"/><path d="M11 12h2" fill="none" stroke="#2563EB" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'unlock': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8 10.4V7.8a4 4 0 017.8-1.3" fill="none" stroke="#2563EB" stroke-width="2.6"/><rect x="5.4" y="10.4" width="13.2" height="10" rx="2.6" fill="#3D8BFD"/><circle cx="12" cy="14.7" r="1.75" fill="#FFFFFF"/><path d="M12 16.2v2" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'upload': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 14.5V4.2" fill="none" stroke="#2563EB" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M8.2 8L12 4.2 15.8 8" fill="none" stroke="#2563EB" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M5 13.8v3.9a2.3 2.3 0 002.3 2.3h9.4a2.3 2.3 0 002.3-2.3v-3.9" fill="none" stroke="#3D8BFD" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'usb': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="9.4" y="2.4" width="5.2" height="5.6" rx="1" fill="#CBD5E1"/><path d="M10.9 4.4h1M13.1 4.4h1" fill="none" stroke="#64748B" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" /><rect x="7.9" y="8" width="8.2" height="9.6" rx="2.1" fill="#3D8BFD"/><circle cx="12" cy="10.8" r="1.05" fill="#FFFFFF"/><path d="M12 17.6v3" fill="none" stroke="#2563EB" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>',
    'user': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="7.6" r="3.5" fill="#3D8BFD"/><path d="M4.4 20.2c.6-4.1 3.4-6.2 7.6-6.2s7 2.1 7.6 6.2z" fill="#2563EB"/></svg>',
    'vm': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3.5" width="18" height="13.5" rx="2.8" fill="#3D8BFD"/><rect x="5.4" y="5.9" width="13.2" height="8.7" rx="1.6" fill="#FFFFFF"/><path d="M10.4 8l4.6 2.25L10.4 12.5z" fill="#2563EB"/><path d="M12 17v3.5" fill="none" stroke="#3D8BFD" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /><path d="M8 20.5h8" fill="none" stroke="#3D8BFD" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>',
}

_BREEZE_DENSITY_QSS = """
/* Плотность под иконки 24px (Breeze) */
QTreeWidget::item, QTreeView::item { padding: 3px 2px; }
QToolBar QToolButton { padding: 3px; margin: 1px; }
"""


class BreezeTheme:
    """Breeze Light — светлая тема KDE Plasma (иконки 24px)."""

    _TOKENS: dict[str, str] = {
        "BG": "#eff0f1",            # Window
        "PANEL": "#fcfcfc",         # Button
        "RAISED": "#ffffff",        # View
        "TRACK": "#e3e5e7",         # Window alternate
        "ALT_ROW": "#f7f7f7",       # View alternate
        "BORDER": "#c3c7cb",        # derived
        "BORDER_LIGHT": "#d8dbde",  # derived
        "BORDER_STRONG": "#a7abaf",  # derived
        "TEXT": "#232629",          # Window foreground
        "TEXT_SEC": "#707d8a",      # Window inactive
        "TEXT_DIM": "#98a2ab",      # derived
        "DISABLED": "#a7abaf",      # derived (ColorEffects:Disabled)
        "ON_ACCENT": "#ffffff",     # Selection foreground
        "ACCENT": "#3daee9",        # DecorationFocus
        "ACCENT_HOVER": "#55b8ec",  # derived
        "ACCENT_LIGHT": "#a3d4fa",  # Button alternate (inactive selection)
        "ACCENT_PRESSED": "#2f96d3",  # derived
        "SUCCESS": "#27ae60",       # Positive
        "SUCCESS_LIGHT": "#e2f6ea",  # derived
        "WARNING": "#f67400",       # Neutral
        "WARNING_TEXT": "#a95400",  # derived
        "DANGER": "#da4453",        # Negative
        "DANGER_SOLID": "#da4453",
        "DANGER_SOLID_HOVER": "#e36a76",  # derived
        "DANGER_SOLID_PRESSED": "#b03745",  # Selection negative
        "STATUS_OK": "#27ae60",
        "STATUS_WARN": "#f67400",
        "STATUS_ERR": "#da4453",
        "HOVER": "#e3e5e7",         # Window alternate
        "ROW_WARN": "#fdf1e3",      # derived (warning tint)
        "TOAST_BG": "#2a2e32",      # Complementary background
        "SCROLLBAR_BG": "#f0f1f2",  # derived
        "SCROLLBAR_HANDLE": "#b9bec4",  # derived
        "SCROLLBAR_HOVER": "#9fa6ad",  # derived
        "ICON_FG": "#232629",
        "ICON_FG_DIM": "#707d8a",
    }

    @property
    def id(self) -> str:
        return "breeze"

    @property
    def name(self) -> str:
        return "Breeze"

    def tokens(self) -> dict[str, str]:
        return dict(self._TOKENS)

    def extra_qss(self) -> str:
        return _BREEZE_DENSITY_QSS

    def icons(self) -> dict[str, str] | None:
        return BREEZE_ICONS

    @property
    def icon_size(self) -> int:
        return 24


class BreezeDarkTheme(BreezeTheme):
    """Breeze Dark — тёмная тема KDE Plasma (иконки 24px)."""

    _TOKENS: dict[str, str] = {
        "BG": "#202326",            # Window
        "PANEL": "#292c30",         # Button
        "RAISED": "#141618",        # View
        "TRACK": "#2c3034",         # derived
        "ALT_ROW": "#1d1f22",       # View alternate
        "BORDER": "#3b4046",        # derived
        "BORDER_LIGHT": "#34383d",  # derived
        "BORDER_STRONG": "#4d5359",  # derived
        "TEXT": "#fcfcfc",          # Window foreground
        "TEXT_SEC": "#a1a9b1",      # Window inactive
        "TEXT_DIM": "#7d868e",      # derived
        "DISABLED": "#6a7178",      # derived (ColorEffects:Disabled)
        "ON_ACCENT": "#fcfcfc",     # Selection foreground
        "ACCENT": "#3daee9",        # DecorationFocus
        "ACCENT_HOVER": "#55b8ec",  # derived
        "ACCENT_LIGHT": "#1e5774",  # Button alternate (inactive selection)
        "ACCENT_PRESSED": "#2f96d3",  # derived
        "SUCCESS": "#27ae60",
        "SUCCESS_LIGHT": "#1c3827",  # derived
        "WARNING": "#f67400",
        "WARNING_TEXT": "#f89b47",  # derived
        "DANGER": "#da4453",
        "DANGER_SOLID": "#da4453",
        "DANGER_SOLID_HOVER": "#e36a76",  # derived
        "DANGER_SOLID_PRESSED": "#b03745",  # Selection negative
        "STATUS_OK": "#27ae60",
        "STATUS_WARN": "#f67400",
        "STATUS_ERR": "#da4453",
        "HOVER": "#34383d",         # derived
        "ROW_WARN": "#44331a",      # derived (warning tint)
        "TOAST_BG": "#17191c",      # derived (darker than BG)
        "SCROLLBAR_BG": "#202326",  # derived
        "SCROLLBAR_HANDLE": "#4a5058",  # derived
        "SCROLLBAR_HOVER": "#5b6269",  # derived
        "ICON_FG": "#fcfcfc",
        "ICON_FG_DIM": "#a1a9b1",
    }

    @property
    def id(self) -> str:
        return "breeze_dark"

    @property
    def name(self) -> str:
        return "Breeze Dark"


class OxygenTheme:
    """Oxygen — классическая тема KDE 4 (иконки 16px)."""

    _TOKENS: dict[str, str] = {
        "BG": "#d6d2d0",            # Window
        "PANEL": "#dfdcdb",         # Button
        "RAISED": "#ffffff",        # View
        "TRACK": "#cfcbc9",         # derived
        "ALT_ROW": "#f8f7f6",       # View alternate
        "BORDER": "#aaa7a5",        # derived
        "BORDER_LIGHT": "#c0bdbb",  # derived
        "BORDER_STRONG": "#8f8c8a",  # derived
        "TEXT": "#1f1c1b",          # View foreground
        "TEXT_SEC": "#898887",      # Window inactive
        "TEXT_DIM": "#9c9a99",      # derived
        "DISABLED": "#b0aeac",      # derived
        "ON_ACCENT": "#ffffff",     # Selection foreground
        "ACCENT": "#3aa7dd",        # DecorationFocus
        "ACCENT_HOVER": "#6ed6ff",  # DecorationHover
        "ACCENT_LIGHT": "#cbe9f9",  # derived
        "ACCENT_PRESSED": "#3e8acc",  # Selection alternate
        "SUCCESS": "#006e28",       # Positive
        "SUCCESS_LIGHT": "#ddf0e2",  # derived
        "WARNING": "#b08000",       # Neutral
        "WARNING_TEXT": "#8a6600",  # derived
        "DANGER": "#bf0303",        # Negative
        "DANGER_SOLID": "#bf0303",
        "DANGER_SOLID_HOVER": "#d63c3c",  # derived
        "DANGER_SOLID_PRESSED": "#9c0e0e",  # Selection negative
        "STATUS_OK": "#006e28",
        "STATUS_WARN": "#b08000",
        "STATUS_ERR": "#bf0303",
        "HOVER": "#dad9d8",         # Window alternate
        "ROW_WARN": "#f5ecd9",      # derived (warning tint)
        "TOAST_BG": "#181513",      # Tooltip background
        "SCROLLBAR_BG": "#d6d2d0",  # derived
        "SCROLLBAR_HANDLE": "#a3a09d",  # derived
        "SCROLLBAR_HOVER": "#8a8785",  # derived
        "ICON_FG": "#221f1e",       # Window foreground
        "ICON_FG_DIM": "#676563",   # derived
    }

    @property
    def id(self) -> str:
        return "oxygen"

    @property
    def name(self) -> str:
        return "Oxygen"

    def tokens(self) -> dict[str, str]:
        return dict(self._TOKENS)

    def extra_qss(self) -> str:
        return ""

    def icons(self) -> dict[str, str] | None:
        return None

    @property
    def icon_size(self) -> int:
        return 16


class GraphiteTheme:
    """Graphite — собственная нейтральная тёмная тема (иконки 16px)."""

    _TOKENS: dict[str, str] = {
        "BG": "#2b2d2f",
        "PANEL": "#333537",
        "RAISED": "#26282a",
        "TRACK": "#222425",
        "ALT_ROW": "#313335",
        "BORDER": "#3e4144",
        "BORDER_LIGHT": "#36393c",
        "BORDER_STRONG": "#4a4d50",
        "TEXT": "#e8eaec",
        "TEXT_SEC": "#a9adb1",
        "TEXT_DIM": "#7e8286",
        "DISABLED": "#6f7377",
        "ON_ACCENT": "#1d1f21",
        "ACCENT": "#8fa6bb",        # светлая сталь
        "ACCENT_HOVER": "#a1b5c7",
        "ACCENT_LIGHT": "#37424c",
        "ACCENT_PRESSED": "#7d94a9",
        "SUCCESS": "#7fbf8e",
        "SUCCESS_LIGHT": "#2c3a2f",
        "WARNING": "#d9a05b",
        "WARNING_TEXT": "#e0b077",
        "DANGER": "#d97379",
        "DANGER_SOLID": "#b8555c",
        "DANGER_SOLID_HOVER": "#c6676e",
        "DANGER_SOLID_PRESSED": "#9c454c",
        "STATUS_OK": "#7fbf8e",
        "STATUS_WARN": "#d9a05b",
        "STATUS_ERR": "#d97379",
        "HOVER": "#383b3e",
        "ROW_WARN": "#3d3527",
        "TOAST_BG": "#1e2022",
        "SCROLLBAR_BG": "#2b2d2f",
        "SCROLLBAR_HANDLE": "#45484c",
        "SCROLLBAR_HOVER": "#565a5e",
        "ICON_FG": "#c9cdd1",
        "ICON_FG_DIM": "#8f9397",
    }

    @property
    def id(self) -> str:
        return "graphite"

    @property
    def name(self) -> str:
        return "Graphite"

    def tokens(self) -> dict[str, str]:
        return dict(self._TOKENS)

    def extra_qss(self) -> str:
        return ""

    def icons(self) -> dict[str, str] | None:
        return None

    @property
    def icon_size(self) -> int:
        return 16


# ── System (следует схеме ОС) ───────────────────────────────────────

_scheme_resolver = None


def set_scheme_resolver(fn) -> None:
    """Хук движка: fn() -> "light" | "dark" (текущая схема ОС)."""
    global _scheme_resolver
    _scheme_resolver = fn


def _resolved_breeze():
    resolver = _scheme_resolver or (lambda: "light")
    return BreezeDarkTheme() if resolver() == "dark" else BreezeTheme()


class SystemTheme:
    """Системная тема: Breeze Light/Dark по colorScheme окружения."""

    @property
    def id(self) -> str:
        return "system"

    @property
    def name(self) -> str:
        return "System"

    def tokens(self) -> dict[str, str]:
        return _resolved_breeze().tokens()

    def extra_qss(self) -> str:
        return _resolved_breeze().extra_qss()

    def icons(self) -> dict[str, str] | None:
        return _resolved_breeze().icons()

    @property
    def icon_size(self) -> int:
        return _resolved_breeze().icon_size


# Явная проверка контракта при импорте модуля.
assert isinstance(LightTheme(), ThemePlugin)
for _plugin in (BreezeTheme(), BreezeDarkTheme(), OxygenTheme(),
                GraphiteTheme(), SystemTheme()):
    assert isinstance(_plugin, ThemePlugin)
