import logging
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...domain import VmStatus, VmType
from ..i18n import tr
from ..icons import get_icon
from ..object_id import HostId, StorageId, VmId
from ..utils import build_cfg_index
from ..vm_actions import (
    VM_ACTION_BUTTON_LABELS,
    VM_ACTION_ICONS,
    VM_ACTION_TOOLTIPS,
    VM_EXTRA_ACTION_ICONS,
    VM_EXTRA_ACTION_LABELS,
    VM_EXTRA_ACTION_TOOLTIPS,
)
from ._constants import _HAS_PG, TabIndex, ensure_pg
from ._host_tabs import HostTabs
from ._storage_tabs import StorageTabs
from ._table_utils import set_cell_text
from ._vm_tabs import VMTabs
from ._worker_manager import WorkerManager

logger = logging.getLogger(__name__)


class DetailPanel(QWidget):
    config_update_result = Signal(str)
    transfer_progress = Signal(str, int)      # (key, percent)
    transfer_started = Signal(str, str)       # (key, description)
    transfer_finished = Signal(str, bool, str) # (key, success, message)
    navigate_requested = Signal(object)        # key_data tuple for tree navigation
    vm_clone_requested = Signal(str, str, int)  # (host_name, node, vmid)
    vm_convert_requested = Signal(str, str, int, str)  # (host_name, node, vmid, direction)
    all_tabs_built = Signal()                  # chunked tab build drained the queue
    vm_ha_add_requested = Signal(str, str, int)  # (host_name, node, vmid)
    vm_ha_remove_requested = Signal(str, str, int)  # (host_name, node, vmid)

    def __init__(self, nodes_cfg):
        super().__init__()
        self.nodes_cfg = nodes_cfg
        self._cfg_by_name = build_cfg_index(self.nodes_cfg)
        self._vm_repo = None
        self._node_repo = None
        self.all_nodes = []
        self.all_vms = []
        self.all_storages = []
        self.details_cache = {}
        self.config_cache = {}
        self.metrics_cache = {}
        self.task_history_cache = {}
        self.vm_snapshots_cache = {}
        self._storage_content_pending = {}
        self._iso_by_host = {}
        self._last_vm_data = None
        self.current_obj_type = None
        self.current_obj_name = None
        self.current_obj_data = None
        self.current_obj_id = None
        self._generation = 0
        self.all_pools = []
        self.all_ha_groups = {}
        self._current_cluster_cfg = None

        self._workers_mgr = WorkerManager()
        self._host_tabs = HostTabs(self)
        self._storage_tabs = StorageTabs(self)
        self._vm_tabs = VMTabs(self)

        self.detail_label = QLabel(tr("Select object in tree"))
        self.detail_label.setWordWrap(True)
        self.detail_label.setAlignment(Qt.AlignTop)
        self.detail_label.setContentsMargins(0, 0, 0, 0)
        self.detail_label.setObjectName("titleMain")

        self.detail_sublabel = QLabel("")
        self.detail_sublabel.setAlignment(Qt.AlignTop)
        self.detail_sublabel.setContentsMargins(0, 0, 0, 0)
        self.detail_sublabel.setObjectName("titleSub")
        self.detail_sublabel.setVisible(False)

        self.vm_action_bar = QWidget()
        self.vm_action_bar.setMinimumHeight(32)
        self.vm_action_bar.setVisible(False)
        action_layout = QHBoxLayout(self.vm_action_bar)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self._vm_actions = VM_ACTION_BUTTON_LABELS
        self._action_buttons = {}
        for action_key, label in self._vm_actions.items():
            btn = QPushButton(get_icon(VM_ACTION_ICONS[action_key]), label)
            btn.setMinimumHeight(30)
            btn.setToolTip(VM_ACTION_TOOLTIPS[action_key])
            btn.clicked.connect(lambda checked, a=action_key: self._on_vm_action(a))
            action_layout.addWidget(btn)
            self._action_buttons[action_key] = btn

        self._console_btn = QToolButton()
        self._console_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._console_btn.setIcon(get_icon("console"))
        self._console_btn.setText(tr("Console"))
        self._console_btn.setMinimumHeight(30)
        self._console_btn.setObjectName("neutralBtn")
        self._console_btn.setToolTip(tr("Open console"))
        self._console_menu = QMenu(self._console_btn)
        self._console_novnc_act = QAction(tr("noVNC (built-in)"), self)
        self._console_novnc_act.triggered.connect(self._on_vm_novnc)
        self._console_menu.addAction(self._console_novnc_act)
        self._console_rv_act = QAction(tr("SPICE/VNC (remote-viewer)"), self)
        self._console_rv_act.triggered.connect(self._on_vm_console)
        self._console_menu.addAction(self._console_rv_act)
        self._console_btn.setMenu(self._console_menu)
        self._console_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self._console_btn.clicked.connect(self._on_vm_console)
        action_layout.addWidget(self._console_btn)

        self._extra_action_buttons = {}
        for action_key, label in VM_EXTRA_ACTION_LABELS.items():
            btn = QPushButton(get_icon(VM_EXTRA_ACTION_ICONS[action_key]), label)
            btn.setMinimumHeight(30)
            btn.setToolTip(VM_EXTRA_ACTION_TOOLTIPS[action_key])
            btn.clicked.connect(lambda checked, a=action_key: self._on_vm_extra_action(a))
            btn.setVisible(False)
            action_layout.addWidget(btn)
            self._extra_action_buttons[action_key] = btn

        self.tabs = QTabWidget()
        self._tabs_built = False
        self._tab_icon_keys: list[str] = []
        self._tab_queue = None
        self._tab_build_t0 = time.perf_counter()
        self.tabs.hide()
        if _HAS_PG:
            threading.Thread(target=self._pg_warm, daemon=True,
                             name="pg-warm").start()
        QTimer.singleShot(0, self._build_tab_chunk)

        title_block = QHBoxLayout()
        title_block.setContentsMargins(24, 20, 24, 0)
        title_block.setSpacing(12)
        title_left = QVBoxLayout()
        title_left.setSpacing(2)
        title_left.addWidget(self.detail_label)
        title_left.addWidget(self.detail_sublabel)
        title_block.addLayout(title_left)
        title_block.addStretch()

        self._cluster_view_toggle = QWidget()
        self._cluster_view_toggle.setVisible(False)
        toggle_layout = QHBoxLayout(self._cluster_view_toggle)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(0)
        self._btn_clusters = QPushButton(tr("Clusters"))
        self._btn_clusters.setCheckable(True)
        self._btn_clusters.setObjectName("segBtnLeft")
        self._btn_clusters.clicked.connect(lambda: self._switch_cluster_view("clusters"))
        self._btn_nodes = QPushButton(tr("Nodes"))
        self._btn_nodes.setCheckable(True)
        self._btn_nodes.setObjectName("segBtnRight")
        self._btn_nodes.clicked.connect(lambda: self._switch_cluster_view("compare"))
        toggle_layout.addWidget(self._btn_clusters)
        toggle_layout.addWidget(self._btn_nodes)
        title_block.addWidget(self._cluster_view_toggle)

        title_block.addWidget(self.vm_action_bar)

        title_widget = QWidget()
        title_widget.setLayout(title_block)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(0)
        main_layout.addWidget(title_widget)
        main_layout.addWidget(self.tabs)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)

    _TAB_BUILD_CHUNK = 2

    def _pg_warm(self):
        """Import pyqtgraph off the main thread so charts never block the UI."""
        try:
            ensure_pg()
        except Exception:
            logger.debug("pyqtgraph warm-up failed", exc_info=True)

    def _tab_specs(self):
        """Tab pages in TabIndex order: (builder, icon, title, hide_after_add)."""
        return [
            # 0: Monitoring
            (self._vm_tabs.build_monitoring_tab, "monitor", tr("Monitoring"), False),
            # 1: Hardware
            (self._vm_tabs.build_hardware_tab, "hardware", tr("Hardware"), False),
            # 2: Options
            (self._vm_tabs.build_options_tab, "options", tr("Options"), False),
            # 3: History
            (self._vm_tabs.build_history_tab, "history", tr("History"), False),
            # 4: Summary
            (self._host_tabs.build_summary_tab, "host", tr("Summary"), True),
            # 5: Host VMs
            (self._host_tabs.build_host_vm_tab, "vm", tr("Virtual Machines"), True),
            # 6: Pool VMs
            (self._vm_tabs.build_pool_tab, "pool", tr("Pool VMs"), True),
            # 7: Storages overview
            (self._storage_tabs.build_storage_overview_tab, "storage", tr("Storage"), True),
            # 8: Host storage
            (self._host_tabs.build_host_storage_tab, "storage", tr("Storage"), True),
            # 9: Storage detail
            (self._storage_tabs.build_storage_detail_tab, "storage", tr("Storage Detail"), True),
            # 10: Storage monitoring (fill-level chart)
            (self._storage_tabs.build_storage_monitoring_tab, "monitor", tr("Monitoring"), True),
            # 11: Backups
            (self._storage_tabs.build_backups_tab, "backup", tr("Backups"), True),
            # 12: VM Disks
            (self._storage_tabs.build_disks_vm_tab, "disk", tr("VM Disks"), True),
            # 13: ISO
            (self._storage_tabs.build_iso_tab, "iso", tr("ISO"), True),
            # 14: Templates
            (self._storage_tabs.build_templates_tab, "template", tr("Templates"), True),
            # 15: Network
            (self._host_tabs.build_network_tab, "network", tr("Network"), True),
            # 16: Services
            (self._host_tabs.build_services_tab, "services", tr("Services"), True),
            # 17: Host disks
            (self._host_tabs.build_host_disks_tab, "disk", tr("Disks"), True),
            # 18: Snapshots
            (self._host_tabs.build_snapshots_tab, "snapshot", tr("Snapshots"), True),
            # 19: Health
            (self._host_tabs.build_health_tab, "monitor", tr("Health"), True),
            # 20: VM Snapshots
            (self._vm_tabs.build_snapshots_tab, "snapshot", tr("Snapshots"), True),
            # 21: VM Backup
            (self._vm_tabs.build_vm_backup_tab, "backup", tr("Backup"), True),
            # 22: Backup Jobs
            (self._host_tabs.build_backup_jobs_tab, "backup", tr("Backup Jobs"), True),
            # 23: Access Management
            (self._host_tabs.build_access_tab, "user", tr("Access"), True),
            # 24: HA
            (self._host_tabs.build_ha_tab, "ha", tr("HA"), True),
        ]

    def _add_next_tab(self):
        builder, icon_key, title, hide = self._tab_queue.pop(0)
        t0 = time.perf_counter()
        idx = self.tabs.addTab(builder(), get_icon(icon_key), title)
        self._tab_icon_keys.append(icon_key)
        dt = time.perf_counter() - t0
        if dt > 0.2:
            logger.info("tab '%s' built in %.2fs", title, dt)
        if hide:
            self.tabs.setTabVisible(idx, False)

    def _build_tab_chunk(self):
        """Build a couple of tab pages per event-loop tick.

        Spreads the ~1s of widget construction over the idle time right
        after the window appears instead of freezing the main thread for
        seconds on the first selection. If the user selects an object
        before the queue drains, _ensure_tabs() finishes the rest at once.
        """
        try:
            self._build_tab_chunk_impl()
        except RuntimeError:
            # singleShot стреляет после deleteLater панели (окно закрыто,
            # очередь табов не опустела) — C++ объект уже удалён.
            pass

    def _build_tab_chunk_impl(self):
        if self._tabs_built:
            return
        if self._tab_queue is None:
            self._tab_queue = self._tab_specs()
            self._tab_build_t0 = time.perf_counter()
        for _ in range(self._TAB_BUILD_CHUNK):
            if not self._tab_queue:
                break
            self._add_next_tab()
        if self._tab_queue:
            QTimer.singleShot(0, self._build_tab_chunk)
        else:
            self._tabs_built = True
            logger.info(
                "detail tabs built in %.2fs", time.perf_counter() - self._tab_build_t0
            )
            self.all_tabs_built.emit()

    def _ensure_tabs(self):
        """Synchronously finish tab building (first selection or tests)."""
        if self._tabs_built:
            return
        if self._tab_queue is None:
            self._tab_queue = self._tab_specs()
            self._tab_build_t0 = time.perf_counter()
        while self._tab_queue:
            self._add_next_tab()
        self._tabs_built = True
        logger.info(
            "detail tabs built synchronously in %.2fs",
            time.perf_counter() - self._tab_build_t0,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_lists(self, all_nodes, all_vms, all_storages=None, node_repo=None, vm_repo=None):
        self.all_nodes = all_nodes
        self.all_vms = all_vms
        self._node_repo = node_repo
        self._vm_repo = vm_repo
        self.all_storages = all_storages or []
        self.details_cache.clear()
        self.config_cache.clear()
        self.metrics_cache.clear()
        self.task_history_cache.clear()
        self.vm_snapshots_cache.clear()

    def update_nodes_cfg(self, nodes_cfg):
        self.nodes_cfg = nodes_cfg
        self._cfg_by_name = build_cfg_index(self.nodes_cfg)

    def reapply_theme(self):
        """Переприсвоить иконки персистентных кнопок после смены темы."""
        for key, btn in self._action_buttons.items():
            btn.setIcon(get_icon(VM_ACTION_ICONS[key]))
        for key, btn in self._extra_action_buttons.items():
            btn.setIcon(get_icon(VM_EXTRA_ACTION_ICONS[key]))
        self._console_btn.setIcon(get_icon("console"))
        for idx, key in enumerate(self._tab_icon_keys):
            self.tabs.setTabIcon(idx, get_icon(key))

    def show_details(self, obj_type, obj_name, data):
        self._ensure_tabs()
        self.tabs.show()
        if obj_type == "vm":
            self.vm_action_bar.setVisible(True)
            self._update_action_buttons(data)
        else:
            self.vm_action_bar.setVisible(False)
        self._cluster_view_toggle.setVisible(False)
        try:
            self.current_obj_type = obj_type
            self.current_obj_name = obj_name
            self.current_obj_data = data
            self.current_obj_id = self._build_obj_id(obj_type, obj_name, data)
            self._generation += 1
            gen = self._generation
            self.metrics_widget.setVisible(True)
            self.info_label.setStyleSheet("")

            self._workers_mgr.cancel_detail_worker()
            self._workers_mgr.cancel_config_worker()
            self._workers_mgr.cancel_history_worker()
            self._workers_mgr.cancel_snapshots_worker()
            self._workers_mgr.cancel_host_workers()
            self._workers_mgr.cancel_general_workers()
            self.metrics_widget.clear_curves()
            self.metrics_widget.setVisible(obj_type in ("vm", "host"))

            for idx in (TabIndex.MONITOR, TabIndex.HARDWARE, TabIndex.OPTIONS,
                        TabIndex.HISTORY, TabIndex.HOST_VMS, TabIndex.POOL_VMS,
                        TabIndex.SUMMARY, TabIndex.STORAGES, TabIndex.HOST_STORAGE,
                        TabIndex.STORAGE_DETAIL, TabIndex.STORAGE_MONITORING,
                        TabIndex.BACKUPS,
                        TabIndex.DISKS_VM, TabIndex.ISO, TabIndex.TEMPLATES,
                        TabIndex.NETWORK, TabIndex.SERVICES,
                        TabIndex.HOST_DISKS, TabIndex.SNAPSHOTS,
                        TabIndex.HEALTH, TabIndex.VM_SNAPSHOTS,
                        TabIndex.VM_BACKUP, TabIndex.BACKUP_JOBS,
                        TabIndex.ACCESS, TabIndex.HA):
                self.tabs.setTabVisible(idx, False)

            if obj_type == "cluster_folder":
                self._host_tabs.show_cluster_folder(obj_name)
            elif obj_type == "storage_folder":
                self._storage_tabs.show_storage_folder()
            elif obj_type == "standalone_folder":
                self._host_tabs.show_standalone_folder(obj_name)
            elif obj_type == "cluster":
                self._host_tabs.show_cluster(obj_name)
            elif obj_type == "group":
                self._host_tabs.show_group(obj_name)
            elif obj_type == "host":
                self._host_tabs.show_host_info(obj_name, data)
            elif obj_type == "pool":
                self._vm_tabs.show_pool_info(obj_name)
            elif obj_type == "vm":
                self._vm_tabs.show_vm_info_init(obj_name, data, gen)
            elif obj_type == "storage":
                self._storage_tabs.show_storage_detail(obj_name, data)

        except Exception as exc:
            logger.debug("show_details error", exc_info=True)
            self.config_update_result.emit(
                tr("Error: {err}").format(err=str(exc)[:100])
            )
            self.detail_label.setText(tr("Error: {name}").format(name=obj_name))
            self.detail_sublabel.setText("")
            self.detail_sublabel.setVisible(False)
            self.info_label.setText(tr("An error occurred while loading information"))
            self.info_stack.setCurrentIndex(0)

    def _build_obj_id(self, obj_type, obj_name, data):
        """Build a typed ID for the current object based on type."""
        if obj_type == "host":
            host_name = (data.host_name if data else "") or obj_name
            return HostId(host_name, obj_name)
        elif obj_type == "vm":
            host_name = (data.host_name if data else "") or (data.node if data else "")
            vmid = data.vmid if data else 0
            return VmId(host_name, vmid)
        elif obj_type == "storage":
            host_name = (data.get("host_name") if data else "") or ""
            cluster = (data.get("cluster") if data else "") or ""
            node = data.get("node", "") if data else ""
            if not node:
                for s in self.all_storages:
                    if s.storage != obj_name:
                        continue
                    if host_name and s.host_name == host_name:
                        node = s.node
                        break
                    if cluster and s.cluster == cluster:
                        node = s.node
                        host_name = s.host_name or host_name
                        break
            return StorageId(host_name, node, obj_name)
        return obj_name

    def refresh_current_view(self):
        if self.current_obj_type is None:
            return
        self._ensure_tabs()
        saved_tab = self.tabs.currentIndex()

        if self.current_obj_type in ("standalone_folder", "cluster_folder", "storage_folder"):
            if self.current_obj_type == "standalone_folder":
                self._host_tabs.show_standalone_folder("")
            elif self.current_obj_type == "cluster_folder":
                self._host_tabs.show_cluster_folder("")
            elif self.current_obj_type == "storage_folder":
                self._storage_tabs.show_storage_folder()
        elif self.current_obj_type == "cluster":
            hosts = []
            for node in self.all_nodes:
                host_name = node.host_name
                cfg = self._cfg_by_name.get(host_name)
                if cfg and cfg.get("cluster") == self.current_obj_name:
                    hosts.append(node)
            self._host_tabs.update_cluster_summary_cells(hosts)
        elif self.current_obj_type == "host":
            if isinstance(self.current_obj_id, HostId):
                host_data = self._node_repo.get(self.current_obj_id.host_name, self.current_obj_id.node) if self._node_repo else None
            else:
                host_data = None
            if host_data is None and self.current_obj_data:
                host_data = self.current_obj_data
            if host_data:
                node_name = self.current_obj_id.node if isinstance(self.current_obj_id, HostId) else self.current_obj_name
                if host_data.status_value == "error":
                    self._host_tabs.show_host_info(node_name, host_data)
                else:
                    self._host_tabs.update_host_cells(host_data)
                    self._host_tabs.fetch_host_metrics(host_data)
        elif self.current_obj_type == "pool":
            self._vm_tabs.update_pool_cells()
        elif self.current_obj_type == "vm":
            vm_data = self.current_obj_data
            if vm_data:
                if isinstance(self.current_obj_id, VmId):
                    fresh = self._vm_repo.get(self.current_obj_id.host_name, self.current_obj_id.vmid) if self._vm_repo else None
                else:
                    lookup_host = vm_data.host_name or vm_data.node
                    fresh = self._vm_repo.get(lookup_host, vm_data.vmid) if self._vm_repo else None
                if fresh:
                    self.current_obj_data = fresh
                    self.hardware_widget.set_vm_status(fresh.status_value)
                self._vm_tabs.update_vm_cells(fresh or vm_data)
                self._vm_tabs.show_vm_metrics(fresh or vm_data)
        elif self.current_obj_type == "storage":
            self._storage_tabs.update_storage_cells()

        self.tabs.setCurrentIndex(saved_tab)

    # ------------------------------------------------------------------
    # Delegates to tab controllers
    # ------------------------------------------------------------------
    def _on_vm_action(self, action):
        self._vm_tabs.on_vm_action(action)

    def _on_vm_extra_action(self, action):
        vm_data = self._last_vm_data
        if not vm_data:
            return
        host_name = vm_data.host_name or vm_data.node
        node = vm_data.node or host_name
        vmid = vm_data.vmid
        if action == "clone":
            self.vm_clone_requested.emit(host_name, node, vmid)
        elif action == "convert_template":
            self.vm_convert_requested.emit(host_name, node, vmid, "to_template")
        elif action == "convert_vm":
            self.vm_convert_requested.emit(host_name, node, vmid, "to_vm")

    def _update_action_buttons(self, vm_data=None):
        self._vm_tabs.update_action_buttons(vm_data)
        is_template = bool(vm_data and vm_data.template)
        is_qemu = vm_data is not None and vm_data.vm_type is VmType.QEMU
        is_running = vm_data is not None and vm_data.status is VmStatus.RUNNING
        clone_btn = self._extra_action_buttons.get("clone")
        if clone_btn:
            clone_btn.setVisible(bool(vm_data))
        tmpl_btn = self._extra_action_buttons.get("convert_template")
        if tmpl_btn:
            tmpl_btn.setVisible(bool(vm_data) and not is_template and is_qemu and not is_running)
        vm_btn = self._extra_action_buttons.get("convert_vm")
        if vm_btn:
            vm_btn.setVisible(bool(vm_data) and is_template and is_qemu)

    def _on_vm_console(self):
        self._vm_tabs.on_vm_console()

    def _on_vm_novnc(self):
        self._vm_tabs.on_vm_novnc()

    def _on_timeframe_changed(self, new_timeframe):
        if self.current_obj_type == "host" and isinstance(self.current_obj_id, HostId):
            host_data = self._node_repo.get(self.current_obj_id.host_name, self.current_obj_id.node) if self._node_repo else None
            if host_data is None and self.current_obj_data:
                host_data = self.current_obj_data
            if host_data:
                self._host_tabs.fetch_host_metrics(host_data)
        elif self._last_vm_data is not None:
            self._vm_tabs.show_vm_metrics(self._last_vm_data)

    def _on_storage_timeframe_changed(self, idx):
        self._storage_tabs.on_storage_timeframe_changed(idx)

    def _on_vm_config_change_requested(self, host_name, vmid_str, params):
        self._vm_tabs.on_vm_config_change_requested(host_name, vmid_str, params)

    def _switch_cluster_view(self, mode):
        self._cluster_view_mode = mode
        if mode == "clusters":
            self.summary_stack.setCurrentIndex(1)
            self._btn_clusters.setChecked(True)
            self._btn_nodes.setChecked(False)
        else:
            self.summary_stack.setCurrentIndex(2)
            self._btn_clusters.setChecked(False)
            self._btn_nodes.setChecked(True)

    # ------------------------------------------------------------------
    # Small helpers that tab controllers call back
    # ------------------------------------------------------------------
    def _set_storage_param(self, label, value):
        table = self.storage_detail_params
        for r in range(table.rowCount()):
            if table.item(r, 0) and table.item(r, 0).text() == label:
                set_cell_text(table, r, 1, str(value))
                break
