"""Shared helpers for backend workers: SSL handling, error sanitizing, task await."""

import os
import re

import urllib3

PVE_PORT = 8006
_WARN_SUPPRESSED = False
def _suppress_ssl_warnings():
    global _WARN_SUPPRESSED
    if not _WARN_SUPPRESSED:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        _WARN_SUPPRESSED = True
def _verify_ssl(cfg):
    """Return verify_ssl value for requests/proxmoxer.
    trust_ssl=False (default) → strict verification, verify_ssl=True.
    trust_ssl=True → accept any cert, verify_ssl=False."""
    trust = cfg.get("trust_ssl", False)
    if trust:
        _suppress_ssl_warnings()
    return not bool(trust)
def _cleanup_vv(vv_path):
    if vv_path and os.path.exists(vv_path):
        try:
            os.unlink(vv_path)
        except OSError:
            pass
def _q(value):
    """URL-encode a path segment for proxmoxer."""
    from urllib.parse import quote
    return quote(str(value), safe="")
_RE_URL = re.compile(r'https?://[^\s\'"]+')
_RE_IPV4_PORT = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+\b')
# quoted host as it appears in requests/urllib3 exceptions:
# "HTTPSConnectionPool(host='pve1.lan', port=8006)"
_RE_QUOTED_HOST = re.compile(r"\bhost='[^']+'")
# dotted hostname (FQDN-like) with a port: "connection to pve1.lan:8006 failed".
# The leading label must contain a letter and the name must be dotted, so
# timestamps ("00:00:00Z") and volid-ish text ("local:iso") are untouched.
_RE_FQDN_PORT = re.compile(r'\b(?![\d.]+\b:)[a-zA-Z][\w-]*(?:\.[\w-]+)+:\d{2,5}\b')


def _sanitize_error(exc):
    """Sanitize exception message for UI display — strip URLs, hostnames, credential fragments.

    Surgical by design: only transport-identifying fragments are replaced
    ([url]/[host]); the diagnostic substance (error classes, PVE messages,
    paths, timestamps) is preserved for the user.
    """
    msg = str(exc)
    # Strip URLs
    msg = _RE_URL.sub('[url]', msg)
    # Strip host:port patterns
    msg = _RE_IPV4_PORT.sub('[host]', msg)
    # Strip quoted hosts from requests exceptions: host='pve1.lan'
    msg = _RE_QUOTED_HOST.sub("[host]", msg)
    # Strip dotted hostnames with ports: pve1.lan:8006
    msg = _RE_FQDN_PORT.sub('[host]', msg)
    # Limit length
    if len(msg) > 150:
        msg = msg[:150] + "..."
    return msg

# ----------------------------------------------------------------------
# Create API token for VirtDeck
# ----------------------------------------------------------------------
def _await_task(provider, node_name, result, timeout=120):
    """Wait for a PVE async task started by an API call.

    PVE returns a UPID for async operations and a data payload for
    synchronous ones. Returns (True, "") on success — task finished with
    exitstatus OK, or the call completed synchronously without a UPID —
    and (False, errmsg) on task failure, unreadable status or timeout.

    Distinguishes (audit stage 3): a FAILED task (exitstatus text from
    PVE) from an UNREADABLE one (poll_failed — the outcome is unknown,
    the task may still be running) from a client-side deadline (timeout).
    All error texts are sanitized before they reach the UI.
    """
    upid = result.get("data", result) if isinstance(result, dict) else result
    if not (isinstance(upid, str) and upid.startswith("UPID:")):
        return True, ""
    status, detail = provider.tasks.poll(
        node_name, upid, timeout=timeout, interval=1.0
    )
    if status == "stopped":
        if detail == "OK":
            return True, ""
        return False, _sanitize_error(detail) if detail else "task failed"
    if status == "poll_failed":
        return False, _sanitize_error(
            f"task outcome unknown — status poll failed: {detail}")
    if status == "timeout":
        return False, f"still running after {int(timeout)} s"
    # defensive: unknown poll status — treat like unreadable state
    return False, _sanitize_error(detail) if detail else f"unknown task status: {status}"

# ----------------------------------------------------------------------
# VmSnapshotCreateWorker
# ----------------------------------------------------------------------
def _safe_emit(signal, *args):
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


def _is_vmid_conflict(err: str) -> bool:
    """PVE rejected the target VMID as taken (nextid race: another
    worker claimed the same fresh id between next_vmid() and POST)."""
    lowered = str(err).lower()
    return "already exists" in lowered or "already in use" in lowered


def _await_vmid_retry(provider, node_name, fork, next_vmid, timeout):
    """_await_task with a one-shot retry on a taken-VMID conflict.

    ``fork(newid)`` performs the POST; on the first conflict the id is
    re-fetched via ``next_vmid()`` and the call is retried once.
    """
    newid = None
    for attempt in range(2):
        try:
            ok, err = _await_task(provider, node_name, fork(newid),
                                  timeout=timeout)
        except Exception as exc:
            ok, err = False, _sanitize_error(exc)
        if ok or not _is_vmid_conflict(err) or attempt == 1:
            return ok, err
        newid = next_vmid()
    return ok, err

# ----------------------------------------------------------------------
# StorageUploadWorker — POST /nodes/{node}/storage/{storage}/upload (multipart)
# ----------------------------------------------------------------------
