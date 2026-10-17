# Audit frames renderer (GAP-1 / R15)

Reproduces the committed key frames in `docs/assets/ux_audit/` from a
clean clone — no network, no live PVE/PBS, offscreen rendering:

```
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/audit_render/render_frames.py
```

The frames are committed next to the report so the evidence survives
/tmp cleanups; re-running the command regenerates them byte-different
(timestamps in status bars) but visually identical.

## Frame → evidence map

| Frame | Evidence |
|---|---|
| `main_light` | honest status bar, hosts tree, task list (stage 5) |
| `main_graphite` | theme persistence via the real switcher path (R5, stage 4) |
| `park200` | GAP-7 / DELIGHT-8: 200-VM park; duplicate names carry VMIDs, unique names stay clean |
| `palette` | GAP-10: disabled actions stay visible in grey with the reason |
| `delete_vm` | DELIGHT-5: purge from HA/backup jobs is an explicit opt-in |
| `backup_job` | Д8: dialog sections (Selection / Backup / Schedule / Retention) |
| `pbs_healthy` | GAP-8 / R12: healthy datastore view with snapshots (through the real provider/workers, wire = `tests/harness/fake_pbs.py`) |
| `fleet_health` | fleet report sections with color-coded issues |

## What is real here

- all widgets, workers, providers and async paths are production code;
- the transport seam substitutes `tests/harness` fakes (FakePveApi /
  FakePbsApi), the same ones the CI gate uses;
- a real PBS behavioral run (owner's environment) is still pending and
  tracked in the audit doc as the GAP-8 remainder.
