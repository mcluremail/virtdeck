"""M4.0: швы монтирования фейков в реальный код провайдера и PBS-клиента.

PVE: `install_fake_pve` патчит имя `ProxmoxAPI` в модуле
`virtdeck.provider._session`. Фабрика создаёт настоящий объект proxmoxer
(token-auth — сетевого round-trip'а нет) и монтирует `FakeApiAdapter`
на его внутреннюю `requests.Session` (`_store["session"]` — тот же шов,
которым прод-код пользуется для явного прокси). Маршрутизация фейков по
host: `cfg["host"]` должен совпадать с `api.name`.

PBS: `pbs_session` — requests.Session с адаптером фейка; передаётся в
`PbsClient(cfg, http=...)` (DI-параметр, добавлен для харнесса).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import requests

from .adapter import FakeApiAdapter, ReplayAdapter

if TYPE_CHECKING:
    from requests.adapters import BaseAdapter


def fake_pve_cfg(name: str = "fake1", **extra) -> dict:
    """cfg провайдера, указывающий на фейк (host = api.name)."""
    cfg = {
        "name": name,
        "host": name,
        "user": "root@pam",
        "token_name": "harness",
        "token_value": "fake-token",
        "trust_ssl": True,
    }
    cfg.update(extra)
    return cfg


def _install_proxmox_patch(monkeypatch,
                           make_adapter: Callable[[str], BaseAdapter]) -> None:
    """Патчит ProxmoxAPI в provider._session: адаптер по host."""
    import virtdeck.provider._session as session_mod

    real_proxmox_api = session_mod.ProxmoxAPI

    def factory(host, **kwargs):
        adapter = make_adapter(host)
        prox = real_proxmox_api(host, **kwargs)
        sess = prox._store.get("session")
        if sess is not None:
            sess.mount("https://", adapter)
            sess.mount("http://", adapter)
        return prox

    monkeypatch.setattr(session_mod, "ProxmoxAPI", factory)


def install_fake_pve(monkeypatch, *apis, record_into: list | None = None) \
        -> None:
    """Маршрутизирует запросы провайдеров в FakePveApi по host.

    `record_into` — общий список entry (формат фиксстуры): каждый запрос
    любого провайдера дописывается туда (запись сценария для replay).
    """
    by_host = {api.name: api for api in apis}

    def make_adapter(host: str) -> BaseAdapter:
        api = by_host.get(host)
        if api is None:
            raise AssertionError(
                f"нет FakePveApi для host={host!r} "
                f"(есть: {sorted(by_host)})")
        return FakeApiAdapter(api.handle, record_into=record_into)

    _install_proxmox_patch(monkeypatch, make_adapter)


def install_replay_pve(monkeypatch, entries: list[dict]) -> None:
    """Обслуживает все провайдеров из записанных entry (replay)."""
    adapter = ReplayAdapter(entries)
    _install_proxmox_patch(monkeypatch, lambda _host: adapter)


def pbs_session(api) -> requests.Session:
    """Session с адаптером FakePbsApi — в `PbsClient(cfg, http=...)`."""
    sess = requests.Session()
    adapter = FakeApiAdapter(api.handle)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess
