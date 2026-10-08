"""M4.0: test harness — fake PVE/PBS APIs and record/replay.

Fleet Health fans out across all clusters at once — live clusters are
not tested. The harness swaps the transport at the `requests` level:
the real provider (proxmoxer, PBS client) runs against an in-memory
scenario or a replay fixture recorded from a live cluster. No network
sockets in tests — the adapter intercepts requests before TLS.

Components:
- `fake_pve.FakePveApi` — in-memory cluster state (nodes/guests/jobs/
  storages/rrddata/snapshots/tasks) + fluent scenarios;
- `fake_pbs.FakePbsApi` — minimal PBS (ticket + datastores/snapshots);
- `adapter.FakeApiAdapter` — requests adapter over the fake's handler;
- `adapter.ReplayAdapter` / `save_fixture` / `load_fixture` — record/
  replay over JSON fixtures (format: see FIXTURE_FORMAT).

Mounting seams:
- PVE: `install_fake_pve(monkeypatch, api)` — patches `ProxmoxAPI` in
  `provider._session` (a real proxmoxer object, a fake adapter on its
  internal `requests.Session` from `_store["session"]`; token-auth does
  no network round-trip — the adapter sees even the "authentication");
- PBS: `PbsClient(cfg, http=session)` — an optional session with an
  adapter.
"""

from .adapter import load_fixture, save_fixture
from .fake_pbs import FakePbsApi
from .fake_pve import FakePveApi
from .install import fake_pve_cfg, install_fake_pve, install_replay_pve, pbs_session

__all__ = [
    "FakePbsApi",
    "FakePveApi",
    "fake_pve_cfg",
    "install_fake_pve",
    "install_replay_pve",
    "load_fixture",
    "pbs_session",
    "save_fixture",
]
