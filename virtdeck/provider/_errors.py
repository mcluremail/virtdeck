"""Typed exception hierarchy for Proxmox API errors.

All exceptions raised by the provider layer are subclasses of ProxmoxError,
allowing callers to catch by category without inspecting message text.
"""

from __future__ import annotations

import re


class ProxmoxError(Exception):
    """Base for all Proxmox API errors."""

    code: str = "unknown"


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


_RE_401 = re.compile(r"\b401\b")
_RE_403 = re.compile(r"\b403\b")
_RE_404 = re.compile(r"\b404\b")
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


def from_exception(exc: Exception) -> ProxmoxError:
    """Classify a raw exception from requests/proxmoxer into a ProxmoxError subclass."""
    if isinstance(exc, ProxmoxError):
        return exc
    msg = str(exc)
    exc_name = type(exc).__name__

    anyevent = _classify_anyevent(exc, msg)
    if anyevent is not None:
        return anyevent
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

