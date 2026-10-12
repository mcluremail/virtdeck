"""TaskAPI — task polling PVE endpoints.

Covers: /nodes/{node}/tasks, /nodes/{node}/tasks/{upid}/status,
and task polling helper.
"""

from __future__ import annotations

import time

from ._errors import ProxmoxNetworkError, ProxmoxTimeoutError
from ._session import ProxmoxSession, _q


class TaskAPI:
    """Task PVE API methods."""

    def __init__(self, session: ProxmoxSession) -> None:
        self._s = session

    def list(self, node: str, limit: int = 100, **params) -> list[dict]:
        """GET /nodes/{node}/tasks."""
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).tasks.get, limit=limit, **params
        )

    def list_cluster(self, limit: int = 100, **params) -> list[dict]:
        """GET /cluster/tasks — recent cluster tasks (Fleet Health)."""
        return self._s.call(self._s.proxmox.cluster.tasks.get,
                            limit=limit, **params)

    def list_for_vm(self, node: str, vmid: int, limit: int = 50) -> list[dict]:
        """GET /nodes/{node}/tasks?vmid={vmid}."""
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).tasks.get, vmid=vmid, limit=limit
        )

    def get_status(self, node: str, upid: str) -> dict:
        """GET /nodes/{node}/tasks/{upid}/status."""
        info = self._s.call(self._s.proxmox.nodes(_q(node)).tasks(_q(upid)).status.get)
        data = info.get("data", info) if isinstance(info, dict) else info
        if not isinstance(data, dict):
            return {}
        return data

    def poll(self, node: str, upid: str, timeout: float = 60,
              interval: float = 1.0,
              max_poll_failures: int = 3) -> tuple[str, str]:
        """Poll task until finished or timeout.

        Returns (status, detail):
          ('stopped', exitstatus)  — the task finished; 'OK' means success,
                                     any other value is the task's own
                                     error text (the task FAILED);
          ('timeout', '')          — the deadline passed while the task was
                                     still running in PVE (the client gave
                                     up, the task did not);
          ('poll_failed', errmsg)  — the task's state could not be read
                                     (transport failures exhausted the
                                     tolerance budget): the outcome is
                                     UNKNOWN, the task may still be
                                     running or have finished meanwhile.

        Tolerance: up to ``max_poll_failures`` CONSECUTIVE transient
        read failures (network/timeout) are waited out within the same
        deadline — a single blip must not fail a long operation.  The
        deadline never extends.  A successful read resets the counter.
        Non-transport errors (auth, permissions, bad request) and
        exhausted budgets return 'poll_failed' immediately.  The detail
        text is the raw exception message — callers must sanitize it
        before showing it to the user.
        """
        deadline = time.monotonic() + timeout
        failures = 0
        while time.monotonic() < deadline:
            try:
                data = self.get_status(node, upid)
                status = data.get("status", "")
                if status == "stopped":
                    return status, data.get("exitstatus", "")
                if not status:
                    # empty/odd payload — unreadable state, same budget
                    failures += 1
                    if failures > max_poll_failures:
                        return "poll_failed", "empty task status response"
                else:
                    failures = 0
            except (ProxmoxNetworkError, ProxmoxTimeoutError) as exc:
                failures += 1
                if failures > max_poll_failures:
                    return "poll_failed", str(exc)
            except Exception as exc:
                # auth/permission/bad-request: retrying cannot help —
                # the task's outcome is simply unreadable
                return "poll_failed", str(exc)
            time.sleep(interval)
        return "timeout", ""
