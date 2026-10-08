# VirtDeck

Desktop client for Proxmox VE management. Written in Python with PySide6.

Monitor clusters and hosts, manage virtual machines and containers, browse Proxmox Backup Server backups — all in one window, no browser needed.

![VirtDeck](Screenshots/main.png?v=3)

## Download

| Platform | Format | Link |
|----------|--------|------|
| Windows | .zip / .exe installer | [Releases](https://github.com/mcluremail/virtdeck/releases) |
| Linux (any) | pip | `pip install virtdeck` |
| Debian / Ubuntu | .deb | [Releases](https://github.com/mcluremail/virtdeck/releases) |
| Fedora / RHEL | .rpm | [Releases](https://github.com/mcluremail/virtdeck/releases) |
| Any | .tar.gz / .whl | [Releases](https://github.com/mcluremail/virtdeck/releases) |

Latest release: [v3.0.0](https://github.com/mcluremail/virtdeck/releases/tag/v3.0.0)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

## Features

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
- Built-in noVNC console for QEMU VMs: WebSocket bridge to `vncwebsocket`, sticky modifier keys (Ctrl/Alt/Shift stay pressed); bundled on Windows, optional `novnc` extra on Linux
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
- Theme switcher in the status bar: Light, KDE Breeze / Breeze Dark (24px icon set, exact KDE palettes), Oxygen, Graphite, and System (follows the OS color scheme); toolbar icons and brand recolor to match; themes are plugins with a documented API ([docs/THEMES.md](docs/THEMES.md))
- Background auto-refresh every 20 seconds without losing selection or tabs
- Toast notifications on host/VM status changes
- Diagnostics for unreachable hosts (DNS error, timeout, auth failure, SSL errors)
- Fast startup: parallel data loading, cluster summary and status bar in seconds
- Persistence: window geometry, splitter positions, create-VM settings, expanded tree nodes, RRD timeframe saved between sessions
- Cluster task cache in SQLite — tasks visible instantly on next launch

## Requirements

- Python 3.10+ (for pip/source install; not needed for Windows .zip or installer)
- PySide6 (full package, incl. WebEngine — for the built-in noVNC console)
- proxmoxer (Debian 12+/Ubuntu 23.04+ have `python3-proxmoxer`; older — via pip)
- requests / urllib3
- pyqtgraph
- keyring — system keyring access (KWallet / GNOME Keyring / Windows Credential Manager)
- cryptography (export/import encrypted config bundle)
- websockets — **optional on Linux**: required only for the built-in noVNC
  console (`pip install virtdeck[novnc]`); the app runs fine without it.
  On **Windows** it is a hard dependency — Windows builds (zip/installer)
  bundle everything, no system Python needed.
- Proxmox VE (cluster or standalone host)
- API access to PVE host (port 8006)
- Proxmox Backup Server (port 8007) — for direct PBS integration
- virt-viewer (for SPICE/VNC console via remote-viewer)

## Installation

### Windows

Download `virtdeck-windows.zip` or `virtdeck-*-setup.exe` from [GitHub Releases](https://github.com/mcluremail/virtdeck/releases).

**Portable:** Extract `.zip` to any folder, run `virtdeck.exe`.

**Installer:** Run `virtdeck-*-setup.exe` — multilingual NSIS installer (English, Russian, Arabic, French, Spanish, Chinese). Creates Start Menu and Desktop shortcuts, registers uninstaller.

For SPICE console, install [virt-viewer for Windows](https://virt-manager.org/download/).

### Via pip (PyPI)

```bash
pip install virtdeck
# optional: built-in noVNC console
pip install "virtdeck[novnc]"
virtdeck
```

### Linux system packages (system Python, no venv)

```bash
# Arch Linux
sudo pacman -S --needed pyside6 python-proxmoxer python-requests \
  python-urllib3 python-pyqtgraph python-keyring python-cryptography
# optional: built-in noVNC console + remote-viewer console
sudo pacman -S --needed python-websockets virt-viewer

# Debian / Ubuntu
sudo apt install python3-pyside6 python3-proxmoxer python3-requests \
  python3-urllib3 python3-pyqtgraph python3-keyring python3-cryptography
# optional
sudo apt install python3-websockets virt-viewer

# Fedora
sudo dnf install python3-pyside6 python3-proxmoxer python3-requests \
  python3-urllib3 python3-pyqtgraph python3-keyring python3-cryptography
# optional
sudo dnf install python3-websockets virt-viewer
```

Then run from the repo: `./run` (or `python -m virtdeck`).

### Isolated environment

```bash
git clone https://github.com/mcluremail/virtdeck.git
cd virtdeck
python -m venv venv
source venv/bin/activate
pip install PySide6 proxmoxer requests urllib3 pyqtgraph cryptography keyring
# optional: built-in noVNC console
pip install websockets
```

### .deb package (Debian / Ubuntu)

Download `.deb` from [GitHub Releases](https://github.com/mcluremail/virtdeck/releases):

```bash
# download .deb from release page
sudo dpkg -i virtdeck_*.deb
# virt-viewer (if SPICE/VNC console via remote-viewer needed)
sudo apt install virt-viewer
# optional: built-in noVNC console
sudo apt install python3-websockets
```

After installing the `.deb` package, launch from the menu or via `virtdeck`.

Build from source (for custom versions):

```bash
sudo apt install devscripts debhelper dh-python python3-all python3-setuptools
cd virtdeck
dpkg-buildpackage -b
sudo dpkg -i ../virtdeck_*.deb
```

### virt-viewer (for SPICE console)

```bash
# Debian / Ubuntu
sudo apt install virt-viewer

# Arch Linux
sudo pacman -S virt-viewer

# Fedora
sudo dnf install virt-viewer

# Windows
# Download from https://virt-manager.org/download/

# macOS
brew install virt-viewer
```

## Usage

```bash
# Windows
# Portable: Extract .zip, run virtdeck.exe
# Installer: Run virtdeck-*-setup.exe

# If installed via pip or .deb:
virtdeck

# From local repository:
./run
# or
python -m virtdeck
```

### First run

1. Launch the application.
2. Click `[+]` in the tree panel toolbar.
3. In the dialog that opens, enter:
   - **Host address** (FQDN or IP)
   - **User** (e.g., `root@pam`)
   - **User password**
4. The API token is created automatically and stored in the system keyring. The application connects to the host and starts monitoring.

For a cluster, adding a single node is sufficient — others are discovered dynamically via `/cluster/resources`.

### Dependencies

| Package | Purpose |
|---------|---------|
| PySide6 | GUI framework (WebEngine — built-in noVNC console) |
| proxmoxer | Proxmox VE API client |
| requests | HTTP library |
| urllib3 | TLS/session handling (imported directly) |
| pyqtgraph | Charts and plotting |
| cryptography | PBKDF2 + Fernet encryption (export/import bundle) |
| keyring | System keyring for token storage |
| websockets | *Optional* — built-in noVNC console WS bridge |

For `.deb` package: `python3-pyside6`, `python3-proxmoxer`, `python3-requests`,
`python3-urllib3`, `python3-pyqtgraph`, `python3-cryptography`, `python3-keyring`
are available from Debian/Ubuntu repos. `python3-websockets` (noVNC console)
and `virt-viewer` (remote-viewer console) are Recommends.

The application is designed to run on the **system Python** and system
packages (no venv required): `./run` uses plain `python -m virtdeck`.

### Project structure

| File | Purpose |
|------|---------|
| `virtdeck/__main__.py` | Module entry (`python -m virtdeck`) |
| `virtdeck/main.py` | Application entry point |
| `virtdeck/backend/` | API client package: workers, `RefreshCoordinator` (hard/soft refresh), event bus seed, unified PVE error parsing |
| `virtdeck/backend/fleet.py` | Fleet Health API workers (per-cluster collection) |
| `virtdeck/pbs/` | Proxmox Backup Server API client (ticket auth) and workers |
| `virtdeck/plugins/_pbs.py` | PBS plugin (dispatch by `cfg["type"] = "pbs"`) |
| `virtdeck/domain/pbs.py` | PBS domain models (datastores, snapshots, jobs) |
| `virtdeck/domain/backup_coverage.py` | Backup compliance matching engine (vzdump job semantics, pure domain) |
| `virtdeck/fleet/` | Fleet Health collectors and analytics (drift, storage runway, snapshot sprawl) |
| `virtdeck/config.py` | Keyring, SQLite config storage, export/import |
| `virtdeck/ui/mainwindow.py` | Main window |
| `virtdeck/ui/tree_panel.py` | Tree panel for clusters, hosts, and VMs |
| `virtdeck/ui/detail_panel/` | VM/host detail panel (package) |
| `virtdeck/ui/add_server_dialog.py` | Add server dialog (with SSL trust toggle) |
| `virtdeck/ui/create_vm_dialog.py` | Create VM dialog |
| `virtdeck/ui/migrate_vm_dialog.py` | VM migration dialog |
| `virtdeck/ui/clone_vm_dialog.py` | VM cloning dialog |
| `virtdeck/ui/vm_config_editor_dialog.py` | VM config editor dialog |
| `virtdeck/ui/vm_device_editors.py` | Specialized device editors |
| `virtdeck/ui/vm_config_display.py` | VM config display widget |
| `virtdeck/ui/vm_actions.py` | VM power action labels and confirmation |
| `virtdeck/ui/pbs_panel.py` | PBS panel: datastores, snapshots, jobs |
| `virtdeck/ui/fleet_health.py` | Fleet Health report dialog (multi-cluster) |
| `virtdeck/ui/command_palette.py` | Command palette (Ctrl+K) |
| `virtdeck/ui/action_registry.py` | Declarative action registry — shared source for the palette and context menus |
| `virtdeck/ui/brand.py` | VirtDeck brand assets: toolbar lockup, app/tray icons |
| `virtdeck/ui/about_dialog.py` | About dialog |
| `virtdeck/ui/theme.py` | Color constants, fonts, QSS theme |
| `virtdeck/plugins/_themes.py` | Built-in theme plugins (Light, Breeze, Breeze Dark, Oxygen, Graphite, System) |
| `virtdeck/ui/icons.py` | SVG icon registry |
| `virtdeck/ui/notification.py` | Toast notifications |
| `virtdeck/ui/i18n/` | Translation module (tr()), JSON translation files |
| `virtdeck/ui/widgets/` | Widget modules (metrics, pool, tasks, hardware, options, card_list) |
| `virtdeck/ui/api/` | API workers (RRD data, storage content) |
| `tests/harness/` | Fake PVE/PBS API harness for UI tests (in-memory scenes) |
| `virtdeck/ui/console/` | Built-in noVNC console: window, WebSocket bridge (vendored noVNC assets) |
| `virtdeck/provider/` | Data provider seam: `ProxmoxProvider` facade, session with per-host proxy |
| `packaging/virtdeck-win.spec` | PyInstaller spec for Windows build |
| `packaging/virtdeck-installer.nsi` | NSIS multilingual installer script |
| `.github/workflows/ci.yml` | CI: ruff lint on PR/push (Python 3.10/3.11/3.12) |
| `.github/workflows/release.yml` | Release: build deb/rpm/zip/installer, create GitHub release |
| `docs/DEV_PROCESS.md` | Development methodology (workflow, gates, coding rules) |
| `docs/AUDIT_PROCESS.md` | Code audit methodology + audit reports |

## Language switching

The interface language is stored in the app config database (`ui_state` table, key `language`):
- Linux: `~/.config/virtdeck/config.sqlite`
- Windows: `%APPDATA%/virtdeck/config.sqlite`
- macOS: `~/Library/Application Support/virtdeck/config.sqlite`

Supported languages:
- English (en)
- Russian (ru)
- Arabic (ar)
- Chinese Simplified (zh)
- French (fr)
- Spanish (es)

Translations are stored in the `translations` table. To add a new language, insert rows with `(lang, msgid, msgstr)`.

## Third-party software

This project bundles noVNC (vendored, MPL-2.0, unmodified — see
`virtdeck/ui/console/novnc/LICENSE.txt`) and uses several third-party
Python packages (PySide6/LGPL-3.0, proxmoxer/MIT, requests/Apache-2.0,
etc.). Full list with licenses and sources:
[docs/THIRD-PARTY-NOTICES.md](docs/THIRD-PARTY-NOTICES.md).

## License

GNU General Public License v3.0. See `LICENSE` file.

VirtDeck is an unofficial third-party client. It is not affiliated with,
endorsed by, or sponsored by Proxmox Server Solutions GmbH or KDE e.V.
See [docs/THIRD-PARTY-NOTICES.md](docs/THIRD-PARTY-NOTICES.md).
