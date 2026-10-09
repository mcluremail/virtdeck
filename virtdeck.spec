%global pypi_name virtdeck

Name:          virtdeck
Version:       2.11.3
Release:       1%{?dist}
Summary:       Desktop client for Proxmox VE clusters

License:       GPLv3
URL:           https://github.com/mcluremail/virtdeck
Source0:       %{pypi_source}

BuildArch:     noarch
BuildRequires: python3-devel
BuildRequires: python3-setuptools

Requires:      python3
Requires:      python3-pyside6
Recommends:    python3-proxmoxer
Requires:      python3-requests
Requires:      python3-urllib3
Requires:      python3-pyqtgraph
Requires:      python3-cryptography
Requires:      python3-keyring

# noVNC console bridge and remote-viewer console — optional features
Recommends:    python3-websockets
Recommends:    virt-viewer

%description
VirtDeck — desktop client for Proxmox VE cluster monitoring and management.

%prep
%autosetup -n %{pypi_name}-%{version}

%build
%py3_build

%install
%py3_install
install -m 644 -D debian/virtdeck.desktop \
  %{buildroot}%{_datadir}/applications/virtdeck.desktop
for s in 16 24 32 48 64 128 256 512; do
  install -m 644 -D "packaging/icons/hicolor/${s}x${s}/apps/virtdeck.png" \
    "%{buildroot}%{_datadir}/icons/hicolor/${s}x${s}/apps/virtdeck.png"
done

%files
%{python3_sitelib}/virtdeck/
%{python3_sitelib}/virtdeck-*.egg-info/
%{_bindir}/virtdeck
%{_datadir}/applications/virtdeck.desktop
%{_datadir}/icons/hicolor/*/apps/virtdeck.png

%changelog
* Tue Sep 08 2026 Taurus McLure <taurus@mclure.ru> - 2.11.3-1
- Sync version with pyproject (was stuck at 2.3.1).
- Add missing Requires: python3-proxmoxer, python3-keyring, python3-urllib3.
- Move python3-websockets to Recommends — built-in noVNC console is optional,
  the app runs without it (fallback message in console menu).

* Fri Jun 20 2026 Taurus McLure <taurus@mclure.ru> - 1.4.0-1
- Redesign Monitoring tab: 3x2 MetricCard grid (Status/CPU/RAM/Disk/Net/Uptime)
  with progress bars + expanding chart. Replace flat parameter table.
- Hardware tab: section headers (Identity/CPU/Memory/System/Network/Storage)
  with bold values and device type icons (disk/network/iso/vm/hardware).
- Options tab: section headers (OS/Boot/Display/System/Hotplug/Behaviour/Misc)
  with bold values.
- History tab: colored circle status badges (green OK / yellow running /
  red error).
- Host monitoring: HTML-formatted info panel with colored status.
- Fix toast positioning (Qt.Tool -> Qt.ToolTip to prevent WM centering).
- Fix hastate reading from basic (cluster/resources) not detail (status/current).
- Section label i18n in 5 languages (Identity/OS/Display/Behaviour/Misc).

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.3.1-1
- Move export/import from File menu to toolbar. Add Add Server button
  and separators to toolbar. Remove menu bar (not enough items for menu).

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.3.0-1
- Add config export/import (File menu). Encrypted nodes.enc can be
  transferred between computers — solves orphan token accumulation when
  using app on multiple machines. Import merges by host+user.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.2.2-1
- Add PyInstaller spec for Windows build (packaging/virtdeck-win.spec).
- Add build-windows job to GitHub Actions release workflow.
- Release now includes .zip for Windows alongside .deb, .rpm, .whl.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.2.1-1
- Cross-platform config paths: %APPDATA%/virtdeck on Windows,
  ~/Library/Application Support/virtdeck on macOS, XDG on Linux.
- Cross-platform remote-viewer launch: search Program Files on Windows,
  platform-aware install hint in error message.
- Add Windows classifier to pyproject.toml.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.2.0-1
- L3: replace hardcoded column widths with ResizeToContents for data columns
  in host_tabs (2 tables) and vm_pool_widget. Keep Stretch for name columns.
  cluster_tasks_widget keeps Interactive (user-persisted widths).
- L4: remove manual [:50] truncation of disk model string in host_disks_table
  (Stretch column handles display).

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.1.9-1
- L1: setFixedSize -> setMinimumSize on 3 QDialogs (password dialog,
  security dialog, add_server_dialog) — dialogs now resizable for long
  translations and DPI scaling.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.1.8-1
- L6: vm_action_bar setFixedHeight(32) -> setMinimumHeight(32), action buttons
  setFixedHeight(24) -> setMinimumHeight(24) — bar adapts to DPI/font scaling.
- L7: storage_plot_widget setFixedHeight(220) -> setMinimumHeight(220).

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.1.4-1
- i18n: split tr("Serial") into "Serial" (disk serial number) and "Serial port" (display type).
- i18n: translate 6 identity keys (Direct sync, RAM (GiB), Unsafe, VM Generation ID,
  Write back, Write through) in all 5 languages.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.1.3-1
- i18n: add 213 missing Russian translations to ru.json.
- i18n: add 20-21 missing keys to ar/zh/fr/es.json.
- i18n: all 517 unique tr() call sites now have translations in all 5 languages.
- Bump _I18N_VERSION 2 -> 3 to force DB re-seed.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.1.2-1
- Fix QProgressBar OverflowError when storage/host has used>0 but total=0.
- Add safe_pct() helper in _table_utils.py with 0-100 clamping.
- Replace 10 unsafe pct calculation sites in detail_panel/ and 2 in tree_panel.py.
- Add clamping in vm_pool_widget.py for consistency.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.1.1-1
- Post-S3 cleanup: remove unused imports from detail_panel/ package (parse_pve_error,
  save_ui_state, load_ui_state, get_icon, compact_table, set_cell_text, Signal,
  VM_ACTION_BUTTON_LABELS, VM_ACTION_ICONS, QPushButton, QSizePolicy, QHeaderView,
  _fmt_pveversion) across 5 files.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.1.0-1
- S3: decompose detail_panel.py (2509 lines) into detail_panel/ package with 7 modules.
- Tab construction and populate logic extracted into _host_tabs.py, _storage_tabs.py, _vm_tabs.py.
- Static helpers extracted into _table_utils.py, worker management into _worker_manager.py.
- Constants and TabIndex enum in _constants.py. DetailPanel is now a thin coordinator (~300 lines).

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.0.4-1
- Race condition fixes (R1/R2/R3): copy lists before iteration, atomic generation guard in soft_refresh.
- M7: remove duplicate setStyleSheet/setDefaultAlignment calls on datacenter_summary.
- Add missing 'Force stop' translations to ru.json.
- seed_translations: forced re-seed when i18n version changes.

* Fri Jun 19 2026 Taurus McLure <taurus@mclure.ru> - 1.0.3-1
- Move i18n translations from inline Python dicts to external JSON files.

* Sun Jun 07 2026 Taurus McLure <taurus@mclure.ru> - 0.1.2-1
- Clean release without diagnostic logging.

* Sun Jun 07 2026 Taurus McLure <taurus@mclure.ru> - 0.1.1-1
- First public release.