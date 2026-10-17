import json
import logging
import os
import sys
import threading
import time
import traceback
import uuid
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer, Slot
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..backend import (
    BulkVmActionWorker,
    ClusterTasksWorker,
    DeleteVmWorker,
    FetchWorker,
    HostTokenDeleteWorker,
)
from ..backend.events import Event, EventBus
from ..backend.fleet import build_fleet_targets
from ..backend.refresh import RefreshCoordinator
from ..config import (
    export_config,
    import_config,
    load_tasks_cache,
    load_ui_state,
    mark_ambiguous,
    name_key,
    save_config,
    save_tasks_cache,
    save_ui_state,
)
from ..domain import (
    HaGroup,
    NodeRepository,
    NodeStatus,
    PoolRepository,
    StorageRepository,
    VmRepository,
    VmStatus,
)
from ..domain import (
    Node as DomainNode,
)
from ..domain import (
    Pool as DomainPool,
)
from ..domain import (
    Storage as DomainStorage,
)
from ..domain import (
    Task as DomainTask,
)
from ..domain import (
    Vm as DomainVm,
)
from ..domain.bulk import plan_bulk_action
from . import brand, theme
from .detail_panel import DetailPanel
from .fleet_health import FleetHealthDialog
from .i18n import get_language, supported_languages, tr
from .icons import get_icon
from .notification import NotificationManager
from .optimistic import OptimisticVMs
from .search_dialog import GlobalSearchDialog
from .theme import Color
from .tree_panel import TreePanel
from .utils import build_cfg_index
from .vm_actions import VM_ACTION_MESSAGE_LABELS, confirm_vm_action
from .widgets.cluster_tasks_widget import ClusterTasksWidget

logger = logging.getLogger(__name__)

# Maximum number of workers running at once
MAX_WORKERS = 16


def _repo_signature(node_repo, vm_repo, storage_repo):
    """Identity snapshot of all repos — detects structural changes."""
    return (
        frozenset((n.host_name, n.node) for n in node_repo.all()),
        frozenset((v.host_name, v.vmid) for v in vm_repo.all()),
        frozenset((s.host_name, s.node, s.storage) for s in storage_repo.all()),
    )


