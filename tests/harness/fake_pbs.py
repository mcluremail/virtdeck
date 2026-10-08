"""M4.0: FakePbsApi — in-memory Proxmox Backup Server for tests.

Serves ticket login (POST /access/ticket, checks username/password
against the values given at creation) and read-only datastore
endpoints: datastore list, status, groups and snapshots (the foundation
of the Fleet Health "last successful backup" — a vmaidx equivalent).
Paths — without the `/api2/json` prefix.
"""

from __future__ import annotations

from datetime import datetime, timezone


class FakePbsApi:
    """Scenario of a single independent PBS."""

    def __init__(self, user: str = "root@pam", password: str = "secret"):
        self.user = user
        self.password = password
        self.calls: list[tuple[str, str, dict]] = []
        # store → {"total": int, "used": int, "snapshots": [entry]}
        self.datastores: dict[str, dict] = {}

    # ── Scenario ────────────────────────────────────────────────────

    def add_datastore(self, store: str, total: int = 10 << 30,
                      used: int = 4 << 30) -> FakePbsApi:
        self.datastores[store] = {"total": total, "used": used,
                                  "snapshots": []}
        return self

    def add_snapshot(self, store: str, backup_id: int | str,
                     backup_type: str = "vm", backup_time: int = 1727740800,
                     ns: str = "", size: int = 3 << 30,
                     verify_state: str = "ok",
                     comment: str = "") -> FakePbsApi:
        iso = datetime.fromtimestamp(backup_time, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        entry = {
            "backup-type": backup_type,
            "backup-id": str(backup_id),
            "backup-time": backup_time,
            "snapshot": f"{backup_type}/{backup_id}/{iso}",
            "size": size,
            "verify-state": verify_state,
            "files": ["index.json.blob", "drive-scsi0.img.fidx"],
            "comment": comment,
        }
        if vmid := _as_vmid(backup_id):
            entry["vmid"] = vmid
        self.datastores[store]["snapshots"].append(
            {"ns": ns, "entry": entry})
        return self

    # ── Request handling ────────────────────────────────────────────

    def handle(self, method: str, path: str,
               params: dict | None = None) -> tuple[int, object]:
        """(method, path, params) → (status, data). path without
        /api2/json."""
        params = dict(params or {})
        self.calls.append((method, path, params))

        parts = [p for p in path.strip("/").split("/") if p]

        if method == "POST" and parts == ["access", "ticket"]:
            if params.get("username") != self.user \
                    or params.get("password") != self.password:
                return 401, {"errors": "authentication failure"}
            return 200, {"ticket": f"PBS:{self.user}!harness",
                         "CSRFPreventionToken": "csrf-fake"}

        if method == "GET" and parts[:2] == ["admin", "datastore"]:
            if len(parts) == 2:
                return 200, [{"store": s, "type": "pbs",
                              "comment": f"fake ds {s}"}
                             for s in self.datastores]
            store = parts[2]
            ds = self.datastores.get(store)
            if ds is None:
                return 404, {"errors": f"no such datastore: {store}"}
            rest = parts[3:]
            if rest == ["status"]:
                avail = max(0, ds["total"] - ds["used"])
                return 200, {"store": store, "total": ds["total"],
                             "used": ds["used"], "avail": avail}
            if rest == ["groups"]:
                seen: dict[tuple[str, str], dict] = {}
                for row in ds["snapshots"]:
                    e = row["entry"]
                    key = (e["backup-type"], e["backup-id"])
                    if key not in seen \
                            or e["backup-time"] > seen[key]["last-backup"]:
                        seen[key] = {"backup-type": e["backup-type"],
                                     "backup-id": e["backup-id"],
                                     "last-backup": e["backup-time"]}
                return 200, list(seen.values())
            if rest == ["snapshots"]:
                want_ns = params.get("ns", "")
                return 200, [row["entry"] for row in ds["snapshots"]
                             if row["ns"] == want_ns]

        return 404, {"errors": f"no handler: {method} {path}"}


def _as_vmid(backup_id: int | str) -> int | None:
    try:
        return int(backup_id)
    except (TypeError, ValueError):
        return None
