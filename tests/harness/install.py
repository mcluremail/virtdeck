"""M4.0: seams for mounting fakes into the real provider and PBS client.

PVE: `install_fake_pve` patches the `ProxmoxAPI` name in the
`virtdeck.provider._session` module. The factory builds a real proxmoxer
object (token-auth — no network round-trip) and mounts `FakeApiAdapter`
on its internal `requests.Session` (`_store["session"]` — the same seam
production code uses for explicit proxies). Fakes are routed by host:
`cfg["host"]` must match `api.name`.

PBS: `pbs_session` — a requests.Session with the fake's adapter; passed
to `PbsClient(cfg, http=...)` (a DI parameter added for the harness).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import requests

from .adapter import FakeApiAdapter, ReplayAdapter

if TYPE_CHECKING:
    from requests.adapters import BaseAdapter


def fake_pve_cfg(name: str = "fake1", **extra) -> dict:
    """Provider cfg pointing at the fake (host = api.name)."""
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
    """Patches ProxmoxAPI in provider._session: adapter by host."""
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
    """Routes provider requests to FakePveApi by host.

    `record_into` — a shared entry list (fixture format): every request
    of any provider is appended there (scenario recording for replay).
    """
    by_host = {api.name: api for api in apis}

    def make_adapter(host: str) -> BaseAdapter:
        api = by_host.get(host)
        if api is None:
            raise AssertionError(
                f"no FakePveApi for host={host!r} "
                f"(have: {sorted(by_host)})")
        return FakeApiAdapter(api.handle, record_into=record_into)

    _install_proxmox_patch(monkeypatch, make_adapter)


def install_replay_pve(monkeypatch, entries: list[dict]) -> None:
    """Serves all providers from recorded entries (replay)."""
    adapter = ReplayAdapter(entries)
    _install_proxmox_patch(monkeypatch, lambda _host: adapter)


def pbs_session(api) -> requests.Session:
    """Session with a FakePbsApi adapter — for `PbsClient(cfg, http=...)`."""
    sess = requests.Session()
    adapter = FakeApiAdapter(api.handle)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess
