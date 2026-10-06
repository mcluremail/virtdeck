import warnings
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..icons import get_icon
from ..object_id import StorageId
from ..storage_actions import StorageMoveDialog, confirm_file_delete
from ..theme import Color
from ..utils import parse_pve_error
from ..widgets.time_range import (
    RangeDialog,
    covering_preset,
    filter_series,
    write_metrics_csv,
)
from ._constants import (
    _HAS_PG,
    TabIndex,
    _progress_style,
    ensure_pg,
    pg_loaded,
    register_plot,
)
from ._table_utils import (
    format_volsize,
    loading_label,
    make_filterable_table,
    make_loading_stack,
    make_table,
    safe_pct,
    set_cell_text,
    update_progress_bar,
)


class StorageToolbar(QWidget):
    """Toolbar with Upload/Download URL/Move/Copy/Remove buttons for storage content tables."""

    upload_requested = Signal()
    download_url_requested = Signal()
    move_requested = Signal()
    copy_requested = Signal()
    remove_requested = Signal()

    _UPLOAD_TYPES = {"iso", "vztmpl", "backup"}
    _DOWNLOAD_TYPES = {"iso", "vztmpl"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._content_type = ""

        self._upload_btn = QToolButton()
        self._upload_btn.setText(tr("Upload"))
        up_icon = get_icon("upload")
        if up_icon:
            self._upload_btn.setIcon(up_icon)
        self._upload_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._upload_btn.setEnabled(False)
        self._upload_btn.clicked.connect(self.upload_requested)
        self._upload_btn.setToolTip("")

        self._download_btn = QToolButton()
        self._download_btn.setText(tr("Download from URL"))
        dl_icon = get_icon("download")
        if dl_icon:
            self._download_btn.setIcon(dl_icon)
        self._download_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._download_btn.setEnabled(False)
        self._download_btn.clicked.connect(self.download_url_requested)
        self._download_btn.setToolTip("")

        self._move_btn = QPushButton(tr("Move"))
        self._move_btn.setEnabled(False)
        self._move_btn.clicked.connect(self.move_requested)
        self._move_btn.setToolTip("")

        self._copy_btn = QPushButton(tr("Copy"))
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self.copy_requested)
        self._copy_btn.setToolTip("")

        self._remove_btn = QPushButton(tr("Remove"))
        rm_icon = get_icon("remove")
        if rm_icon:
            self._remove_btn.setIcon(rm_icon)
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self.remove_requested)
        self._remove_btn.setToolTip("")

        layout = QHBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._upload_btn)
        layout.addWidget(self._download_btn)
        layout.addWidget(self._move_btn)
        layout.addWidget(self._copy_btn)
        layout.addWidget(self._remove_btn)
        layout.addStretch()

    def set_content_type(self, ct):
        self._content_type = ct
        can_upload = ct in self._UPLOAD_TYPES
        can_download = ct in self._DOWNLOAD_TYPES
        self._upload_btn.setEnabled(can_upload)
        self._download_btn.setEnabled(can_download)
        if not can_upload:
            self._upload_btn.setToolTip(tr("Cannot upload to this storage type"))
        else:
            self._upload_btn.setToolTip("")
        if not can_download:
            self._download_btn.setToolTip(tr("Download from URL is only available for ISO and template storages"))
        else:
            self._download_btn.setToolTip("")

    def set_has_selection(self, has_sel):
        can_upload = self._content_type in self._UPLOAD_TYPES
        can_download = self._content_type in self._DOWNLOAD_TYPES
        self._upload_btn.setEnabled(can_upload)
        self._download_btn.setEnabled(can_download)
        self._move_btn.setEnabled(has_sel)
        self._copy_btn.setEnabled(has_sel)
        self._remove_btn.setEnabled(has_sel)

    def set_context(self, node_name, storage_name, host_name, cfg, content_type):
        self._content_type = content_type
        can_upload = content_type in self._UPLOAD_TYPES
        can_download = content_type in self._DOWNLOAD_TYPES
        self._upload_btn.setEnabled(can_upload)
        self._download_btn.setEnabled(can_download)
        if not can_upload:
            self._upload_btn.setToolTip(tr("Cannot upload to this storage type"))
        else:
            self._upload_btn.setToolTip("")
        if not can_download:
            self._download_btn.setToolTip(tr("Download from URL is only available for ISO and template storages"))
        else:
            self._download_btn.setToolTip("")


class StorageTabs:
    def __init__(self, panel):
        self.panel = panel

    def build_storage_overview_tab(self):
        from ..widgets.card_list import CardList
        columns = {
            "key": "name",
            "title": "name",
            "fields": [
                ("type_text", 75),
                ("content_text", 225),
                ("location_text", 80),
                ("used_text", 100),
                ("total_text", 100),
                ("usage_text", 65),
            ],
        }
        self.panel.storage_list = CardList(columns)
        self.panel.storage_list.cardDoubleClicked.connect(self._on_storage_card_nav)
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        tab.setWidget(self.panel.storage_list)
        return tab

    def build_storage_detail_tab(self):
        panel = self.panel
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        panel.storage_detail_name = QLabel()
        panel.storage_detail_name.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(panel.storage_detail_name)

        panel.storage_detail_params = make_table(
            [tr("Parameter"), tr("Value")],
            [(QHeaderView.Stretch, None), (QHeaderView.Stretch, None)],
        )
        layout.addWidget(panel.storage_detail_params)

        panel.storage_detail_bar = QProgressBar()
        panel.storage_detail_bar.setRange(0, 100)
        panel.storage_detail_bar.setTextVisible(True)
        panel.storage_detail_bar.setMinimumHeight(24)
        layout.addWidget(panel.storage_detail_bar)

        panel.storage_detail_nodes_label = QLabel()
        panel.storage_detail_nodes_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(panel.storage_detail_nodes_label)

        panel.storage_detail_nodes_table = make_table(
            [tr("Node"), tr("Type"), tr("Content"), tr("Used"), tr("Total"), tr("Usage")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 65),
             (QHeaderView.Stretch, None), (QHeaderView.Interactive, 100),
             (QHeaderView.Interactive, 100), (QHeaderView.Interactive, 95)],
            sortable=True,
        )
        layout.addWidget(panel.storage_detail_nodes_table)

        layout.addStretch()
        # Content (params + fill bar + chart + per-node table) can exceed
        # the tab height at FullHD — wrap in a scroll area so nothing is
        # clipped.
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        tab.setWidget(widget)
        return tab

    def build_storage_monitoring_tab(self):
        """Fill-level chart on its own tab with a spinner while rrddata
        loads (moved out of Storage Detail in v2.11.2 — the combined
        content did not fit at FullHD)."""
        panel = self.panel
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        metrics_row = QHBoxLayout()
        metrics_row.addWidget(QLabel(tr("Fill level")))
        metrics_row.addStretch()
        panel.storage_detail_tf_combo = QComboBox()
        panel.storage_detail_tf_combo.addItem(tr("hour"), "hour")
        panel.storage_detail_tf_combo.addItem(tr("day"), "day")
        panel.storage_detail_tf_combo.addItem(tr("week"), "week")
        panel.storage_detail_tf_combo.addItem(tr("month"), "month")
        panel.storage_detail_tf_combo.addItem(tr("year"), "year")
        panel.storage_detail_tf_combo.addItem(tr("Custom"), "custom")
        panel._storage_custom_range = None
        from ...config import load_ui_state
        saved_tf = load_ui_state("metrics_timeframe") or "hour"
        for i in range(panel.storage_detail_tf_combo.count()):
            if panel.storage_detail_tf_combo.itemData(i) == saved_tf:
                panel.storage_detail_tf_combo.setCurrentIndex(i)
                break
        panel.storage_detail_tf_combo.currentIndexChanged.connect(
            panel._on_storage_timeframe_changed
        )
        metrics_row.addWidget(panel.storage_detail_tf_combo)
        panel.storage_export_btn = QToolButton()
        panel.storage_export_btn.setIcon(get_icon("export"))
        panel.storage_export_btn.setToolTip(tr("Export CSV"))
        panel.storage_export_btn.clicked.connect(self._on_storage_export_csv)
        metrics_row.addWidget(panel.storage_export_btn)
        layout.addLayout(metrics_row)

        panel.storage_detail_plot = QWidget()
        sd_plot_layout = QVBoxLayout(panel.storage_detail_plot)
        sd_plot_layout.setContentsMargins(0, 0, 0, 0)
        pg = pg_loaded() if _HAS_PG else None
        if pg is not None:
            date_axis = pg.DateAxisItem(orientation='bottom')
            panel.storage_plot_widget = pg.PlotWidget(
                axisItems={'bottom': date_axis}, title=tr("Used")
            )
            panel.storage_plot_widget.setLabel('left', 'GiB')
            panel.storage_plot_widget.showGrid(x=False, y=True, alpha=0.3)
            panel.storage_plot_widget.enableAutoRange(axis='y')
            panel.storage_plot_widget.setMouseEnabled(x=False, y=False)
            panel.storage_plot_widget.setMinimumHeight(260)
            panel.storage_plot_curve = panel.storage_plot_widget.plot(
                [], [], pen=pg.mkPen(Color.STATUS_WARN, width=2),
                fillLevel=0, fillBrush=pg.mkBrush(Color.STATUS_WARN + "33")
            )
            panel.storage_plot_curve._vd_token = "STATUS_WARN"
            register_plot(panel.storage_plot_widget)
            sd_plot_layout.addWidget(panel.storage_plot_widget)
            panel._storage_plot_deferred = False
        elif _HAS_PG:
            # pyqtgraph is still importing in the background thread;
            # the chart is built on first data (see _ensure_storage_plot).
            panel._storage_plot_deferred = True
        else:
            sd_plot_layout.addWidget(QLabel(tr("PyQtGraph not installed")))
            panel._storage_plot_deferred = False
        layout.addWidget(panel.storage_detail_plot)
        layout.addStretch()

        # Spinner while StorageMetricsWorker fetches rrddata.
        panel.storage_monitor_stack = make_loading_stack(widget)
        panel.storage_monitor_stack.setCurrentIndex(1)
        return panel.storage_monitor_stack

    def build_backups_tab(self):
        panel = self.panel
        table = make_table(
            [tr("VM"), tr("Type"), tr("Format"), tr("Size"), tr("Created")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 65),
             (QHeaderView.Interactive, 70), (QHeaderView.Interactive, 80),
             (QHeaderView.Stretch, None)],
            sortable=True,
        )
        panel.storage_backups_table = table
        table.cellDoubleClicked.connect(self._on_storage_table_nav)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_storage_backups_menu)
        panel._storage_backups_pbs = False
        toolbar = StorageToolbar()
        panel.storage_backups_toolbar = toolbar
        stack = QStackedWidget()
        loading = loading_label()
        stack.addWidget(loading)
        filter_table = make_filterable_table(table)
        filter_widget = filter_table
        stack.addWidget(filter_widget)
        stack.setCurrentIndex(0)
        panel.storage_backups_loading = loading
        panel.storage_backups_stack = stack
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        tab.setWidget(container)
        return tab

    def build_disks_vm_tab(self):
        panel = self.panel
        table = make_table(
            [tr("VM"), tr("Name"), tr("Volume"), tr("Bus"), tr("Size")],
            [(QHeaderView.Stretch, None), (QHeaderView.Stretch, None),
             (QHeaderView.Stretch, None), (QHeaderView.Interactive, 60),
             (QHeaderView.Interactive, 80)],
            sortable=True,
        )
        panel.storage_disks_table = table
        table.cellDoubleClicked.connect(self._on_storage_table_nav)
        toolbar = StorageToolbar()
        panel.storage_disks_toolbar = toolbar
        stack = QStackedWidget()
        loading = loading_label()
        stack.addWidget(loading)
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.storage_disks_loading = loading
        panel.storage_disks_stack = stack
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        tab.setWidget(container)
        return tab

    def build_iso_tab(self):
        panel = self.panel
        table = make_table(
            [tr("Volume"), tr("Format"), tr("Size"), tr("Modified")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 70),
             (QHeaderView.Interactive, 80), (QHeaderView.Stretch, None)],
            sortable=True,
        )
        panel.storage_iso_table = table
        toolbar = StorageToolbar()
        panel.storage_iso_toolbar = toolbar
        stack = QStackedWidget()
        loading = loading_label()
        stack.addWidget(loading)
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.storage_iso_loading = loading
        panel.storage_iso_stack = stack
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        tab.setWidget(container)
        return tab

    def build_templates_tab(self):
        panel = self.panel
        table = make_table(
            [tr("Volume"), tr("Format"), tr("Size"), tr("Modified")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 70),
             (QHeaderView.Interactive, 80), (QHeaderView.Stretch, None)],
            sortable=True,
        )
        panel.storage_tpl_table = table
        toolbar = StorageToolbar()
        panel.storage_tpl_toolbar = toolbar
        stack = QStackedWidget()
        loading = loading_label()
        stack.addWidget(loading)
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.storage_tpl_loading = loading
        panel.storage_tpl_stack = stack
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        tab.setWidget(container)
        return tab

    # --- Populate / fetch ---

    def populate_storage_table(self, storages):
        card_items = []
        for st in storages:
            name = st.storage
            cluster = st.cluster
            location = cluster if cluster else (st.node or st.host_name)
            if cluster:
                nav_key = ("storage", name, "cluster", cluster)
            else:
                nav_key = ("storage", name, "host", st.host_name)
            card_items.append({
                "name": name,
                "type_text": st.type_text or st.storage_type,
                "content_text": st.content_text,
                "location_text": location,
                "used_text": st.used_text,
                "total_text": st.total_text,
                "usage_text": st.usage_text,
                "nav_key": nav_key,
            })
        self.panel.storage_list.set_items(card_items)

    def _on_storage_card_nav(self, data):
        nav_key = data.get("nav_key")
        if nav_key:
            self.panel.navigate_requested.emit(nav_key)

    def _on_storage_table_nav(self, row, _col):
        for tbl in (self.panel.storage_disks_table, self.panel.storage_backups_table):
            item = tbl.item(row, 0)
            if not item:
                continue
            for role in (Qt.UserRole, Qt.UserRole + 1):
                key = item.data(role)
                if isinstance(key, tuple) and len(key) == 3:
                    self.panel.navigate_requested.emit(key)
                    return

    def show_storage_folder(self):
        panel = self.panel
        panel.detail_label.setText(tr("Storage"))
        panel.detail_sublabel.setText("")
        panel.detail_sublabel.setVisible(False)
        panel.tabs.setTabVisible(TabIndex.MONITOR, False)
        panel.tabs.setTabVisible(TabIndex.HARDWARE, False)
        panel.tabs.setTabVisible(TabIndex.STORAGES, True)
        panel.tabs.setCurrentIndex(TabIndex.STORAGES)
        seen = set()
        deduped = []
        for st in panel.all_storages:
            cluster = st.cluster
            if cluster:
                key = (st.storage, cluster)
            else:
                key = (st.storage, st.host_name)
            if key not in seen:
                seen.add(key)
                deduped.append(st)
        self.populate_storage_table(deduped)

    def show_storage_detail(self, storage_name, data):
        panel = self.panel
        cluster = data.get("cluster")
        host_name_filter = data.get("host_name")
        if cluster:
            title = f"{storage_name} @ {cluster}"
        elif host_name_filter:
            title = f"{storage_name} ({host_name_filter})"
        else:
            title = storage_name
        panel.detail_label.setText(title)
        panel.detail_sublabel.setText("")
        panel.detail_sublabel.setVisible(False)
        panel.tabs.setTabVisible(TabIndex.MONITOR, False)
        panel.tabs.setTabVisible(TabIndex.HARDWARE, False)
        panel.tabs.setTabVisible(TabIndex.OPTIONS, False)
        panel.tabs.setTabVisible(TabIndex.HISTORY, False)
        panel.tabs.setTabVisible(TabIndex.HOST_VMS, False)
        panel.tabs.setTabVisible(TabIndex.POOL_VMS, False)
        panel.tabs.setTabVisible(TabIndex.SUMMARY, False)
        panel.tabs.setTabVisible(TabIndex.STORAGES, False)
        panel.tabs.setTabVisible(TabIndex.HOST_STORAGE, False)
        panel.tabs.setTabVisible(TabIndex.STORAGE_DETAIL, True)
        panel.tabs.setTabVisible(TabIndex.STORAGE_MONITORING, True)
        panel.tabs.setTabVisible(TabIndex.BACKUPS, False)
        panel.tabs.setTabVisible(TabIndex.DISKS_VM, False)
        panel.tabs.setTabVisible(TabIndex.ISO, False)
        panel.tabs.setTabVisible(TabIndex.TEMPLATES, False)
        panel.tabs.setCurrentIndex(TabIndex.STORAGE_DETAIL)
        panel.storage_detail_name.setText(title)
        if cluster:
            filtered = [s for s in panel.all_storages
                        if s.storage == storage_name and s.cluster == cluster]
        elif host_name_filter:
            filtered = [s for s in panel.all_storages
                        if s.storage == storage_name and s.host_name == host_name_filter]
        else:
            filtered = [s for s in panel.all_storages if s.storage == storage_name]
        if not filtered:
            panel.storage_detail_params.setRowCount(0)
            panel.storage_detail_bar.setValue(0)
            panel.storage_detail_bar.setFormat(tr("No data"))
            panel.storage_detail_nodes_table.setRowCount(0)
            return
        rep = filtered[0]
        st_type = rep.storage_type
        content = rep.content_text
        total_used = sum(s.used_bytes for s in filtered)
        total_total = sum(s.total_bytes for s in filtered)
        total_pct = safe_pct(total_used, total_total)
        used_gb = round(total_used / (1024**3), 1) if total_used else 0
        total_gb = round(total_total / (1024**3), 1) if total_total else 0
        params = [
            (tr("Type"), st_type),
            (tr("Content"), content),
            (tr("Used"), f"{used_gb} GiB"),
            (tr("Total"), f"{total_gb} GiB"),
            (tr("Usage"), f"{total_pct}%"),
            (tr("Nodes"), str(len(filtered))),
        ]
        panel.storage_detail_params.setRowCount(len(params))
        for i, (k, v) in enumerate(params):
            panel.storage_detail_params.setItem(i, 0, QTableWidgetItem(k))
            panel.storage_detail_params.setItem(i, 1, QTableWidgetItem(str(v)))
        panel.storage_detail_params.resizeRowsToContents()
        for r in range(panel.storage_detail_params.rowCount()):
            if panel.storage_detail_params.rowHeight(r) > 22:
                panel.storage_detail_params.setRowHeight(r, 22)
        panel.storage_detail_bar.setStyleSheet(_progress_style(total_pct))
        panel.storage_detail_bar.setValue(total_pct)
        panel.storage_detail_bar.setFormat(f"{total_pct}%  ({used_gb}/{total_gb} GiB)")
        panel.storage_detail_nodes_label.setText(tr("Per node:") if cluster else tr("Node:"))
        panel.storage_detail_nodes_table.setRowCount(len(filtered))
        for i, st in enumerate(filtered):
            node = st.node
            panel.storage_detail_nodes_table.setItem(i, 0, QTableWidgetItem(node))
            panel.storage_detail_nodes_table.setItem(i, 1, QTableWidgetItem(st.storage_type))
            sc = st.content_text
            panel.storage_detail_nodes_table.setItem(i, 2, QTableWidgetItem(sc))
            used = st.used_bytes
            total = st.total_bytes
            u_gb = round(used / (1024**3), 1) if used else 0
            t_gb = round(total / (1024**3), 1) if total else 0
            pct = safe_pct(used, total)
            panel.storage_detail_nodes_table.setItem(i, 3, QTableWidgetItem(f"{u_gb} GiB"))
            panel.storage_detail_nodes_table.setItem(i, 4, QTableWidgetItem(f"{t_gb} GiB"))
            if total:
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(pct)
                bar.setStyleSheet(_progress_style(pct))
                bar.setFormat(f"{pct}%")
                panel.storage_detail_nodes_table.setCellWidget(i, 5, bar)
            else:
                bi = QTableWidgetItem("")
                bi.setFlags(Qt.ItemIsEnabled)
                panel.storage_detail_nodes_table.setItem(i, 5, bi)
        panel.storage_detail_nodes_table.resizeRowsToContents()
        for r in range(panel.storage_detail_nodes_table.rowCount()):
            if panel.storage_detail_nodes_table.rowHeight(r) > 24:
                panel.storage_detail_nodes_table.setRowHeight(r, 24)
        self._ensure_storage_plot(panel)
        curve = getattr(panel, "storage_plot_curve", None)
        if curve is not None:
            curve.setData([], [])
        self.fetch_storage_metrics(storage_name, filtered)
        self.load_storage_content(storage_name, filtered, rep)

    def load_storage_content(self, storage_name, filtered, rep):
        panel = self.panel
        allowed = rep.content_list
        tab_map = {
            "backup": (TabIndex.BACKUPS, tr("Backups"), [tr("VM"), tr("Type"), tr("Format"), tr("Size"), tr("Created")]),
            "images": (TabIndex.DISKS_VM, tr("VM Disks"), [tr("VM"), tr("Name"), tr("Volume"), tr("Bus"), tr("Size")]),
            "rootdir": (TabIndex.DISKS_VM, tr("VM Disks"), [tr("VM"), tr("Name"), tr("Volume"), tr("Bus"), tr("Size")]),
            "iso": (TabIndex.ISO, tr("ISO"), [tr("Volume"), tr("Format"), tr("Size"), tr("Modified")]),
            "vztmpl": (TabIndex.TEMPLATES, tr("Templates"), [tr("Volume"), tr("Format"), tr("Size"), tr("Modified")]),
            "snippets": (TabIndex.TEMPLATES, tr("Templates"), [tr("Volume"), tr("Format"), tr("Size"), tr("Modified")]),
        }
        panel._storage_backups_pbs = rep.storage_type == "pbs"
        if panel._storage_backups_pbs:
            tab_map["backup"] = (
                TabIndex.BACKUPS, tr("Backups"),
                [tr("Snapshot"), tr("Owner"), tr("Verify"),
                 tr("Size"), tr("Created"), tr("Notes")],
            )
        panel.storage_backups_table.setRowCount(0)
        panel.storage_disks_table.setRowCount(0)
        panel.storage_iso_table.setRowCount(0)
        panel.storage_tpl_table.setRowCount(0)
        seen_tabs = set()
        for ct in allowed:
            info = tab_map.get(ct)
            if info:
                idx, title, headers = info
                seen_tabs.add(idx)
                panel.tabs.setTabVisible(idx, True)
                panel.tabs.setTabText(idx, title)
                table_map = {
                    TabIndex.BACKUPS: panel.storage_backups_table,
                    TabIndex.DISKS_VM: panel.storage_disks_table,
                    TabIndex.ISO: panel.storage_iso_table,
                    TabIndex.TEMPLATES: panel.storage_tpl_table,
                }
                tbl = table_map.get(idx)
                if tbl:
                    tbl.setColumnCount(len(headers))
                    tbl.setHorizontalHeaderLabels(headers)
        loading_map = {
            TabIndex.BACKUPS: panel.storage_backups_stack,
            TabIndex.DISKS_VM: panel.storage_disks_stack,
            TabIndex.ISO: panel.storage_iso_stack,
            TabIndex.TEMPLATES: panel.storage_tpl_stack,
        }
        for idx in seen_tabs:
            stack = loading_map.get(idx)
            if stack:
                stack.setCurrentIndex(0)
                stack.widget(0).setText(tr("Loading..."))
        node_entry = filtered[0]
        node_name = node_entry.node
        host_name = node_entry.host_name
        cfg = panel._cfg_by_name.get(host_name)
        if not cfg:
            # Without a config no worker can be launched — replace the
            # "Loading..." placeholders instead of leaving them forever.
            for idx in seen_tabs:
                stack = loading_map.get(idx)
                if stack:
                    stack.widget(0).setText(tr("No data"))
            return
        panel._storage_backups_ctx = (storage_name, node_name, host_name, cfg)
        panel._storage_content_pending = {}
        workers_launched = 0
        from ..api.metrics import StorageContentListWorker
        for ct in allowed:
            if ct == "backup":
                self.fetch_storage_backups_simple(storage_name, node_name, host_name, cfg)
                continue
            if ct in tab_map:
                worker = StorageContentListWorker(cfg, node_name, storage_name, ct)
                worker.signals.result.connect(
                    lambda sn, content_type, data, h=host_name, nd=node_name, w=worker: (
                        self.on_storage_content_piece(sn, content_type, data, h, nd),
                        panel._workers_mgr.discard_worker(w)
                    )
                )
                worker.signals.error.connect(
                    lambda sn, content_type, err, h=host_name, nd=node_name, w=worker: (
                        self.on_storage_content_piece(sn, content_type, [], h, nd),
                        panel._workers_mgr.discard_worker(w)
                    )
                )
                panel._workers_mgr.run_worker(worker)
                workers_launched += 1
        if workers_launched > 0:
            panel._storage_content_pending[storage_name] = {ct: None for ct in allowed if ct in tab_map and ct != "backup"}
        if "images" in allowed or "rootdir" in allowed:
            host_names_with_sto = {s.host_name for s in filtered}
            node_vms = [vm for vm in panel.all_vms
                        if vm.node in {s.node for s in filtered}
                        and vm.host_name in host_names_with_sto]
            self.fetch_storage_disks_simple(storage_name, node_name, host_name, cfg, node_vms)

        toolbar_map = {
            "backup": panel.storage_backups_toolbar,
            "images": panel.storage_disks_toolbar,
            "rootdir": panel.storage_disks_toolbar,
            "iso": panel.storage_iso_toolbar,
            "vztmpl": panel.storage_tpl_toolbar,
            "snippets": panel.storage_tpl_toolbar,
        }
        connected = set()
        for ct in allowed:
            tb = toolbar_map.get(ct)
            if tb and id(tb) not in connected:
                tb.set_context(node_name, storage_name, host_name, cfg, ct)
                connected.add(id(tb))
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    for sig in (tb.upload_requested, tb.download_url_requested,
                                tb.move_requested, tb.copy_requested,
                                tb.remove_requested):
                        try:
                            sig.disconnect()
                        except (RuntimeError, TypeError):
                            pass
                tb.upload_requested.connect(lambda ct=ct, n=node_name, s=storage_name, h=host_name:
                    self._on_upload(n, s, h, ct))
                tb.download_url_requested.connect(lambda ct=ct, n=node_name, s=storage_name, h=host_name:
                    self._on_download_url(n, s, h, ct))
                tb.move_requested.connect(lambda n=node_name, s=storage_name, h=host_name:
                    self._on_move(n, s, h))
                tb.copy_requested.connect(lambda n=node_name, s=storage_name, h=host_name:
                    self._on_move(n, s, h, mode="copy"))
                tb.remove_requested.connect(lambda n=node_name, s=storage_name, h=host_name:
                    self._on_remove_file(n, s, h))
                table_map_tb = {
                    panel.storage_backups_toolbar: panel.storage_backups_table,
                    panel.storage_disks_toolbar: panel.storage_disks_table,
                    panel.storage_iso_toolbar: panel.storage_iso_table,
                    panel.storage_tpl_toolbar: panel.storage_tpl_table,
                }
                tbl = table_map_tb.get(tb)
                if tbl:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        try:
                            tbl.itemSelectionChanged.disconnect()
                        except (RuntimeError, TypeError):
                            pass
                    tbl.itemSelectionChanged.connect(
                        lambda t=tbl, b=tb: b.set_has_selection(len(t.selectedItems()) > 0 and t.currentRow() >= 0)
                    )

    def on_storage_content_piece(self, storage_name, content_type, data, host_name="", node=""):
        panel = self.panel
        if panel.current_obj_type != "storage" or panel.current_obj_id != StorageId(host_name, node, storage_name):
            return
        pending = panel._storage_content_pending.get(storage_name)
        if pending:
            pending[content_type] = data
            if all(v is not None for v in pending.values()):
                del panel._storage_content_pending[storage_name]
                self.render_storage_content(storage_name, pending)

    def render_storage_content(self, storage_name, pending):
        panel = self.panel
        for ct, items in pending.items():
            if ct == "iso" and items:
                panel.storage_iso_stack.setCurrentIndex(1)
                self.populate_content_table(panel.storage_iso_table, items, "iso")
            elif ct == "iso":
                panel.storage_iso_stack.widget(0).setText(tr("No data"))
                panel.storage_iso_stack.setCurrentIndex(0)
                panel.storage_iso_table.setRowCount(0)
            elif ct in ("vztmpl", "snippets") and items:
                panel.storage_tpl_stack.setCurrentIndex(1)
                self.populate_content_table(panel.storage_tpl_table, items, "template")
            elif ct in ("vztmpl", "snippets"):
                panel.storage_tpl_stack.widget(0).setText(tr("No data"))
                panel.storage_tpl_stack.setCurrentIndex(0)
                panel.storage_tpl_table.setRowCount(0)

    def populate_content_table(self, table, items, icon_type=None):
        table.setRowCount(len(items))
        for i, vol in enumerate(items):
            volid_item = QTableWidgetItem(vol.get("volid", ""))
            if icon_type:
                volid_item.setIcon(get_icon(icon_type))
            table.setItem(i, 0, volid_item)
            table.setItem(i, 1, QTableWidgetItem(vol.get("format", "")))
            table.setItem(i, 2, QTableWidgetItem(format_volsize(vol.get("size", 0))))
            ctime = vol.get("ctime")
            if ctime:
                table.setItem(i, 3, QTableWidgetItem(datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")))
            else:
                mtime = vol.get("mtime")
                if mtime:
                    table.setItem(i, 3, QTableWidgetItem(datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")))
                else:
                    table.setItem(i, 3, QTableWidgetItem(""))
        table.resizeRowsToContents()
        for r in range(table.rowCount()):
            if table.rowHeight(r) > 24:
                table.setRowHeight(r, 24)

    def on_storage_timeframe_changed(self, idx):
        panel = self.panel
        tf = panel.storage_detail_tf_combo.currentData()
        if tf == "custom":
            dlg = RangeDialog(panel)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                # Cancelled: revert without refetching.
                prev = idx - 1 if idx > 0 else idx + 1
                panel.storage_detail_tf_combo.blockSignals(True)
                panel.storage_detail_tf_combo.setCurrentIndex(prev)
                panel.storage_detail_tf_combo.blockSignals(False)
                return
            panel._storage_custom_range = dlg.values()
        else:
            panel._storage_custom_range = None
        if panel.current_obj_type == "storage" and isinstance(panel.current_obj_id, StorageId):
            sid = panel.current_obj_id
            storage_name = sid.storage
            host_name_filter = sid.host_name
            data = panel.current_obj_data or {}
            cluster = data.get("cluster")
            if cluster:
                filtered = [s for s in panel.all_storages
                            if s.storage == storage_name and s.cluster == cluster]
            elif host_name_filter:
                filtered = [s for s in panel.all_storages
                            if s.storage == storage_name and s.host_name == host_name_filter]
            else:
                filtered = [s for s in panel.all_storages if s.storage == storage_name]
            if filtered:
                self.fetch_storage_metrics(storage_name, filtered)

    def fetch_storage_metrics(self, storage_name, filtered):
        panel = self.panel
        node_entry = filtered[0]
        node_name = node_entry.node
        host_name = node_entry.host_name
        cfg = panel._cfg_by_name.get(host_name)
        if not cfg:
            return
        timeframe = panel.storage_detail_tf_combo.currentData()
        rng = getattr(panel, "_storage_custom_range", None)
        fetch_tf = timeframe
        if timeframe == "custom" and rng:
            s, e = rng
            fetch_tf = covering_preset(s, e)
        else:
            rng = None
        self._ensure_storage_plot(panel)
        curve = getattr(panel, "storage_plot_curve", None)
        if curve is not None:
            curve.setData([], [])
        # Spinner while the rrddata request runs.
        panel.storage_monitor_stack.setCurrentIndex(0)
        from ..api.metrics import StorageMetricsWorker
        worker = StorageMetricsWorker(cfg, node_name, storage_name, fetch_tf)
        sid = StorageId(host_name, node_name, storage_name)
        worker.signals.data_fetched.connect(
            lambda tf, nn, md, w=worker, sid=sid, rng=rng: (
                self.on_storage_metrics_fetched(tf, nn, md, sid, rng),
                panel._workers_mgr.discard_worker(w)
            )
        )
        worker.signals.error_occurred.connect(
            lambda err, w=worker: (
                panel.storage_monitor_stack.setCurrentIndex(1),
                panel._workers_mgr.discard_worker(w)
            )
        )
        panel._workers_mgr.run_worker(worker)

    def _ensure_storage_plot(self, panel):
        """Build the storage usage chart if it was deferred (pg warm-up)."""
        if not panel._storage_plot_deferred:
            return
        pg = ensure_pg()
        if pg is None:
            return
        panel._storage_plot_deferred = False
        date_axis = pg.DateAxisItem(orientation='bottom')
        panel.storage_plot_widget = pg.PlotWidget(
            axisItems={'bottom': date_axis}, title=tr("Used")
        )
        panel.storage_plot_widget.setLabel('left', 'GiB')
        panel.storage_plot_widget.showGrid(x=False, y=True, alpha=0.3)
        panel.storage_plot_widget.enableAutoRange(axis='y')
        panel.storage_plot_widget.setMouseEnabled(x=False, y=False)
        panel.storage_plot_widget.setMinimumHeight(260)
        panel.storage_plot_curve = panel.storage_plot_widget.plot(
            [], [], pen=pg.mkPen(Color.STATUS_WARN, width=2),
            fillLevel=0, fillBrush=pg.mkBrush(Color.STATUS_WARN + "33")
        )
        panel.storage_plot_curve._vd_token = "STATUS_WARN"
        register_plot(panel.storage_plot_widget)
        panel.storage_detail_plot.layout().addWidget(panel.storage_plot_widget)

    def on_storage_metrics_fetched(self, timeframe, node_name, metrics_dict, sid=None, rng=None):
        panel = self.panel
        panel.storage_monitor_stack.setCurrentIndex(1)
        if sid is None or panel.current_obj_type != "storage" or panel.current_obj_id != sid:
            return
        self._ensure_storage_plot(panel)
        curve = getattr(panel, "storage_plot_curve", None)
        if curve is None or not metrics_dict.get("usage"):
            return
        usage = metrics_dict["usage"]
        if rng:
            s, e = rng
            usage = filter_series(usage, s, e)
        # Keep the visible points for CSV export.
        panel._storage_last_usage = usage
        times = [pt["time"] for pt in usage]
        # StorageMetricsWorker already converted bytes to GiB.
        values = [pt["value"] for pt in usage]
        curve.setData(times, values)

    def _on_storage_export_csv(self):
        panel = self.panel
        usage = getattr(panel, "_storage_last_usage", None)
        if not usage:
            return
        path, _ = QFileDialog.getSaveFileName(
            panel, tr("Export CSV"), "storage_usage.csv", "CSV (*.csv)"
        )
        if not path:
            return
        write_metrics_csv(path, {"used_gib": usage})

    def fetch_storage_backups_simple(self, storage_name, node_name, host_name, cfg):
        panel = self.panel
        from ..api.metrics import StorageBackupWorker
        worker = StorageBackupWorker(cfg, node_name, storage_name)
        worker.signals.backups_ready.connect(
            lambda sn, data, w=worker: (
                self.on_storage_backups(sn, data, host_name, node_name),
                panel._workers_mgr.discard_worker(w)
            )
        )
        worker.signals.backups_error.connect(
            lambda sn, err, w=worker: (
                self.on_storage_backups(sn, [], host_name, node_name),
                panel._workers_mgr.discard_worker(w)
            )
        )
        panel._workers_mgr.run_worker(worker)

    def on_storage_backups(self, storage_name, backups, host_name="", node=""):
        panel = self.panel
        if panel.current_obj_type != "storage" or panel.current_obj_id != StorageId(host_name, node, storage_name):
            return
        if backups:
            panel.storage_backups_stack.setCurrentIndex(1)
            self.populate_storage_backups_table(backups, host_name, node)
        else:
            panel.storage_backups_stack.widget(0).setText(tr("No data"))
            panel.storage_backups_stack.setCurrentIndex(0)
            panel.storage_backups_table.setRowCount(0)

    def populate_storage_backups_table(self, backups, host_name="", node=""):
        table = self.panel.storage_backups_table
        if getattr(self.panel, "_storage_backups_pbs", False):
            self._populate_storage_backups_pbs(backups, host_name, node)
            return
        table.setRowCount(len(backups))
        for i, b in enumerate(backups):
            vm_item = QTableWidgetItem(f"VM {b.get('vmid', '')}")
            vm_item.setIcon(get_icon("backup"))
            volid = b.get("volid", "")
            if volid:
                vm_item.setData(Qt.UserRole, volid)
            vmid = b.get("vmid")
            if host_name and vmid is not None:
                try:
                    vm_item.setData(Qt.UserRole + 1, (host_name, int(vmid), node))
                except (ValueError, TypeError):
                    pass
            table.setItem(i, 0, vm_item)
            table.setItem(i, 1, QTableWidgetItem(b.get("subtype") or b.get("type", "")))
            table.setItem(i, 2, QTableWidgetItem(b.get("format", "")))
            size = b.get("size", 0) or 0
            table.setItem(i, 3, QTableWidgetItem(format_volsize(size) if size else "0"))
            ctime = b.get("ctime")
            if ctime:
                table.setItem(i, 4, QTableWidgetItem(datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")))
            else:
                table.setItem(i, 4, QTableWidgetItem(""))
        table.resizeRowsToContents()
        for r in range(table.rowCount()):
            if table.rowHeight(r) > 24:
                table.setRowHeight(r, 24)

    def _populate_storage_backups_pbs(self, backups, host_name="", node=""):
        """Populate the Backups table for PBS storages (snapshot columns)."""
        from ...domain.backup import BackupSnapshot

        table = self.panel.storage_backups_table
        table.setRowCount(len(backups))
        for i, b in enumerate(backups):
            snap = BackupSnapshot.from_content_item(b)
            name_item = QTableWidgetItem(snap.snapshot_name)
            name_item.setIcon(get_icon("backup"))
            name_item.setData(Qt.UserRole, snap.volid)
            name_item.setToolTip(snap.volid)
            if snap.vmid is not None and host_name:
                name_item.setData(Qt.UserRole + 1, (host_name, snap.vmid, node))
            table.setItem(i, 0, name_item)
            table.setItem(i, 1, QTableWidgetItem(snap.owner))
            verify_item = QTableWidgetItem(snap.verify or "—")
            if snap.verify == "failed":
                verify_item.setForeground(QBrush(QColor(Color.DANGER)))
            table.setItem(i, 2, verify_item)
            size = snap.size_bytes
            table.setItem(i, 3, QTableWidgetItem(format_volsize(size) if size else "0"))
            created = snap.time.astimezone().strftime("%Y-%m-%d %H:%M") if snap.time else ""
            table.setItem(i, 4, QTableWidgetItem(created))
            notes_item = QTableWidgetItem(snap.notes)
            notes_item.setToolTip(snap.notes)
            table.setItem(i, 5, notes_item)
        table.resizeRowsToContents()
        for r in range(table.rowCount()):
            if table.rowHeight(r) > 24:
                table.setRowHeight(r, 24)

    def _on_storage_backups_menu(self, pos):
        panel = self.panel
        table = panel.storage_backups_table
        row = table.rowAt(pos.y())
        if row < 0:
            return
        item = table.item(row, 0)
        if not item:
            return
        volid = item.data(Qt.UserRole)
        if not volid:
            return
        menu = QMenu(table)
        restore_act = menu.addAction(get_icon("restore"), tr("Restore"))
        del_act = menu.addAction(get_icon("remove"), tr("Delete"))
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen == restore_act:
            self._restore_storage_backup(volid)
        elif chosen == del_act:
            self._delete_storage_backup(volid)

    def _storage_backup_vm_type(self, volid):
        """Guest type for a backup volid: PBS snapshot path or vzdump name."""
        from ...domain.backup import parse_pbs_volid

        pbs = parse_pbs_volid(volid)
        if pbs:
            return pbs["vm_type"]
        return "lxc" if "vzdump-lxc" in volid else "qemu"

    def _restore_storage_backup(self, volid):
        panel = self.panel
        ctx = getattr(panel, "_storage_backups_ctx", None)
        if not ctx:
            return
        storage_name, node_name, host_name, cfg = ctx
        vm_type = self._storage_backup_vm_type(volid)
        used_vmids = {v.vmid for v in panel.all_vms if v.vmid}
        next_vmid = next((v for v in range(100, 999999999) if v not in used_vmids), 100)
        from ..vm_restore_dialog import VmRestoreDialog
        storages = [s for s in panel.all_storages
                    if s.node == node_name and s.host_name == host_name]
        dlg = VmRestoreDialog(panel, volid=volid, vm_type=vm_type,
                              storages=storages, next_vmid=next_vmid)
        if dlg.exec() != VmRestoreDialog.Accepted:
            return
        params = dlg.get_params()
        from ...backend import VmRestoreWorker
        worker = VmRestoreWorker(
            cfg, node_name, params["vmid"], vm_type, volid,
            storage=params["storage"],
            name=params["name"],
            force=params["force"],
            unique=params["unique"],
        )
        key = f"restore:{host_name}:{params['vmid']}"
        panel.transfer_started.emit(key, tr("Restore VM {vmid}").format(vmid=params["vmid"]))
        worker.signals.result.connect(lambda msg, k=key, w=worker: (
            panel.transfer_finished.emit(k, True, msg),
            panel.config_update_result.emit(msg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, k=key, w=worker: (
            panel.transfer_finished.emit(k, False, err),
            panel.config_update_result.emit(parse_pve_error(err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_worker(worker)

    def _delete_storage_backup(self, volid):
        panel = self.panel
        ctx = getattr(panel, "_storage_backups_ctx", None)
        if not ctx:
            return
        storage_name, node_name, host_name, cfg = ctx
        if not confirm_file_delete(volid, parent=panel):
            return
        from ...backend import StorageContentDeleteWorker
        worker = StorageContentDeleteWorker(cfg, node_name, storage_name, volid, timeout=600)
        key = f"deletebackup:{host_name}:{volid}"
        panel.transfer_started.emit(key, tr("Delete backup {volid}").format(volid=volid))
        worker.signals.result.connect(lambda msg, k=key, w=worker: (
            panel.transfer_finished.emit(k, True, msg),
            panel.config_update_result.emit(msg),
            self._refresh_storage_backups(),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, k=key, w=worker: (
            panel.transfer_finished.emit(k, False, err),
            panel.config_update_result.emit(parse_pve_error(err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_worker(worker)

    def _refresh_storage_backups(self):
        panel = self.panel
        ctx = getattr(panel, "_storage_backups_ctx", None)
        if not ctx or panel.current_obj_type != "storage":
            return
        storage_name, node_name, host_name, cfg = ctx
        panel.storage_backups_stack.setCurrentIndex(0)
        panel.storage_backups_loading.setText(tr("Loading..."))
        self.fetch_storage_backups_simple(storage_name, node_name, host_name, cfg)

    def fetch_storage_disks_simple(self, storage_name, node_name, host_name, cfg, node_vms):
        panel = self.panel
        from ..api.metrics import StorageDisksWorker
        worker = StorageDisksWorker(cfg, node_name, storage_name, node_vms)
        worker.signals.disks_ready.connect(
            lambda sn, data, h=host_name, nd=node_name, w=worker: (
                self.on_storage_disks(sn, data, h, nd),
                panel._workers_mgr.discard_worker(w)
            )
        )
        worker.signals.disks_error.connect(
            lambda sn, err, h=host_name, nd=node_name, w=worker: (
                self.on_storage_disks(sn, [], h, nd),
                panel._workers_mgr.discard_worker(w)
            )
        )
        panel._workers_mgr.run_worker(worker)

    def on_storage_disks(self, storage_name, disks, host_name="", node=""):
        panel = self.panel
        if panel.current_obj_type != "storage" or panel.current_obj_id != StorageId(host_name, node, storage_name):
            return
        if disks:
            panel.storage_disks_stack.setCurrentIndex(1)
            self.populate_storage_disks_table(disks)
        else:
            panel.storage_disks_stack.widget(0).setText(tr("No data"))
            panel.storage_disks_stack.setCurrentIndex(0)
            panel.storage_disks_table.setRowCount(0)

    def populate_storage_disks_table(self, disks):
        table = self.panel.storage_disks_table
        table.setRowCount(len(disks))
        for i, d in enumerate(disks):
            vmid_item = QTableWidgetItem(str(d.get("vmid", "")))
            vmid_item.setIcon(get_icon("disk"))
            host_name = d.get("host_name", "")
            node = d.get("node", "")
            vmid = d.get("vmid")
            if host_name and vmid is not None:
                try:
                    vmid_item.setData(Qt.UserRole, (host_name, int(vmid), node))
                except (ValueError, TypeError):
                    pass
            table.setItem(i, 0, vmid_item)
            table.setItem(i, 1, QTableWidgetItem(d.get("vm_name", "")))
            table.setItem(i, 2, QTableWidgetItem(d.get("volid", "")))
            table.setItem(i, 3, QTableWidgetItem(d.get("bus", "")))
            table.setItem(i, 4, QTableWidgetItem(format_volsize(d.get("size", 0))))
        table.resizeRowsToContents()
        for r in range(table.rowCount()):
            if table.rowHeight(r) > 24:
                table.setRowHeight(r, 24)

    def update_storage_cells(self):
        panel = self.panel
        if not isinstance(panel.current_obj_id, StorageId):
            return
        sid = panel.current_obj_id
        storage_name = sid.storage
        host_name_filter = sid.host_name
        data = panel.current_obj_data or {}
        cluster = data.get("cluster")
        if cluster:
            filtered = [s for s in panel.all_storages
                        if s.storage == storage_name and s.cluster == cluster]
        elif host_name_filter:
            filtered = [s for s in panel.all_storages
                        if s.storage == storage_name and s.host_name == host_name_filter]
        else:
            filtered = [s for s in panel.all_storages if s.storage == storage_name]
        if not filtered:
            return
        total_used = sum(s.used_bytes for s in filtered)
        total_total = sum(s.total_bytes for s in filtered)
        total_pct = safe_pct(total_used, total_total)
        used_gb = round(total_used / (1024**3), 1) if total_used else 0
        total_gb = round(total_total / (1024**3), 1) if total_total else 0

        panel._set_storage_param(tr("Used"), f"{used_gb} GiB")
        panel._set_storage_param(tr("Total"), f"{total_gb} GiB")
        panel._set_storage_param(tr("Usage"), f"{total_pct}%")
        panel.storage_detail_bar.setStyleSheet(_progress_style(total_pct))
        panel.storage_detail_bar.setValue(total_pct)
        panel.storage_detail_bar.setFormat(f"{total_pct}%  ({used_gb}/{total_gb} GiB)")

        node_table = panel.storage_detail_nodes_table
        node_by_storage = {}
        for st in filtered:
            node_by_storage[st.node] = st
        for r in range(node_table.rowCount()):
            name_item = node_table.item(r, 0)
            if name_item is None:
                continue
            st = node_by_storage.get(name_item.text())
            if st is None:
                continue
            used = st.used_bytes
            total = st.total_bytes
            u_gb = round(used / (1024**3), 1) if used else 0
            t_gb = round(total / (1024**3), 1) if total else 0
            pct = safe_pct(used, total)
            set_cell_text(node_table, r, 3, f"{u_gb} GiB")
            set_cell_text(node_table, r, 4, f"{t_gb} GiB")
            old_bar = node_table.cellWidget(r, 5)
            if isinstance(old_bar, QProgressBar):
                update_progress_bar(old_bar, pct, f"{pct}%")

    # --- File operations: Upload / Move / Remove ---

    def _get_selected_volid(self, table):
        """Extract volid from the selected row of a storage content table.
        Different tables store volid in different columns:
        - ISO/Templates: column 0 (Volume)
        - VM Disks: column 2 (Volume)
        - Backups: column 0 shows 'VM {vmid}', volid is not displayed;
          we reconstruct it from backup data.
        """
        row = table.currentRow()
        if row < 0:
            return None, None
        if table is self.panel.storage_disks_table:
            item = table.item(row, 2)
        else:
            item = table.item(row, 0)
        if not item:
            return None, None
        volid = item.data(Qt.UserRole) or item.text()
        return row, volid

    def _get_active_table(self, node_name, storage_name):
        """Return the currently visible content table based on active tab."""
        panel = self.panel
        idx = panel.tabs.currentIndex()
        if idx == TabIndex.BACKUPS:
            return panel.storage_backups_table
        if idx == TabIndex.DISKS_VM:
            return panel.storage_disks_table
        if idx == TabIndex.ISO:
            return panel.storage_iso_table
        if idx == TabIndex.TEMPLATES:
            return panel.storage_tpl_table
        return None

    def _on_upload(self, node_name, storage_name, host_name, content_type):
        panel = self.panel
        cfg = panel._cfg_by_name.get(host_name)
        if not cfg:
            return
        if content_type == "images":
            QMessageBox.information(self.panel, tr("Upload"), tr("Cannot upload to this storage type"))
            return
        file_filter_map = {
            "iso": tr("ISO images (*.iso);;All files (*.*)"),
            "vztmpl": tr("Templates (*.tar.gz *.tar.xz);;All files (*.*)"),
            "backup": tr("Backups (*.vma *.vma.gz *.vma.zst);;All files (*.*)"),
            "snippets": tr("All files (*.*)"),
        }
        path, _ = QFileDialog.getOpenFileName(
            self.panel, tr("Select file to upload"), "",
            file_filter_map.get(content_type, tr("All files (*.*)"))
        )
        if not path:
            return
        import os
        file_name = os.path.basename(path)
        key = f"upload:{storage_name}:{file_name}"
        panel.transfer_started.emit(key, tr("Upload {name}").format(name=file_name))
        from ...backend import StorageUploadWorker
        worker = StorageUploadWorker(cfg, node_name, storage_name, content_type, path)
        worker.signals.progress.connect(
            lambda pct, k=key: panel.transfer_progress.emit(k, pct)
        )
        worker.signals.result.connect(
            lambda msg, k=key: (
                panel.transfer_finished.emit(k, True, msg),
                panel.config_update_result.emit(msg),
                self._reload_storage_content(),
                panel._workers_mgr.discard_worker(worker),
            )
        )
        worker.signals.error.connect(
            lambda err, k=key: (
                panel.transfer_finished.emit(k, False, err),
                panel.config_update_result.emit(tr("Upload failed: {err}").format(err=err), ),
                panel._workers_mgr.discard_worker(worker),
            )
        )
        panel._workers_mgr.run_worker(worker)

    def _on_download_url(self, node_name, storage_name, host_name, content_type):
        panel = self.panel
        cfg = panel._cfg_by_name.get(host_name)
        if not cfg:
            return
        if content_type not in ("iso", "vztmpl"):
            return
        dlg = QDialog(self.panel)
        dlg.setWindowTitle(tr("Download from URL"))
        dlg.setMinimumWidth(450)
        layout = QFormLayout(dlg)
        url_edit = QLineEdit()
        url_edit.setPlaceholderText("https://...")
        filename_edit = QLineEdit()
        filename_edit.setPlaceholderText(tr("Auto-detect from URL"))
        checksum_edit = QLineEdit()
        checksum_edit.setPlaceholderText(tr("Optional"))
        verify_cb = QCheckBox()
        verify_cb.setChecked(True)
        layout.addRow(tr("URL:"), url_edit)
        layout.addRow(tr("Filename:"), filename_edit)
        layout.addRow(tr("Checksum:"), checksum_edit)
        layout.addRow(tr("Verify certificates"), verify_cb)
        btns = QHBoxLayout()
        ok_btn = QPushButton(tr("Download"))
        ok_btn.setEnabled(False)
        cancel_btn = QPushButton(tr("Cancel"))
        btns.addStretch()
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addRow(btns)
        cancel_btn.clicked.connect(dlg.reject)
        url_edit.textChanged.connect(lambda t: ok_btn.setEnabled(bool(t.strip())))
        ok_btn.clicked.connect(dlg.accept)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url = url_edit.text().strip()
        if not url:
            return
        filename = filename_edit.text().strip() or None
        checksum = checksum_edit.text().strip() or None
        verify = verify_cb.isChecked()
        display_name = filename or url.split("/")[-1].split("?")[0] or "file"
        key = f"download:{storage_name}:{display_name}"
        panel.transfer_started.emit(key, tr("Download {name}").format(name=display_name))
        from ...backend import StorageDownloadUrlWorker
        worker = StorageDownloadUrlWorker(
            cfg, node_name, storage_name, content_type, url,
            filename=filename, checksum=checksum, verify_certificates=verify
        )
        worker.signals.result.connect(
            lambda msg, k=key: (
                panel.transfer_finished.emit(k, True, msg),
                panel.config_update_result.emit(msg),
                self._reload_storage_content(),
                panel._workers_mgr.discard_worker(worker),
            )
        )
        worker.signals.error.connect(
            lambda err, k=key: (
                panel.transfer_finished.emit(k, False, err),
                panel.config_update_result.emit(tr("Download failed: {err}").format(err=err)),
                panel._workers_mgr.discard_worker(worker),
            )
        )
        panel._workers_mgr.run_worker(worker)

    def _on_move(self, node_name, storage_name, host_name, mode="move"):
        panel = self.panel
        cfg = panel._cfg_by_name.get(host_name)
        if not cfg:
            return
        table = self._get_active_table(node_name, storage_name)
        if not table:
            return
        _, volid = self._get_selected_volid(table)
        if not volid:
            return
        volid_full = volid
        if ":" not in volid and not volid.startswith(storage_name):
            volid_full = f"{storage_name}:{volid}"
        is_disk = table is panel.storage_disks_table
        target_storages = [
            s for s in panel.all_storages
            if s.node == node_name
            and s.host_name == host_name
            and s.storage != storage_name
        ]
        dlg = StorageMoveDialog(volid_full, target_storages, is_disk, self.panel, mode=mode)
        if dlg.exec() != QDialog.Accepted:
            return
        params = dlg.get_params()
        if not params["target_storage"]:
            return
        fail_msg = (tr("Copy failed: {err}") if mode == "copy"
                    else tr("Move failed: {err}"))
        from ...backend import StorageMoveWorker
        worker = StorageMoveWorker(
            cfg, node_name, storage_name, volid_full,
            params["target_storage"],
            params["target_vmid"],
            params["delete_source"],
        )
        worker.signals.result.connect(
            lambda msg, w=worker: (
                panel.config_update_result.emit(msg),
                self._reload_storage_content(),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.error.connect(
            lambda err, w=worker: (
                panel.config_update_result.emit(fail_msg.format(err=err)),
                panel._workers_mgr.discard_worker(w),
            )
        )
        panel._workers_mgr.run_worker(worker)

    def _on_remove_file(self, node_name, storage_name, host_name):
        panel = self.panel
        cfg = panel._cfg_by_name.get(host_name)
        if not cfg:
            return
        table = self._get_active_table(node_name, storage_name)
        if not table:
            return
        _, volid = self._get_selected_volid(table)
        if not volid:
            return
        volid_full = volid
        if ":" not in volid and not volid.startswith(storage_name):
            volid_full = f"{storage_name}:{volid}"
        if not confirm_file_delete(volid_full, self.panel):
            return
        from ...backend import StorageContentDeleteWorker
        worker = StorageContentDeleteWorker(cfg, node_name, storage_name, volid_full)
        worker.signals.result.connect(
            lambda msg, w=worker: (
                panel.config_update_result.emit(msg),
                self._reload_storage_content(),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.error.connect(
            lambda err, w=worker: (
                panel.config_update_result.emit(tr("Delete failed: {err}").format(err=err)),
                panel._workers_mgr.discard_worker(w),
            )
        )
        panel._workers_mgr.run_worker(worker)

    def _reload_storage_content(self):
        panel = self.panel
        if panel.current_obj_type != "storage" or not isinstance(panel.current_obj_id, StorageId):
            return
        sid = panel.current_obj_id
        storage_name = sid.storage
        host_name_filter = sid.host_name
        data = panel.current_obj_data or {}
        cluster = data.get("cluster")
        if cluster:
            filtered = [s for s in panel.all_storages
                        if s.storage == storage_name and s.cluster == cluster]
        elif host_name_filter:
            filtered = [s for s in panel.all_storages
                        if s.storage == storage_name and s.host_name == host_name_filter]
        else:
            filtered = [s for s in panel.all_storages if s.storage == storage_name]
        if filtered:
            rep = filtered[0]
            self.load_storage_content(storage_name, filtered, rep)
