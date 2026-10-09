# VirtDeck

[![CI](https://github.com/mcluremail/virtdeck/actions/workflows/ci.yml/badge.svg)](https://github.com/mcluremail/virtdeck/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mcluremail/virtdeck)](https://github.com/mcluremail/virtdeck/releases)
[![License: GPL-3.0](https://img.shields.io/github/license/mcluremail/virtdeck)](LICENSE)

A fast, native desktop client for Proxmox VE — monitor clusters and hosts, manage virtual machines and containers, browse Proxmox Backup Server backups. Everything in one window, no browser needed.

VirtDeck speaks directly to the PVE API (port 8006) and to PBS (port 8007), and adds what no competitor has: **Fleet Health** — a single report across all your independent clusters: backup compliance, version drift, storage runway and snapshot sprawl.

![VirtDeck](Screenshots/main.png?v=3)

## Highlights

- **Fleet Health (multi-cluster)** — one report across all independent clusters: backup compliance, version drift, storage runway with a 95% confidence interval, snapshot sprawl; an offline cluster degrades to a "data from HH:MM" plate instead of an empty report
- **Full VM/CT lifecycle** — create, clone, migrate, snapshots, bulk power actions with optimistic UI (instant apply, rollback on error)
- **PBS integration** — direct Proxmox Backup Server connection: datastores, snapshots, sync/verify/prune jobs, restore into a new VM or container
- **Command palette (Ctrl+K)** — fuzzy search over every action; the palette and the tree context menu are built from one declarative registry
- **Built-in noVNC console** for QEMU VMs + SPICE support
- **Themes** — Light, exact KDE Breeze / Breeze Dark (24px icons), Oxygen, Graphite, System; plugin API in [docs/THEMES.md](docs/THEMES.md)
- **Security by default** — user-bound API tokens in the system keyring, encrypted config export/import, per-host SSL trust and HTTP(S) proxy
- **6 UI languages** — English, Russian, Arabic, Chinese, French, Spanish

[Full feature list →](docs/FEATURES.md)

## Download

| Platform | Format | Link |
|----------|--------|------|
| Windows | .zip / .exe installer | [Releases](https://github.com/mcluremail/virtdeck/releases) |
| Debian / Ubuntu | .deb | [Releases](https://github.com/mcluremail/virtdeck/releases) |
| Fedora / RHEL | .rpm | [Releases](https://github.com/mcluremail/virtdeck/releases) |
| Any | .tar.gz / .whl | [Releases](https://github.com/mcluremail/virtdeck/releases) |

Latest release: [v3.0.0](https://github.com/mcluremail/virtdeck/releases/tag/v3.0.0)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

## Requirements

- Python 3.10+ (for source install; not needed for Windows .zip or installer)
- PySide6 (full package, incl. WebEngine — for the built-in noVNC console)
- proxmoxer (Debian 12+/Ubuntu 23.04+ have `python3-proxmoxer`; older — via pip)
- requests / urllib3
- pyqtgraph
- keyring — system keyring access (KWallet / GNOME Keyring / Windows Credential Manager)
- cryptography (export/import encrypted config bundle)
- websockets — **optional on Linux**: required only for the built-in noVNC
  console (`pip install websockets`); the app runs fine without it.
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

### From source (any Linux)

```bash
# download and unpack virtdeck-3.0.0.tar.gz (or .whl) from Releases,
# then install the dependencies:
pip install PySide6 proxmoxer requests urllib3 pyqtgraph cryptography keyring
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

# If installed via .deb:
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
