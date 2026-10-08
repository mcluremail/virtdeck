"""ProxmoxSession — unified connection to PVE API.

Wraps proxmoxer.ProxmoxAPI with unified error handling, SSL management,
and connection lifecycle.  All provider API modules use this class instead
of creating raw ProxmoxAPI / requests.Session instances.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

import urllib3
from proxmoxer import ProxmoxAPI

from ._errors import ProxmoxError, from_exception

if TYPE_CHECKING:
    import requests

logger = logging.getLogger(__name__)

PVE_PORT = 8006

_WARN_SUPPRESSED = False

# Explicit proxy is set per-host: cfg["proxy"] (the "Proxy" field in the
# add-server dialog). Empty/missing — standard requests behavior:
# env proxies (HTTP(S)_PROXY, ALL_PROXY, no_proxy) are honored, like curl.
# An explicit URL fully replaces env: trust_env=False + session.proxies,
# otherwise session-level proxies lose to env proxies in requests.


def _suppress_ssl_warnings() -> None:
    global _WARN_SUPPRESSED
    if not _WARN_SUPPRESSED:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        _WARN_SUPPRESSED = True


def _proxy_url(cfg: dict) -> str | None:
    """Explicit per-host proxy URL from cfg["proxy"] (empty → None)."""
    url = str(cfg.get("proxy") or "").strip()
    return url or None


def _proxies(url: str | None) -> dict[str, str] | None:
    """requests proxies dict for an explicit proxy URL (None → env default)."""
    return {"http": url, "https": url} if url else None


def build_requests_session(cfg: dict) -> requests.Session:
    """Raw requests session with per-host proxy (for UI raw workers).

    A bare Session() ignores cfg["proxy"] — in proxy-only environments all
    raw workers timed out while the tree via provider kept working.
    Explicit proxy: trust_env=False + proxies (env does not override
    session-level). Empty cfg["proxy"]: env proxies honored as before
    (trust_env=True).
    """
    import requests  # deferred: keep requests out of the startup path (cfce3cd)

    sess = requests.Session()
    proxy = _proxy_url(cfg)
    if proxy:
        sess.trust_env = False
        sess.proxies.update({"http": proxy, "https": proxy})
    return sess


def _verify_ssl(cfg: dict) -> bool:
    """Return verify_ssl value for requests/proxmoxer.

    trust_ssl=False (default) → strict verification, verify_ssl=True.
    trust_ssl=True → accept any cert, verify_ssl=False.
    """
    trust = cfg.get("trust_ssl", False)
    if trust:
        _suppress_ssl_warnings()
    return not bool(trust)


def _q(value) -> str:
    """URL-encode a path segment for proxmoxer."""
    return quote(str(value), safe="")


class ProxmoxSession:
    """Wraps ProxmoxAPI with unified error handling and connection lifecycle."""

    def __init__(self, cfg: dict, timeout: float = 15) -> None:
        self.cfg = cfg
        self.timeout = timeout
        self._proxmox: ProxmoxAPI | None = None
        self._closed = False

    @property
    def proxmox(self) -> ProxmoxAPI:
        if self._proxmox is None:
            proxy = _proxy_url(self.cfg)
            self._proxmox = ProxmoxAPI(
                self.cfg["host"],
                user=self.cfg["user"],
                token_name=self.cfg["token_name"],
                token_value=self.cfg["token_value"],
                verify_ssl=_verify_ssl(self.cfg),
                timeout=self.timeout,
                proxies=_proxies(proxy),
            )
            if proxy:
                # proxmoxer 2.3.0 does not apply the proxies kwarg to
                # token-auth requests — pin the explicit proxy on the
                # session directly.
                sess = self._proxmox._store.get("session")
                if sess is not None:
                    sess.trust_env = False
                    sess.proxies.update(_proxies(proxy))
        return self._proxmox

    def close(self) -> None:
        """Close underlying requests.Session to prevent connection pool leaks."""
        if self._closed:
            return
        self._closed = True
        if self._proxmox is not None:
            try:
                sess = self._proxmox._store.get("session")
                if sess is not None:
                    sess.close()
            except Exception:
                pass

    def __enter__(self) -> ProxmoxSession:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- convenience: call proxmoxer chain, convert exceptions --

    def call(self, func, *args, **kwargs):
        """Call a proxmoxer accessor with unified exception conversion."""
        try:
            return func(*args, **kwargs)
        except ProxmoxError:
            raise
        except Exception as exc:
            raise from_exception(exc) from exc

    @property
    def host(self) -> str:
        return self.cfg["host"]

    @property
    def auth_header(self) -> str:
        return (
            f"PVEAPIToken={self.cfg['user']}!{self.cfg['token_name']}"
            f"={self.cfg['token_value']}"
        )

    @property
    def verify(self) -> bool:
        return _verify_ssl(self.cfg)

    @property
    def request_proxies(self) -> dict[str, str] | None:
        """Explicit proxies for raw requests calls (None → env default)."""
        return _proxies(_proxy_url(self.cfg))

    @property
    def base_url(self) -> str:
        return f"https://{self.cfg['host']}:{PVE_PORT}/api2/json"
