# VirtDeck Theme Contract (v1)

This document is the public contract for VirtDeck themes. It describes the
`ThemePlugin` API, the canonical color token set, and what happens when a
theme is activated. Anything not described here is an implementation detail
and may change; anything described here is stable for v1.

> **Status:** contract v1, shipped in 3.0. A declarative JSON theme format
> and a third-party theme import channel are planned **after** 3.0 (see
> [Delivery channels](#delivery-channels)).

---

## 1. Architecture in one paragraph

The core owns the QSS template and the canonical token set (`virtdeck/ui/theme.py:TOKENS`).
A theme is a plugin that supplies **colors only**: it returns a full mapping of
canonical token names to `#rrggbb` values. On activation the engine validates
the mapping, swaps the values on the live `Color` facade, rebuilds the
application-wide QSS from the built-in template, applies optional icon
overrides and extra QSS contributed by the theme, and repaints charts and
cached-color consumers. Widgets never hardcode colors — they read
`theme.Color.TOKEN`, so a theme switch restyles the whole application with a
single `setStyleSheet` pass.

```
ThemePlugin.tokens() ─▶ validate ─▶ Color facade ─▶ QSS rebuild ─▶ app.setStyleSheet
       │                                                        │
       ├─ icons()  (optional, partial icon override)            ├─ icons re-render
       ├─ extra_qss() (optional, appended verbatim)             ├─ charts recolor
       └─ icon_size (optional, default 16)                      └─ listeners notified
```

## 2. ThemePlugin API

Defined in `virtdeck/plugins/base.py` as the `ThemePlugin` protocol:

| Member | Required | Signature | Description |
| --- | --- | --- | --- |
| `id` | yes | `str` property | Stable theme id (lowercase, used for persistence). |
| `name` | yes | `str` property | Human-readable name shown in the theme combo. |
| `tokens` | yes | `tokens() -> dict[str, str]` | Full canonical token set (see §3). |
| `extra_qss` | no | `extra_qss() -> str` | QSS appended verbatim after the built-in template (density tweaks, extra selectors). |
| `icons` | no | `icons() -> dict[str, str] \| None` | Partial icon override: icon name → SVG source (see §6). |
| `icon_size` | no | `int` property, default `16` | Base icon size in px; every icon scales from it (see §6). |

**Validation** (`theme.validate_tokens`):

* `tokens()` must return a `dict`.
* Every value must be a string matching `#[0-9a-fA-F]{6}` — six-digit hex
  only; no `#rgb`, no `rgba()`, no `transparent`.
* Every key must be a canonical token name (§3) or a legacy alias (§4).
* The mapping must cover **all 36** canonical tokens; missing names raise.
* Violations raise `plugins.PluginError` and the theme is not activated.

**Error isolation:** failures inside `icons()` or `extra_qss()` are logged
and ignored — the theme still activates with the built-in icons and template.
A failure in `tokens()` aborts activation; at startup the saved theme id is
re-tried and, if it fails, the app falls back to the built-in Light theme.

## 3. Canonical token set (36)

The contract is exactly these 36 tokens. The reference column shows the
built-in **Light** palette values — use them as an anchor when designing
cohesive alternatives.

### Backgrounds

| Token | Purpose | Light |
| --- | --- | --- |
| `BG` | Window background | `#fafafa` |
| `PANEL` | Panels, cards, controls | `#ffffff` |
| `RAISED` | Raised hover background | `#f4f5f7` |
| `TRACK` | Sunken background: progress tracks, segment wells | `#f3f4f6` |
| `ALT_ROW` | Alternating table rows | `#f8f9fb` |

### Borders

| Token | Purpose | Light |
| --- | --- | --- |
| `BORDER` | Standard hairline borders | `#e5e7eb` |
| `BORDER_LIGHT` | Subtle separators | `#f0f1f4` |
| `BORDER_STRONG` | Emphasized control outline | `#cbd5e1` |

### Text

| Token | Purpose | Light |
| --- | --- | --- |
| `TEXT` | Primary text | `#181c26` |
| `TEXT_SEC` | Secondary text | `#6b7280` |
| `TEXT_DIM` | Dim/hint text | `#9ca3af` |
| `DISABLED` | Disabled text and controls | `#b0b8c4` |
| `ON_ACCENT` | Text/strokes on saturated fills | `#ffffff` |

### Accent

| Token | Purpose | Light |
| --- | --- | --- |
| `ACCENT` | Primary accent (selection, focus, actions) | `#0a6ed1` |
| `ACCENT_HOVER` | Hover state of accent elements | `#005bbf` |
| `ACCENT_LIGHT` | Accent-tinted backgrounds | `#e8f0fe` |
| `ACCENT_PRESSED` | Pressed controls (spin arrows, etc.) | `#c6dafc` |

### Statuses

| Token | Purpose | Light |
| --- | --- | --- |
| `SUCCESS` | Positive status text/strokes | `#16a34a` |
| `SUCCESS_LIGHT` | Light green surface (toasts) | `#bbf7d0` |
| `WARNING` | Warning strokes/borders | `#d97706` |
| `WARNING_TEXT` | Dark amber hint text | `#b45309` |
| `DANGER` | Error accent in text/frames | `#dc2626` |
| `DANGER_SOLID` | Saturated red: strict text, solid button | `#c0392b` |
| `DANGER_SOLID_HOVER` | Hover of solid danger | `#e74c3c` |
| `DANGER_SOLID_PRESSED` | Pressed of solid danger | `#a93226` |
| `STATUS_OK` | Indicator dots/icons: ok | `#22c55e` |
| `STATUS_WARN` | Indicator dots/icons: warning | `#f59e0b` |
| `STATUS_ERR` | Indicator dots/icons: error | `#ef4444` |

### Rows and surfaces

| Token | Purpose | Light |
| --- | --- | --- |
| `HOVER` | Row/cell highlight | `#e8edf4` |
| `ROW_WARN` | Warning row background | `#fff3cd` |
| `TOAST_BG` | Dark toast backdrop | `#1f2937` |

### Scrollbar

| Token | Purpose | Light |
| --- | --- | --- |
| `SCROLLBAR_BG` | Scrollbar groove | `#eef1f5` |
| `SCROLLBAR_HANDLE` | Scrollbar handle | `#c0c6d0` |
| `SCROLLBAR_HOVER` | Handle hover | `#a4abb8` |

### Icons

| Token | Purpose | Light |
| --- | --- | --- |
| `ICON_FG` | Primary SVG icon stroke | `#4b5563` |
| `ICON_FG_DIM` | Secondary stroke | `#374151` |

### Font tokens — not part of the contract

`UI_FONT` and `MONO_FONT` exist on the `Color` facade but are resolved by the
engine from fonts installed on the system (`_resolve_fonts`). Themes must not
supply them; they are not accepted by `validate_tokens`.

## 4. Legacy aliases

For convenience, themes built on older in-repo scale names may use the
following aliases on **input**. The engine maps them to canonical tokens
during validation; canonical names always win if both are supplied. Built-in
themes do not use aliases.

| Alias | Canonical |
| --- | --- |
| `GRAY_400` / `GRAY_500` / `GRAY_200` / `GRAY_100` | `TEXT_DIM` / `TEXT_SEC` / `BORDER` / `TRACK` |
| `SLATE_100` / `SLATE_200` / `SLATE_300` / `SLATE_400` / `SLATE_500` | `TRACK` / `HOVER` / `BORDER_STRONG` / `BORDER_STRONG` / `TEXT_SEC` |
| `SLATE_700` / `SLATE_800` / `SLATE_900` | `TEXT` / `TOAST_BG` / `ICON_FG_DIM` |
| `D1_D5_DB` / `ERROR_RED` | `BORDER_STRONG` / `DANGER_SOLID` |
| `ACCENT_GREEN` / `OK_ROW_BG` | `SUCCESS` / `SUCCESS_LIGHT` |
| `WARN_BG` / `WARN_ROW_BG` / `WARN_BORDER` | `ROW_WARN` / `ROW_WARN` / `WARNING` |
| `SELECTED` | `HOVER` |

## 5. Activation pipeline

`theme.load_theme(theme_id, registry=None, persist=True)` performs, in order:

1. Resolve the plugin from the registry (`plugins.PluginRegistry.get_theme`).
2. `validate_tokens(plugin.tokens())` → canonical mapping.
3. `apply_tokens()` — values are swapped onto the `Color` facade (`setattr`),
   so anything reading `Color.X` immediately sees the theme.
4. Register the System-scheme resolver and set the active id.
5. `icons()` override (exception-isolated) → `set_theme_icons()` →
   `reset_icons()` re-renders the icon cache.
6. `extra_qss()` (exception-isolated) → the application QSS is rebuilt as
   `built-in template + extra_qss` and applied with `app.setStyleSheet`.
7. `set_base_size(plugin.icon_size or 16)`.
8. Charts (pyqtgraph) recolor via `apply_chart_colors`.
9. Persist the id: `config.save_ui_state("theme", theme_id)` (skipped with
   `persist=False`, used at startup).
10. Notify subscribers of `subscribe_theme_changed(fn)` — widgets that cache
    `QColor`/`QBrush` objects must repaint there.

At startup `main.py` calls `theme.load()` (Light, no persistence), and the
status-bar switcher restores the saved id with fallback to Light on failure.

## 6. Icon overrides

A theme may replace any subset of the built-in SVG icon set: `icons()` returns
a partial `{name: svg_source}` dict; names not present fall back to the
built-in set, recolored from theme tokens. Unknown names in the dict are
ignored by consumers — overrides only take effect for names the app requests.

**Built-in icon names** (43):
`add`, `about`, `app`, `acl`, `backup`, `clone`, `cluster`, `collapse`,
`console`, `disk`, `download`, `expand`, `export`, `folder`, `group`,
`ha`, `hardware`, `history`, `host`, `import`, `iso`, `lock`, `migrate`,
`monitor`, `network`, `options`, `pci`, `pool`, `refresh`, `remove`,
`reset`, `reboot`, `resume`, `restore`, `role`, `search`, `serial`,
`services`, `shutdown`, `snapshot`, `start`, `stop`, `storage`, `template`,
`token`, `tpm`, `unlock`, `upload`, `usb`, `user`, `vm`.

**Recoloring:** built-in templates use `{c}`, `{c2}`, `{ok}`, `{err}`, `{b}`
placeholders filled with `ICON_FG`, `ICON_FG_DIM`, `STATUS_OK`, `STATUS_ERR`,
`BORDER`. A foreign SVG **without** placeholders is used as-is (verbatim), so
a theme has full control over its own artwork. Inline SVG only — no external
files are loaded. The Breeze override ships a **filled fixed-color set**
(approved 2026-09-15) — its SVGs carry literal hex colors and render
identically in light and dark, by design.

**Sizing:** every icon is rendered at exactly `icon_size` px — no per-name
down-scaling (owner decision 2026-09-15: "все иконки в 24px, ВСЕ"). The only
exception is the branded `app` mark at 1.5×. All icon slots (tree, toolbar,
toggle buttons) take their size from `icons.base_size()` and follow the
active theme. The status dot overlaid by `get_icon(name, status)` scales from
the template viewBox. The built-in Breeze/Breeze Dark themes ship an original
24 px icon set covering the whole registry and set `icon_size = 24` —
density is tuned through `extra_qss()`.

**Contrast:** every built-in theme keeps WCAG legibility for text:
`TEXT`/`TEXT_SEC`/`STATUS_*`/`DANGER` >= 4.5:1 and `TEXT_DIM`/`DISABLED` >= 3.0:1
on every background token, `ON_ACCENT` >= 4.5:1 on `ACCENT`. Dark themes
(Breeze Dark, Graphite, System-dark) use dark selection text on the light-blue
accent; light themes use darkened status colors (KDE/Material hues that could
not reach 4.5 on light backgrounds were darkened). Some derived tokens
therefore deviate from the exact scheme values. Locked by
`test_theme_text_contrast`.

**Label backgrounds:** the global `QWidget {{ background: BG }}` rule paints
every styled widget, so text widgets (`QLabel`, `QCheckBox`, `QRadioButton`,
`QGroupBox`) are explicitly `background: transparent` — they must show their
container's surface (card PANEL/RAISED), not the window background.

## 7. Built-in themes and ordering

| id | Name | Notes |
| --- | --- | --- |
| `light` | Light | Default; the reference palette of §3. |
| `breeze` | Breeze | Exact KDE Breeze palette (values taken from KDE's LGPL-2.0-or-later scheme files as reference data); original 24 px icon set. |
| `breeze_dark` | Breeze Dark | KDE Breeze Dark palette; 24 px icon set. |
| `oxygen` | Oxygen | From KDE `Oxygen.colors`. |
| `graphite` | Graphite | Neutral dark with steel accent. |
| `system` | System | Follows the OS color scheme live (Qt `colorScheme` + `colorSchemeChanged` listener); reports active id `system`. |

`theme.ordered_theme_ids(registry)` returns themes in that fixed UX order;
unknown (future third-party) ids are appended alphabetically.

## 8. Delivery channels

* **Built-in** — shipped in `virtdeck/plugins/_themes.py`, registered at
  startup into the process registry (`plugins.get_registry()`).
* **Third-party import** — *not implemented yet.* The registry already
  supports it (`register_theme` / `unregister`); the plan is `.py` theme
  modules discovered in the user config directory, registered before the
  saved theme is restored. Targeted after 3.0.
* **JSON themes** — declarative format, after 3.0.

## 9. Minimal example

A complete, valid custom theme — every canonical token supplied, no aliases:

```python
"""Violet — an example VirtDeck theme (contract v1)."""

ACCENT = "#7c3aed"


class VioletTheme:
    id = "violet"
    name = "Violet"
    icon_size = 16

    def tokens(self) -> dict[str, str]:
        return {
            # Backgrounds
            "BG": "#14141b", "PANEL": "#1c1c26", "RAISED": "#242432",
            "TRACK": "#101018", "ALT_ROW": "#181822",
            # Borders
            "BORDER": "#2c2c3a", "BORDER_LIGHT": "#232333",
            "BORDER_STRONG": "#3d3d52",
            # Text
            "TEXT": "#e7e7f0", "TEXT_SEC": "#a0a0b8", "TEXT_DIM": "#6e6e88",
            "DISABLED": "#55556b", "ON_ACCENT": "#ffffff",
            # Accent
            "ACCENT": ACCENT, "ACCENT_HOVER": "#6d28d9",
            "ACCENT_LIGHT": "#2a2440", "ACCENT_PRESSED": "#3b2f5c",
            # Statuses
            "SUCCESS": "#22c55e", "SUCCESS_LIGHT": "#14532d",
            "WARNING": "#f59e0b", "WARNING_TEXT": "#fbbf24",
            "DANGER": "#ef4444", "DANGER_SOLID": "#dc2626",
            "DANGER_SOLID_HOVER": "#f87171", "DANGER_SOLID_PRESSED": "#b91c1c",
            "STATUS_OK": "#4ade80", "STATUS_WARN": "#facc15",
            "STATUS_ERR": "#f87171",
            # Rows and surfaces
            "HOVER": "#26263a", "ROW_WARN": "#3a2f14", "TOAST_BG": "#26263a",
            # Scrollbar
            "SCROLLBAR_BG": "#1a1a24", "SCROLLBAR_HANDLE": "#3d3d52",
            "SCROLLBAR_HOVER": "#4d4d66",
            # Icons
            "ICON_FG": "#c3c3d5", "ICON_FG_DIM": "#8a8aa3",
        }

    def extra_qss(self) -> str:
        return ""  # optional: density tweaks, extra selectors
```

Registering (until the import channel ships, e.g. from a debug hook):

```python
from virtdeck.plugins import get_registry
from virtdeck.ui.theme import load_theme

registry = get_registry()
registry.register_theme(VioletTheme())
load_theme("violet")
```
