"""PbsClient — REST client for Proxmox Backup Server (B17 stage 2).

PBS serves its API on port 8007 under ``/api2/json``. Authentication uses
a ticket obtained via ``POST /access/ticket`` (username ``user@realm`` or
``user@pbs!tokenid`` plus password/token secret); subsequent requests carry
the ``PBSAuthCookie`` cookie and the ``CSRFPreventionToken`` header.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

PBS_PORT = 8007


class PbsError(Exception):
    """Raised for PBS connection / API errors."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def _q(value) -> str:
    """URL-encode a path segment."""
    return quote(str(value), safe="")


class PbsClient:
    """Ticket-authenticated PBS API client (login on demand)."""

    def __init__(self, cfg: dict, timeout: float = 15,
                 http: requests.Session | None = None):
        self._host = cfg.get("host", "")
        self._port = int(cfg.get("port", PBS_PORT) or PBS_PORT)
        self._user = cfg.get("user", "root@pam")
        self._secret = cfg.get("token_value", "")
        self._timeout = timeout
        self._base = f"https://{self._host}:{self._port}/api2/json"
        self._ticket: str = ""
        self._csrf: str = ""
        # http — DI-шов тестового харнесса (M4.0): подмена транспорта.
        self._http = http if http is not None else requests.Session()
        if cfg.get("trust_ssl", False):
            self._http.verify = False
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:  # pragma: no cover
                pass
        proxy = str(cfg.get("proxy") or "").strip()
        if proxy:
            # Явный прокси: env-прокси не должен перебивать session-level.
            self._http.trust_env = False
            self._http.proxies.update({"http": proxy, "https": proxy})

    def close(self) -> None:
        """Release the underlying TLS connection pool."""
        self._http.close()

    # ── auth ─────────────────────────────────────────────────────

    def login(self) -> None:
        """Obtain a ticket (password or API-token secret as password)."""
        try:
            resp = self._http.post(
                f"{self._base}/access/ticket",
                data={"username": self._user, "password": self._secret},
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout as e:
            raise PbsError(f"PBS timeout: {e}") from e
        except requests.exceptions.RequestException as e:
            raise PbsError(f"PBS connection failed: {e}") from e
        if resp.status_code != 200:
            raise PbsError(
                f"PBS auth failed (HTTP {resp.status_code})", resp.status_code)
        data = (resp.json() or {}).get("data") or {}
        ticket = data.get("ticket", "")
        csrf = data.get("CSRFPreventionToken", "")
        if not ticket:
            raise PbsError("PBS auth failed: no ticket in response")
        self._ticket = ticket
        self._csrf = csrf

    def _headers(self) -> dict:
        return {"CSRFPreventionToken": self._csrf} if self._csrf else {}

    def _cookies(self) -> dict:
        return {"PBSAuthCookie": self._ticket} if self._ticket else {}

    # ── request helpers ──────────────────────────────────────────

    def _request(self, method: str, path: str, params=None, data=None,
                 retried: bool = False):
        if not self._ticket:
            self.login()
        try:
            resp = self._http.request(
                method,
                f"{self._base}{path}",
                params=params or None,
                data=data,
                headers=self._headers(),
                cookies=self._cookies(),
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout as e:
            raise PbsError(f"PBS timeout: {e}") from e
        except requests.exceptions.RequestException as e:
            raise PbsError(f"PBS connection failed: {e}") from e
        if resp.status_code == 401 and not retried:
            self._ticket = ""
            self._csrf = ""
            return self._request(method, path, params=params, data=data,
                                 retried=True)
        if resp.status_code not in (200, 201):
            detail = ""
            try:
                err = (resp.json() or {}).get("errors") or {}
                detail = str(err) if err else ""
            except ValueError:
                pass
            raise PbsError(
                f"PBS API error (HTTP {resp.status_code}) {path} {detail}".rstrip(),
                resp.status_code)
        try:
            return (resp.json() or {}).get("data")
        except ValueError:
            return None

    def get(self, path: str, **params):
        return self._request("GET", path, params=params or None)

    def post(self, path: str, data: dict | None = None):
        return self._request("POST", path, data=data or {})

    def delete(self, path: str, **params):
        return self._request("DELETE", path, params=params or None)

    # ── high-level endpoints ─────────────────────────────────────

    def version(self) -> dict:
        return self.get("/version") or {}

    def nodes(self) -> list[dict]:
        return self.get("/nodes") or []

    def datastores(self) -> list[dict]:
        """Datastore configs (name, path, comment, ...)."""
        return self.get("/config/datastore") or []

    def datastore_status(self, store: str) -> dict:
        return self.get(f"/admin/datastore/{_q(store)}/status") or {}

    def namespaces(self, store: str, parent: str = "") -> list[dict]:
        """Namespaces below ``parent`` (list of {ns, name?})."""
        params = {"parent": parent} if parent else None
        return self.get(f"/admin/datastore/{_q(store)}/namespace",
                        **(params or {})) or []

    def snapshots(self, store: str, ns: str = "") -> list[dict]:
        params = {"ns": ns} if ns else None
        return self.get(f"/admin/datastore/{_q(store)}/snapshots",
                        **(params or {})) or []

    def jobs(self, kind: str) -> list[dict]:
        """List job configs: kind in sync/verify/prune."""
        if kind not in ("sync", "verify", "prune"):
            raise ValueError(f"unknown job kind: {kind!r}")
        return self.get(f"/admin/{kind}") or []

    def run_job(self, kind: str, job_id: str) -> str:
        """Start a job, return the UPID."""
        return self.post(f"/admin/{kind}/{_q(job_id)}/run") or ""

    def verify_datastore(self, store: str) -> str:
        """Start a datastore verify job, return the UPID."""
        return self.post(f"/admin/datastore/{_q(store)}/verify") or ""

    def forget_snapshot(self, store: str, backup_type: str, backup_id: str,
                        backup_time: int, ns: str = "") -> None:
        """Forget (delete) a snapshot."""
        params = {"backup-type": backup_type, "backup-id": backup_id,
                  "backup-time": str(int(backup_time))}
        if ns:
            params["ns"] = ns
        self.delete(f"/admin/datastore/{_q(store)}/snapshots", **params)
