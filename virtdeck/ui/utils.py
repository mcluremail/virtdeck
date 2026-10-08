"""Common UI helpers: status text, formatting."""

import re

from ..domain._format import format_uptime  # noqa: F401  (re-export)
from .i18n import tr

_STATUS_KEYS = frozenset((
    "running", "stopped", "paused", "error",
    "offline", "online", "unknown", "mounted",
))


def status_text(s):
    """Return human-readable status for display.
    tr() translates the status label to the current language.
    """
    return tr(s if s in _STATUS_KEYS else (s or "unknown"))


def build_cfg_index(nodes_cfg):
    """Build {name: cfg} dict from nodes_cfg list for O(1) lookup.
    On duplicate names (should not happen) last one wins."""
    return {c.get("name", ""): c for c in nodes_cfg}


def parse_pve_error(err):
    """Translate a raw PVE API error string into a user-facing message.
    Returns the original string if no known pattern matches.
    """
    if not err:
        return ""
    err_lower = err.lower()
    # Pseudo-statuses 595-599 (AnyEvent::HTTP): these are pveproxy RESPONSES —
    # a server-side problem, not the client or its proxy.
    m = re.match(r"^(59[5-9])\b", err.strip())
    if m:
        hints = {
            "595": tr("PVE web service cannot reach the PVE API backend (pvedaemon)"),
            "596": tr("PVE web service TLS error — check node certificates (pveproxy)"),
            "597": tr("PVE web service error while receiving response body"),
            "598": tr("Request aborted inside PVE web service"),
            "599": tr("PVE web service could not process the request"),
        }
        return f"{hints[m.group(1)]} (HTTP {m.group(1)})"
    if "permission check failed" in err_lower:
        m = re.search(r"Permission check failed\s*\(([^)]+)\)", err)
        if m:
            return tr("PVE permission denied: {path}").format(path=m.group(1))
        return tr("PVE permission denied")
    if "403" in err_lower:
        return tr("PVE permission denied (403)")
    if "unauthorized" in err_lower or "401" in err_lower:
        return tr("API token authorization error (401)")
    if "resolve" in err_lower or "dns" in err_lower or "name or service not known" in err_lower:
        return tr("Cannot resolve DNS name")
    if "connection refused" in err_lower or "connection reset" in err_lower:
        return tr("PVE API unavailable (connection refused)")
    if "timeout" in err_lower:
        return tr("Host not responding (timeout)")
    if "ssl" in err_lower or "certificate" in err_lower or "cert" in err_lower:
        if "self-signed" in err_lower or "self signed" in err_lower:
            return tr("SSL certificate self-signed — enable Trust SSL in context menu")
        if "expired" in err_lower or "not valid" in err_lower:
            return tr("SSL certificate invalid or expired — enable Trust SSL in context menu")
        return tr("SSL certificate error — enable Trust SSL in context menu")
    return err
