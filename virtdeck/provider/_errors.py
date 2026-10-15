"""Typed exception hierarchy for Proxmox API errors.

All exceptions raised by the provider layer are subclasses of ProxmoxError,
allowing callers to catch by category without inspecting message text.
"""

from __future__ import annotations

import re

import requests.exceptions


class ProxmoxError(Exception):
    """Base for all Proxmox API errors."""

    code: str = "unknown"
    # HTTP status when the error came from an API response (None for
    # transport-level errors).  Set by from_exception / ProxmoxApiError.
    status_code: int | None = None


class ProxmoxAuthError(ProxmoxError):
    """Authentication or authorization failure (401/403)."""

    code = "auth"


class ProxmoxNetworkError(ProxmoxError):
    """Network-level failure (connection refused, DNS, SSL handshake)."""

    code = "network"


class ProxmoxTimeoutError(ProxmoxError):
    """Request timed out."""

    code = "timeout"


class ProxmoxNotFoundError(ProxmoxError):
    """Resource not found (404)."""

    code = "not_found"


class ProxmoxPermissionError(ProxmoxError):
    """Insufficient permissions (403 with permission message)."""

    code = "permission"


class ProxmoxApiError(ProxmoxError):
    """Generic API error with HTTP status code."""

    code = "api"

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# Numeric statuses are matched ONLY with an HTTP anchor ("HTTP 401",
# "401 Client Error: ..." from raise_for_status).  A bare \b401\b also
# matches VMIDs inside request URLs quoted by requests errors
# (e.g. ".../qemu/401/status/current" from a DNS failure), which used to
# misclassify network failures as auth/not-found (audit D4).
_RE_401 = re.compile(r"\bHTTP\s*401\b|\b401\s+Client\s+Error\b")
_RE_403 = re.compile(r"\bHTTP\s*403\b|\b403\s+Client\s+Error\b")
_RE_404 = re.compile(r"\bHTTP\s*404\b|\b404\s+Client\s+Error\b")
_RE_PERMISSION = re.compile(r"permission\s+check\s+failed", re.IGNORECASE)
_RE_TIMEOUT = re.compile(r"tim\s?e?o?u?t", re.IGNORECASE)
_RE_CONN = re.compile(
    r"connection|refused|unreachable|name resolution|dns|"
    r"ssl|certificate|handshake|eof.*protocol",
    re.IGNORECASE,
)

# Pseudo-statuses 595-599 — AnyEvent::HTTP convention. proxmoxer delivers
# them as regular responses, but they are actually pveproxy reports: the
# PVE web service itself failed to handle the request (upstream/TLS/response
# body). This is a SERVER problem, not the client's or its proxy's.
ANYEVENT_HINTS = {
    595: "pveproxy could not reach the PVE API backend (pvedaemon)",
    596: "pveproxy TLS failure — check node certificates (pveproxy)",
    597: "pveproxy failed while receiving the response body",
    598: "request aborted inside pveproxy",
    599: "pveproxy could not process the request",
}
_RE_ANYEVENT = re.compile(r"^(59[5-9])\b")


def describe_anyevent(code: int) -> str:
    """Human-readable one-liner for a pveproxy pseudo-status (595-599)."""
    return ANYEVENT_HINTS.get(code, f"pveproxy error {code}")


def _classify_anyevent(exc: Exception, msg: str) -> ProxmoxNetworkError | None:
    code = getattr(exc, "status_code", None)
    if not isinstance(code, int) or code not in ANYEVENT_HINTS:
        m = _RE_ANYEVENT.search(msg)
        if not m:
            return None
        code = int(m.group(1))
    hint = describe_anyevent(code)
    return ProxmoxNetworkError(f"HTTP {code} — {hint} | {msg}")


def _with_status(err: ProxmoxError, status: int | None) -> ProxmoxError:
    """Attach the HTTP status to a classified error (probe-friendly)."""
    if status is not None:
        err.status_code = status
    return err


def _classify_http_status(msg: str, status: int) -> ProxmoxError:
    """Classify a real HTTP response status (never text heuristics)."""
    if status == 401:
        return _with_status(ProxmoxAuthError(msg), status)
    if status == 403:
        cls = (ProxmoxPermissionError if _RE_PERMISSION.search(msg)
               else ProxmoxAuthError)
        return _with_status(cls(msg), status)
    if status == 404:
        return _with_status(ProxmoxNotFoundError(msg), status)
    if status == 504:
        return _with_status(ProxmoxTimeoutError(msg), status)
    return _with_status(ProxmoxApiError(msg), status)


def from_exception(exc: Exception) -> ProxmoxError:
    """Classify a raw exception from requests/proxmoxer into a ProxmoxError subclass.

    Classification order (audit D4 — type before text):
    1. already a ProxmoxError — pass through;
    2. AnyEvent pseudo-status (595-599) via status attr or message prefix;
    3. exact ``status_code`` attribute (proxmoxer ResourceException);
    4. requests exception TYPES: ``HTTPError`` via its real response
       status, transport errors (``Timeout``, ``ConnectionError``) by
       class — a DNS/connection failure whose message quotes a URL with
       a VMID like 401/403/404 must not become an auth/not-found error;
    5. message-text fallback for non-requests exceptions, with numeric
       regexes anchored to HTTP forms only.
    """
    if isinstance(exc, ProxmoxError):
        return exc
    msg = str(exc)
    exc_name = type(exc).__name__

    anyevent = _classify_anyevent(exc, msg)
    if anyevent is not None:
        return anyevent

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return _classify_http_status(msg, status)

    # requests exceptions: classify by TYPE before any text heuristics.
    if isinstance(exc, requests.exceptions.HTTPError):
        resp_status = getattr(getattr(exc, "response", None), "status_code",
                              None)
        if isinstance(resp_status, int):
            # real HTTP response — same contract as the status branch
            return _classify_http_status(msg, resp_status)
        # HTTPError without a usable response: fall through to the
        # anchored-text fallback (e.g. "404 Client Error: ...").
    if isinstance(exc, requests.exceptions.Timeout):
        return ProxmoxTimeoutError(msg)
    if isinstance(exc, (requests.exceptions.ConnectionError,
                        requests.exceptions.ChunkedEncodingError)):
        return ProxmoxNetworkError(msg)

    if exc_name == "TimeoutError" or "Timeout" in exc_name or _RE_TIMEOUT.search(msg):
        return ProxmoxTimeoutError(msg)
    if _RE_PERMISSION.search(msg):
        return ProxmoxPermissionError(msg)
    if _RE_401.search(msg):
        return ProxmoxAuthError(msg)
    if _RE_404.search(msg):
        return ProxmoxNotFoundError(msg)
    if _RE_403.search(msg):
        return ProxmoxAuthError(msg)
    if _RE_CONN.search(msg):
        return ProxmoxNetworkError(msg)
    return ProxmoxApiError(msg)

