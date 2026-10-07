"""TaskAPI — task polling PVE endpoints.

Covers: /nodes/{node}/tasks, /nodes/{node}/tasks/{upid}/status,
and task polling helper.
"""

from __future__ import annotations

import time

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
        """GET /cluster/tasks — недавние задачи кластера (Fleet Health)."""
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
              interval: float = 1.0) -> tuple[str, str]:
        """Poll task until finished or timeout.

        Returns (status, exitstatus) tuple: ('stopped', 'OK') on success.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data = self.get_status(node, upid)
                status = data.get("status", "")
                if status == "stopped":
                    return status, data.get("exitstatus", "")
                time.sleep(interval)
            except Exception as exc:
                return "error", str(exc)
        return "timeout", ""