class MainWindow(QMainWindow):
    def __init__(self, nodes_cfg=None):
        super().__init__()
        self.setWindowTitle("VirtDeck")
        from .icons import init_icons
        init_icons()
        self.setWindowIcon(brand.make_logo_icon(256))
        self.resize(1600, 900)

        theme.load()

        self.nodes_cfg = nodes_cfg or []
        # Audit 4.2, D3: two active representatives of the SAME configured
        # cluster duplicate nodes/VMs and counters — keep the first, drop
        # the duplicates with an explicit notification.
        self._dup_cluster_warnings: list[str] = []
        self.nodes_cfg, dup_dropped = self._dedupe_cluster_cfgs(self.nodes_cfg)
        self._warn_dup_clusters(dup_dropped)
        # Stage 5.1.2: assign in-memory conn_ids where missing and build
        # both indexes (name and conn_id) — see _rebuild_cfg_indexes.
        self._rebuild_cfg_indexes()
        self.all_iso_images = {}
        self.all_ha_groups = {}
        self.all_pools = []

        # Domain repositories (typed, indexed — replace raw dict indexes)
        self._node_repo = NodeRepository()
        self._vm_repo = VmRepository()
        self._storage_repo = StorageRepository()
        self._pool_repo = PoolRepository()
        # Soft-refresh temporary repositories
        self._soft_node_repo = NodeRepository()
        self._soft_vm_repo = VmRepository()
        self._soft_storage_repo = StorageRepository()
        # host_name -> attempt epoch of the soft answer for that host
        self._soft_epochs: dict[str, int] = {}

        self._first_selection_done = False
        self._last_host_statuses = {}
        self._last_vm_statuses = {}
        self._offline_mode = False
        self._offline_ts = None
        # One host/cluster removal at a time (audit 6.3.2a D13).
        self._host_token_del_active = False

        self.tree_panel = TreePanel(self.nodes_cfg)
        self.detail_panel = DetailPanel(self.nodes_cfg)
        self.detail_panel.config_update_result.connect(
            lambda msg: self._notifications.show(msg, error=tr("Error") in msg)
        )
        self.detail_panel.transfer_started.connect(
            lambda key, desc: self.tasks_widget.add_progress_row(key, desc)
        )
        self.detail_panel.transfer_progress.connect(
            lambda key, pct: self.tasks_widget.update_progress_row(key, pct)
        )
        self.detail_panel.transfer_finished.connect(
            lambda key, ok, msg: self.tasks_widget.finish_progress_row(key, ok, msg)
        )
        self.detail_panel.all_tabs_built.connect(self._on_all_tabs_built)

        from .pbs_panel import PbsPanel
        self.pbs_panel = PbsPanel()
        self.pbs_panel.update_nodes_cfg(self.nodes_cfg)
        self.pbs_panel.datastores_loaded.connect(self.tree_panel.set_pbs_datastores)

        self.tree_panel.item_selected.connect(self._on_tree_item_selected)
        self.detail_panel.navigate_requested.connect(self.tree_panel.find_and_select)
        self.detail_panel.vm_clone_requested.connect(self._on_vm_clone)
        self.detail_panel.vm_convert_requested.connect(self._on_vm_convert)

        self.tree_panel.host_remove_requested.connect(self._on_host_remove)
        self.tree_panel.host_token_refresh_requested.connect(self._on_host_token_refresh)
        self.tree_panel.host_trust_ssl_changed.connect(self._on_host_trust_ssl)
        self.tree_panel.vm_create_requested.connect(self._on_vm_create_requested)
        self.tree_panel.vm_delete_requested.connect(self._on_vm_delete_requested)
        self.tree_panel.vm_action_requested.connect(self._on_vm_action_from_tree)
        self.tree_panel.bulk_vm_action_requested.connect(self._on_bulk_vm_action)
        self._palette = None   # M2: command palette, lazy init
        # M0.3: optimistic UI — instant status + rollback on error.
        self._optimistic = OptimisticVMs(
            self._vm_repo, on_change=self._on_optimistic_change
        )
        self.tree_panel.group_move_requested.connect(self._on_group_move)
        self.tree_panel.group_rename_requested.connect(self._on_group_rename)
        self.tree_panel.group_delete_requested.connect(self._on_group_delete)
        self.tree_panel.storage_create_requested.connect(self._on_storage_create)
        self.tree_panel.storage_edit_requested.connect(self._on_storage_edit)
        self.tree_panel.storage_delete_requested.connect(self._on_storage_delete)
        self.tree_panel.cluster_join_requested.connect(self._on_cluster_join)
        self.tree_panel.cluster_create_requested.connect(self._on_cluster_create)
        self.tree_panel.vm_migrate_requested.connect(self._on_vm_migrate)
        self.tree_panel.vm_clone_requested.connect(self._on_vm_clone)
        self.tree_panel.vm_convert_requested.connect(self._on_vm_convert)
        self.tree_panel.vm_clone_from_template_requested.connect(self._on_vm_clone_from_template)
        self.tree_panel.console_requested.connect(self._on_console_from_tree)
        self.tree_panel.novnc_requested.connect(self._on_novnc_from_tree)
        self.tree_panel.vm_ha_add_requested.connect(self._on_vm_ha_add)
        self.tree_panel.vm_ha_remove_requested.connect(self._on_vm_ha_remove)

        self._notifications = NotificationManager(self)
        # Deferred duplicate-cluster warnings (raised before the manager
        # existed in __init__)
        for msg in self._dup_cluster_warnings:
            self._notifications.show(msg, error=True)
        self._dup_cluster_warnings = []

        self._tray = None
        self._tray_state = "ok"
        self._tray_minimize_to_tray = True
        self._soft_had_errors = False
        # host_name -> error text of hosts whose soft worker failed: their
        # previous known-good data is kept, nodes are only flagged ERROR
        self._soft_errors: dict[str, str] = {}
        # U20: auto-refresh pauses when every host fails authorization
        # (expired/revoked token); a manual Refresh un-pauses it.
        self._auto_refresh_paused = False
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._init_tray()

        self.h_splitter = QSplitter(Qt.Horizontal)
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.detail_panel)
        self.right_stack.addWidget(self.pbs_panel)
        self.h_splitter.addWidget(self.tree_panel)
        self.h_splitter.addWidget(self.right_stack)

        self.tasks_widget = ClusterTasksWidget()
        # GAP-11: double-click on a task row -> select the affected object
        self.tasks_widget.navigate_requested.connect(self._on_task_navigate)

        self.v_splitter = QSplitter(Qt.Vertical)
        self.v_splitter.addWidget(self.h_splitter)
        self.v_splitter.addWidget(self.tasks_widget)

        # Restore splitter positions from SQLite
        self._restore_splitter_state()

        # Persist splitter positions on change
        def _save_splitter():
            save_ui_state("splitter_h", json.dumps(self.h_splitter.sizes()))
            save_ui_state("splitter_v", json.dumps(self.v_splitter.sizes()))
        self.h_splitter.splitterMoved.connect(_save_splitter)
        self.v_splitter.splitterMoved.connect(_save_splitter)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.v_splitter)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.status_bar = self.statusBar()
        self.status_label = QLabel("")
        self.status_bar.addPermanentWidget(self.status_label)
        # U8/GAP-4: an explicit "when did the data last arrive" stamp.
        # The status line itself no longer shows a live clock that used
        # to be mistaken for the data update time.
        self._updated_label = QLabel("")
        self._updated_label.setStyleSheet(
            f"color: {Color.TEXT_SEC}; padding-right: 8px;")
        self.status_bar.addPermanentWidget(self._updated_label)

        self._refresh_spinner = QLabel("")
        self._refresh_spinner.setStyleSheet(f"color: {Color.TEXT_SEC}; padding-right: 8px;")
        self._refresh_spinner.setAccessibleName(tr("Refreshing data"))
        self._refresh_spinner.setToolTip(tr("Data refresh in progress"))
        self.status_bar.insertPermanentWidget(0, self._refresh_spinner)

        self._lang_combo = QComboBox()
        self._lang_combo.setMinimumWidth(110)
        # U37: comboboxes of the status bar are named for screen readers
        self._lang_combo.setAccessibleName(tr("Interface language"))
        # A5: the same style source as on re-apply (a duplicated inline
        # QSS used to drift from _status_combo_style).
        self._lang_combo.setStyleSheet(self._status_combo_style())
        self._lang_combo.blockSignals(True)
        current_lang = get_language()
        for code, native_name in sorted(supported_languages().items(), key=lambda x: x[0]):
            self._lang_combo.addItem(native_name, code)
            if code == current_lang:
                self._lang_combo.setCurrentIndex(self._lang_combo.count() - 1)
        self._lang_combo.blockSignals(False)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self.status_bar.insertPermanentWidget(1, self._lang_combo)
        self._build_theme_switcher()
        self._spin_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._spin_idx = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(100)
        self._spin_timer.timeout.connect(self._tick_spinner)
        self._soft_refresh_active = False

        self._workers = set()
        self._tasks_gen = 0
        self._tasks_started = False

        # Hard/soft refresh generations, pending and guards live in the
        # coordinator
        self._refresh = RefreshCoordinator(soft_timeout=90)

        # Event bus (seed v3.0): producers publish, panels subscribe
        self._events = EventBus()

        # Soft refresh state
        # (_soft_had_errors is initialized earlier — before _init_tray, see above)
        self.last_refresh_ts = 0
        self.refresh_interval = 5

        # Restore window state: geometry, maximized, last selected item
        self._restore_window_state()

        self.show()
        self.refresh_data()
        # Stage 5.1.2 §3.2: surface legacy name conflicts once the window
        # is up (deferred so the dialog never blocks construction/tests).
        QTimer.singleShot(0, self._notify_ambiguous)

        self._toolbar = QToolBar()
        self._toolbar.setMovable(False)
        from .icons import base_size

        _tb = base_size()
        self._toolbar.setIconSize(QSize(_tb, _tb))
        self._toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)

        add_action = QAction(get_icon("add"), tr("Add server"), self)
        add_action.setToolTip(tr("Add server") + " (Ctrl+N)")
        add_action.triggered.connect(lambda: self._on_add_server())
        self._toolbar.addAction(add_action)
        self._toolbar_icon_actions = [(add_action, "add")]

        refresh_action = QAction(get_icon("refresh"), tr("Refresh"), self)
        refresh_action.setToolTip(tr("Refresh data") + " (Ctrl+R)")
        refresh_action.triggered.connect(self.refresh_data)
        self._toolbar.addAction(refresh_action)
        self._toolbar_icon_actions.append((refresh_action, "refresh"))

        search_action = QAction(get_icon("search"), tr("Global search"), self)
        search_action.setToolTip(tr("Global search") + " (Ctrl+F)")
        search_action.triggered.connect(self._open_global_search)
        self._toolbar.addAction(search_action)
        self._toolbar_icon_actions.append((search_action, "search"))

        fleet_action = QAction(get_icon("monitor"), tr("Fleet Health"), self)
        fleet_action.setToolTip(
            tr("Fleet Health report across all clusters") + " (Ctrl+Shift+F)")
        fleet_action.triggered.connect(self._open_fleet_health)
        self._toolbar.addAction(fleet_action)
        self._toolbar_icon_actions.append((fleet_action, "monitor"))

        self._toolbar.addSeparator()

        export_action = QAction(get_icon("export"), tr("Export configuration"), self)
        export_action.setToolTip(tr("Export configuration") + " (Ctrl+E)")
        export_action.triggered.connect(self._on_export_config)
        self._toolbar.addAction(export_action)
        self._toolbar_icon_actions.append((export_action, "export"))

        import_action = QAction(get_icon("import"), tr("Import configuration"), self)
        import_action.setToolTip(tr("Import configuration") + " (Ctrl+I)")
        import_action.triggered.connect(self._on_import_config)
        self._toolbar.addAction(import_action)
        self._toolbar_icon_actions.append((import_action, "import"))

        self._toolbar.addSeparator()

        about_action = QAction(get_icon("about"), tr("About"), self)
        about_action.setToolTip(tr("About") + " (F1)")
        about_action.triggered.connect(self._on_about)
        self._toolbar.addAction(about_action)
        self._toolbar_icon_actions.append((about_action, "about"))

        # U37: the tool buttons are icon-only — give them an explicit
        # accessible name (the action text, without the shortcut suffix)
        for action, _kind in self._toolbar_icon_actions:
            btn = self._toolbar.widgetForAction(action)
            if btn is not None:
                btn.setAccessibleName(action.text())

        # A11: the text-only Quit action is gone — it was the only
        # non-icon element in the icon-only toolbar. Quit stays reachable
        # via Ctrl+Q (global.quit spec) and the tray menu.
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Fixed)
        self._toolbar.addWidget(spacer)

        self._brand = brand.make_brand_widget(self)
        self._toolbar.addWidget(self._brand)

        self.addToolBar(self._toolbar)

        # U35: QToolBar is NoFocus by default, so its QToolButtons never
        # entered the Tab chain — Export/Import/About had no keyboard path
        # at all (no shortcut, no menubar). StrongFocus makes each button
        # reachable by Tab and activatable with Space/Enter.
        for tb in self._toolbar.findChildren(QToolButton):
            tb.setFocusPolicy(Qt.StrongFocus)

        # U16: window-level shortcuts are bound from the registry — the
        # single source whose spec.shortcut the palette also displays
        # ("Ctrl+R, F5" expands into two sequences). Del and Ctrl+K stay
        # physical bindings: Del routes through request_delete_current
        # (per-type semantics with confirmations), Ctrl+K is the
        # palette's own meta-action.
        from .action_registry import Selection
        from .action_specs import build_registry
        for spec in build_registry(self).all():
            if not spec.action_id.startswith("global.") or not spec.shortcut:
                continue
            for seq in spec.shortcut.split(","):
                seq = seq.strip()
                if seq:
                    QShortcut(QKeySequence(seq), self,
                              activated=lambda sp=spec: sp.invoke(Selection()))
        QShortcut(QKeySequence("Del"), self, activated=self.tree_panel.request_delete_current)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_command_palette)

        # U35: initial focus belongs to the tree (the primary navigation
        # surface), not to the mode combo that merely starts the Tab chain.
        QTimer.singleShot(0, lambda: self.tree_panel.tree.setFocus(
            Qt.OtherFocusReason))

        # Auto-refresh timer for the main data
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(20000)          # 20 seconds
        self.refresh_timer.timeout.connect(self.soft_refresh)
        self.refresh_timer.start()

        # Check for updates 3 seconds after startup
        QTimer.singleShot(3000, self._check_version)

        # Main thread freeze detector
        self._last_heartbeat = time.time()
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(500)
        self._heartbeat_timer.timeout.connect(self._heartbeat)
        self._heartbeat_timer.start()
        self._closing = False
        # In offscreen/pytest the event loop stalls — the detector gets
        # noisy and a traceback storm degrades test performance.
        if (os.environ.get("QT_QPA_PLATFORM") != "offscreen"
                and "PYTEST_CURRENT_TEST" not in os.environ):
            self._freeze_detector = threading.Thread(
                target=self._detect_freeze, daemon=True, name="freeze-detector")
            self._freeze_detector.start()

        # Cluster tasks refresh timer
        self.tasks_timer = QTimer(self)
        self.tasks_timer.setInterval(60000)            # 60 seconds
        self.tasks_timer.timeout.connect(self.refresh_cluster_tasks)
        self.tasks_timer.start()

        # First task load — started from on_worker_finished once all_nodes is filled
        self._cached_tasks = [DomainTask.from_pve(d) for d in load_tasks_cache()]

        # Offline mode: load cached resources immediately so tree is populated
        # before the first network response arrives
        self._restore_offline_cache()

    def _restore_offline_cache(self):
        """Populate the repos from the offline resource cache.

        Stage 5.1.2: only rows produced by a connection that still exists
        are restored — filtered by conn_id, not by the display name. A
        deleted and re-created connection (same name, new conn_id)
        restores nothing, and legacy rows without conn_id are never
        attached (they cannot be proven to belong to this
        infrastructure).
        """
        from ..config import load_resources_cache
        cached_res, cached_ts = load_resources_cache()
        if cached_res:
            try:
                cluster_name_cache = {}
                valid_conn_ids = {
                    cfg.get("conn_id") for cfg in self.nodes_cfg
                    if not cfg.get("skip", False)
                    and not cfg.get("_ambiguous", False)
                    and cfg.get("type", "pve") != "pbs"
                    and cfg.get("conn_id")
                }
                legacy_rows = 0
                for cfg in self.nodes_cfg:
                    cn = cfg.get("cluster", "") or ""
                    cluster_name_cache[cfg.get("name", "")] = cn
                for n_dict in cached_res.get("nodes", []):
                    cid = n_dict.get("conn_id", "")
                    if cid not in valid_conn_ids:
                        legacy_rows += not cid
                        continue
                    hn = n_dict.get("host_name", "")
                    cn = cluster_name_cache.get(hn, "")
                    ic = n_dict.get("_is_cluster", False)
                    self._node_repo.add(DomainNode.from_pve(n_dict, hn, cn, ic))
                for v_dict in cached_res.get("vms", []):
                    if v_dict.get("conn_id", "") not in valid_conn_ids:
                        legacy_rows += not v_dict.get("conn_id")
                        continue
                    self._vm_repo.add(DomainVm.from_pve(v_dict, v_dict.get("host_name", "")))
                for s_dict in cached_res.get("storages", []):
                    cid = s_dict.get("conn_id", "")
                    if cid not in valid_conn_ids:
                        legacy_rows += not cid
                        continue
                    hn = s_dict.get("host_name", "")
                    cn = cluster_name_cache.get(hn, "")
                    self._storage_repo.add(DomainStorage.from_pve(s_dict, hn, cn))
                if legacy_rows:
                    logger.info(
                        "offline cache: %d row(s) from a previous version "
                        "have no conn_id and were not restored", legacy_rows)
                self.detail_panel.set_lists(
                    self._node_repo.all(), self._vm_repo.all(), self._storage_repo.all(),
                node_repo=self._node_repo, vm_repo=self._vm_repo
                )
                self.tree_panel.update_node_statuses(
                    self._node_repo.all(), self._vm_repo.all(),
                    node_repo=self._node_repo, vm_repo=self._vm_repo,
                )
                self._offline_mode = True
                self._offline_ts = cached_ts
                self._update_status_bar()
            except Exception:
                self._offline_mode = False
                self._offline_ts = None
        else:
            self._offline_mode = False
            self._offline_ts = None

    def _run_worker(self, worker) -> bool:
        """Start a worker in the pool. False — rejected (pool full): the
        worker never starts and never reports, so the caller must not
        count it in its expectations (track_hard/begin_soft)."""
        if len(self._workers) >= MAX_WORKERS:
            try:
                worker.signals.deleteLater()
            except Exception:
                pass
            self._notifications.show(
                tr("Too many concurrent operations. Please wait and try again."),
                error=True,
            )
            return False
        self._workers.add(worker)
        if hasattr(worker.signals, "finished"):
            worker.signals.finished.connect(lambda w=worker: self._discard_worker(w))
        QThreadPool.globalInstance().start(worker)
        return True

    def _discard_worker(self, worker):
        """Removes the worker from _workers and disconnects its signals."""
        self._workers.discard(worker)
        if not worker or not hasattr(worker, "signals"):
            return
        import warnings
        sigs = worker.signals
        for attr in ("finished", "result_ready", "tasks_ready", "tasks_error",
                     "detail_ready", "config_ready", "config_error",
                     "config_updated", "config_update_error",
                     "action_result", "action_error",
                     "console_ready", "console_error",
                     "vm_created", "vm_error", "vm_deleted",
                     "vm_migrated", "vm_cloned",
                     "token_ready", "token_error",
                     "update_available",
                     "ha_resources_ready", "ha_resources_error",
                     "result", "error",
                     "cluster_status_ready", "cluster_status_error"):
            sig = getattr(sigs, attr, None)
            if sig is None:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sig.disconnect()
            except (RuntimeError, TypeError):
                pass

    def _on_about(self):
        from .about_dialog import AboutDialog
        AboutDialog(self).exec()

    def _check_version(self):
        from .. import __version__
        from ..backend import VersionCheckWorker
        worker = VersionCheckWorker(__version__)
        worker.signals.update_available.connect(self._on_update_available)
        self._run_worker(worker)

    def _on_update_available(self, latest_version, release_url):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle(tr("Update available"))
        msg_box.setText(tr(
            "A new version of VirtDeck is available: v{version}"
        ).format(version=latest_version))
        download_btn = msg_box.addButton(tr("Download"), QMessageBox.AcceptRole)
        msg_box.addButton(tr("Later"), QMessageBox.RejectRole)
        msg_box.setDefaultButton(download_btn)
        msg_box.exec()
        if msg_box.clickedButton() == download_btn:
            import webbrowser
            webbrowser.open(release_url)

    def _on_export_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export configuration"), "virtdeck-nodes.enc",
            tr("Encrypted config (*.enc);;All files (*.*)"))
        if not path:
            return
        if export_config(path):
            QMessageBox.information(self, tr("Export"),
                                    tr("Configuration exported to:\n{path}").format(path=path))
        else:
            QMessageBox.warning(self, tr("Export"),
                                 tr("No servers to export. "
                                    "Add at least one server first."))

    def _on_import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Import configuration"), "",
            tr("Encrypted config (*.enc);;All files (*.*)"))
        if not path:
            return
        report: list[str] = []
        merged = import_config(path, merge=True, report=report)
        if merged is None:
            return
        merged, dup_dropped = self._dedupe_cluster_cfgs(merged)
        self.nodes_cfg = merged
        self._rebuild_cfg_indexes()
        self.tree_panel.set_servers(merged)
        self.detail_panel.update_nodes_cfg(merged)
        self.pbs_panel.update_nodes_cfg(merged)
        save_config(self.nodes_cfg)
        self.refresh_data()
        self._warn_dup_clusters(dup_dropped)
        summary = tr("Configuration imported ({count} hosts).").format(
            count=len(merged))
        if report:
            summary += "\n\n" + "\n".join(report[:20])
            if len(report) > 20:
                summary += tr("\n… and {count} more").format(
                    count=len(report) - 20)
        QMessageBox.information(self, tr("Import"), summary)

    # ------------------------------------------------------------
    # Add server
    # ------------------------------------------------------------
    def _on_add_server(self, context=""):
        from .add_server_dialog import AddServerDialog
        dialog = AddServerDialog(
            self, context,
            taken_name_keys={name_key(c.get("name", ""))
                             for c in self.nodes_cfg})
        if dialog.exec() != AddServerDialog.Accepted:
            return
        cfg = dialog.get_config()
        # Flow-level defense (stage 5.1): the dialog checks inline, this
        # check makes the invariant independent of the dialog path.
        if name_key(cfg.get("name", "")) in {
                name_key(c.get("name", "")) for c in self.nodes_cfg}:
            self._notifications.show(
                tr("A connection named «{name}» already exists (name "
                   "comparison ignores case and outer spaces)").format(
                       name=cfg.get("name", "")),
                error=True)
            return
        cfg, dup_dropped = self._dedupe_cluster_cfgs(self.nodes_cfg + [cfg])
        self.nodes_cfg = cfg
        self._rebuild_cfg_indexes()
        self.tree_panel.set_servers(self.nodes_cfg)
        self.detail_panel.update_nodes_cfg(self.nodes_cfg)
        self.pbs_panel.update_nodes_cfg(self.nodes_cfg)
        save_config(self.nodes_cfg)
        self.refresh_data()
        self._warn_dup_clusters(dup_dropped)

    # ------------------------------------------------------------
    # Create VM
    # ------------------------------------------------------------
    def _on_vm_create_requested(self, node_name, host_name):
        from .create_vm_dialog import CreateVmDialog
        dialog = CreateVmDialog(self, nodes=self._node_repo.all(), storages=self._storage_repo.all(),
                                pools=self._pool_repo.for_host(host_name),
                                iso_images=getattr(self, 'all_iso_images', {}),
                                ha_groups=getattr(self, 'all_ha_groups', {}))
        if dialog.exec() != CreateVmDialog.Accepted:
            return
        params = dialog.get_params()
        sel_node = dialog.get_node()
        ha_group = dialog.get_ha_group()

        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self.status_label.setText(tr("Config not found for {}").format(host_name))
            return

        from ..backend import CreateVmWorker
        worker = CreateVmWorker(cfg, sel_node, params, ha_group=ha_group)
        worker.signals.vm_created.connect(lambda msg, w=worker: (
            self._notifications.show(msg),
            self.status_label.setText(msg),
            QTimer.singleShot(1500, self.refresh_data),
            self._discard_worker(w)
        ))
        worker.signals.vm_error.connect(lambda err, w=worker: (
            self._notifications.show(tr("VM creation error: {}").format(err), error=True),
            self.status_label.setText(tr("Error: {}").format(err)),
            self._discard_worker(w)
        ))
        self._run_worker(worker)
        self.status_label.setText(tr("Creating VM..."))

    # ------------------------------------------------------------
    # Storage config CRUD (B4)
    # ------------------------------------------------------------
    def _on_storage_create(self, host_name):
        from .storage_config_dialog import StorageConfigDialog
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self.status_label.setText(tr("Config not found for {}").format(host_name))
            return
        dialog = StorageConfigDialog(parent=self)
        if dialog.exec() != StorageConfigDialog.Accepted:
            return
        params = dialog.get_params()
        params["storage"] = dialog.get_storage_id()
        params["type"] = dialog.get_storage_type()
        from ..backend import StorageConfigSaveWorker
        worker = StorageConfigSaveWorker(cfg, None, params)
        self._run_storage_config_worker(worker)

    def _on_storage_edit(self, host_name, storage):
        from .storage_config_dialog import StorageConfigDialog
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self.status_label.setText(tr("Config not found for {}").format(host_name))
            return
        from ..backend import StorageConfigListWorker
        list_worker = StorageConfigListWorker(cfg)

        def _on_configs(configs, w=list_worker):
            self._discard_worker(w)
            config = next((c for c in configs if c.get("storage") == storage), None)
            if config is None:
                self.status_label.setText(tr("Storage not found: {}").format(storage))
                return
            dialog = StorageConfigDialog(config, parent=self)
            if dialog.exec() != StorageConfigDialog.Accepted:
                return
            from ..backend import StorageConfigSaveWorker
            worker = StorageConfigSaveWorker(cfg, storage, dialog.get_params())
            self._run_storage_config_worker(worker)

        list_worker.signals.result.connect(_on_configs)
        list_worker.signals.error.connect(lambda err, w=list_worker: (
            self._notifications.show(tr("Error: {}").format(err), error=True),
            self._discard_worker(w)
        ))
        self._run_worker(list_worker)

    def _on_storage_delete(self, host_name, storage):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, tr("Delete storage"),
            tr("Delete storage {name}?").format(name=storage),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self.status_label.setText(tr("Config not found for {}").format(host_name))
            return
        from ..backend import StorageConfigDeleteWorker
        worker = StorageConfigDeleteWorker(cfg, storage)
        self._run_storage_config_worker(worker)

    def _run_storage_config_worker(self, worker):
        worker.signals.result.connect(lambda msg, w=worker: (
            self._notifications.show(msg),
            self.status_label.setText(msg),
            QTimer.singleShot(1500, self.refresh_data),
            self._discard_worker(w)
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            self._notifications.show(tr("Error: {}").format(err), error=True),
            self.status_label.setText(tr("Error: {}").format(err)),
            self._discard_worker(w)
        ))
        self._run_worker(worker)
        self.status_label.setText(tr("Working..."))

    def _on_cluster_join(self, cluster_name):
        from .cluster_join_dialog import ClusterJoinDialog
        # Candidates are the actual cfg dicts from nodes_cfg: the worker
        # needs full credentials, and _mark_joinee mutates this dict in place.
        candidates = [
            c for c in self.nodes_cfg
            if c.get("cluster") != cluster_name
            and c.get("type") != "pbs" and not c.get("skip")
        ]
        if not candidates:
            self._notifications.show(
                tr("No node available to add to the cluster"), error=True)
            return
        peer = next(
            (c for c in self.nodes_cfg if c.get("cluster") == cluster_name
             and c.get("type") != "pbs"), None)
        dialog = ClusterJoinDialog(
            candidates, cluster_name, peer_host=(peer or {}).get("host", ""),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        params = dialog.get_params()
        from ..backend import ClusterJoinWorker
        worker = ClusterJoinWorker(
            params["cfg"], params["hostname"], params["password"],
            fingerprint=params["fingerprint"], link0=params["link0"],
            votes=params["votes"],
        )
        worker.signals.result.connect(lambda msg, w=worker: (
            self._notifications.show(msg),
            self.status_label.setText(msg),
            self._mark_joinee(params["cfg"], cluster_name),
            QTimer.singleShot(3000, self.refresh_data),
            self._discard_worker(w)
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            self._notifications.show(tr("Error: {}").format(err), error=True),
            self.status_label.setText(tr("Error: {}").format(err)),
            self._discard_worker(w)
        ))
        self._run_worker(worker)
        self.status_label.setText(
            tr("Adding node to cluster (this may take several minutes)..."))

    def _mark_joinee(self, cfg, cluster_name):
        cfg["cluster"] = cluster_name
        cfg.pop("cluster_rep", None)
        self._persist_cfg_views()

    def _on_cluster_create(self, host_name):
        cfg = self._cfg_by_name.get(host_name)
        if cfg is None:
            return
        from .cluster_create_dialog import ClusterCreateDialog
        dialog = ClusterCreateDialog(host_name, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        params = dialog.get_params()
        from ..backend import ClusterCreateWorker
        worker = ClusterCreateWorker(
            cfg, params["clustername"], link0=params["link0"])
        worker.signals.result.connect(lambda msg, w=worker: (
            self._notifications.show(msg),
            self.status_label.setText(msg),
            self._mark_cluster_creator(cfg, params["clustername"]),
            QTimer.singleShot(3000, self.refresh_data),
            self._discard_worker(w)
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            self._notifications.show(tr("Error: {}").format(err), error=True),
            self.status_label.setText(tr("Error: {}").format(err)),
            self._discard_worker(w)
        ))
        self._run_worker(worker)
        self.status_label.setText(tr("Working..."))

    def _mark_cluster_creator(self, cfg, cluster_name):
        cfg["cluster"] = cluster_name
        cfg["cluster_rep"] = True
        self._persist_cfg_views()

    def _persist_cfg_views(self):
        save_config(self.nodes_cfg)
        self.tree_panel.set_servers(self.nodes_cfg)
        self.detail_panel.update_nodes_cfg(self.nodes_cfg)
        self.pbs_panel.update_nodes_cfg(self.nodes_cfg)

    # ------------------------------------------------------------
    # Delete VM
    # ------------------------------------------------------------
    def _on_vm_delete_requested(self, host_name, node, vmid):
        # Find the VM by vmid + host_name
        vm = self._vm_repo.get(host_name, vmid)
        vm_name = vm.name if vm else f"VM {vmid}"
        vm_status = vm.status_value if vm else ""
        vm_type = vm.vm_type.value if vm else "qemu"
        is_running = vm_status == "running"

        # Find the host config
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return

        # Confirmation dialog
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Delete VM"))
        # minimum instead of setFixedSize: in locales with long translations
        # the wrapped text and checkboxes didn't fit into 240px of height
        dlg.setMinimumWidth(480)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        warning = QLabel(
            f"<b>{tr('VM')} «{vm_name}» (VMID: {vmid})</b> {tr('on node')} <b>{node}</b>"
            "<br><br>"
            f"<span style='color:{Color.DANGER_SOLID};'>{tr('This action is irreversible.')} "
            f"{tr('All VM disks will be deleted.')}</span>"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        if is_running:
            run_warning = QLabel(
                f"<span style='color:{Color.DANGER_SOLID}; font-weight:bold;'>{tr('VM is running!')}</span>"
                f"<br>{tr('It will be forcibly stopped and deleted.')}"
            )
            run_warning.setWordWrap(True)
            layout.addWidget(run_warning)

        confirm_check = QCheckBox(tr("I confirm deletion"))
        layout.addWidget(confirm_check)

        # DELIGHT-5: purge also removes the guest from HA resources and
        # backup jobs — destructive enough to require an explicit opt-in
        # (owner decision: safe default; re-check = one line if disliked)
        purge_check = QCheckBox(tr("Purge from HA resources and backup jobs"))
        purge_check.setChecked(False)
        layout.addWidget(purge_check)

        if is_running:
            force_check = QCheckBox(tr("Force stop and delete"))
            force_check.setStyleSheet(f"color: {Color.DANGER_SOLID};")
            layout.addWidget(force_check)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        delete_btn = QPushButton(tr("Delete"))
        delete_btn.setMinimumWidth(120)
        delete_btn.setObjectName("dangerBtn")
        delete_btn.setEnabled(False)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setDefault(True)

        if is_running:
            confirm_check.toggled.connect(
                lambda checked: delete_btn.setEnabled(checked and force_check.isChecked()))
            force_check.toggled.connect(
                lambda checked: delete_btn.setEnabled(checked and confirm_check.isChecked()))
        else:
            confirm_check.toggled.connect(delete_btn.setEnabled)
        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        cancel_btn.clicked.connect(dlg.reject)

        confirmed = [False]
        def do_delete():
            confirmed[0] = True
            dlg.accept()
        delete_btn.clicked.connect(do_delete)

        dlg.exec()
        if not confirmed[0]:
            return

        worker = DeleteVmWorker(cfg, node, vmid, vm_type,
                                purge=purge_check.isChecked())
        worker.signals.vm_deleted.connect(lambda msg, w=worker: (
            self._notifications.show(msg),
            self.status_label.setText(msg),
            QTimer.singleShot(1500, self.refresh_data),
            self._discard_worker(w)
        ))
        worker.signals.vm_error.connect(lambda err, w=worker: (
            self._notifications.show(tr("VM deletion error: {}").format(err), error=True),
            self.status_label.setText(tr("Error: {}").format(err)),
            self._discard_worker(w)
        ))
        self._run_worker(worker)
        self.status_label.setText(tr("Deleting VM {}...").format(vmid))

    def _confirm_delete(self, text):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Delete"))
        # minimum instead of setFixedSize: long confirmations in some locales
        # got clipped to a single line without wrapping
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        msg = QLabel(text)
        msg.setWordWrap(True)
        layout.addWidget(msg)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        yes_btn = QPushButton(tr("Yes"))
        yes_btn.setMinimumWidth(80)
        no_btn = QPushButton(tr("No"))
        no_btn.setMinimumWidth(80)
        no_btn.setDefault(True)
        btn_layout.addWidget(yes_btn)
        btn_layout.addWidget(no_btn)
        layout.addLayout(btn_layout)
        result = [False]
        yes_btn.clicked.connect(lambda: (result.__setitem__(0, True), dlg.accept()))
        no_btn.clicked.connect(dlg.reject)
        dlg.exec()
        return result[0]

    def _on_optimistic_change(self):
        self.tree_panel.set_pending_vm_keys(self._optimistic.pending_keys())

    def _on_vm_action_from_tree(self, host_name, node, vmid, action):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        vm = self._vm_repo.get(host_name, vmid)
        if vm and vm.template:
            self._notifications.show(tr("Lifecycle actions are not available for templates"), error=True)
            return
        # GAP-6: a second click while the first task is still in flight
        # would send a duplicate worker that PVE rejects with a confusing
        # "already running" error. Block for the duration of the flight.
        if self._optimistic.pending_action(host_name, vmid) is not None:
            self._notifications.show(
                tr("An action for VM {vmid} is already in progress").format(
                    vmid=vmid))
            return
        vm_type = (vm.vm_type.value if vm else "qemu")
        if not confirm_vm_action(action, vmid, parent=self):
            return
        # M0.3: apply the optimistic status right away, confirm on reply.
        self._optimistic.apply(host_name, vmid, action)
        from ..backend import VmActionWorker
        worker = VmActionWorker(cfg, node, vmid, vm_type, action)
        worker.signals.action_result.connect(lambda msg: (
            self._optimistic.confirm(host_name, vmid),
            self._notifications.show(msg),
            self.refresh_data()
        ))
        worker.signals.action_error.connect(lambda err: (
            self._optimistic.rollback(host_name, vmid),
            self._notifications.show(tr("Action error: {}").format(err), error=True)
        ))
        if not self._run_worker(worker):
            # Pool full: the worker never starts and never reports — undo
            # the optimistic status so the tree does not show a phantom
            # pending state (audit 6.3.2a D6).
            self._optimistic.rollback(host_name, vmid)
            return

    def _on_bulk_vm_action(self, vm_keys, action):
        plan = plan_bulk_action(vm_keys, self._vm_repo, set(self._cfg_by_name.keys()))
        if plan.skipped_count:
            self._notifications.show(
                tr("Skipped templates and unavailable VMs: {n}").format(n=plan.skipped_count))
        if not plan.targets:
            self._notifications.show(tr("No VMs available"), error=True)
            return
        action_label = VM_ACTION_MESSAGE_LABELS.get(action, action)
        vmids = ", ".join(str(t.vmid) for t in plan.targets[:20])
        if len(plan.targets) > 20:
            vmids += "..."
        box = QMessageBox(self)
        if action in ("stop", "reset", "shutdown", "reboot"):
            box.setIcon(QMessageBox.Warning)
        else:
            box.setIcon(QMessageBox.Question)
        box.setWindowTitle(action_label)
        box.setText(tr("Apply {action} to {n} VMs?").format(
            action=action_label, n=len(plan.targets)))
        box.setInformativeText(vmids)
        yes_btn = box.addButton(tr("Yes"), QMessageBox.YesRole)
        box.addButton(tr("No"), QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is not yes_btn:
            return
        targets = [
            {"host_cfg": self._cfg_by_name[t.host_name], "node": t.node,
             "vmid": t.vmid, "vm_type": t.vm_type}
            for t in plan.targets
        ]
        total = len(targets)
        progress = QProgressDialog(
            tr("Bulk operation: {done}/{total} — VM {vmid}...").format(
                done=0, total=total, vmid=targets[0]["vmid"]),
            tr("Cancel"), 0, total, self)
        progress.setWindowTitle(action_label)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        stats = {"ok": 0, "fail": 0}
        worker = BulkVmActionWorker(targets, action)

        def on_progress(done, _total, vmid):
            progress.setLabelText(
                tr("Bulk operation: {done}/{total} — VM {vmid}...").format(
                    done=done, total=total, vmid=vmid))
            progress.setValue(done)

        def on_vm_done(_vmid, ok, _msg):
            stats["ok" if ok else "fail"] += 1

        def on_finished():
            progress.setValue(total)
            if worker.was_cancelled:
                self._notifications.show(tr("Operation cancelled"), error=True)
            self._notifications.show(
                tr("Bulk operation completed: {ok} ok, {failed} failed").format(
                    ok=stats["ok"], failed=stats["fail"]))
            self.refresh_data()

        worker.signals.progress.connect(on_progress)
        worker.signals.vm_done.connect(on_vm_done)
        worker.signals.finished.connect(on_finished)
        progress.canceled.connect(worker.cancel)
        if not self._run_worker(worker):
            # Pool full: no progress/vm_done/finished will ever arrive —
            # close the dialog instead of freezing it (audit 6.3.2a D6).
            progress.cancel()
            return

    # ------------------------------------------------------------
    # Server groups (B16)
    def _on_group_move(self, kind, name, group):
        if kind == "host":
            names = [name]
        else:
            names = [c.get("name", "") for c in self.nodes_cfg if c.get("cluster") == name]
        for n in names:
            cfg = self._cfg_by_name.get(n)
            if cfg is None:
                continue
            if group:
                cfg["group"] = group
            else:
                cfg.pop("group", None)
        save_config(self.nodes_cfg)
        self.tree_panel.set_servers(self.nodes_cfg)
        self.detail_panel.update_nodes_cfg(self.nodes_cfg)
        self.pbs_panel.update_nodes_cfg(self.nodes_cfg)

    def _on_group_rename(self, old_name, new_name):
        for cfg in self.nodes_cfg:
            if cfg.get("group") == old_name:
                cfg["group"] = new_name
        save_config(self.nodes_cfg)
        self.tree_panel.set_servers(self.nodes_cfg)

    def _on_group_delete(self, group_name):
        for cfg in self.nodes_cfg:
            if cfg.get("group") == group_name:
                cfg.pop("group", None)
        save_config(self.nodes_cfg)
        self.tree_panel.set_servers(self.nodes_cfg)

    def _on_console_from_tree(self, host_name, node, vmid):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        vm = self._vm_repo.get(host_name, vmid)
        vm_type = (vm.vm_type.value if vm else "qemu")
        from ..backend import VmConsoleWorker
        worker = VmConsoleWorker(cfg, node, vmid, vm_type)
        worker.signals.console_ready.connect(lambda msg: self._notifications.show(msg))
        worker.signals.console_error.connect(lambda err: self._notifications.show(err, error=True))
        self._run_worker(worker)

    def _on_novnc_from_tree(self, host_name, node, vmid):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        vm = self._vm_repo.get(host_name, vmid)
        vm_type = (vm.vm_type.value if vm else "qemu")
        from ..backend import NoVncWorker
        worker = NoVncWorker(cfg, node, vmid, vm_type)
        worker.signals.ready.connect(lambda ws_url, ticket: self._open_novnc(cfg, node, vmid, vm_type, ws_url, ticket))
        worker.signals.error.connect(lambda err: self._notifications.show(err, error=True))
        self._run_worker(worker)

    def _open_novnc(self, cfg, node, vmid, vm_type, ws_url, ticket):
        from .console.window import NoVncWindow
        try:
            NoVncWindow.open_console(cfg, node, vmid, vm_type, ws_url, ticket, parent=self)
        except RuntimeError as e:
            self._notifications.show(str(e), error=True)

    def _get_cluster_nodes(self, host_name, current_node):
        return [n for n in self._node_repo.get_by_host(host_name)
                if n.node != current_node]

    def _on_vm_migrate(self, host_name, node, vmid):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        vm = self._vm_repo.get(host_name, vmid)
        if vm and vm.template:
            self._notifications.show(tr("Migration is not available for templates"), error=True)
            return
        vm_info = {
            "name": vm.name if vm else "",
            "vmid": vmid,
            "type": vm.vm_type.value if vm else "qemu",
            "node": node,
        }
        cluster_nodes = self._get_cluster_nodes(host_name, node)
        from .migrate_vm_dialog import MigrateVMDialog
        dialog = MigrateVMDialog(self, vm_info=vm_info,
                                 cluster_nodes=cluster_nodes,
                                 current_node=node)
        if dialog.exec() != MigrateVMDialog.Accepted:
            return
        target = dialog.get_target()
        if not target:
            return
        vm_type = vm_info["type"]
        with_local_disks = dialog.get_with_local_disks()
        running = bool(vm and vm.status_value == "running")
        from ..backend import MigrateVmWorker
        worker = MigrateVmWorker(cfg, node, vmid, vm_type, target,
                                 with_local_disks=with_local_disks,
                                 running=running)
        worker.signals.vm_migrated.connect(lambda msg: (
            self._notifications.show(msg),
            self.status_label.setText(msg),
            QTimer.singleShot(2000, self.refresh_data)
        ))
        worker.signals.vm_error.connect(lambda err: (
            self._notifications.show(tr("Migration error: {}").format(err), error=True),
            self.status_label.setText(tr("Error: {}").format(err))
        ))
        self._run_worker(worker)
        self.status_label.setText(tr("Migrating VM {vmid}...").format(vmid=vmid))

    def _on_vm_clone(self, host_name, node, vmid):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        vm = self._vm_repo.get(host_name, vmid)
        vm_info = {
            "name": vm.name if vm else "",
            "vmid": vmid,
            "type": vm.vm_type.value if vm else "qemu",
            "node": node,
        }
        cluster_nodes = self._get_cluster_nodes(host_name, node)
        node_storages = self._storage_repo.filter_by_host(host_name, node)
        from .clone_vm_dialog import CloneVMDialog
        dialog = CloneVMDialog(self, vm_info=vm_info,
                               cluster_nodes=cluster_nodes,
                               current_node=node,
                               storages=node_storages)
        if dialog.exec() != CloneVMDialog.Accepted:
            return
        params = dialog.get_params()
        vm_type = vm_info["type"]
        from ..backend import CloneVmWorker
        worker = CloneVmWorker(cfg, node, vmid, vm_type, params)
        worker.signals.vm_cloned.connect(lambda msg: (
            self._notifications.show(msg),
            self.status_label.setText(msg),
            QTimer.singleShot(2000, self.refresh_data)
        ))
        worker.signals.vm_error.connect(lambda err: (
            self._notifications.show(tr("Clone error: {}").format(err), error=True),
            self.status_label.setText(tr("Error: {}").format(err))
        ))
        self._run_worker(worker)
        self.status_label.setText(tr("Cloning VM {vmid}...").format(vmid=vmid))

    def _on_vm_clone_from_template(self, node, host_name):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        templates = [vm for vm in self._vm_repo.all()
                     if vm.template and vm.host_name == host_name]
        if not templates:
            return
        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QLabel,
            QVBoxLayout,
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Clone from Template"))
        dlg.setMinimumWidth(350)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        tmpl_combo = QComboBox()
        for vm in sorted(templates, key=lambda v: v.vmid):
            name = vm.name or f"VM {vm.vmid or '?'}"
            vmid = vm.vmid
            node_name = vm.node or node
            label = f"{name} ({vmid}) [{node_name}]"
            tmpl_combo.addItem(label, vmid)
        form.addRow(QLabel(tr("Template:")), tmpl_combo)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        vmid = tmpl_combo.currentData()
        if not vmid:
            return
        self._on_vm_clone(host_name, node, vmid)

    def _on_vm_convert(self, host_name, node, vmid, direction):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        vm = self._vm_repo.get(host_name, vmid)
        if direction == "to_template":
            if vm and vm.status_value == "running":
                self._notifications.show(
                    tr("VM must be stopped before converting to template"), error=True)
                return
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox(QMessageBox.Question, tr("Confirm"),
                             tr("Convert VM {vmid} to template? The VM must be stopped. This action can be reversed.")
                             .format(vmid=vmid),
                             QMessageBox.Yes | QMessageBox.No, parent=self)
            if msg.exec() != QMessageBox.Yes:
                return
            from ..backend import ConvertToTemplateWorker
            worker = ConvertToTemplateWorker(cfg, node, vmid)
            worker.signals.result.connect(lambda m: (
                self._notifications.show(m),
                self.status_label.setText(m),
                QTimer.singleShot(2000, self.refresh_data)
            ))
            worker.signals.error.connect(lambda e: (
                self._notifications.show(tr("Convert error: {}").format(e), error=True),
                self.status_label.setText(tr("Error: {}").format(e))
            ))
            self._run_worker(worker)
            self.status_label.setText(tr("Converting VM {vmid} to template...").format(vmid=vmid))
        elif direction == "to_vm":
            vm = self._vm_repo.get(host_name, vmid)
            vm_type = vm.vm_type.value if vm else "qemu"
            if vm_type != "qemu":
                self._notifications.show(
                    tr("Converting a container template back to a container "
                       "is not supported"), error=True)
                return
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox(QMessageBox.Warning, tr("Confirm"),
                             tr("Convert template {vmid} to VM?").format(vmid=vmid),
                             QMessageBox.Yes | QMessageBox.No, parent=self)
            # the reverse conversion is not a supported PVE operation:
            # PUT config template=0 just clears the flag (audit D6)
            msg.setInformativeText(tr(
                "PVE does not officially support this operation: the "
                "template flag is silently cleared and volumes remain "
                "base volumes — linked clones may break."))
            if msg.exec() != QMessageBox.Yes:
                return
            from ..backend import ConvertToVmWorker
            worker = ConvertToVmWorker(cfg, node, vmid)
            worker.signals.result.connect(lambda m: (
                self._notifications.show(m),
                self.status_label.setText(m),
                QTimer.singleShot(2000, self.refresh_data)
            ))
            worker.signals.error.connect(lambda e: (
                self._notifications.show(tr("Convert error: {}").format(e), error=True),
                self.status_label.setText(tr("Error: {}").format(e))
            ))
            self._run_worker(worker)
            self.status_label.setText(tr("Converting template {vmid} to VM...").format(vmid=vmid))

    def _on_vm_ha_add(self, host_name, node, vmid):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        if not cfg.get("cluster"):
            self._notifications.show(tr("HA is only available for cluster hosts"), error=True)
            return
        ha_groups_raw = self.all_ha_groups.get(host_name, [])
        ha_group_names = []
        for g in ha_groups_raw:
            if g.group:
                ha_group_names.append(g.group)
        if not ha_group_names:
            self._notifications.show(tr("No HA groups available"), error=True)
            return
        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QFormLayout,
            QHBoxLayout,
            QPushButton,
            QSpinBox,
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Add VM {vmid} to HA").format(vmid=vmid))
        dlg.setMinimumWidth(380)
        layout = QFormLayout(dlg)
        group_combo = QComboBox()
        for g in sorted(set(ha_group_names)):
            group_combo.addItem(g, g)
        layout.addRow(tr("HA group:"), group_combo)
        state_combo = QComboBox()
        state_combo.addItem(tr("Default"), "default")
        state_combo.addItem(tr("Started"), "started")
        state_combo.addItem(tr("Stopped"), "stopped")
        layout.addRow(tr("State:"), state_combo)
        max_restart_spin = QSpinBox()
        max_restart_spin.setRange(0, 10)
        max_restart_spin.setValue(1)
        layout.addRow(tr("Max restart:"), max_restart_spin)
        max_relocate_spin = QSpinBox()
        max_relocate_spin.setRange(0, 10)
        max_relocate_spin.setValue(1)
        layout.addRow(tr("Max relocate:"), max_relocate_spin)
        btns = QHBoxLayout()
        ok_btn = QPushButton(tr("Add"))
        cancel_btn = QPushButton(tr("Cancel"))
        btns.addStretch()
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addRow(btns)
        cancel_btn.clicked.connect(dlg.reject)
        ok_btn.clicked.connect(dlg.accept)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        group = group_combo.currentData()
        state = state_combo.currentData()
        max_restart = max_restart_spin.value()
        max_relocate = max_relocate_spin.value()
        from ..backend import HaResourceAddWorker
        worker = HaResourceAddWorker(
            cfg, f"vm:{vmid}", group, state=state,
            max_restart=max_restart, max_relocate=max_relocate,
        )
        worker.signals.result.connect(lambda m: (
            self._notifications.show(m),
            self.status_label.setText(m),
        ))
        worker.signals.error.connect(lambda e: (
            self._notifications.show(tr("HA error: {}").format(e), error=True),
            self.status_label.setText(tr("Error: {}").format(e)),
        ))
        self._run_worker(worker)
        self.status_label.setText(tr("Adding VM {vmid} to HA...").format(vmid=vmid))

    def _on_vm_ha_remove(self, host_name, node, vmid):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            self._notifications.show(tr("Config not found for {}").format(host_name), error=True)
            return
        from PySide6.QtWidgets import QMessageBox
        ret = QMessageBox.question(
            self, tr("Remove from HA"),
            tr("Remove VM {vmid} from HA?").format(vmid=vmid),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        from ..backend import HaResourceDeleteWorker
        worker = HaResourceDeleteWorker(cfg, f"vm:{vmid}")
        worker.signals.result.connect(lambda m: (
            self._notifications.show(m),
            self.status_label.setText(m),
        ))
        worker.signals.error.connect(lambda e: (
            self._notifications.show(tr("HA error: {}").format(e), error=True),
            self.status_label.setText(tr("Error: {}").format(e)),
        ))
        self._run_worker(worker)
        self.status_label.setText(tr("Removing VM {vmid} from HA...").format(vmid=vmid))

    def _on_host_remove(self, item_type, item_name):
        if item_type == "host":
            text = tr("Remove host «{}» from configuration?").format(item_name)
            matched = [c for c in self.nodes_cfg if c.get("name") == item_name]
        elif item_type == "cluster":
            if not item_name:
                return
            count = sum(1 for c in self.nodes_cfg if c.get("cluster") == item_name)
            text = tr("Remove cluster «{name}» ({count} records) from configuration?").format(name=item_name, count=count)
            matched = [c for c in self.nodes_cfg if c.get("cluster") == item_name]
        else:
            return
        if not self._confirm_delete(text):
            return
        if self._host_token_del_active:
            # One removal at a time (audit 6.3.2a D13): the same token must
            # not be deleted twice in parallel, and two async removals would
            # race on nodes_cfg.
            self._notifications.show(
                tr("Too many concurrent operations. Please wait and try again."),
                error=True)
            return
        worker = HostTokenDeleteWorker(matched)
        self._host_token_del_active = True
        worker.signals.delete_result.connect(
            lambda failed: self._finish_host_removal(matched, failed))
        worker.signals.finished.connect(
            lambda: setattr(self, "_host_token_del_active", False))
        if not self._run_worker(worker):
            self._host_token_del_active = False
            return

    def _finish_host_removal(self, matched, failed_names):
        """Applies the host/cluster removal after the token deletion
        worker reports back (runs in the GUI thread via the signal)."""
        if failed_names:
            self._notifications.show(
                tr("Failed to delete tokens: {}. Configuration cleared.").format(", ".join(failed_names)),
                error=True
            )
        self.nodes_cfg = [c for c in self.nodes_cfg if c not in matched]
        self._rebuild_cfg_indexes()
        self.tree_panel.set_servers(self.nodes_cfg)
        self.detail_panel.update_nodes_cfg(self.nodes_cfg)
        self.pbs_panel.update_nodes_cfg(self.nodes_cfg)
        save_config(self.nodes_cfg)
        from ..config import delete_node_tokens
        delete_node_tokens([c.get("name", "") for c in matched])
        self.refresh_data()

    def _on_host_token_refresh(self, host_name):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            return
        if cfg.get("_ambiguous"):
            # Stage 5.1.2 §3.1: token operations are excluded for
            # conflicting connections — resolve the name conflict first.
            self._notifications.show(
                tr("Resolve the name conflict for «{name}» before "
                   "refreshing its token").format(name=host_name),
                error=True)
            return
        from .add_server_dialog import AddServerDialog
        dialog = AddServerDialog(self, "reconnect")
        dialog.setWindowTitle(tr("Refresh token — {}").format(host_name))
        dialog.host_input.setText(cfg.get("host", ""))
        dialog.host_input.setEnabled(False)
        dialog.user_input.setText(cfg.get("user", "root@pam"))
        dialog.trust_ssl_cb.setChecked(bool(cfg.get("trust_ssl", False)))
        dialog.proxy_input.setText(str(cfg.get("proxy") or ""))
        if dialog.exec() != AddServerDialog.Accepted:
            return
        new_cfg = dialog.get_config()
        idx = next((i for i, c in enumerate(self.nodes_cfg) if c.get("name") == host_name), None)
        if idx is not None:
            # Stage 5.1.2 §6: the dialog output must not REBUILD the
            # connection from a short field list — start from the current
            # cfg and override only what the dialog actually collected.
            # This preserves conn_id, skip, group, type, port, proxy and
            # any other option the dialog does not carry.
            merged = dict(self.nodes_cfg[idx])
            for k, v in new_cfg.items():
                if k != "conn_id":
                    merged[k] = v
            merged["name"] = host_name
            merged["host"] = cfg["host"]
            merged["cluster"] = cfg.get("cluster", False)
            if cfg.get("cluster_rep"):
                merged["cluster_rep"] = True
            self.nodes_cfg[idx] = merged
            self._cfg_by_name[host_name] = merged
            if merged.get("conn_id"):
                self._cfg_by_conn[merged["conn_id"]] = merged
        self.tree_panel.set_servers(self.nodes_cfg)
        self.detail_panel.update_nodes_cfg(self.nodes_cfg)
        self.pbs_panel.update_nodes_cfg(self.nodes_cfg)
        save_config(self.nodes_cfg)
        self.refresh_data()

    def _on_host_trust_ssl(self, host_name, trust_ssl):
        cfg = self._cfg_by_name.get(host_name)
        if not cfg:
            return
        if cfg.get("_ambiguous"):
            # Stage 5.1.2 §3.1: token/credential operations are excluded
            # for conflicting connections — resolve the conflict first.
            self._notifications.show(
                tr("Resolve the name conflict for «{name}» before "
                   "changing its certificate trust").format(name=host_name),
                error=True)
            return
        cfg["trust_ssl"] = bool(trust_ssl)
        save_config(self.nodes_cfg)
        self.tree_panel.set_servers(self.nodes_cfg)
        self.refresh_data()

    def _open_command_palette(self):
        """M2: command palette (Ctrl+K) over the action registry."""
        if self._palette is None:
            from .action_specs import build_registry
            from .command_palette import CommandPalette
            self._palette = CommandPalette(
                build_registry(self), self.tree_panel.current_selection, self,
            )
        self._palette.open_for()

    def _open_global_search(self):
        """Open the global search dialog and jump to the chosen object."""
        dlg = GlobalSearchDialog(
            lambda: (self._node_repo, self._vm_repo, self._storage_repo, self._pool_repo),
            self,
        )
        dlg.object_selected.connect(self.tree_panel.reveal_key)
        dlg.exec()

    def _open_fleet_health(self):
        """Fleet Health: summary report across all fleet clusters (M4)."""
        dlg = FleetHealthDialog(
            build_fleet_targets(self.nodes_cfg), self,
            pbs_cfgs=[c for c in self.nodes_cfg
                      if c.get("type") == "pbs" and not c.get("skip")])
        dlg.object_selected.connect(self.tree_panel.reveal_key)
        dlg.exec()

    def refresh_data(self):
        # U20: a manual (or programmatic) refresh is an explicit retry —
        # re-enable the auto-refresh timer paused by an auth failure.
        if self._auto_refresh_paused:
            self._auto_refresh_paused = False
            self.refresh_timer.start()
            self._update_status_bar()
        # Stage 5.1.2: sync the indexes with the current nodes_cfg before
        # anything consumes them (worker filters, result gates).
        self._rebuild_cfg_indexes()
        # Cancel all pending soft_refresh — their results are stale
        self._refresh.reset_soft()
        self._soft_refresh_active = False
        self._soft_had_errors = False
        self._soft_node_repo.clear()
        self._soft_vm_repo.clear()
        self._soft_storage_repo.clear()
        self._spin_timer.stop()
        self._refresh_spinner.setText("")

        # Save the selection and tab (to restore them after the refresh)
        current_key = self.tree_panel.get_current_item_key()
        if current_key is not None:
            self._saved_key = current_key
        current_tab = self.detail_panel.tabs.currentIndex()
        if current_tab is not None:
            self._saved_tab = current_tab
        current_type = self.detail_panel.current_obj_type
        if current_type is not None:
            self._saved_obj_type = current_type

        self.detail_panel.all_nodes.clear()
        self.detail_panel.all_vms.clear()
        self.detail_panel.all_storages.clear()
        self.all_iso_images.clear()
        self.all_pools.clear()
        self._first_selection_done = False
        self._tasks_started = False
        self._soft_errors.clear()
        self._soft_epochs.clear()
        # Repositories are NOT cleared here (audit 4.1): each worker
        # replaces its own host's snapshot on "ok", so a host whose worker
        # is rejected or fails keeps its last known-good data.  Only hosts
        # that left the configuration are dropped.
        # Stage 5.1.2: ambiguous entries (legacy name conflicts) are
        # excluded from refresh entirely.
        active_cfgs = [cfg for cfg in self.nodes_cfg
                       if not cfg.get("skip", False)
                       and not cfg.get("_ambiguous", False)
                       and cfg.get("type", "pve") != "pbs"]
        active_names = {cfg.get("name") for cfg in active_cfgs}
        for host in [h for h in {n.host_name for n in self._node_repo.all()}
                     if h and h not in active_names]:
            self._node_repo.remove_host(host)
            self._vm_repo.remove_host(host)
            self._storage_repo.remove_host(host)
        # Pools and HA groups are NOT cleared here (audit 4.2, D2; audit
        # 6.1.1, C-2): a host whose worker fails or is rejected keeps its
        # last known-good data.  Only hosts that left the configuration
        # are dropped.
        for host in [h for h in {p.host_name for p in self._pool_repo.all()}
                     if h and h not in active_names]:
            self._pool_repo.remove_host(host)
        for host in [h for h in self.all_ha_groups
                     if h and h not in active_names]:
            self.all_ha_groups.pop(host, None)

        # Stage 5.1.2 §3.1: ambiguous entries (legacy name conflicts) must
        # stay visible and must not look healthy — inject a warning stub.
        # status=error rows never reach the resource cache, and no worker
        # is started for these connections.
        for cfg in self.nodes_cfg:
            if not cfg.get("_ambiguous"):
                continue
            host = cfg.get("name", "")
            if not host or self._node_repo.get(host, host):
                continue
            self._node_repo.add(DomainNode.from_pve({
                "node": host,
                "status": "error",
                "error": "name conflict — resolve before use",
                "host_name": host,
                "conn_id": cfg.get("conn_id", ""),
                "_display_name": host,
                "_is_cluster": False,
            }, host, "", False))

        self.tree_panel.start_loading()

        refresh_gen = self._refresh.begin_hard()

        started = 0
        refresh_epoch = self._refresh.epoch
        for cfg in active_cfgs:
            worker = FetchWorker(cfg)
            worker.signals.result_ready.connect(
                lambda data, w=worker, g=refresh_gen, e=refresh_epoch:
                    self.on_worker_finished(data, w, g, e)
            )
            # track_hard only for actually started workers: a rejected
            # worker never reports and would block finalization forever
            if self._run_worker(worker):
                self._refresh.track_hard(worker)
                started += 1

        if not active_cfgs or started == 0:
            # Nothing runs (empty config or the pool rejected every worker):
            # no report will ever arrive — restore the UI from the current
            # repositories right away instead of waiting in loading stubs
            # forever (audit 4, D3).  The cache is not rewritten here: the
            # snapshot is not fresher than before.
            self.tree_panel.update_data(
                self._node_repo.all(), self._vm_repo.all(), self._storage_repo.all(), final=True,
                node_repo=self._node_repo, vm_repo=self._vm_repo,
            )
            self.detail_panel.set_lists(
                self._node_repo.all(), self._vm_repo.all(), self._storage_repo.all(),
                node_repo=self._node_repo, vm_repo=self._vm_repo
            )
            self._first_selection_done = True
            self._update_status_bar()

    def _rebuild_cfg_indexes(self):
        """Rebuild both config indexes: name → cfg and conn_id → cfg.

        The name index drives display/routing; the conn_id index drives
        the worker-result identity gates (stage 5.1.2). Every entry
        missing a conn_id gets an in-memory one (entries from
        load_config() already carry persisted ids), and ambiguity flags
        are recomputed so a conflict group that shrank to one member
        (e.g. after a repair) resumes refreshing.
        """
        mark_ambiguous(self.nodes_cfg)
        for cfg in self.nodes_cfg:
            if isinstance(cfg, dict) and not cfg.get("conn_id"):
                cfg["conn_id"] = uuid.uuid4().hex
        self._cfg_by_name = build_cfg_index(self.nodes_cfg)
        self._cfg_by_conn = {cfg["conn_id"]: cfg for cfg in self.nodes_cfg
                             if isinstance(cfg, dict) and cfg.get("conn_id")}

    def _resolve_result_cfg(self, data, worker):
        """Resolve the CURRENT config for an incoming worker result.

        Stage 5.1.2 identity gate: returns None when the result must be
        dropped BEFORE any state mutation — unknown conn_id (connection
        deleted or re-created under the same name), ambiguous entry, or
        a legacy payload without conn_id whose name does not resolve.
        The name fallback exists only for payloads produced before the
        conn_id stamping (test doubles); production FetchWorker results
        always carry conn_id — both on the payload and on the worker's
        node_cfg (migration guarantees every cfg has one), so the fallback
        is unreachable in production and logs a warning when hit. It
        resolves against the CURRENT index: the owner namespace always
        comes from the live config, never from the stale result.
        """
        conn_id = data.get("conn_id") or (
            worker.node_cfg.get("conn_id") if worker else None)
        if conn_id:
            cfg = self._cfg_by_conn.get(conn_id)
        else:
            # No identity anywhere — pre-5.1 payload shape. Production
            # never emits this; keep the resolution strict (current cfg
            # only, ambiguous excluded) and make the hit observable.
            logger.warning(
                "refresh result without conn_id for %r — legacy payload "
                "path; attach by current name only", data.get("host", ""))
            cfg = self._cfg_by_name.get(data.get("host", ""))
        if cfg is None or cfg.get("_ambiguous"):
            return None
        return cfg

    @Slot(str, str, dict)
    def _dedupe_cluster_cfgs(self, cfgs):
        """Audit 4.2, D3: keep the FIRST active representative per
        configured cluster name and drop the duplicates.

        Cluster identity here is the user-configured cluster name only:
        node names / VMIDs are NOT compared across different cluster
        names, because independent infrastructures may legitimately use
        the same names.  A repeated representative for the same cluster
        name cannot be verified to be the same infrastructure without a
        live check, so it is not silently merged — it is dropped with an
        explicit notification.
        """
        kept: list[dict] = []
        dups: list[tuple[str, str]] = []
        seen: set[str] = set()
        for cfg in cfgs:
            cl = cfg.get("cluster")
            if (cfg.get("cluster_rep")
                    and cl and cl not in (False, None, "Standalone")):
                if cl in seen:
                    dups.append((str(cl), cfg.get("name", "")))
                    continue
                seen.add(cl)
            kept.append(cfg)
        return kept, dups

    def _warn_dup_clusters(self, dups) -> None:
        """Notify about dropped duplicate cluster representatives."""
        for cl, name in dups:
            msg = tr(
                "Cluster \"{cluster}\" is configured more than once "
                "(host \"{name}\") — only the first connection is used"
            ).format(cluster=cl, name=name)
            if getattr(self, "_notifications", None) is not None:
                self._notifications.show(msg, error=True)
            else:
                self._dup_cluster_warnings.append(msg)

    # ------------------------------------------------------------
    # Legacy name conflicts (stage 5.1.1 §3.2)
    # ------------------------------------------------------------

    def _conflict_groups(self) -> dict[str, list[dict]]:
        """Current unresolved name-conflict groups (by normalized name)."""
        groups: dict[str, list[dict]] = {}
        for cfg in self.nodes_cfg:
            if cfg.get("_ambiguous"):
                groups.setdefault(name_key(cfg.get("name", "")), []).append(cfg)
        return groups

    def _notify_ambiguous(self):
        """Surface legacy name conflicts and offer the resolution dialog.

        Conflicting connections stay visible and keep their tokens; they
        are excluded from refresh and cache until the conflict is resolved
        by the user.
        """
        groups = self._conflict_groups()
        if not groups:
            return
        lines = []
        for members in groups.values():
            listed = "  /  ".join(
                f"«{c.get('name')}» ({c.get('host', '?')})" for c in members)
            lines.append("• " + listed)
        text = tr(
            "Connections with equivalent names were found (name comparison "
            "ignores case and outer spaces). They stay visible but are not "
            "refreshed until the conflict is resolved:\n{list}"
        ).format(list="\n".join(lines))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(tr("Connection name conflict"))
        box.setText(text)
        resolve_btn = box.addButton(tr("Resolve…"), QMessageBox.AcceptRole)
        box.addButton(tr("Later"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is resolve_btn:
            self._resolve_ambiguity_dialog()

    def _resolve_ambiguity_dialog(self):
        """Per conflict group: pick the connection to KEEP; the losers are
        removed through the regular delete flow (its own confirmation,
        token revoke, keyring cleanup). The winner is not modified."""
        for members in self._conflict_groups().values():
            labels = [f"«{c.get('name')}» — {c.get('host', '?')}"
                      for c in members]
            choice, ok = QInputDialog.getItem(
                self,
                tr("Resolve name conflict"),
                tr("Several connections share the same name.\n"
                   "Select the one to KEEP — the others will be removed:\n"
                   + "\n".join(labels)),
                labels, 0, False)
            if not ok:
                continue
            keep_idx = labels.index(choice)
            for i, member in enumerate(members):
                if i != keep_idx:
                    self._on_host_remove("host", member.get("name", ""))

    def _on_tree_item_selected(self, obj_type, obj_name, data):
        current_key = self.tree_panel.get_current_item_key()
        if current_key is not None:
            self._saved_key = current_key
        if obj_type in ("pbs", "pbs_datastore"):
            self.right_stack.setCurrentWidget(self.pbs_panel)
            if obj_type == "pbs":
                self.pbs_panel.show_server(obj_name)
            else:
                self.pbs_panel.show_datastore(
                    data.get("server", obj_name), data.get("store", "")
                )
            return
        self.right_stack.setCurrentWidget(self.detail_panel)
        self.detail_panel.show_details(obj_type, obj_name, data)

    @Slot(dict)
    def on_worker_finished(self, data, worker=None, gen=0, epoch=None):
        if not self._refresh.hard_result_current(gen):
            return
        # Drop the worker from _workers right away: its finished (queued)
        # arrives later than its own result_ready, and without this reset
        # the _workers set never empties at the check below — the final
        # branch (cache save, offline reset) would never run.
        self._workers.discard(worker)
        self._refresh.hard_done(worker, gen)
        # Stage 5.1.2 identity gate: a result of an unknown, deleted or
        # re-created connection (and of an ambiguous entry) must not touch
        # repos, epochs, UI or cache. Runs BEFORE any state mutation; the
        # cycle bookkeeping above already counted the report so the cycle
        # can finalize (the cache save below is identity-gated too).
        cfg = self._resolve_result_cfg(data, worker)
        if cfg is None:
            return
        status = data.get("status", "error")
        # The CURRENT config name is the namespace owner — never trust the
        # name inside a stale result.
        conn_id = cfg.get("conn_id", "")
        host = cfg.get("name", "") or data.get("host", "")
        # Audit 4.2, D1: a late answer of an already-finished attempt must
        # not overwrite a fresher snapshot of this host, nor trigger side
        # effects (notifications, first selection, cache save).
        if epoch is not None and not self._refresh.answer_current(host, epoch):
            return
        if status == "ok":
            is_cluster = worker.node_cfg.get("cluster_rep", False) if worker else False
            cluster_name = (worker.node_cfg.get("cluster", "") or "") if worker else ""
            # A confirmed full response replaces THIS host's snapshot
            # entirely: resources really removed on the server disappear,
            # while other hosts' data stays untouched (audit 4.1).
            self._node_repo.remove_host(host)
            self._vm_repo.remove_host(host)
            self._storage_repo.remove_host(host)
            for node in data.get("nodes", []):
                node["host_name"] = host
                node["conn_id"] = conn_id
                node["_is_cluster"] = is_cluster
                self._node_repo.add(DomainNode.from_pve(node, host, cluster_name, is_cluster))
            for vm in data.get("vms", []):
                vm["host_name"] = host
                vm["conn_id"] = conn_id
                self._vm_repo.add(DomainVm.from_pve(vm, host))
            for st_dict in data.get("storages", []):
                st_dict["host_name"] = host
                st_dict["conn_id"] = conn_id
                self._storage_repo.add(DomainStorage.from_pve(st_dict, host, cluster_name))
            # Collect pools (domain objects; identity is (host, poolid)).
            # None means the optional pool source failed — keep the
            # previous pool data of this host; [] is a confirmed absence
            # and clears it (audit 4.2, D2).
            pools_data = data.get("pools")
            if pools_data is not None:
                self._pool_repo.remove_host(host)
                for pd in pools_data:
                    self._pool_repo.add(DomainPool.from_pve(pd, host))
            self.all_pools = self._pool_repo.all()
            # Collect ISO images (host_name -> list volid).  An empty list
            # from a successful response is a confirmed absence — replace
            # the previous data; a failed optional fetch omits the key, so
            # stale entries survive (audit 4.1).
            for iso_host, isos in data.get("iso_images", {}).items():
                self.all_iso_images[iso_host] = isos
            # Collect HA groups (host_name -> [group, ...]) — the pools
            # rule (audit 6.1.1, C-2): [] is a confirmed absence and
            # clears this host's previous groups; None ("not fetched")
            # keeps them.
            ha_data = data.get("ha_groups")
            if ha_data is not None:
                self.all_ha_groups[host] = [
                    HaGroup.from_pve(g) for g in ha_data]
            # Audit 4.2, D1: this attempt's snapshot of the host is now
            # the freshest applied data
            if epoch is not None:
                self._refresh.note_applied(host, epoch)
        else:
            is_cluster_err = worker.node_cfg.get("cluster_rep", False) if worker else False
            err_msg = data.get("error", "Unknown error")
            existing_nodes = self._node_repo.get_by_host(host)
            if existing_nodes:
                # A node of this host already exists (short name from the
                # cache or a successful fetch) — flag it with the error
                # instead of adding a duplicate named from the config (FQDN).
                for old in existing_nodes:
                    self._node_repo.add(
                        replace(old, status=NodeStatus.ERROR, error=err_msg))
            else:
                err_node = {
                    "node": host,
                    "status": "error",
                    "error": err_msg,
                    "host_name": host,
                    "conn_id": conn_id,
                    "_display_name": host,
                    "_is_cluster": is_cluster_err
                }
                self._node_repo.add(DomainNode.from_pve(err_node, host, "", is_cluster_err))
            from .utils import parse_pve_error
            reason = parse_pve_error(err_msg)
            self._notifications.show(
                tr("Connection error: {host} — {reason}").format(host=host, reason=reason),
                error=True,
            )

        self._detect_status_changes()

        # Update the status bar right away — partial data beats emptiness
        self._update_status_bar()

        # Intermediate tree update — no spinner cleanup. Clusters that
        # failed to load stay in the tree as stubs with spinners.
        self.tree_panel.update_data(
            self._node_repo.all(), self._vm_repo.all(), self._storage_repo.all(), final=False,
            node_repo=self._node_repo, vm_repo=self._vm_repo,
        )
        self.detail_panel.set_lists(
            self._node_repo.all(), self._vm_repo.all(), self._storage_repo.all(),
                node_repo=self._node_repo, vm_repo=self._vm_repo
        )
        self.detail_panel.all_pools = self.all_pools
        self.detail_panel.all_ha_groups = self.all_ha_groups

        # Select the first tree item at the earliest opportunity.
        if not getattr(self, '_first_selection_done', False) and self.tree_panel.tree.topLevelItemCount() > 0:
            self._do_first_selection()
            self.detail_panel.refresh_current_view()

        # Task loading starts on the first worker — no waiting for all data
        if not self._tasks_started:
            self._tasks_started = True
            QTimer.singleShot(0, self.refresh_cluster_tasks)

        # Final branch — all workers of THIS generation reported
        # (success or error). The shared _workers set won't do here:
        # soft workers and detail workers keep it non-empty constantly.
        if not self._refresh.hard_pending_count:
            # Select the first item before the final tree rebuild — the
            # cluster summary appears immediately, without waiting for a
            # _build_tree with hundreds of VMs
            if not getattr(self, '_first_selection_done', False):
                self._do_first_selection()
                self.detail_panel.refresh_current_view()
            # All data loaded — final rebuild: spinners go away, VMs/pools in the tree
            self.tree_panel.update_data(
                self._node_repo.all(), self._vm_repo.all(), self._storage_repo.all(), final=True,
                node_repo=self._node_repo, vm_repo=self._vm_repo,
            )
            self.last_refresh_ts = time.time()
            self._mark_data_updated()
            self._update_status_bar()
            from ..config import save_resources_cache
            save_resources_cache(
                [dict(n) for n in self._node_repo.all()],
                [dict(v) for v in self._vm_repo.all()],
                [dict(s) for s in self._storage_repo.all()],
            )
            if self._offline_mode:
                self._offline_mode = False
                self._offline_ts = None
                self._update_status_bar()

    def _detect_status_changes(self, nodes=None, vms=None):
        if nodes is None:
            nodes = self._node_repo.all()
        if vms is None:
            vms = self._vm_repo.all()
        for node in nodes:
            # Key by (host_name, node): identical node names on different
            # hosts are legal (standalone servers) and would otherwise
            # trigger false status-change notifications.
            key = (node.host_name, node.node)
            status = node.status_value
            old = self._last_host_statuses.get(key)
            if old is not None and old != status:
                display = node.display_name or node.node
                self._notifications.host_status_changed(display, old, status)
                self._events.publish(Event(
                    "node.status_changed",
                    {"node": node.node, "host": node.host_name,
                     "display": display, "old": old, "new": status},
                ))
            self._last_host_statuses[key] = status

        for vm in vms:
            key = (vm.host_name, vm.vmid)
            status = vm.status_value
            old = self._last_vm_statuses.get(key)
            if old is not None and old != status:
                vm_name = vm.name or f"VM {vm.vmid}"
                self._notifications.vm_status_changed(vm_name, vm.host_name, status)
                self._events.publish(Event(
                    "vm.status_changed",
                    {"vmid": vm.vmid, "host": vm.host_name, "name": vm_name,
                     "old": old, "new": status},
                ))
            self._last_vm_statuses[key] = status

    # ------------------------------------------------------------
    # Background (soft) refresh
    # ------------------------------------------------------------
    def _maybe_pause_auto_refresh(self):
        """U20: every host of the cycle failed with an auth error — stop
        the 20 s hammering, notify once, let a manual Refresh retry."""
        if not self._soft_errors or self._auto_refresh_paused:
            return
        import re
        auth_pat = re.compile(
            r"\bhttp\s*401\b|unauthorized|no ticket|"
            r"ticket expired|invalid ticket", re.I)
        auth_hosts = {h for h, err in self._soft_errors.items()
                      if auth_pat.search(err or "")}
        if not auth_hosts:
            return
        active = {c.get("name") for c in self.nodes_cfg
                  if not c.get("skip") and c.get("type") != "pbs"}
        if not active or auth_hosts != active:
            return
        self._auto_refresh_paused = True
        self.refresh_timer.stop()
        self._notifications.show(
            tr("Auto-refresh paused: authorization failed on all hosts. "
               "Press Refresh to retry."),
            error=True,
        )
        self._update_status_bar()

    def soft_refresh(self):
        now = time.time()
        # U20: auto-refresh stays paused after an auth failure until the
        # user explicitly retries with Refresh.
        if self._auto_refresh_paused:
            return
        # Stage 5.1.2: sync the indexes with the current nodes_cfg before
        # the worker filters and result gates consume them (same as the
        # hard cycle entry).
        self._rebuild_cfg_indexes()
        # Hard-cycle watchdog (audit 4, D3): unreported hard workers would
        # block finalization forever. After the ceiling, leave the loading
        # state — late worker results still apply per-host when they
        # arrive (their generation stays current). Checked before the
        # interval guard so a hung cycle is finalized regardless of the
        # soft refresh schedule.
        if self._refresh.hard_timed_out():
            self._finalize_hard_timeout()
        if now - self.last_refresh_ts < self.refresh_interval:
            return
        if self._refresh.soft_running:
            if self._refresh.soft_timed_out(now):
                self._refresh.reset_soft()
                self._soft_refresh_active = False
                self._soft_node_repo.clear()
                self._soft_vm_repo.clear()
                self._soft_storage_repo.clear()
            else:
                return
        # Atomic guard: claim ownership before any nested event loop can fire.
        self._soft_refresh_active = True
        if not self._spin_timer.isActive():
            self._spin_timer.start()
        self.last_refresh_ts = now

        self._soft_node_repo.clear()
        self._soft_vm_repo.clear()
        self._soft_storage_repo.clear()
        self._soft_had_errors = False
        self._soft_errors.clear()
        self._soft_epochs.clear()

        # Stage 5.1.2: ambiguous entries (legacy name conflicts) are
        # excluded from refresh entirely.
        active_cfgs = [cfg for cfg in self.nodes_cfg
                       if not cfg.get("skip", False)
                       and not cfg.get("_ambiguous", False)
                       and cfg.get("type", "pve") != "pbs"]
        soft_gen = self._refresh.begin_soft(len(active_cfgs), now)
        if not active_cfgs:
            self._refresh.finish_soft()
            return
        # The pool may be full: workers above the limit never start, while
        # begin_soft already counted them in expected → the loop would hang
        # until timeout. Start only what fits; the rest waits for the next tick.
        capacity = max(0, MAX_WORKERS - len(self._workers))
        if capacity == 0:
            # D7: leave the soft state cleanly — the spinner must not spin
            # for a cycle that never started; the next tick retries.
            self._refresh.finish_soft()
            self._soft_refresh_active = False
            return
        if len(active_cfgs) > capacity:
            active_cfgs = active_cfgs[:capacity]
            soft_gen = self._refresh.begin_soft(len(active_cfgs), now)
        soft_epoch = self._refresh.epoch
        for cfg in active_cfgs:
            worker = FetchWorker(cfg)
            worker.signals.result_ready.connect(
                lambda data, w=worker, g=soft_gen, e=soft_epoch: (
                    self.on_soft_refresh_result(data, w, g, e),
                    self._discard_worker(w)
                )
            )
            self._run_worker(worker)

    def _finalize_hard_timeout(self):
        """Leave the loading state after a hung hard cycle (audit 4, D3).

        Workers stuck in a hung thread are NOT stopped by this: a late
        result still applies per-host (same generation stays current).
        The cache is not rewritten here — a late report or the next soft
        cycle persists the merged data.
        """
        self._refresh.finish_hard()
        self.tree_panel.update_data(
            self._node_repo.all(), self._vm_repo.all(), self._storage_repo.all(), final=True,
            node_repo=self._node_repo, vm_repo=self._vm_repo,
        )
        self._update_status_bar()
        self._notifications.show(
            tr("Update timed out — showing last known data"))

    @Slot(dict)
    def on_soft_refresh_result(self, data, worker=None, gen=0, epoch=None):
        if not self._refresh.soft_result_current(gen):
            return
        # Stage 5.1.2 identity gate (same rules as the hard slot): a
        # result of an unknown/deleted/re-created connection must not
        # mutate the soft repos, the epoch bookkeeping or the cache.
        cfg = self._resolve_result_cfg(data, worker)
        if cfg is None:
            return
        status = data.get("status", "error")
        conn_id = cfg.get("conn_id", "")
        host = cfg.get("name", "") or data.get("host", "")
        if status == "ok":
            if epoch is not None:
                self._soft_epochs[host] = epoch
            is_cluster = worker.node_cfg.get("cluster_rep", False) if worker else False
            cluster_name = (worker.node_cfg.get("cluster", "") or "") if worker else ""
            for node in data.get("nodes", []):
                node["host_name"] = host
                node["conn_id"] = conn_id
                node["_is_cluster"] = is_cluster
                self._soft_node_repo.add(DomainNode.from_pve(node, host, cluster_name, is_cluster))
            for vm in data.get("vms", []):
                vm["host_name"] = host
                vm["conn_id"] = conn_id
                self._soft_vm_repo.add(DomainVm.from_pve(vm, host))
            for st_dict in data.get("storages", []):
                st_dict["host_name"] = host
                st_dict["conn_id"] = conn_id
                self._soft_storage_repo.add(DomainStorage.from_pve(st_dict, host, cluster_name))
        else:
            # Do NOT put an empty error stub into the soft repos (audit 4,
            # D1): the merge below keeps the host's previous known-good
            # data and only flags its nodes with the error. An error stub
            # would erase the host's VMs/storages from the UI and cache.
            self._soft_had_errors = True
            self._soft_errors[host] = data.get("error", "Unknown error")

        # PBS servers don't take part in soft refresh, but they used to be
        # counted in active_count — the loop never finished and the cache
        # was never saved.
        if self._refresh.soft_result(gen):
            try:
                old_sig = _repo_signature(
                    self._node_repo, self._vm_repo, self._storage_repo)
                # Per-host merge instead of the old wholesale clear+swap
                # (audit 4, D1): hosts that reported "ok" replace their own
                # snapshot entirely — resources really removed on the server
                # disappear; hosts that errored keep their last known-good
                # data with ERROR flags; hosts that did not take part in
                # this soft cycle are untouched.
                for h in {n.host_name for n in self._soft_node_repo.all()}:
                    self._node_repo.remove_host(h)
                    self._vm_repo.remove_host(h)
                    self._storage_repo.remove_host(h)
                for n in self._soft_node_repo.all():
                    self._node_repo.add(n)
                for v in self._soft_vm_repo.all():
                    self._vm_repo.add(v)
                for s in self._soft_storage_repo.all():
                    self._storage_repo.add(s)
                # Audit 4.2, D1: the soft snapshot of each answered host is
                # now the freshest applied data — late hard answers of an
                # older attempt must not overwrite it
                if epoch is not None:
                    for h in {n.host_name for n in self._soft_node_repo.all()}:
                        self._refresh.note_applied(h, epoch)
                # Errored hosts: flag their existing nodes with the error;
                # when the host has no data at all (first run offline), add
                # a stub so the failure stays visible.
                for h, err_msg in self._soft_errors.items():
                    existing = self._node_repo.get_by_host(h)
                    if existing:
                        for old in existing:
                            self._node_repo.add(
                                replace(old, status=NodeStatus.ERROR,
                                        error=err_msg))
                    else:
                        err_node = {
                            "node": h,
                            "status": "error",
                            "error": err_msg,
                            "host_name": h,
                            "conn_id": self._cfg_by_name.get(
                                h, {}).get("conn_id", ""),
                            "_display_name": h,
                        }
                        self._node_repo.add(DomainNode.from_pve(err_node, h, "", False))
                # U20: an expired/revoked token makes every 20 s cycle
                # re-fail and spam notifications — pause auto-refresh
                # until the user presses Refresh.
                self._maybe_pause_auto_refresh()
                new_sig = _repo_signature(
                    self._node_repo, self._vm_repo, self._storage_repo)
                if old_sig != new_sig:
                    self.tree_panel.update_data(
                        self._node_repo.all(), self._vm_repo.all(),
                        self._storage_repo.all(), final=True,
                        node_repo=self._node_repo, vm_repo=self._vm_repo,
                    )
                else:
                    self.tree_panel.update_node_statuses(
                        self._node_repo.all(), self._vm_repo.all(),
                        node_repo=self._node_repo, vm_repo=self._vm_repo,
                    )
                self.detail_panel.set_lists(
                    self._node_repo.all(), self._vm_repo.all(), self._storage_repo.all(),
                    node_repo=self._node_repo, vm_repo=self._vm_repo
                )
                self.detail_panel.refresh_current_view()
                # Pass through pools/HA already collected during hard
                # refresh — soft refresh has no ProxmoxAPI and can't
                # re-collect them
                self.detail_panel.all_pools = self.all_pools
                self.detail_panel.all_ha_groups = self.all_ha_groups
                self._detect_status_changes()
                self._update_status_bar()
                # U8/GAP-4: at least one host answered this cycle — the
                # polled data is confirmed fresh, move the stamp.
                if self._soft_node_repo.all():
                    self._mark_data_updated()
                from ..config import save_resources_cache
                save_resources_cache(
                    [dict(n) for n in self._node_repo.all()],
                    [dict(v) for v in self._vm_repo.all()],
                    [dict(s) for s in self._storage_repo.all()],
                )
                if self._offline_mode:
                    self._offline_mode = False
                    self._offline_ts = None
            except Exception as exc:
                logger.debug("soft_refresh error", exc_info=True)
                self._notifications.show(
                    tr("Error: {err}").format(err=str(exc)[:100]),
                    error=True,
                )
            self._soft_node_repo.clear()
            self._soft_vm_repo.clear()
            self._soft_storage_repo.clear()
            self._refresh.finish_soft()
            self._soft_refresh_active = False
            self._update_tray_state()

    # ------------------------------------------------------------
    # Cluster tasks refresh
    # ------------------------------------------------------------
    def _on_task_navigate(self, task):
        """GAP-11: double-click on a task row selects the affected
        object in the tree — the VM if the task carries a vmid and is
        still known, otherwise the task's node."""
        if task is None:
            return
        node_name = task.node or ""
        vmid = int(task.vmid or 0)
        if vmid:
            vm = (self._vm_repo.get(node_name, vmid)
                  if self._vm_repo else None)
            if vm is not None:
                self.tree_panel.find_and_select(
                    (vm.host_name or node_name, vmid, vm.node))
                return
        if node_name:
            self.tree_panel.find_and_select(("host", node_name, node_name))

    def refresh_cluster_tasks(self):
        # Show cached tasks instantly while the worker fetches fresh ones
        if self._cached_tasks:
            self.tasks_widget.set_tasks(self._cached_tasks)
        elif not self._workers:
            self.tasks_widget.set_placeholder(tr("Loading tasks..."))
        if not self.nodes_cfg or not self._node_repo:
            return

        node_requests = []
        seen_nodes = set()

        rep_cfg = next((c for c in self.nodes_cfg if c.get("cluster_rep")), None)
        for n in self._node_repo.all():
            pve_node = n.node or ""
            host_name = n.host_name
            if not pve_node or pve_node in seen_nodes:
                continue
            display = n.display_name or ""

            if rep_cfg and display.endswith(f"@{rep_cfg.get('cluster', '')}"):
                cfg = rep_cfg
            else:
                cfg = self._cfg_by_name.get(host_name)
                if cfg is None:
                    cfg = next((c for c in self.nodes_cfg
                                if c["name"].split("@")[0] == pve_node), None)
            if cfg:
                node_requests.append((cfg, pve_node))
                seen_nodes.add(pve_node)

        if not node_requests:
            return

        self._tasks_gen += 1
        tasks_gen = self._tasks_gen
        worker = ClusterTasksWorker(node_requests)
        worker.signals.tasks_ready.connect(
            lambda t, w=worker, g=tasks_gen: (
                self._on_cluster_tasks_loaded(t, g),
                self._discard_worker(w)
            )
        )
        worker.signals.tasks_error.connect(lambda err, w=worker: self._discard_worker(w))
        # finished is connected in _run_worker; but ClusterTasksWorker runs
        # via threading.Thread (not QThreadPool) so the pool slot isn't
        # blocked for the join() inside run(). So we register it in _workers
        # manually — otherwise the worker isn't counted in MAX_WORKERS and
        # leaks if it fails before emit.
        if len(self._workers) >= MAX_WORKERS:
            try:
                worker.signals.tasks_ready.disconnect()
                worker.signals.tasks_error.disconnect()
            except (RuntimeError, TypeError):
                pass
            return
        self._workers.add(worker)
        worker.signals.finished.connect(lambda w=worker: self._discard_worker(w))
        t = threading.Thread(target=worker.run, daemon=True)
        t.start()

    def _on_cluster_tasks_loaded(self, tasks, gen):
        if gen != self._tasks_gen:
            return
        self._update_cluster_tasks_widget(tasks)

    def _update_cluster_tasks_widget(self, tasks):
        self._cached_tasks = tasks
        save_tasks_cache([dict(t) for t in tasks])
        try:
            node_map = {}
            for n in self._node_repo.all():
                node_map[n.node] = n.display_name or n.node
            vm_map = {}
            for vm in self._vm_repo.all():
                vm_map[int(vm.vmid)] = vm.name
            enriched = []
            for task in tasks:
                new = task
                if task.node in node_map:
                    new = replace(new, display_name=node_map[task.node])
                if task.vmid is not None:
                    new = replace(new, vm_name=vm_map.get(task.vmid, ""))
                enriched.append(new)
            tasks = enriched
        except Exception as e:
            logger.error("Failed to enrich tasks: %s", e)
        try:
            self.tasks_widget.set_tasks(tasks)
        except Exception as e:
            logger.error("Failed to set tasks: %s", e)

    # ------------------------------------------------------------
    # Window state save/restore (SQLite)
    # ------------------------------------------------------------
    def _restore_window_state(self):
        """Restores geometry, maximized state, splitters and the last selected item.
        Called before show() so the window appears in the right position.
        We use SQLite (ui_state) instead of QSettings because:
          - Single storage: tasks and UI state in one file
          - Transparency: the file lives in ~/.config/virtdeck/, easy to inspect
          - QSettings scatters data across platform-specific places
            (registry/dconf/INI)"""
        raw = load_ui_state("window_geometry")
        if raw:
            try:
                geo = json.loads(raw)
                if isinstance(geo, list) and len(geo) == 4:
                    self.setGeometry(*geo)
            except (TypeError, ValueError):
                pass
        raw = load_ui_state("window_maximized")
        if raw == "1":
            self.showMaximized()
        raw = load_ui_state("saved_key")
        if raw:
            try:
                val = json.loads(raw)
                if isinstance(val, list):
                    self._saved_key = tuple(val)
                else:
                    self._saved_key = val
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        raw = load_ui_state("saved_tab")
        if raw:
            try:
                self._saved_tab = int(raw)
            except (TypeError, ValueError):
                pass
        raw = load_ui_state("saved_obj_type")
        if raw:
            self._saved_obj_type = raw

    def _restore_splitter_state(self):
        """Restores splitter positions from SQLite."""
        raw = load_ui_state("splitter_h")
        if raw:
            try:
                vals = json.loads(raw)
                if isinstance(vals, list):
                    self.h_splitter.setSizes([int(x) for x in vals])
            except (TypeError, ValueError):
                pass
        else:
            self.h_splitter.setSizes([360, 1140])
        raw = load_ui_state("splitter_v")
        if raw:
            try:
                vals = json.loads(raw)
                if isinstance(vals, list):
                    self.v_splitter.setSizes([int(x) for x in vals])
            except (TypeError, ValueError):
                pass
        else:
            self.v_splitter.setSizes([550, 150])

    # ------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------
    def _mark_data_updated(self):
        """U8/GAP-4: call when a final data snapshot has been applied."""
        from datetime import datetime
        self._updated_label.setText(
            tr("Updated {time}").format(
                time=datetime.now().strftime("%H:%M:%S")))

    def _update_status_bar(self):
        nodes = self._node_repo.all()
        vms = self._vm_repo.all()
        hosts_ok = sum(1 for n in nodes if n.status is NodeStatus.ONLINE)
        hosts_total = len(nodes)
        hosts_err = sum(1 for n in nodes if n.status is NodeStatus.ERROR)
        vms_count = len(vms)
        vms_running = sum(1 for v in vms if v.status is VmStatus.RUNNING)
        clusters = {n.cluster for n in nodes if n.cluster and n.cluster != "Standalone"}
        online_nodes = [n for n in nodes if n.status is NodeStatus.ONLINE]
        # cpu_fraction is per-node utilization (0..1 of that node's cores);
        # cluster-wide CPU load is the mean across online nodes.
        cpu_pct = (
            sum(n.cpu_fraction for n in online_nodes) / len(online_nodes) * 100
            if online_nodes else 0
        )
        total_mem = sum(n.mem_bytes for n in online_nodes)
        total_maxmem = sum(n.maxmem_bytes for n in online_nodes)
        mem_pct = (total_mem / total_maxmem * 100) if total_maxmem else 0
        parts = [
            # L3: the denominator is the CONFIGURED hosts, not the ones
            # that happened to answer — "Hosts: 0/1 → 1/10" during a
            # refresh was unreadable.
            tr("Hosts: {ok}/{total}").format(
                ok=hosts_ok, total=max(len(self.nodes_cfg), hosts_total)),
            tr("Clusters: {n}").format(n=len(clusters)) if clusters else "",
            tr("VMs: {running}/{total}").format(running=vms_running, total=vms_count),
            tr("CPU: {pct}%").format(pct=f"{cpu_pct:.0f}"),
            tr("RAM: {pct}%").format(pct=f"{mem_pct:.0f}"),
        ]
        if hosts_err:
            parts.append(tr("Errors: {n}").format(n=hosts_err))
        if self._offline_mode:
            parts.append(tr("Offline (cached)"))
        if self._auto_refresh_paused:
            parts.append(tr("Auto-refresh paused"))
        # U5: an empty application's "Hosts: 0/0 VMs: 0/0 CPU: 0% RAM: 0%"
        # is honest but pure noise — stay silent until the first fleet.
        if not self.nodes_cfg:
            parts = []
        self.status_label.setText("  ".join(p for p in parts if p))

    def _do_first_selection(self):
        self._first_selection_done = True
        self._pending_first_selection = False
        # Detail panel tabs are still built in chunks — postpone the selection
        # until they are ready, otherwise _ensure_tabs() would build everything
        # synchronously and freeze the main thread for seconds (regression:
        # FREEZE DETECTED at startup).
        if not self.detail_panel._tabs_built:
            self._pending_first_selection = True
            return
        # If the user already picked an item (e.g. a PBS server) — don't
        # hijack the selection to the first tree item.
        if self.tree_panel.get_current_item_key() is not None:
            return
        saved_key = getattr(self, '_saved_key', None)
        if saved_key:
            item = self.tree_panel.find_item_by_key(saved_key)
            if item:
                self.tree_panel.tree.setCurrentItem(item)
                self.tree_panel._on_item_clicked(item, 0)
                saved_tab = getattr(self, '_saved_tab', 0)
                saved_type = getattr(self, '_saved_obj_type', None)
                if saved_type and saved_type == self.detail_panel.current_obj_type:
                    QTimer.singleShot(100, lambda: self.detail_panel.tabs.setCurrentIndex(saved_tab))
            else:
                self.tree_panel.select_first_item()
        else:
            self.tree_panel.select_first_item()

    def _on_all_tabs_built(self):
        # The first selection decision was postponed until the chunked tab
        # build finished (see _do_first_selection) — run it now.
        if getattr(self, "_pending_first_selection", False):
            self._pending_first_selection = False
            if self.tree_panel.tree.topLevelItemCount() > 0:
                self._do_first_selection()
                self.detail_panel.refresh_current_view()

    # ------------------------------------------------------------
    # Freeze detector
    # ------------------------------------------------------------
    def _tick_spinner(self):
        """Animates the spinner in the status bar during background refresh."""
        if not self._soft_refresh_active:
            self._refresh_spinner.setText("")
            self._spin_timer.stop()
            return
        self._refresh_spinner.setText(self._spin_frames[self._spin_idx])
        self._spin_idx = (self._spin_idx + 1) % len(self._spin_frames)

    def _heartbeat(self):
        self._last_heartbeat = time.time()

    def _detect_freeze(self):
        while not self._closing:
            time.sleep(2)
            if self._closing:
                break
            now = time.time()
            elapsed = now - self._last_heartbeat
            if elapsed > 3:
                logger.error("=== FREEZE DETECTED: main thread unresponsive for %.1fs ===", elapsed)
                try:
                    main_thread = threading.main_thread()
                    frame = sys._current_frames().get(main_thread.ident)
                    if frame is not None:
                        import io
                        buf = io.StringIO()
                        traceback.print_stack(frame, file=buf)
                        stack = buf.getvalue()
                        if stack:
                            logger.error("MainThread stack:\n%s", stack)
                        else:
                            logger.error("MainThread stack: <empty>")
                    else:
                        logger.error("MainThread frame not found")
                except Exception as exc:
                    logger.error("Failed to dump stack: %s", exc, exc_info=True)
                logger.error("=== END FREEZE REPORT ===")

    def _status_combo_style(self):
        return (f"QComboBox {{ font-size: 12px; border: 1px solid {Color.BORDER_STRONG}; border-radius: 3px; "
                f"padding: 1px 4px; background: {Color.TRACK}; color: {Color.TEXT}; }}"
                f"QComboBox:hover {{ border-color: {Color.BORDER_STRONG}; background: {Color.HOVER}; }}"
                f"QComboBox::drop-down {{ border: none; width: 16px; }}"
                f"QComboBox QAbstractItemView {{ font-size: 12px; }}")

    def _build_theme_switcher(self):
        """Theme switcher — a permanent status bar widget, next to the language."""
        from ..plugins import get_registry
        from . import theme as theme_mod
        from .theme import load_theme

        saved = load_ui_state("theme") or "light"
        if saved != "light":
            try:
                load_theme(saved, persist=False)
            except Exception as exc:
                logger.error("saved theme %r failed: %s", saved, exc)
        self._theme_combo = QComboBox()
        self._theme_combo.setMinimumWidth(110)
        self._theme_combo.setAccessibleName(tr("Theme"))
        self._theme_combo.setStyleSheet(self._status_combo_style())
        reg = get_registry()
        saved = load_ui_state("theme") or "light"
        ids = theme_mod.ordered_theme_ids(reg)
        if saved not in ids:
            saved = "light" if "light" in ids else (ids[0] if ids else None)
        self._theme_combo.blockSignals(True)
        for tid in ids:
            try:
                label = reg.get_theme(tid).name
            except Exception:
                label = tid
            self._theme_combo.addItem(label, tid)
            if tid == saved:
                self._theme_combo.setCurrentIndex(self._theme_combo.count() - 1)
        self._theme_combo.blockSignals(False)
        self._applied_theme_tid = saved  # theme already applied at startup (main())
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.status_bar.insertPermanentWidget(2, self._theme_combo)
        # Repaint the tree on theme change (cached QColor in cells).
        self._theme_listener = lambda _tid: self._on_theme_applied()
        theme_mod.subscribe_theme_changed(self._theme_listener)
        self.destroyed.connect(
            lambda: theme_mod.unsubscribe_theme_changed(self._theme_listener))

    def _on_theme_changed(self, idx):
        from .theme import load_theme

        tid = self._theme_combo.itemData(idx)
        if not tid:
            return
        if tid == self._applied_theme_tid:
            # Same theme: a full UI repolish (setStyleSheet across all
            # widgets) costs seconds — don't repeat it on a click on the
            # already active combo item.
            return
        try:
            load_theme(tid)
            self._applied_theme_tid = tid
        except Exception as exc:
            self._applied_theme_tid = None  # failure — retry allowed
            logger.error("theme switch failed (%s): %s", tid, exc, exc_info=True)
            self.status_label.setText(tr("Theme failed to load"))

    def _on_theme_applied(self):
        """UI reaction to an applied theme: inline styles + tree + toolbar."""
        from .icons import base_size, init_icons

        for combo in (self._lang_combo, self._theme_combo):
            combo.setStyleSheet(self._status_combo_style())
        init_icons()
        for act, icon_name in self._toolbar_icon_actions:
            act.setIcon(get_icon(icon_name))
        size = base_size()
        self._toolbar.setIconSize(QSize(size, size))
        self._brand.restyle()
        self._update_tray_state()
        self.tree_panel.reapply_theme()
        self.detail_panel.reapply_theme()
        # A7/Д4: pbs_panel keeps inline-styled labels and cached QColor
        # brushes — without this they held the old theme until the next
        # data arrival (confirmed 1.6:1 on graphite).
        self.pbs_panel.reapply_theme()
        if self._palette is not None:
            self._palette.retheme()

    def _on_language_changed(self, idx):
        code = self._lang_combo.itemData(idx)
        if not code or code == get_language():
            return
        save_ui_state("language", code)
        msg = QMessageBox(QMessageBox.Question, tr("Language changed"),
                          tr("The language will change after restart. Restart now?"),
                          parent=self)
        yes = msg.addButton(tr("Yes"), QMessageBox.YesRole)
        msg.addButton(tr("No"), QMessageBox.NoRole)
        msg.setDefaultButton(yes)
        msg.exec()
        if msg.clickedButton() == yes:
            # Save everything and restart via Python module (path-independent)
            self.refresh_timer.stop()
            self.tasks_timer.stop()
            self.tree_panel.save_state()
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.quit()
            import os
            import sys
            self_dir = os.path.dirname(os.path.abspath(__file__))          # ui/
            pkg_dir = os.path.dirname(self_dir)                            # virtdeck/
            parent_dir = os.path.dirname(pkg_dir)                          # /home/taurus
            env = os.environ.copy()
            env["PYTHONPATH"] = f"{parent_dir}:{env.get('PYTHONPATH', '')}"
            os.execve(sys.executable, [sys.executable, "-m", "virtdeck.main"], env)

    # ------------------------------------------------------------
    # Tray icon
    # ------------------------------------------------------------
    def _init_tray(self):
        icon = get_icon("app")
        if icon is None:
            return
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("VirtDeck")
        menu = QMenu(self)
        show_act = menu.addAction(tr("Show window"))
        show_act.triggered.connect(self._tray_show)
        refresh_act = menu.addAction(tr("Refresh"))
        refresh_act.triggered.connect(self.refresh_data)
        fleet_act = menu.addAction(tr("Fleet Health"))
        fleet_act.triggered.connect(self._open_fleet_health)
        menu.addSeparator()
        quit_act = menu.addAction(tr("Quit"))
        quit_act.triggered.connect(self._tray_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        self._update_tray_state()

    def _update_tray_state(self):
        """Brand tray icon reflecting the state: offline / error / ok."""
        if self._tray is None:
            return
        if not self.nodes_cfg or self._offline_mode:
            state = "offline"
        elif self._soft_had_errors:
            state = "error"
        else:
            state = "ok"
        self._tray_state = state
        icon = brand.tray_icon(state)
        if not icon.isNull():
            self._tray.setIcon(icon)

    def _tray_show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_quit(self):
        self._tray_minimize_to_tray = False
        self._save_state_and_quit()

    def _save_state_and_quit(self):
        self._closing = True
        self.refresh_timer.stop()
        self.tasks_timer.stop()
        self._heartbeat_timer.stop()
        self._spin_timer.stop()
        self.tree_panel.save_state()
        geo = self.geometry()
        save_ui_state("window_geometry", json.dumps([geo.x(), geo.y(), geo.width(), geo.height()]))
        save_ui_state("window_maximized", "1" if self.isMaximized() else "0")
        key = self.tree_panel.get_current_item_key()
        if key:
            save_ui_state("saved_key", json.dumps(key))
        save_ui_state("saved_tab", str(self.detail_panel.tabs.currentIndex()))
        save_ui_state("saved_obj_type", str(self.detail_panel.current_obj_type or ""))
        save_ui_state("splitter_h", json.dumps(self.h_splitter.sizes()))
        save_ui_state("splitter_v", json.dumps(self.v_splitter.sizes()))
        for w in list(self._workers):
            cancel = getattr(w, "cancel", None)
            if callable(cancel):
                cancel()
        QThreadPool.globalInstance().clear()
        QThreadPool.globalInstance().waitForDone(1000)
        if self._tray:
            self._tray.hide()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._tray_show()

    # ------------------------------------------------------------
    # Application shutdown
    # ------------------------------------------------------------
    def closeEvent(self, event):
        if self._tray and self._tray.isVisible() and self._tray_minimize_to_tray:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "VirtDeck",
                tr("Minimize to tray"),
                QSystemTrayIcon.Information,
                2000,
            )
            return
        self._save_state_and_quit()
        super().closeEvent(event)
