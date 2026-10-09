# VirtDeck — full feature list

Install options and requirements: [README](../README.md). Themes API:
[THEMES.md](THEMES.md).

**Fleet Health (multi-cluster)**
- One report across all your independent clusters: backup compliance, version drift, storage runway and snapshot sprawl — the whole estate at a glance
- Backup compliance: guests not covered by any backup job — pure client-side matching of PVE job semantics (all > pool > vmid, exclude lists, templates exempt); "last successful backup" from PBS or task history
- Version drift: nodes lagging behind their cluster leader highlighted (patch / minor / major)
- Storage runway: least-squares forecast with a 95% confidence interval — "site B runs out of disk in ~12 days"
- Snapshot sprawl: forgotten snapshots (>30 days) across every guest, on-demand scan with bounded parallelism
- Partial failure isolation: an offline cluster degrades to a "data from HH:MM" plate — the report never goes empty
- Launch from the toolbar, tray or Ctrl+Shift+F; double-click jumps to the object in the tree

**Monitoring**
- CPU, RAM, network, and disk usage charts (RRD data from PVE); arbitrary time range (Custom From/To) and CSV export for VM, host and storage charts
- VM pool summary with resource progress bars
- Storage: aggregated overview, per-node detail, fill-level chart
- Storage content: backups, VM disks, ISO images, templates
- Snapshots — all snapshots on a host in a single table
- VM hardware configuration, options, task history
- VM hardware management: add/remove/edit devices (disk, CD/DVD, network, USB, PCI, serial, EFI, TPM) with hotplug awareness
- Storage management: create, edit and delete cluster-wide storage definitions (9 common plugins, content types, node restriction) from the tree context menu
- Storage file operations: upload, copy, move, remove files on storage content tables
- Host network interfaces, PVE services, disks (with FC multipath dedup)
- Health check tab: CPU/mem/disk thresholds, critical service status, subscription & apt updates
- Status indicators with colored markers (green, red, yellow)

**Management**
- Power actions for QEMU and LXC: Start, Shutdown, Reboot, Reset, Stop, Resume
- Bulk actions: multi-select VMs in the tree (Ctrl/Shift+click) and mass Start / Shutdown / Reboot / Stop with progress dialog and per-VM results
- Optimistic UI: power actions apply instantly with tree spinners and roll back with a clear error on failure
- Snapshot rollback: revert a VM/container to a snapshot from the Snapshots tab (guarded for the pseudo-snapshot "current")
- Create Virtual Machines: dialog with CPU, RAM, disk, network settings — right from the node context menu
- Cluster operations: create a cluster from a standalone host and add a node to an existing cluster (peer hostname, root password, fingerprint, corosync link0, votes) via context menus
- Migrate QEMU VMs between cluster nodes (with local disks option)
- Clone QEMU VMs and LXC containers (full or linked, target node, storage selection), clone from templates, convert VM ↔ template
- SPICE console (requires virt-viewer)
- Built-in noVNC console for QEMU VMs: WebSocket bridge to `vncwebsocket`, sticky modifier keys (Ctrl/Alt/Shift stay pressed); bundled on Windows, on Linux install `websockets`
- Delete host with API token removal on the server
- Token recreation via context menu

**Backups**
- PBS backup browsing via PVE: backups table on PBS storages with owner, verify state and notes columns
- Delete a single backup (prune one) from the storage content table
- Restore a PBS backup into a new VM or container
- Direct Proxmox Backup Server connection (port 8007): PBS servers added via the Add Server dialog (with connection check) appear in the object tree with their datastores and fill levels
- PBS panel: datastore status and usage, snapshots per namespace with verify state, owner and size, snapshot deletion
- PBS jobs: sync / verify / prune schedules with manual run

**Security & Audit**
- User-bound API tokens: created automatically when adding a server, actual operator visible in PVE audit log
- Token storage: system keyring (KWallet / GNOME Keyring / Windows Credential Manager)
- Node config stored in SQLite database, no plaintext tokens on disk
- Config export/import: encrypted bundle with password (PBKDF2 + Fernet)
- SSL certificate validation: per-host toggle (trust / self-signed)
- Optional per-host HTTP(S) proxy: all API traffic (provider, raw workers, PBS) goes through the configured proxy; an explicit proxy overrides env variables
- Audit log filters: text search + status filter (All/OK/Errors/Running)

**Interface**
- Object tree: one flat, name-sorted top level — user groups, clusters and standalone hosts → Hosts → VMs/Containers with color status indicators; templates get a distinct icon; "Hosts"/"Storages"/"Backup servers" view modes; shared cluster storages show per-node usage rows; compact two-line rows (24px icons throughout) with running/total counters as a name suffix
- User-defined host groups: named groups at the tree top level, assign hosts/clusters via context menu or drag&drop; clicking a group shows an aggregated summary
- Tree notes: short per-item note (host, cluster, group, VM, storage) rendered as a pale line under the item name; host notes default to the host FQDN; the full text is in the tooltip
- Global search (Ctrl+F): find VMs, hosts, pools and storages across all clusters and jump to the object in the tree
- Command palette (Ctrl+K): fuzzy search over every tree and toolbar action, keyboard navigation, context header; the tree context menu is built from the same declarative action registry
- Monitoring dashboard: metric cards with progress bars (CPU, RAM, Disk, Network, Uptime) and live charts
- CardList widget — list views as card rows (Host VMs, Cluster Summary, Storage Overview) with status dots, filter, double-click editing
- Node comparison view: side-by-side cluster node metrics (CPU, RAM, disk, VMs, uptime, PVE version)
- Multi-cluster dashboard: Clusters summary + Nodes comparison toggle
- Hardware/Options tabs with section grouping and device type icons
- Task history with colored status badges and filter bar
- Status bar: live hosts/VMs/CPU/RAM summary
- System tray icon: minimize to tray, quick quit, context menu
- Offline mode: cached resources shown on startup before first network response
- Multi-language UI (English, Russian, Arabic, Chinese, French, Spanish)
- Theme switcher in the status bar: Light, KDE Breeze / Breeze Dark (24px icon set, exact KDE palettes), Oxygen, Graphite, and System (follows the OS color scheme); toolbar icons and brand recolor to match; themes are plugins with a documented API ([docs/THEMES.md](THEMES.md))
- Background auto-refresh every 20 seconds without losing selection or tabs
- Toast notifications on host/VM status changes
- Diagnostics for unreachable hosts (DNS error, timeout, auth failure, SSL errors)
- Fast startup: parallel data loading, cluster summary and status bar in seconds
- Persistence: window geometry, splitter positions, create-VM settings, expanded tree nodes, RRD timeframe saved between sessions
- Cluster task cache in SQLite — tasks visible instantly on next launch
