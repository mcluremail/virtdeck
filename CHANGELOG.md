# Changelog

## Unreleased (v3.0 dev)

**New features**
- Performance foundation (M0): static sync-contract test (AST scanner — no sync client calls in UI), runtime contract guard on `PluginRegistry.create_provider` (caught and fixed a real DetailPanel timer bug), optimistic UI helper with tree spinners (pilot: VM power actions), perf baseline (`scripts/perf_session.py`, `docs/PERF_BASELINE.md`, CI smoke thresholds), PVE feature detection (`domain/compat.py`: `PveVersion`, `PVE_FEATURES`, `provider.supports()`)
- Theme engine (M1.1): 36 canonical color tokens, `Color` facade, theme plugin API v1, `load_theme()` pipeline (validation → facade → QSS + extra_qss → icons → persist), theme switcher in the status bar, built-in LightTheme
- KDE themes (M1.2): Breeze and Breeze Dark with exact KDE palettes (LGPL-2.0-or-later scheme files used as reference data), Oxygen, custom Graphite, and System theme that follows the OS color scheme live (colorSchemeChanged listener); theme plugins may override icons — Breeze/Breeze Dark ship an original filled fixed-color SVG set covering the entire icon registry (50 icons: all tree/toolbar/tab/action glyphs except the branded app mark), with density QSS; every icon renders at exactly the theme's base size — 24px under Breeze, tree/toolbar/toggle slots follow `icons.base_size()` (owner: "все иконки в 24px"; only the branded app mark stays 1.5×); monitoring charts repaint live on theme change (background, axes, title, series via token-tagged curves)
- App branding (designer kit, 2026-09-15): original V+D monogram replaces the programmatic mark — vector SVG assets in `virtdeck/ui/brand_assets/` (light/dark app tiles, toolbar lockup with fixed designer colors, mono marks, 16 tray state icons: ok/error/offline per theme, light/dark and compact); tray icon now reflects connection state (offline/error/ok); installer icons shipped — hicolor PNGs for deb/rpm, `.ico` for NSI, PyInstaller window icon

**Bug fixes**
- Theme switching (2026-09-15): toolbar and detail-panel action/tab icons are now reassigned on theme change (they kept stale light-theme QIcon references and stayed dark-on-dark in dark themes); plain QWidget containers get the theme background in QSS — the central placeholder and the tasks header no longer glow with the system light palette in dark themes; `init_icons()` now consults theme icon overrides for every name (previously only 7 of 51 were applied to the cache — e.g. the Breeze search icon was silently ignored); a startup crash with a real system tray is fixed (`_soft_had_errors` was read by `_update_tray_state()` before initialization — offscreen test environments never hit the tray path)
- First-run fixes (zero-start pass): the pre-3.0 config directory (`~/.config/pve-center` etc.) is renamed to `virtdeck` on first start so hosts/UI state survive the rename; Add Server dialog defaults to port 8006 for PVE (was 8007), auto-swaps 8006↔8007 on type change (custom ports kept) and the port field stays visible for both types; the token Show button sizes to its label (was clipped in ru locale); clusters are now detected automatically via `/cluster/status` after token creation (cluster name auto-filled, `cluster_rep` set without the manual checkbox, which was removed)

**Breaking / rename**
- PVECenter renamed to **VirtDeck**: Python module `pve_center` → `virtdeck`, console script, deb/rpm/NSI package names, GitHub repo (`mcluremail/virtdeck`), config directory (`~/.config/pve-center` → `~/.config/virtdeck`), keyring service (`pvecenter` → `virtdeck`); tokens stored under the legacy keyring service are migrated transparently on first read
- PVE API tokens created on servers by new host additions are named `virtdeck-*` (previously `pvecenter-*`); tokens of existing hosts keep working unchanged

**Internal**
- 942 tests (M0 contracts, optimistic UI, perf smoke, compat matrix, theme plugins incl. full Breeze icon registry coverage + exact-24px sizing + live chart retheme, brand assets/tray states incl. tray-available startup, add-server dialog, keyring and config-dir legacy migration), ruff clean

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