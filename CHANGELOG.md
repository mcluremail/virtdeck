# Changelog

## v3.0.5 — backup job safety and Fleet Health honesty (external audit stages 6.1.1 and 6.2.1)

**Bug fixes**
- Backup job editing no longer destroys the guest selection: the editor now models the three PVE selection kinds (`all` / `pool` / `vmid` list) as they exist in the API, and an unchanged save sends nothing at all — a pool or all-guests job can no longer silently degrade into an explicit VMID list (the old editor carried `vmid` in every PUT, and PVE deletes `pool`/`all`/`exclude` the moment `vmid` arrives). The word "all" typed into the VMID field is rejected with an explicit message instead of producing a guaranteed 400, foreign fields of the chosen mode are disabled, clearing `exclude`/`node` goes through the PUT `delete` parameter, and a job without any selection stays intact on a no-change save
- The retention policy is preserved verbatim: `prune-backups` is kept in full in both the property-string and the object form PVE 8 returns, every `keep-*` element survives an edit, an unparsable policy blocks the save with an explicit error instead of being replaced by an invented `keep-last=3`, and the server defaults the API omits (`remove`, `compress`) are displayed but never written back unless the user actually changed them — editing a job no longer silently switches pruning off
- Fleet Health stops asserting what it could not verify: a failed task-history collection now shows each unevidenced guest as a yellow "Backup state unverified" row naming the failed source instead of the false red "Never backed up" (a confirmed empty history still produces the honest red), a plain caveat explains that scheduled job runs cannot be attributed to guests on PVE below 7.2 (their UPIDs carry no job id), and one corrupt task row (no parsable timestamp) can no longer crash the whole cluster report
- Refresh safety for optional sources (audit 6.1.1): a timed-out or failed pools/HA fetch is now reported as "not fetched" instead of looking like a confirmed absence — the previous data of a host whose worker fails or is rejected is kept through refresh cycles, HA errors surface as a partial payload, and hosts that left the configuration are dropped explicitly instead of a wholesale clear
- The backup jobs table shows the selection kind (All guests / pool / VMID list / node) instead of a VMIDs column that was empty for pool and all-guests jobs

**Internal**
- The `fake_pve` test stand implements backup-job CRUD with the real PVE `update_job` semantics (mutually exclusive selection keys, the `delete` parameter, pve-vmid-list validation, "no options specified" on an empty PUT), so round-trip tests assert the end state of a job after server-side processing; 58 new tests (1358 → 1416) covering the dialog contracts, the server semantics and the Fleet Health partial-data rules; i18n version 39 (21 new keys in all 5 locales)
- Release engineering: `python3-pyside6` debs declare the full Qt runtime closure in `Depends` (private Qt libraries were pulled in only transitively before)

## v3.0.4 — connection identity and safe cache restore (external audit stage 5.1)

**Bug fixes**
- Connection identity: every connection now carries a stable `conn_id`, independent of its display name. Connection names must be unique up to normalization (NFC + outer-space strip + case-insensitive comparison). Legacy databases that already contain colliding names (`Web`/`web`, trailing spaces, different Unicode compositions of the same text) load untouched — the entries are not merged, renamed or removed; they stay visible with a distinct warning and are excluded from hard/soft refresh, cache restore, token operations, the PBS panel and fleet collection until the user resolves the conflict in the new repair dialog (pick the connection to keep — the loser is removed through the regular delete flow with its own confirmation and token revoke). Creating new conflicts is rejected at the add dialog, at the add flow and centrally at config save
- Startup cache restore is identity-keyed: cached rows are matched by the producing connection's `conn_id`, never by the display name. A connection deleted and re-created under the same name restores nothing, rows written by previous versions (no conn_id) and rows of unknown connections are never attached — the data is re-fetched from the server instead of showing resources of a foreign infrastructure. Resource-cache writes are skipped entirely while a conn_id migration has not been persisted (e.g. a read-only config directory), and rows without an identity are never stored
- Worker results are identity-gated: a refresh result of an unknown, deleted or re-created connection (or of an ambiguous one) is dropped before it can touch the repositories, the update epochs, the UI or the cache; the owner's name is taken from the current configuration, not from the stale result. The existing generation/epoch checks are preserved — a late answer of a deleted connection cannot resurrect its data
- Config import: entries are matched by `(type, host, user)` instead of `(host, user)` — a PBS entry at the same address as a PVE entry no longer silently replaces it. A matched connection keeps its local name and identity; only credential/option fields are imported, and the token is written to the keyring only when it actually changed. Identifiers from the bundle are never accepted as local identity: new entries get fresh local ids, and a full-restore import (merge=False) assigns fresh ids to every entry — a restored backup can never attach the local cache of another installation. Conflicting names, invalid entries and ambiguous matches are skipped with explicit reasons collected into the import summary instead of aborting the whole import or silently overwriting; re-importing the same bundle is idempotent and no longer leaves orphaned keyring entries
- Token refresh (reconnect) no longer rebuilds the connection from the dialog's short field list — `skip`, `group`, port/proxy/cluster settings and the conn_id survive a token rotation (previously `skip` and `group` were silently dropped)

**Internal**
- The conn_id migration runs at config load and persists in a single SQLite transaction touching only the changed rows; on failure the app keeps working with in-memory ids while resource-cache writes stay blocked until a successful config save anchors them. Tokens and other secrets are never touched by the migration
- Name normalization, ambiguity detection and uniqueness checks are centralized in the config layer (`normalize_name`, `name_key`, `mark_ambiguous`, `save_config`); the shrink-only guarantee for legacy conflict groups is enforced inside `save_config` itself, against the stored database — no caller can widen the tolerance (a group may stay verbatim, shrink or disappear, never grow, and no new group may appear)
- 50 new regression tests (config-level and UI-level) covering the audit 5.1/5.1.1 matrices and the 5.1.3 review: id migration and the pending state (including failed saves keeping the flag), ambiguity handling and the shrink-only save rule, import rules, the three data-ingestion gates, the legacy name-fallback boundaries and cache-write blocking
- Release engineering: the CI matrix covers Python 3.10–3.14 and PySide6 is capped to `>=6.5,<6.12` per the project policy (the floating CI resolution pulled the buggy 6.12.0 and was red); a new `scripts/check_release.py` runs as a CI job and verifies install-command versions, CI-matrix-vs-declared-support, i18n key parity and fingerprint formatting; the README install command, the PEP 668 note (venv-first), the fingerprint spacing (+ machine verification snippet) and the Language switching section were corrected to match the actual implementation
- python3-pyside6 debs (revision -3) declare `Provides: libpyside6-py3, libshiboken6-py3` and `Conflicts:` against the distro split-PySide6 packages: Ubuntu 26.04's python3-pyqtgraph hard-depends on `libpyside6-py3`, which previously made `apt install virtdeck` unsolvable there (file clash with our wheel). The virtual provides satisfy pyqtgraph, the conflicts remove the distro pieces gracefully instead of a dpkg error

## v3.0.3 — data integrity and concurrent refresh (external audit stages 4 and 4.2)

