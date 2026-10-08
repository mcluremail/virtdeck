"""Plugin API seed (v3.5, ARCHITECTURE.md).

A plugin is a named extension unit contributing functionality to the
application. The first family is data-source plugins: they build a
DataProvider from a host config dict. The Proxmox VE plugin is built-in;
PBS (B17 stage 2) and virtdeck Server (v4.0) land as further plugins
without touching backend workers.

Feature plugins (Notifications, Policies, Reports, Prometheus, Redfish)
will extend this seam later; registration stays explicit — no dynamic
import magic.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..provider import DataProvider


class PluginError(Exception):
    """Raised for unknown plugin ids or misuse of a registered plugin."""


@runtime_checkable
class Plugin(Protocol):
    """Named extension unit."""

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


@runtime_checkable
class ProviderPlugin(Plugin, Protocol):
    """Data-source plugin: builds a DataProvider from a host config.

    Host configs carry ``"type"`` (missing type defaults to ``"pve"``);
    the plugin receives the raw config dict and must return an object
    satisfying provider.DataProvider.
    """

    def create_provider(self, cfg: dict, timeout: float = 15) -> DataProvider: ...


@runtime_checkable
class ThemePlugin(Plugin, Protocol):
    """Theme plugin: supplies color tokens for the QSS engine (v1).

    The core owns the QSS template and the canonical token set
    (ui/theme.TOKENS); a theme only supplies colors. ``tokens()`` must
    cover the whole canonical set — the activation engine validates it.
    Optional extension points: ``extra_qss()`` (appended verbatim after
    the built-in template — density tweaks, extra selectors) and
    ``icons()`` (partial override: icon name -> SVG source; missing
    names fall back to the built-in set recolored with theme tokens)
    plus ``icon_size`` (base icon size in px, default 24).
    """

    def tokens(self) -> dict[str, str]: ...

    def extra_qss(self) -> str:
        return ""

    def icons(self) -> dict[str, str] | None:
        return None

    @property
    def icon_size(self) -> int:
        return 24


class PluginRegistry:
    """Id → plugin map with data-source dispatch and theme lookup."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._themes: dict[str, ThemePlugin] = {}

    def register(self, plugin: Plugin) -> None:
        pid = plugin.id
        if pid in self._plugins:
            raise PluginError(f"plugin already registered: {pid!r}")
        self._plugins[pid] = plugin

    def unregister(self, plugin_id: str) -> None:
        """Unregister a plugin (e.g. importing third-party themes as a replacement)."""
        if plugin_id in self._themes:
            del self._themes[plugin_id]
            return
        if plugin_id not in self._plugins:
            raise PluginError(f"unknown plugin: {plugin_id!r}")
        del self._plugins[plugin_id]

    def get(self, plugin_id: str) -> Plugin:
        try:
            return self._plugins[plugin_id]
        except KeyError:
            raise PluginError(f"unknown plugin: {plugin_id!r}") from None

    def ids(self) -> list[str]:
        return sorted(self._plugins)

    # -- Themes --

    def register_theme(self, plugin: ThemePlugin) -> None:
        """Register a theme with contract-method validation."""
        for attr in ("tokens", "extra_qss", "icons"):
            if not callable(getattr(plugin, attr, None)):
                raise PluginError(
                    f"theme {plugin.id!r} is missing {attr}()")
        tid = plugin.id
        if tid in self._plugins or tid in self._themes:
            raise PluginError(f"plugin already registered: {tid!r}")
        self._themes[tid] = plugin

    def theme_ids(self) -> list[str]:
        """Ids of all registered themes."""
        return sorted(self._themes)

    def get_theme(self, theme_id: str) -> ThemePlugin:
        try:
            plugin = self._themes[theme_id]
        except KeyError:
            raise PluginError(f"unknown theme: {theme_id!r}") from None
        return plugin

    def create_provider(self, cfg: dict, timeout: float = 15) -> DataProvider:
        plugin_id = cfg.get("type", "pve")
        plugin = self.get(plugin_id)
        create = getattr(plugin, "create_provider", None)
        if create is None:
            raise PluginError(
                f"plugin {plugin_id!r} does not provide data sources")
        return create(cfg, timeout=timeout)