**Bug fixes**
- Late answers: a refresh answer is judged by the attempt it was made in, not by its arrival time. `RefreshCoordinator` now stamps every attempt with a monotonic epoch (incremented when an attempt starts or is discarded) and records the epoch of the last snapshot APPLIED per host; an answer older than that is dropped silently — it does not overwrite the fresher snapshot, re-trigger notifications, re-run the first selection or rewrite the cache. Previously a hard cycle closed by the watchdog could still accept a late answer with stale content and wipe fresher data applied by a later soft cycle. A lone late answer for a host with no fresher data is still accepted, so the only available result is never lost
- Pools: pool identity is now `(host_name, poolid)` — a poolid is unique within a PVE cluster/standalone instance but not across independent infrastructures, so identical ids of two hosts silently replaced each other before. A hard cycle no longer clears the shared pool repository: pools of hosts whose workers fail or are rejected keep their last known-good data, only hosts that left the configuration are dropped; a confirmed empty list clears the host's pools, a failed pool fetch signals "not fetched" (`pools: null`) instead of pretending "no pools". The create-VM dialog receives the pools of the host the VM is created on, and global search distinguishes same-id pools by host
- Cluster config: two active representatives of the SAME configured cluster duplicated every node and VM in the repositories, counters and the tree. The first representative per cluster name is kept, the duplicates are dropped with an explicit notification instead of silently doubling resources. Clusters with different names but coinciding node names are treated as independent infrastructures and never merged — identity is the configured cluster name only, node names are not compared across clusters
- Refresh snapshots: the absence of an answer is no longer the absence of resources. FetchWorker classified failures of mandatory API requests (cluster resources; node status; guest/storage listings) as `status="ok"` with empty lists, so the UI erased a host's real resources from the tree and the persistent cache whenever the host was unreachable. Results are now `ok` (every mandatory source completed successfully — an empty list is a confirmed absence, not a failure), `partial` (the host identity is confirmed, some mandatory resource lists are not — the consumer keeps the previous snapshot) or `error` (nothing confirmed). A thread that outlives its join deadline counts as data that never arrived; optional sources (pools, HA, versions, storage details, ISO images) never affect the status
- Soft refresh merges per-host snapshots instead of swapping the whole world: a host that answered replaces its own snapshot entirely (resources really removed on the server disappear), a host whose worker failed keeps its last known-good data with its nodes flagged ERROR, hosts that did not take part stay untouched. Previously one dead host wiped its VMs/storages, and a fully failed cycle wiped every host and rewrote the persistent cache with that emptiness
- Hard refresh no longer clears the repositories at cycle start: each worker replaces only its own host's confirmed snapshot, so a host whose worker was rejected by a full pool (or failed) keeps its data. When nothing can be started the UI leaves the loading state immediately instead of waiting forever, and a watchdog (180 s ceiling) force-finalizes a hard cycle whose workers stopped reporting — late reports still apply per-host, stale generations never overwrite newer state
- Repository indexes: moving a VM to another node no longer leaves a ghost in the old node's bucket — `filter_by_host()`/`count_by_host()` no longer report the pre-migration placement
- Startup cache: hosts removed from the configuration or excluded by skip are no longer resurrected from the cache; cluster representatives are matched by config name, so PVE node names inside a cluster snapshot are never filtered out. The first hard cycle no longer clears the freshly loaded cache — cached hosts keep serving until their own fresh confirmed answer replaces them
- The error branch of a failed refresh worker crashed on a broken internal import (`virtdeck.utils` instead of `virtdeck.ui.utils`), skipping the notification, the tree update and the cache save for that cycle
- ISO/HA lists of a successful response replace the previous data even when the new list is empty (a confirmed absence), while a failed optional fetch no longer pretends "no ISOs" — the previous list survives

**Internal**
- Package platforms refreshed to current distro releases: rpm builds target Fedora 43 / 44 (one build per Fedora release — the auto-generated `python3.Xdist(proxmoxer)` dependencies must resolve against that release's Python); the apt side adds Ubuntu 26.04 "resolute" (Python 3.14) alongside Debian 12/13 and Ubuntu 24.04. The EOL fedora/41 catalog stays frozen on the repository server (append-only — existing dnf users keep working) but is no longer built for or documented
- The python3-pyside6 deb for resolute is built from the official PySide6 6.11.2 wheel (abi3 cp310+, officially supports Python 3.14); 6.8.3 remains for bookworm/noble/trixie. 6.12.x stays avoided (known refcount bug)
- Release artifacts are now GPG-signed (.asc, same key as the package repository): signatures are produced on repo.mclure.ru — the private key never leaves the server — and uploaded next to the release files; the v3.0.2 artifacts were signed retroactively
- The signing key's fingerprint (117D EABD 3EA4 8810 B219 BA6B 401F 700F B97D E8B8) is published in three independent places — README, website, and the repo.mclure.ru root page — with explicit "verify the fingerprint after download" instructions; the release CI smoke test checks the fingerprint before trusting the repository
- repo.mclure.ru now serves an index page at its root (install commands for all supported distros, the key fingerprint, links) instead of a bare autoindex
- Release procedure: the release body must lead with "Fixed: …" from the CHANGELOG (v3.0.2's boilerplate body was fixed retroactively); a website-update step (version strings + install blocks synced with README, i18n parity checks) and a semi-annual platform/EOL review were added to docs/RELEASE_PROCESS.md
- README: an honest comparison with Proxmox Datacenter Manager added (nothing to deploy server-side — a window on your desktop); the "From source" instructions now actually install the package (`pip install virtdeck-<ver>-py3-none-any.whl …`), not just its dependencies

## v3.0.2 — provider/API layer fixes (external audit stage 3.1)

**Bug fixes**
- Storage: deleting and moving storage content (ISO/backup volumes) is fixed for real PVE — the volume ID (`local:iso/name.iso`) was passed into the proxmoxer resource chain unencoded; proxmoxer splits such strings on "/" (turning them into extra URL segments), so every standard volid broke the API path and PVE answered 404. Both `volid` and `storage` are now percent-encoded; covered by URL-construction tests against the real installed proxmoxer, not mocks
- Backup jobs (scheduled vzdump): the silent "/cluster/jobs → /cluster/backup" fallback on ANY error is gone. The API path is now chosen BEFORE the request (availability probed once per provider session with a harmless GET and cached); errors from the primary path propagate. This removes three verified hazards: a timed-out create silently re-POSTed to the legacy path and could duplicate the job; a 400 validation error was swallowed and the job was silently created on the legacy path; a timed-out delete re-ran and reported a misleading 404 while the job had actually been deleted. A timed-out write is re-raised with an explicit "may still have been applied — refresh the job list" hint
- Task polling: one transient network failure during a long operation no longer reports the operation as failed while the PVE task keeps running. `TaskAPI.poll()` tolerates up to 3 consecutive transport failures within the unchanged deadline (a successful read resets the budget) and returns a distinct `poll_failed` ("outcome unknown") result instead of a fake task failure; auth/validation errors fail fast. A genuinely failed task still carries its real PVE exitstatus
- Upload: failed file uploads raise a classified `ProxmoxApiError` with the HTTP status (401/403/413/5xx; pveproxy 595-599 get their usual hint) instead of a bare Exception the UI could not classify; a 200 with a broken/non-JSON body raises a clean error instead of crashing on parsing; oversized read chunks are capped (no whole-file buffering)
- Error texts: messages reaching the UI via `_await_task` are sanitized now (previously only the outer worker exception was) — bare hostnames (`host='pve1.lan'`, `pve1.lan:8006`) are masked alongside URLs and IP:port, while timestamps, volids and the task's own error text survive intact
- Error classification uses the exact HTTP status from proxmoxer exceptions first (`ResourceException.status_code`), with the message regexes only as a fallback — a 400 whose text merely contains "401"/"404" is no longer misclassified; all classified errors carry `.status_code`

**Internal**
- CI runs the full pytest suite now (3 python versions, offscreen Qt) — it previously never ran, so a stale test (`test_migrate`) sat red on main unnoticed. The UI suite no longer degrades quadratically: pytest-qt's deferred widget deletions were never delivered at event-loop level 0, so windows accumulated across tests and every theme re-application re-polished the whole pile (a full run went from 30+ min to ~1.5 min; a conftest teardown hook drains the deferred-delete queue after every test)

## v3.0.1 — honest VM/CT operations (external audit stage 2)

**New features**
- Fleet Health: the storage runway forecast now communicates data quality — a sparse-history estimate (few rrddata points, no confidence interval) is shown as "~N days left (sparse history — rough estimate)" instead of a bare day count; reliable forecasts keep their 95% confidence-interval range (i18n version 35)
- VM/CT ops: LXC migration is implemented — PVE 7/8/9 support `POST /nodes/{node}/lxc/{vmid}/migrate` (verified against the pve-container sources); running VMs migrate live (`online=1`), running containers via restart migration (`restart=1`, the dialog says the CT will be rebooted on the target node); the migration task is awaited (30 min ceiling) so a failed migration is reported instead of silently forgotten

**Bug fixes**
- VM ops: the LXC migrate stub no longer leaks a worker slot and freezes the status line — the early return before the `try/finally` skipped `finished` forever, so 16 attempts would exhaust the main-window worker pool ("Too many concurrent operations")
- VM ops: start/stop/reboot/shutdown/reset/suspend/resume and disk resize/move await their PVE tasks — a failed action is reported as an error instead of a false "completed" (the old messages fired on task acceptance, an UPID, not the outcome); a task still running after the wait window reads "still running after Ns", not "timeout"
- VM ops: converting a template back to a VM now warns that PVE does not officially support the reverse conversion (the flag is silently cleared, volumes stay base volumes — linked clones may break); the action is refused for container templates
- VM ops: a taken-VMID conflict between workers (nextid race) retries once with a freshly fetched id in create and clone
- VM ops: the delete dialog exposes the purge choice (removal from HA resources and backup jobs — previously hardwired on); bulk actions reuse one provider (login) per host instead of re-authenticating per VM
- Packaging: the project now hosts its own package repository at https://repo.mclure.ru (apt suites: bookworm / noble / trixie; rpm: fedora/41; signed, GPG key published there). The repository provides what the distro archives lack: PySide6 (full, incl. WebEngine — converted from the official wheel, one build per python version) and proxmoxer (rpm; built on the same Fedora release the virtdeck rpm targets so the generated python3.Xdist provides match). As a result `apt install virtdeck` / `dnf install virtdeck` are fully self-contained — no pip steps anywhere; the .deb depends on `python3-pyside6` again (satisfied from our repo), and the CI smoke gate installs from the repository exactly like users do. This also fixed a chain of real packaging bugs caught by the smoke gate on its first runs: the .deb depended on the nonexistent `python3-pyside6` (pip-only upstream), the generated `python3-cryptography (>= 42.0.0)` was unsatisfiable on bookworm (38.0.3) and noble (41.0.7) — the pin is weakened to `>=38.0` (the code uses only Fernet + PBKDF2HMAC) — and the .rpm was built on Fedora 40 with python3.12 dist requirements that cannot resolve on Fedora 41
- Fleet Health: a cluster whose provider cannot even be created no longer shows a "Data from 1970" plate — it says "Data unavailable"
- Fleet Health: the status line no longer claims a bare "No issues found" when some clusters returned incomplete data — the suffix "N with incomplete data" is appended
- Fleet Health: one degenerate storage series (identical timestamps) no longer ZeroDivisionError's the whole cluster report — the forecast is isolated per source like every other collector; a flat series lands in the honest "no trend" branch
- Fleet Health: cluster-wide scheduled vzdump job runs (UPID without a vmid, id slot = job id) now serve as indirect "backed up" evidence for the guests they cover — a guest backed up daily by such a job is no longer reported as "never backed up"; direct per-guest evidence always wins (a failed guest task is not masked by a green job run)
- Fleet Health: node-restricted backup jobs (``node`` field) no longer cover guests on other nodes — the matching engine follows vzdump semantics
- Fleet Health: snapshots without any timestamp ("zombies") no longer render "oldest None days" — the issue reads "N snapshots, unknown age"
- Fleet Health: PBS backup freshness is actually wired into the fleet scan (it was collected nowhere) — the last verified PBS snapshot time participates in the "last successful backup" per guest; each PBS server is isolated (one dead server never breaks the report)
- Fleet Health: when the task history hits the fetch limit (200 rows), the report carries a "Task history truncated" caveat instead of silently risking false "never backed up" verdicts
- Fleet Health: a nearly full storage (≥90% warn / ≥95% danger) speaks up even when the trend says "no growth" — "99% full" no longer hides behind "no trend"
- Fleet Health: per-VM snapshot scan failures are surfaced ("scan incomplete: N guests failed" in the status line + per-cluster failed list) instead of silently looking like "no snapshots"; scan ages are computed against the scan's own wall clock and the guest list is re-fetched before scanning
- Fleet Health: an open-ended confidence interval renders as "~N–∞ days left"; a forecast built on a stale series (last point ≥3 days old) carries an explicit "data N days old" suffix
- Fleet Health: shared storages (NFS/Ceph/PBS) are forecast once per cluster instead of once per node (N identical forecasts and N rrddata requests before)
- Fleet Health: collection runs under a bounded thread pool (8) with a wait ceiling — a hung target yields a partial report instead of a frozen dialog; a crashed scan/collection always restores the dialog state

**Internal**
- External audit of VM/CT operations (stage 2): every `vmops`/`vm.py` worker path proven to emit `finished` exactly once with the provider closed (parameterized worker tests against a fake PVE with write routes + task simulation — `FakePveApi.set_next_task_result` for OK/failed/never-finishing tasks, `POST/PUT/DELETE` endpoint routes, `/cluster/nextid`); PVE API claims verified against the pve-container/qemu-server sources (stable-7, stable-bookworm, master) — LXC migration exists on PVE 7/8/9, a running VM refuses to migrate without `--online`, `template=0` has no special handling in the config PUT path; i18n versions 36–38 (false LXC-unsupported warning replaced with restart-migration semantics); 1189 tests, ruff clean

**Internal**
- Release pipeline: the new `smoke-packages` job installs the built `.deb` (Ubuntu 24.04) and `.rpm` (Fedora 41) in clean containers and import-checks the installed package before the GitHub Release is created — broken packages now block the release; release notes no longer reference the removed pip install channel

## v3.0.0 — Fleet Health, theme engine, command palette (production desktop)

**New features**
- Fleet Health (M4): cross-cluster health dashboard — backup compliance, version drift, storage runway and snapshot sprawl across all independent clusters ("the whole park at a glance"). Harness first (M4.0): `tests/harness/` with fake PVE/PBS APIs (in-memory cluster scenes), record/replay requests adapters with JSON fixtures (match on method+path+params), socket-free mounting into the real provider/proxmoxer path (fakes routed by host via a ProxmoxAPI patch in `provider._session`; `PbsClient` gained an optional `http` session DI seam). Matching engine as a pure domain module (`domain/backup_coverage.py`, M4.1) with pinned vzdump semantics — all > pool > vmid priority, exclude only with all, templates exempt, disabled jobs cover nobody, job intersections allowed, stateless recompute on fresh resources (VMs migrate between pools between runs) — table-driven tests. Report collection (`domain/fleet.py`, `fleet/collector.py`, M4.2) fans out per source with isolation: a failed source becomes an error entry and a "data from HH:MM" plate instead of an empty report; guest backup states come from vzdump task history (last ok/failed/attempt) plus an optional PBS snapshot mapping (verify-failed snapshots never count as successful). Version drift (`fleet/drift.py`) compares each node against the cluster leader (patch/minor/major/unknown — unparsable versions are shown, not hidden); storage runway (`fleet/runway.py`) fits least squares over a windowed rrddata series with gaps dropped, a 95% confidence interval on the slope and quality grades ok/sparse/no-trend/no-capacity/no-data. Snapshot sprawl scanner (`fleet/sprawl.py`) issues one request per VM through a bounded thread pool and aggregates forgotten snapshots (30-day threshold, age-less zombies count as forgotten, `current` excluded). Fleet Health dialog (`ui/fleet_health.py`, worker `backend/fleet.py`, M4.5) renders the "what's red where" report in four sections with severity colors (tokens only), double-click jumps to the object in the tree, clusters are collected in parallel (a thread per cluster), sprawl scan runs on demand from the dialog; launched from the toolbar, tray menu and Ctrl+Shift+F; strings translated in all 5 locales (i18n version 33)
- Performance foundation (M0): static sync-contract test (AST scanner — no sync client calls in UI), runtime contract guard on `PluginRegistry.create_provider` (caught and fixed a real DetailPanel timer bug), optimistic UI helper with tree spinners (pilot: VM power actions), perf baseline (`scripts/perf_session.py`, `docs/PERF_BASELINE.md`, CI smoke thresholds), PVE feature detection (`domain/compat.py`: `PveVersion`, `PVE_FEATURES`, `provider.supports()`)
- Theme engine (M1.1): 36 canonical color tokens, `Color` facade, theme plugin API v1, `load_theme()` pipeline (validation → facade → QSS + extra_qss → icons → persist), theme switcher in the status bar, built-in LightTheme
- KDE themes (M1.2): Breeze and Breeze Dark with exact KDE palettes (LGPL-2.0-or-later scheme files used as reference data), Oxygen, custom Graphite, and System theme that follows the OS color scheme live (colorSchemeChanged listener); theme plugins may override icons — Breeze/Breeze Dark ship an original filled fixed-color SVG set covering the entire icon registry (50 icons: all tree/toolbar/tab/action glyphs except the branded app mark), with density QSS; every icon renders at exactly the theme's base size — 24px under Breeze, tree/toolbar/toggle slots follow `icons.base_size()` (owner: "все иконки в 24px"; only the branded app mark stays 1.5×); monitoring charts repaint live on theme change (background, axes, title, series via token-tagged curves); every theme keeps WCAG text contrast (>=4.5 text/status, >=3.0 dim/disabled; dark themes use dark selection text on accent) — status/danger/disabled tokens deviate from scheme values where legibility required it, locked by a contrast test; text widgets (QLabel/QCheckBox/QRadioButton/QGroupBox) are background-transparent so labels on cards match the card surface, not the window background; MetricCard re-styles its inline colors on theme change (weakref card registry, token-tagged value colors) and sizes by content — fixed 84px height clipped 18pt values
- App branding (designer kit, 2026-09-15): original V+D monogram replaces the programmatic mark — vector SVG assets in `virtdeck/ui/brand_assets/` (light/dark app tiles, toolbar lockup with fixed designer colors, mono marks, 16 tray state icons: ok/error/offline per theme, light/dark and compact); tray icon now reflects connection state (offline/error/ok); installer icons shipped — hicolor PNGs for deb/rpm, `.ico` for NSI, PyInstaller window icon
- Command palette (M2, first wave): declarative action registry (`ui/action_registry.py`, Qt-free core — `Selection` descriptor, `ActionSpec`, fuzzy search with prefix/word/substring/subsequence ranking); Ctrl+K palette (`ui/command_palette.py`) filtered by the current tree selection with a context header, live fuzzy search, keyboard navigation (arrows/Enter/Esc, click to run), shortcuts shown right-aligned, dangerous actions in danger color; frameless popup closes on outside click, restyles on theme change; registry seeds app actions — toolbar globals (add server, refresh, global search, export/import config, about, quit) plus delete and VM/CT power actions (start/shutdown/reboot/stop/reset/resume/console) reusing the exact handlers of the tree context menu with enabled-predicates by VM status/template; `TreePanel.current_selection()` builds the selection descriptor (vm/ct/template/host/storage/cluster/pool/pbs/group); palette strings translated in all 5 locales (i18n version 32). Second wave: multi-selection shows bulk VM actions ("Start all"…) instead of singles via `Selection.vm_keys`; the tree context menu's VM block (bulk + power actions + console) is now built from the same ActionSpec registry (`register_vm_actions` — one source of labels/icons/enabled for menu and palette, disabled items shown per menu semantics); fixed two stale tests hardcoding the pre-audit light DANGER hex. Third wave: the whole tree context menu is registry-driven — VM tools (noVNC console, Migrate, Clone, Convert to VM/Template, Add/Remove from HA, Delete VM) and the host/cluster/group/storage blocks all come from ActionSpec (menu keeps structural presence rules: tree mode, template availability, storage api-host resolution via new TreePanel helpers; Trust SSL with its dynamic label and Edit note… stay menu-side on purpose); the palette now offers context actions for every object type (host/cluster/group/storage selections included)

**Changed**
- Server tree redesigned to a single column without a header (2026-10-08 pass, user request): secondary info — host/cluster/storage/group notes (FQDN by default) and datastore/storage usage — is rendered by a two-line item delegate as a pale smaller line under the name (INFO_ROLE) instead of the second "Info" column; the [running/total] VM counters stay as a name suffix (user's explicit call); tooltips merge node metrics with the note; column drag/resize and its persisted header state are removed (stale ui_state keys are ignored); rows are compacted — QSS item padding 3px→1px vertical with min-height 20px (including the Breeze density QSS that previously re-thickened rows and shadowed the base value under Breeze/System themes) and the info line tucked into the row padding (two-line row ~41px, single-line ~26px — the 24px icon is the floor). The toolbar brand lockup scales with the theme base icon size (24px → 42px high, ×1.75 per user's call, was fixed 22px)
- Icons unified at a 24px base size across all themes (previously 16px in Light/Oxygen/Graphite/System, 24px only under Breeze): `icons.ICON_SIZE` and the theme-engine fallback default to 24, every built-in theme plugin declares `icon_size = 24` (System resolves through Breeze), the branded app mark keeps its 1.5× relative scale. Widgets without an explicit `setIconSize` (detail-panel tabs, buttons, item-view tables — anything relying on the Qt default) now follow the theme base size too, via an application-wide `QProxyStyle` overriding the icon pixel metrics (`PM_SmallIconSize`, `PM_ListViewIconSize`, `PM_IconViewIconSize`, `PM_TabBarIconSize`) — previously they fell back to the Qt default 16px even after the unification. Fleet Health polish: report sections render expanded by default (Qt kept freshly built items collapsed, hiding all rows behind section headers), child rows no longer repeat the cluster name in the first column, the "data from HH:MM" plate turns warning-colored on partial data, section headers are bold and dim, dialog buttons carry refresh/snapshot icons, the snapshot scan reports aggregated progress ("Scanning… 45/120") and the cluster icon distinguishes a fully failed collection (error) from usable partial data (warning)

**Bug fixes**
- Theme re-application guard (2026-10-08 freeze report): picking the already-active theme in the status-bar combo no longer re-runs the full `load_theme` pipeline — a redundant `setStyleSheet` re-polishes every widget in the app and froze the main thread for seconds on a large session; retry after a failed switch stays possible. The hot `pixelMetric` path of the icon proxy style was also slimmed (module-level metric tuple, cached `base_size` — no per-call imports; measured: the Python override itself is ~0.1s of the whole re-polish, the rest is Qt's own QSS work)
- Add Server dialog (2026-10-08 user report): the three-section body is wrapped in a scroll area and the dialog minimum height lowered to 480px — on scaled screens the old 660px minimum compressed the layout below its minimum size and widgets overlapped
- Cluster page (2026-10-08 user report): the quorum table now fits its content height via `fit_table_height` (it kept its ~256px+ sizeHint regardless of row count — two nodes produced half a page of dead space that squeezed the host list below) and the redundant "Online" column is dropped — node online status is already shown in the host list right under the table
- Theme switching (2026-09-15): toolbar and detail-panel action/tab icons are now reassigned on theme change (they kept stale light-theme QIcon references and stayed dark-on-dark in dark themes); plain QWidget containers get the theme background in QSS — the central placeholder and the tasks header no longer glow with the system light palette in dark themes; `init_icons()` now consults theme icon overrides for every name (previously only 7 of 51 were applied to the cache — e.g. the Breeze search icon was silently ignored); a startup crash with a real system tray is fixed (`_soft_had_errors` was read by `_update_tray_state()` before initialization — offscreen test environments never hit the tray path)
- First-run fixes (zero-start pass): the pre-3.0 config directory (`~/.config/pve-center` etc.) is renamed to `virtdeck` on first start so hosts/UI state survive the rename; Add Server dialog defaults to port 8006 for PVE (was 8007), auto-swaps 8006↔8007 on type change (custom ports kept) and the port field stays visible for both types; the token Show button sizes to its label (was clipped in ru locale); clusters are now detected automatically via `/cluster/status` after token creation (cluster name auto-filled, `cluster_rep` set without the manual checkbox, which was removed)

**Breaking / rename**
- PVECenter renamed to **VirtDeck**: Python module `pve_center` → `virtdeck`, console script, deb/rpm/NSI package names, GitHub repo (`mcluremail/virtdeck`), config directory (`~/.config/pve-center` → `~/.config/virtdeck`), keyring service (`pvecenter` → `virtdeck`); tokens stored under the legacy keyring service are migrated transparently on first read
- PVE API tokens created on servers by new host additions are named `virtdeck-*` (previously `pvecenter-*`); tokens of existing hosts keep working unchanged

**Internal**
- UI audit (full pass, `docs/AUDIT_2026-10-08.md`): locale-fit harness `tests/ui/test_locale_fit.py` (16 dialogs + cluster tasks widget × 6 locales, sizeHint vs maximum constraints, DB seeding isolated); 60 text buttons converted from fixed to minimum width (fr/ru clips), delete-VM and confirm dialogs un-fixed with word wrap, storage dialog wrapped in a scroll area, tasks filter bar and PBS/role spacing polished, card-list fixed columns gained full-value tooltips
- Incremental audit per `docs/AUDIT_PROCESS.md` (`docs/AUDIT_2026-10-06.md`, tag `audit/2026-10-06`): delta v2.13.0 → M2 (23 commits) — theme engine, rename migrations, brand, first-run, M0/M1/M2; fixed palette offering host actions on the initial-load skeleton placeholder with an empty host name (E1) and a stale palette icon size after theme switch (E2); 5 observations recorded
- 1129 tests (M0 contracts, optimistic UI, perf smoke, compat matrix, theme plugins incl. full Breeze icon registry coverage + exact-24px sizing + live chart retheme, brand assets/tray states incl. tray-available startup, add-server dialog, keyring and config-dir legacy migration; M2 action registry + command palette incl. menu parity and bulk-selection; M4 test harness — fake PVE/PBS scenes + record/replay, backup compliance matching engine, fleet collector with partial failure, drift/runway/sprawl analytics, Fleet Health dialog with cluster grouping by tree semantics incl. the static sync-contract guard), ruff clean

## v2.13.0 — cluster create/join via UI, storage management, stabilization (last 2.x)

**New features**
- Cluster operations via UI: create a cluster from a standalone node ("Create cluster…" host menu, optional corosync link0) and add a node to an existing cluster ("Add node to cluster…" cluster menu — peer hostname, root password, fingerprint, link0, votes); long-running join runs in a worker with 10-minute timeout
- Storage management (B4 completion): create, edit and delete cluster-wide storage definitions from the tree context menu — dialog for the 9 most common plugins (dir, nfs, cifs, zfspool, lvm, lvmthin, rbd, btrfs, pbs) with content types, node restriction and enable flag; volume copy added next to move (move-content API with `delete=0`)
- Metrics history (B11): arbitrary time range — "Custom" in the timeframe combo opens a From/To dialog; the smallest rrddata preset covering the span is fetched and filtered client-side; CSV export for VM, host and storage charts
- Backup servers view: PBS servers moved into a dedicated tree mode ("Backup servers view"), hosts/storages views are PVE-only; shared cluster storages now show per-node rows (usage may differ per node)
- Styling: accent color reserved for primary actions (Start, Create VM); Console and menu buttons use a neutral palette

**Bug fixes**
- Audit 2026-09-10 (E1): the cluster join worker received a stripped candidate dict without host/user/password — the join could not connect to the joinee and the cluster mark was never saved; candidates now carry full host configs
- First tree selection no longer freezes the UI when it races the chunked detail-tab build (synchronous tab finishing deferred behind `all_tabs_built`)

**Internal**
- i18n: 51 keys translated in all 5 locales (ru/es/fr/ar/zh), key parity restored (1245 keys), i18n version 31
- Incremental audit per `docs/AUDIT_PROCESS.md` (`docs/AUDIT_2026-09-10.md`, tag `audit/2026-09-10`)
- 806 tests (+76), ruff clean; Python 3.10–3.12

## v2.12.0 — Proxmox Backup Server integration, built-in noVNC console, backend package

**New features**
- Direct Proxmox Backup Server connection (port 8007) as a provider plugin: PBS servers are added via the Add Server dialog (with connection check), appear in the object tree with their datastores and fill levels; dedicated PBS panel shows datastore status and usage, snapshots per namespace (verify state, owner, size, notes) with deletion, and sync/verify/prune jobs with manual run
- PBS backup browsing via PVE: backups table on PBS storages with owner, verify state and notes columns, restore a backup into a new VM/container, prune a single backup from the storage content table
- Built-in noVNC console for QEMU VMs: WebSocket bridge to `vncwebsocket` (127.0.0.1 only, TLS verify from host config), sticky modifier keys; vendored noVNC assets (MPL-2.0) and pako (MIT) with third-party notices
- Optional per-host HTTP(S) proxy: all API traffic — provider session, raw workers and PBS — goes through the proxy configured per host; an explicit proxy overrides env variables
- Detail tables: column reorder with saved layout and autofit
- Readable error hints for PVE web service failures (TLS/certificates, pvedaemon unreachable, request processing, response body, aborted request)

**Bug fixes**
- VNC console password field (PSA-2026-00014-1); PVE 7/8/9 compatibility documented
- Audit 2026-09-09 (11 findings): PBS provider/client were never closed (TLS pool leak); config import lost `type`/`port`/`proxy` (PBS host degraded to broken PVE host); WsBridge `stop()` before the event loop was assigned leaked a thread, and stopping during startup raised `CancelledError`; `websockets` pin raised to >=14 (`additional_headers`); timeouts on `vncproxy:` messages were misreported as "Console not supported"; noVNC window leaked without `WA_DeleteOnClose`; workers rejected by the full thread pool blocked hard/soft refresh cycles forever; 8 raw-requests workers ignored the per-host proxy (timeouts in proxy-only environments); i18n: 7 untranslated keys + parity restored; tests no longer touch the real user config
- Audit 2026-09-04: global search could not jump to a cluster node's local storage (storage result key mirrored the pre-redesign tree)
- Tree showed duplicate entries in some cluster layouts and could serve stale cached data; storage detail showed "Type: storage" instead of the plugin type; standalone hosts' local storages were hidden in the Storages view; storage content tabs appeared shifted by one after the Monitoring tab insertion (now pinned by a `TabIndex` contract test)

**Performance**
- Faster startup (~3.3s → ~1s): detail tabs are built lazily in chunks after the window shows, the `pyqtgraph` import warms up in a background thread, `requests` is imported only where used, keyring backend is detected once; spinners for async data loading instead of frozen tables

**Internal**
- `backend.py` split into a package: `RefreshCoordinator` (hard/soft refresh generations with timeouts), event bus seed, unified PVE error parsing (`parse_pve_error`); UI unchanged via facade
- Incremental audits per the new methodology (`docs/AUDIT_PROCESS.md`, reports 2026-06-20/09-04/09-09), new development methodology (`docs/DEV_PROCESS.md`)
- 730 tests (+209), ruff clean; Python 3.10–3.12

## v2.11.3 — performance: fast startup, no freeze on first selection

**Performance**
- Much faster startup: the window appears in ~1s instead of ~3.3s — detail tab building is deferred, the `pyqtgraph` import (~0.6s) happens in a background thread after launch, `requests` is imported only where used (file upload, update checker) and the keyring backend is detected once instead of per token
- Selecting an object no longer freezes the UI: the 25 detail tab pages are built in small chunks between event-loop ticks right after the window appears, and the remaining pages (if any) are finished synchronously on the first selection; charts (VM metrics, storage monitoring) are created lazily on first data once the pyqtgraph warm-up completes
- First selection pays at most a fraction of the old ~1-3.5s tab construction cost; subsequent selections are unchanged (~ms)

**Internal**
- 521 tests (+6): lazy tab building contract (nothing built at construction, chunked queue drains in TabIndex order, `_ensure_tabs()` finishes partial builds), chart deferral guards


## v2.11.2 — spinners, stale-tree fix, faster startup/shutdown

**New features**
- Animated spinners for async data loading: storage detail tables, storage monitoring chart, VM metrics and task history, host metrics and cluster quorum card show a spinner while data is fetched; loading pages keep the QLabel-compatible `setText`/`text` API so error/empty states work unchanged

**Bug fixes**
- Storage content tabs were shifted by one after the Monitoring tab insertion: `load_storage_content` used stale raw indexes 10-13, so the chart appeared under "Backups", backups under "VM Disks", disks under "ISO" and ISO images under "Templates"; now addressed via `TabIndex` (regression test added)
- Soft refresh now rebuilds the tree when the cluster structure changes — storages/VMs/nodes removed on the PVE side disappear from the tree within one auto-refresh cycle instead of lingering until a hard refresh
- Faster shutdown: on quit all fetch workers are cancelled and the pool wait is reduced from 3s to 1s; the process no longer lingers up to ~80s after the window closes
- Fix: loading pages keep the QLabel-compatible `setText`/`text` API (fixes "QWidget object has no attribute 'setText'" on every error/empty state shown in a loading stack)
- Fix: right-panel tables fit at FullHD
- Fix: standalone hosts' local storages were hidden in the Storages view
- Fix: storage detail showed "Type: storage" — prefer the `plugintype` field

**Performance**
- Faster startup: `requests` import is deferred (used only by file upload and the update checker, ~0.5s saved); the keyring backend is detected once instead of per token (~0.3s saved with many hosts)

**Internal**
- Test suite grown to 515 tests: tab order pinned to `TabIndex`, storage content tabs regression, soft-refresh structure diff, `FetchWorker.cancel()`, `LoadingPage` compatibility


## v2.11.1 — hotfix: crash on cluster summary quorum card

**Bug fixes**
- MetricCard.set_value() now accepts an optional `subtitle` keyword (cluster detail quorum card called it as `set_value("2/4", subtitle=...)`, which raised TypeError on every cluster metrics refresh)

## v2.11.0 — tree redesign: flat tree, Hosts/Storages view modes

**New features**
- Tree redesign (B20): the "Clusters" / "Standalone hosts" / "Storage" sections are gone — user groups (B16), clusters and standalone hosts now form one flat, name-sorted top level
- View switcher at the top of the tree panel: "Hosts" (previous tree structure) / "Storages" (shared cluster storages deduplicated at the cluster level as "name (@cluster)", local storages under each host, standalone hosts keep all their storages, shared storages are not repeated under cluster hosts); the choice is persisted in config.sqlite (ui_state `treeMode`)
- Host groups participate in the Storages view too (group counter = number of unique storage names)
- Global search: picking a storage result switches the tree to the Storages view automatically

**Bug fixes**
- Global search: jump to a local (non-shared) storage of a cluster node now works — the search key mirrors the tree (host-scope instead of wrongly cluster-scope); found by the incremental audit (docs/AUDIT_2026-09-04.md)

**Changed**
- Drag&drop onto a tree section for ungrouping is no longer available — use "Remove from group" in the context menu
- i18n: 2 new keys in all 5 languages ("Hosts view", "Storages view"), _I18N_VERSION bumped to 28

## v2.10.0 — tree notes, global search, snapshot rollback, bulk actions, host groups

**New features**
- Tree notes: short user note per tree item (host, cluster, group, VM, storage) shown in a second muted column; host items default to the host FQDN until a custom note is set; edited via "Edit note…" context menu; stored in config.sqlite (`tree_notes` table)
- Global search: toolbar button + Ctrl+F dialog searches VMs (name, VMID, tags, pool, node), hosts, pools and storages across all clusters; selecting a result jumps to the object in the tree
- Snapshot rollback: revert a VM/container to a snapshot from the Snapshots tab (toolbar button + context menu, with confirmation)
- Rollback action is guarded for the pseudo-snapshot "current" and waits for the UPID task to finish
- Bulk VM actions: multi-select in the tree (Ctrl+click / Shift+click), context menu offers mass Start / Shutdown / Reboot / Stop; progress dialog with Cancel, per-VM results summary
- User-defined host groups: named groups above the tree sections, hosts/clusters assigned via "Move to group..." context menu (rename/delete supported) or drag&drop onto a group / the Clusters and Standalone hosts sections, grouping persisted in config.sqlite; clicking a group shows an aggregated summary with host VMs
- i18n: 9 new keys in all 5 languages, _I18N_VERSION bumped to 23; 6 more keys for groups (_I18N_VERSION 24)
- Internal: cluster tasks and VM task history now flow through the domain `Task` model instead of raw dicts (task history cache roundtrips via `Task.from_pve`); VM snapshots likewise flow through the domain `Snapshot` model (size computed in the worker, tree built from attributes); HA resources and groups use domain `HaResource`/`HaGroup` models end-to-end; cluster quorum/corosync status is delivered as a domain `ClusterStatus` container (ClusterInfo + merged ClusterNode list); pools are collected as domain `Pool` objects (with comments) into `PoolRepository` instead of `poolid` string dicts; UI layer now reads domain objects via attributes everywhere (`.get()` removed from panels, dialogs, workers and summary cards — tree, detail panel, main window, pool widget, metrics workers, all VM/storage dialogs); `DictCompat` kept as model base for the JSON cache roundtrip (`dict(obj)`) and unknown-key fallback

## v2.9.0 — VM templates, cloning, audit fixes, update check

**New features**
- VM templates: convert QEMU VM ↔ template (context menu + detail panel buttons)
- Clone from template: host context menu shows templates, clone dialog picks template then target
- Template-aware UI: template VMs get distinct icon in tree, lifecycle/migrate/console actions disabled for templates
- LXC console: VNC proxy support (was SPICE-only, always failed for containers)
- Automatic update check: fetches GitHub releases on startup, notifies if newer version available

**Bug fixes (audit)**
- Tree soft refresh: template VMs now show template icon (was reverting to VM status icon)
- Worker pool exhaustion: user now gets notification when max concurrent workers reached (was silent)
- DeleteVmWorker: LXC containers now deleted via lxc endpoint (was always QEMU endpoint)
- VmConsoleWorker: LXC uses VNC proxy, QEMU uses SPICE (was SPICE for both)
- _on_vm_convert: pre-checks VM is stopped before converting to template
- _on_vm_action_from_tree: rejects lifecycle actions for templates
- _on_vm_migrate: rejects migration for templates
- Dead code: removed unused `suspend` from _CONFIRM_ACTIONS/_CONFIRM_MESSAGES
- Signal consistency: `vm_clone_from_template_requested` now `(host_name, node)` order

## v2.8.1 — audit bug fixes

**Bug fixes (18 issues)**
- LXC restore: used `hostname` param instead of `name`; `unique` only sent for QEMU VMs
- PVE8 `/cluster/jobs`: filtered to `vzdump` type only (was returning all job types)
- Removed dead `/cluster/replication` API call (endpoint doesn't exist)
- PVE8 job create/update: now includes `type=vzdump` param (was falling back to PVE7)
- ClusterJobUpdateWorker: `id` stripped from PUT body (was causing HTTP 400)
- BackupJobDialog: weekday names now translatable (`tr()` at call time, not module load)
- BackupJobDialog: `prune-backups` parsing handles `keep-last=N` format
- BackupJobDialog: Save button disabled + warning shown when no backup storages
- BackupJobDialog: `bool("0")` == True bug for `enabled` field (now `int()`)
- BackupJobDialog: removed dead `is_pve8` parameter
- VzdumpDialog: canonical i18n key `Backup VM {vmid}`
- VM backup tab: storage name now shown in Storage column (was always empty)
- VM backup tab: generation guard prevents cross-VM data corruption on rapid switch
- Cluster snapshots: crash fix — `data` is a list, not dict (was calling `.items()`)
- Cluster storage aggregation: filtered by cluster name (was summing all clusters)
- Cluster health tab: completion check for hosts without config
- Backup jobs: fetched for cluster-member hosts via cluster config
- TabIndex.HARDWARE: now hidden on type switch (was always visible)
- Notification: `online→online` no longer shows spurious warning toast
- Notification: `vm_status_changed` unused `old_status` parameter removed

## v2.8.0 — vzdump backup & restore, backup jobs, cluster tabs

**New features**
- VM on-demand backup (vzdump): storage, mode (snapshot/suspend/stop), compression (none/gzip/lzo/zstd), notes, remove-old, bandwidth limit
- VM restore from backup: new VMID auto-suggest, target storage, force overwrite, unique MAC
- Backup jobs scheduling: add/edit/remove jobs with Daily/Weekly/Custom schedule, retention, compression — supports both PVE 8+ (`/cluster/jobs`) and PVE 7 (`/cluster/backup`)
- Cluster-level tabs: Virtual Machines (aggregated), Storage (aggregated), Snapshots, Health, Backup Jobs
- Cluster summary cards: hosts (online/total), VMs (running/total), CPU, RAM, Storage with progress bars
- VM stats header: VMs total (running/stopped), CPU used, RAM used
- Summary tab moved to first position for cluster view
- Double-click on backup job row to edit
- Restore icon added to icon set

**Bug fixes**
- FadeToast crash: weakref pattern prevents "Internal C++ object already deleted" (strong ref kept toast alive after parent deleted)
- Cluster health tab stuck on Loading: replaced arbitrary `total * 2` threshold with done/total counter

## v2.7.0 — hardware management, storage operations, audit

**New features**
- VM Hardware Add/Remove/Edit: toolbar with 8 device types (Hard Disk, CD/DVD, Network, USB, PCI, Serial, EFI Disk, TPM)
- Disk destroy on removal: optional delete storage content after removing disk from VM config
- Hotplug-aware guards: Add/Remove blocked for running VMs unless hotplug allows the device type
- Storage file operations: Upload (ISO, templates, backups), Move (between storages), Remove — toolbar above each content table
- Upload progress bar: real-time progress shown in cluster tasks table
- 137 new i18n keys for ar/zh/fr/es (health-check, status-bar, SSL notifications, hardware editors)

**Bug fixes**
- Backup volid: stored in Qt.UserRole (was returning "VM 123" instead of actual volid for Move/Remove)
- Progress row stale index: reindexed on insert (concurrent uploads shifted rows)
- itemSelectionChanged reconnect leak: disconnect before reconnect (accumulated callbacks)
- set_vm_status order: called before set_hardware_data (buttons reflected previous VM's status)
- _parse_net/_parse_disk: handle None without str(None)="None" bug
- VmDiskEditorDialog: preserve non-cache params (discard, ssd, iothread) on cache change
- EFI disk: size=2 for efitype=2m, size=4 for 4m (was always 4)
- is_cdrom_key: check value for ide2, not always True (hard disks on ide2 no longer treated as CD-ROM)
- create_admin_token: handle r is None, init sess=None before try
- _ProgressReader: add seek/tell/fileno for requests compatibility
- StorageUploadWorker: fix resp.json double-parse when data is string
- _poll_task: guard against non-dict data response
- fetch_standalone: use v.get("vmid") instead of v["vmid"]
- on_snapshots_error: pop stale cache entry on error
- ISO worker: routed through _workers_mgr, errors logged instead of swallowed

**Dead code removed**
- Download feature (PVE API doesn't support file download via token)
- Dead signals: destroy_disk, opacity Property
- Dead fields: _MAX_SLOTS, _has_selection, seen set
- Duplicate PVE_PORT, unused imports, stale comments
- Debug logging (token_create, remote-viewer) INFO → DEBUG

## v2.6.0 — features & fixes

**New features**
- Status bar: hosts, VMs, CPU, RAM summary in bottom bar
- Tray icon: minimize to tray on close, quick actions menu
- RRD timeframe persistence: chart range saved between sessions
- Node comparison: side-by-side cluster node comparison view
- Multi-cluster dashboard: Clusters | Nodes toggle in cluster folder summary
- Health check tab: CPU/mem/disk thresholds, PVE service status, apt updates
- Audit log filters: text search + status dropdown (All/OK/Errors/Running)
- Pool resource summary: aggregated VM count, CPU, memory, disk with progress bars
- Offline mode: cached resources loaded on startup, shown until first live data arrives

**Bug fixes**
- SSL error detection: actionable message for self-signed/expired/invalid certificates
- Session leak: requests.Session closed in finally block of all 13 ProxmoxAPI workers
- Node deduplication: nodes matched by (node, host_name) — standalone hosts with same PVE node name no longer count each other's VMs
- CardList key collisions: key changed from "node" to "node@host_name" for uniqueness
- Summary view column alignment: header labels + VMs column added to standalone host list
- Cluster folder: standalone hosts no longer appear in cluster node compare view
- Pool metric cards: fixed height instead of expanding to fill available space
- Audit log filter bar: compact, right-aligned, minimal vertical space
- Tasks table sort freeze: sort in Python before table insert — eliminated 3-5s freeze on 400+ rows
- Worker memory leak: signal connections disconnected in _discard_worker — was leaking 108K lambda objects (30+ MiB)
- Cluster summary VM count: matched by host_name set instead of node name set

## v2.5.1 — bugfix release

Comprehensive code audit: ~21 bugs fixed across backend, UI, metrics, i18n, and resource management.

**Backend**
- Fixed API token creation: removed broken fallback that set token value to token name instead of secret
- Fixed SSL trust inversion: `trust_ssl` semantics now consistent across all code paths
- Fixed `UnboundLocalError` on connection error during token creation
- Fixed session leak: `requests.Session` now closed in `finally` block
- Standalone hosts: added missing `host_name` and `cluster` fields (caused UI KeyError)
- Fixed pool assignment race in standalone mode (re-applied after pool fetch)
- Removed duplicate API call in standalone fetch
- `fetch_resources`: guard against missing `type` field
- `ClusterTasksWorker`: now emits `tasks_error` on merge/sort failure (was hanging UI)

**UI crashes**
- All `data["key"]` accesses replaced with `.get()` guards in worker callbacks
- Fixed spinner leak: `_soft_refresh_active` and `_spin_timer` now reset on hard refresh
- Fixed hotplug validation typo: `networkdisk,usb` → `network,disk,usb` (invalid PVE API value)

**Metrics & notification**
- Fixed `KeyError` on RRD sparse data (`entry.get('time')`)
- Fixed notification crash on deleted widget (`RuntimeError` guard in `_restore_color`)
- Fixed toast replacement race: disconnect `destroyed` signal before `deleteLater`
- Fixed double `metric_changed` emit in metrics widget
- Fixed sort indicator arrow mismatch in cluster tasks table
- Host workers now tracked and cancelled on tab switch (no more orphaned QThreads)

**i18n**
- Added 8 missing lowercase status translations (running, stopped, paused, error, offline, online, unknown, mounted)
- Wrapped untranslated UI strings: Method, CIDR, Filter, No data, VM/CT prefix

**Dead code removed**
- Unused attributes: `_vm_iso_pending`, `_iso_volids`, `_disk_visible`, `_scroll`
- Dead `seen_names` initialization in tree panel

**Resource leaks**
- Detail panel caches (details, config, metrics, task history) now cleared on data refresh
- `QTimer` in table filter now has parent (was parentless)
- Freeze detector thread stopped on application close
- `ClusterTasksWorker`: signals disconnected when max workers cap hit (was orphaning workers)

## v2.5.0 — UI redesign

- MetricCard-based dashboard with progress bars
- CardList widget for list views (Host VMs, Cluster Summary, Storage Overview)
- Hardware/Options tabs with section grouping and device icons
- Hide empty section headers
- Fixed freeze on close (timers + thread pool shutdown)
- Tree expanded-state persistence
- CD-ROM detection by value (`media=cdrom`)

## v2.4.0

- Theme refresh (minimalist style)
- Header bar, segmented tabs, borderless tables
- Charts with area fill
- AddServer dialog with SSL trust toggle