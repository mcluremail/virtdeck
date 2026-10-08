from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...domain import QuorumState
from ..i18n import tr
from ..icons import get_icon
from ..object_id import HostId
from ..theme import Color
from ..utils import format_uptime as _format_uptime
from ..utils import status_text
from ._constants import TabIndex, _progress_style
from ._table_utils import (
    fit_table_height,
    loading_label,
    make_table,
    safe_pct,
)


class HostTabs:
    def __init__(self, panel):
        self.panel = panel

    @staticmethod
    def _host_subtitle(host_data, host_name):
        parts = []
        if not host_data:
            return parts
        status = host_data.status_value
        parts.append(status_text(status))
        pve_ver = host_data.pve_version_raw or ""
        if pve_ver:
            ver = pve_ver.split("/")[1] if "/" in pve_ver else pve_ver
            parts.append("pve " + ver.split("-")[0] if "-" in ver else "pve " + ver)
        uptime = host_data.uptime_seconds or 0
        if uptime:
            parts.append(_format_uptime(uptime) + " " + tr("uptime"))
        return parts

    def build_host_vm_tab(self):
        from ..widgets.card_list import CardList
        columns = {
            "key": "vmid",
            "dot": "status",
            "title": "name",
            "fields": [
                ("status_text", 90),
                ("cpu_text", 55),
                ("ram_text", 125),
                ("disk_text", 115),
                ("uptime_text", 125),
            ],
        }
        self.panel.host_vm_list = CardList(columns)
        self.panel.host_vm_list.cardDoubleClicked.connect(self._on_vm_card_nav)
        from ..widgets.metric_card import MetricCard
        self.panel.vm_stats_widget = QWidget()
        stats_grid = QGridLayout(self.panel.vm_stats_widget)
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setSpacing(8)
        self.panel.card_vm_total = MetricCard(tr("VMs"), "—")
        self.panel.card_vm_cpu = MetricCard(tr("CPU used"), "—", show_progress=True)
        self.panel.card_vm_ram = MetricCard(tr("RAM used"), "—", show_progress=True)
        stats_grid.addWidget(self.panel.card_vm_total, 0, 0)
        stats_grid.addWidget(self.panel.card_vm_cpu, 0, 1)
        stats_grid.addWidget(self.panel.card_vm_ram, 0, 2)
        self.panel.vm_stats_widget.setVisible(False)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.panel.vm_stats_widget)
        layout.addWidget(self.panel.host_vm_list, 1)
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        tab.setWidget(container)
        return tab

    def build_host_storage_tab(self):
        table = make_table(
            [tr("Name"), tr("Type"), tr("Content"), tr("Used"), tr("Total"), tr("Usage")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 65),
             (QHeaderView.Stretch, None), (QHeaderView.Interactive, 100),
             (QHeaderView.Interactive, 100), (QHeaderView.Interactive, 95)],
        )
        self.panel.host_storage_table = table
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(table)
        return widget

    def build_network_tab(self):
        loading = loading_label()
        table = make_table(
            [tr("Interface"), tr("Type"), tr("State"), tr("Method"), tr("Address"),
             tr("Gateway"), tr("Bridge ports"), tr("VLAN"), tr("MTU"), tr("Pending")],
            [(QHeaderView.Interactive, 100), (QHeaderView.Interactive, 65),
             (QHeaderView.Interactive, 50), (QHeaderView.Interactive, 65),
             (QHeaderView.Stretch, None), (QHeaderView.Interactive, 100),
             (QHeaderView.Stretch, None), (QHeaderView.Interactive, 50),
             (QHeaderView.Interactive, 55), (QHeaderView.Interactive, 65)],
        )
        table.setSortingEnabled(True)

        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(0, 0, 0, 0)
        tb_layout.setSpacing(4)
        add_btn = QPushButton(get_icon("add"), tr("Add"))
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._on_network_add)
        edit_btn = QPushButton(tr("Edit"))
        edit_btn.setMinimumHeight(28)
        edit_btn.clicked.connect(self._on_network_edit)
        delete_btn = QPushButton(get_icon("remove"), tr("Delete"))
        delete_btn.setMinimumHeight(28)
        delete_btn.clicked.connect(self._on_network_delete)
        apply_btn = QPushButton(tr("Apply"))
        apply_btn.setMinimumHeight(28)
        apply_btn.setStyleSheet(f"QPushButton {{ color: {Color.STATUS_OK}; font-weight: 600; }}")
        apply_btn.clicked.connect(self._on_network_apply)
        revert_btn = QPushButton(tr("Revert"))
        revert_btn.setMinimumHeight(28)
        revert_btn.clicked.connect(self._on_network_revert)
        tb_layout.addWidget(add_btn)
        tb_layout.addWidget(edit_btn)
        tb_layout.addWidget(delete_btn)
        tb_layout.addStretch()
        tb_layout.addWidget(apply_btn)
        tb_layout.addWidget(revert_btn)

        stack = QStackedWidget()
        stack.addWidget(loading)
        stack.addWidget(table)
        stack.setCurrentIndex(0)
        self.panel.host_network_loading = loading
        self.panel.host_network_table = table
        self.panel.host_network_stack = stack
        self.panel.host_network_add_btn = add_btn
        self.panel.host_network_edit_btn = edit_btn
        self.panel.host_network_delete_btn = delete_btn
        self.panel.host_network_apply_btn = apply_btn
        self.panel.host_network_revert_btn = revert_btn

        table.itemSelectionChanged.connect(
            lambda: self._on_network_selection_changed()
        )
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

    def build_services_tab(self):
        loading = loading_label()
        table = make_table(
            [tr("Service"), tr("State"), tr("Description")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 75),
             (QHeaderView.Stretch, None)],
        )
        stack = QStackedWidget()
        stack.addWidget(loading)
        stack.addWidget(table)
        stack.setCurrentIndex(0)
        self.panel.host_services_loading = loading
        self.panel.host_services_table = table
        self.panel.host_services_stack = stack
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(stack)
        tab.setWidget(container)
        return tab

    def build_host_disks_tab(self):
        loading = loading_label()
        table = make_table(
            [tr("Device"), tr("Type"), tr("Model"), tr("Size"), tr("Serial")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 65),
             (QHeaderView.Stretch, None), (QHeaderView.Interactive, 90),
             (QHeaderView.Stretch, None)],
        )
        stack = QStackedWidget()
        stack.addWidget(loading)
        stack.addWidget(table)
        stack.setCurrentIndex(0)
        self.panel.host_disks_loading = loading
        self.panel.host_disks_table = table
        self.panel.host_disks_stack = stack
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(stack)
        tab.setWidget(container)
        return tab

    def build_snapshots_tab(self):
        from PySide6.QtWidgets import QTreeWidget
        loading = loading_label()
        tree = QTreeWidget()
        tree.setHeaderLabels([
            tr("Snapshot"), tr("Description"), tr("Created"),
            tr("VM State"), tr("Size"), tr("Parent"),
        ])
        tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(True)
        tree.setColumnWidth(0, 200)
        tree.setColumnWidth(1, 200)
        tree.setColumnWidth(2, 160)
        tree.setColumnWidth(3, 80)
        tree.setColumnWidth(4, 100)
        tree.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        tree.header().setStretchLastSection(True)
        stack = QStackedWidget()
        stack.addWidget(loading)
        stack.addWidget(tree)
        stack.setCurrentIndex(0)
        self.panel.host_snapshots_loading = loading
        self.panel.host_snapshots_tree = tree
        self.panel.host_snapshots_stack = stack
        tree.itemDoubleClicked.connect(self._on_snap_tree_nav)
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(stack)
        tab.setWidget(container)
        return tab

    def build_health_tab(self):
        from ..widgets.card_list import CardList
        health_columns = {
            "key": "id",
            "dot": "severity",
            "title": "title",
            "fields": [
                ("message", 400),
            ],
        }
        self.panel.host_health_list = CardList(health_columns)
        loading = loading_label()
        stack = QStackedWidget()
        stack.addWidget(loading)
        stack.addWidget(self.panel.host_health_list)
        stack.setCurrentIndex(0)
        self.panel.host_health_loading = loading
        self.panel.host_health_stack = stack
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(stack)
        tab.setWidget(container)
        return tab

    def build_summary_tab(self):
        from ..widgets.card_list import CardList
        host_columns = {
            "key": "_key",
            "dot": "status",
            "title": "name",
            "title_width": 200,
            "header_labels": [
                (tr("Host"), 200),
                (tr("Status"), 80),
                (tr("Address"), 140),
                (tr("CPU"), 50),
                (tr("RAM"), 110),
                (tr("VMs"), 35),
                (tr("Uptime"), 90),
            ],
            "fields": [
                ("status_text", 80),
                ("address", 140),
                ("cpu_text", 50),
                ("ram_text", 110),
                ("vms_text", 35),
                ("uptime_text", 90),
            ],
        }
        self.panel.host_summary_list = CardList(host_columns, filterable=True)
        self.panel.host_summary_list.cardDoubleClicked.connect(self._on_host_card_nav)

        compare_columns = {
            "key": "_key",
            "dot": "status",
            "title": "name",
            "title_width": 140,
            "header_labels": [
                (tr("Node"), 140),
                (tr("Cluster"), 80),
                (tr("Status"), 70),
                (tr("CPU"), 50),
                (tr("RAM"), 95),
                (tr("Disk"), 90),
                (tr("VMs"), 35),
                (tr("Uptime"), 80),
            ],
            "fields": [
                ("cluster_text", 80),
                ("status_text", 70),
                ("cpu_text", 50),
                ("ram_text", 95),
                ("disk_text", 90),
                ("vms_text", 35),
                ("uptime_text", 80),
            ],
        }
        self.panel.node_compare_list = CardList(compare_columns, filterable=True)
        self.panel.node_compare_list.cardDoubleClicked.connect(self._on_host_card_nav)

        cluster_columns = {
            "key": "name",
            "title": "name",
            "title_width": 120,
            "header_labels": [
                (tr("Cluster"), 120),
                (tr("Hosts"), 70),
                (tr("VMs"), 70),
                (tr("CPU"), 55),
                (tr("RAM"), 125),
            ],
            "fields": [
                ("hosts_text", 70),
                ("vms_text", 70),
                ("cpu_text", 55),
                ("ram_text", 125),
            ],
        }
        self.panel.cluster_summary_list = CardList(cluster_columns)
        self.panel.cluster_summary_list.cardDoubleClicked.connect(self._on_cluster_card_nav)

        from PySide6.QtWidgets import QGridLayout, QScrollArea, QStackedWidget
        self.panel.summary_stack = QStackedWidget()
        self.panel.summary_stack.addWidget(self.panel.host_summary_list)
        self.panel.summary_stack.addWidget(self.panel.cluster_summary_list)
        self.panel.summary_stack.addWidget(self.panel.node_compare_list)

        self.panel.cluster_summary_cards = QWidget()
        cards_grid = QGridLayout(self.panel.cluster_summary_cards)
        cards_grid.setContentsMargins(0, 0, 0, 0)
        cards_grid.setSpacing(8)
        from ..widgets.metric_card import MetricCard
        self.panel.card_cluster_hosts = MetricCard(tr("Hosts"), "—")
        self.panel.card_cluster_vms = MetricCard(tr("VMs"), "—")
        self.panel.card_cluster_cpu = MetricCard(tr("CPU"), "—", show_progress=True)
        self.panel.card_cluster_ram = MetricCard(tr("RAM"), "—", show_progress=True)
        self.panel.card_cluster_disk = MetricCard(tr("Storage"), "—", show_progress=True)
        self.panel.card_cluster_quorum = MetricCard(tr("Quorum"), "—")
        cards_grid.addWidget(self.panel.card_cluster_hosts, 0, 0)
        cards_grid.addWidget(self.panel.card_cluster_vms, 0, 1)
        cards_grid.addWidget(self.panel.card_cluster_cpu, 0, 2)
        cards_grid.addWidget(self.panel.card_cluster_ram, 1, 0)
        cards_grid.addWidget(self.panel.card_cluster_disk, 1, 1)
        cards_grid.addWidget(self.panel.card_cluster_quorum, 1, 2)
        self.panel.cluster_summary_cards.setVisible(False)

        self.panel.cluster_quorum_widget = QWidget()
        self.panel.cluster_quorum_widget.setVisible(False)
        quorum_layout = QVBoxLayout(self.panel.cluster_quorum_widget)
        quorum_layout.setContentsMargins(0, 0, 0, 0)
        quorum_layout.setSpacing(0)
        self.panel.cluster_quorum_label = QLabel("")
        self.panel.cluster_quorum_label.setStyleSheet("font-size: 12px; padding: 4px 8px;")
        quorum_layout.addWidget(self.panel.cluster_quorum_label)
        self.panel.cluster_quorum_table = make_table(
            # Online column removed (2026-10-08 audit): duplicates the node
            # status from the host list right below the table
            [tr("Node"), tr("Quorum votes"), tr("Ring 0 addr"), tr("Ring 1 addr")],
            [(QHeaderView.Interactive, 120),
             (QHeaderView.Interactive, 90), (QHeaderView.Stretch, None),
             (QHeaderView.Stretch, None)],
        )
        quorum_layout.addWidget(self.panel.cluster_quorum_table)

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cl.addWidget(self.panel.cluster_summary_cards)
        cl.addWidget(self.panel.cluster_quorum_widget)
        cl.addWidget(self.panel.summary_stack, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        return scroll

    def populate_host_summary(self, hosts):
        panel = self.panel
        panel.summary_stack.setCurrentIndex(0)
        card_items = []
        for node in hosts:
            node_name = node.display_name or node.node or "?"
            host_name = node.host_name
            cfg = panel._cfg_by_name.get(host_name)
            if cfg and cfg.get("cluster_rep"):
                node_name = "★ " + node_name
            status = node.status_value
            vms_count = sum(
                1 for v in panel.all_vms
                if v.node == node.node
                and v.host_name == host_name
            )
            cpu_text = node.cpu_text
            ram_text = node.ram_text
            uptime_text = node.uptime_str
            card_items.append({
                "_key": f"{node.node}@{host_name}",
                "node": node.node,
                "name": node_name,
                "status": status,
                "status_text": status_text(status),
                "address": cfg.get("host", "") if cfg else "",
                "cpu_text": cpu_text,
                "ram_text": ram_text,
                "vms_text": str(vms_count),
                "uptime_text": uptime_text,
            })
        panel.host_summary_list.set_items(card_items)

    def _populate_vm_stats(self, vms):
        panel = self.panel
        total = len(vms)
        running = sum(1 for v in vms if v.status_value == "running")
        stopped = total - running
        panel.card_vm_total.set_value(str(total))
        panel.card_vm_total.set_subtitle(f"{running} {tr('running')} · {stopped} {tr('stopped')}")
        running_vms = [v for v in vms if v.status_value == "running"]
        cpu_sum = sum(v.cpu_fraction for v in running_vms if hasattr(v, "cpu_fraction"))
        cpu_pct = round(cpu_sum * 100, 1) if cpu_sum else 0
        panel.card_vm_cpu.set_value(f"{cpu_pct}%")
        panel.card_vm_cpu.set_progress(min(cpu_pct, 100))
        mem_sum = sum(v.mem_bytes for v in vms if hasattr(v, "mem_bytes"))
        maxmem_sum = sum(v.maxmem_bytes for v in vms if hasattr(v, "maxmem_bytes"))
        mem_gb = round(mem_sum / (1024**3), 1) if mem_sum else 0
        maxmem_gb = round(maxmem_sum / (1024**3), 1) if maxmem_sum else 0
        panel.card_vm_ram.set_value(f"{mem_gb} / {maxmem_gb} {tr('GiB')}")
        panel.card_vm_ram.set_progress(safe_pct(mem_sum, maxmem_sum))
        panel.vm_stats_widget.setVisible(True)

    def _populate_cluster_summary_cards(self, hosts):
        panel = self.panel
        host_names = {h.host_name for h in hosts}
        node_names = {h.node for h in hosts}
        cluster_name = ""
        first_cfg = next((panel._cfg_by_name.get(h.host_name) for h in hosts), None)
        if first_cfg:
            cluster_name = first_cfg.get("cluster", "")
        vms = [vm for vm in panel.all_vms
               if vm.node in node_names and vm.host_name in host_names]
        vms_running = sum(1 for v in vms if v.status.value == "running")
        vms_stopped = len(vms) - vms_running
        panel.card_cluster_hosts.set_value(f"{len(hosts)}")
        running_hosts = sum(1 for h in hosts if h.status_value == "online")
        panel.card_cluster_hosts.set_subtitle(f"{running_hosts} {tr('online')}")
        panel.card_cluster_vms.set_value(f"{vms_running}/{len(vms)}")
        panel.card_cluster_vms.set_subtitle(f"{vms_stopped} {tr('stopped')}")
        online_hosts = [h for h in hosts if h.status_value == "online"]
        n_online = len(online_hosts) or 1
        avg_cpu_pct = round(sum(h.cpu_pct for h in online_hosts) / n_online, 1)
        panel.card_cluster_cpu.set_value(f"{avg_cpu_pct}%")
        panel.card_cluster_cpu.set_progress(avg_cpu_pct)
        total_mem = sum(h.mem_bytes for h in online_hosts)
        total_maxmem = sum(h.maxmem_bytes for h in online_hosts)
        mem_gb = round(total_mem / (1024**3), 1) if total_mem else 0
        maxmem_gb = round(total_maxmem / (1024**3), 1) if total_maxmem else 0
        panel.card_cluster_ram.set_value(f"{mem_gb} / {maxmem_gb} {tr('GiB')}")
        ram_pct = safe_pct(total_mem, total_maxmem)
        panel.card_cluster_ram.set_progress(ram_pct)
        if cluster_name:
            cluster_storages = [s for s in panel.all_storages if s.cluster == cluster_name]
        else:
            cluster_storages = [s for s in panel.all_storages
                                if s.node in node_names]
        total_used = sum(s.used_bytes or 0 for s in cluster_storages)
        total_total = sum(s.total_bytes or 0 for s in cluster_storages)
        used_gb = round(total_used / (1024**3), 1) if total_used else 0
        total_gb = round(total_total / (1024**3), 1) if total_total else 0
        panel.card_cluster_disk.set_value(f"{used_gb} / {total_gb} {tr('GiB')}")
        disk_pct = safe_pct(total_used, total_total)
        panel.card_cluster_disk.set_progress(disk_pct)
        panel.cluster_summary_cards.setVisible(True)

    def show_cluster_folder(self, name):
        panel = self.panel
        panel.detail_label.setText(tr("All clusters"))
        panel.detail_sublabel.setText("")
        panel.detail_sublabel.setVisible(False)
        panel.cluster_summary_cards.setVisible(False)
        panel._cluster_view_toggle.setVisible(True)
        panel.tabs.setTabVisible(TabIndex.MONITOR, False)
        panel.tabs.setTabVisible(TabIndex.HARDWARE, False)
        panel.tabs.setTabVisible(TabIndex.HOST_VMS, False)
        panel.tabs.setTabVisible(TabIndex.SUMMARY, True)
        panel.tabs.setCurrentIndex(TabIndex.SUMMARY)
        self._populate_cluster_summary()
        self._populate_node_compare()
        if not hasattr(panel, '_cluster_view_mode'):
            panel._cluster_view_mode = 'compare'
        from PySide6.QtCore import QTimer
        if panel._cluster_view_mode == 'clusters':
            panel.summary_stack.setCurrentIndex(1)
            panel._btn_clusters.setChecked(True)
            panel._btn_nodes.setChecked(False)
        else:
            panel.summary_stack.setCurrentIndex(2)
            panel._btn_clusters.setChecked(False)
            panel._btn_nodes.setChecked(True)
        QTimer.singleShot(0, lambda: panel.summary_stack.updateGeometry())

    def _populate_cluster_summary(self):
        panel = self.panel
        clusters = {}
        for node in panel.all_nodes:
            host_name = node.host_name
            cfg = panel._cfg_by_name.get(host_name)
            cl = cfg.get("cluster") if cfg else None
            if cl and cl not in (False, None, "Standalone"):
                clusters.setdefault(cl, {"hosts": [], "host_names": set(), "nodes": set()})
                clusters[cl]["hosts"].append(node)
                clusters[cl]["host_names"].add(host_name)
                clusters[cl]["nodes"].add(node.node)
        for cl in clusters.values():
            cl["vms"] = [vm for vm in panel.all_vms
                         if vm.host_name in cl["host_names"]]
        cluster_items = []
        for cl_name, cl_data in sorted(clusters.items(), key=lambda x: x[0].lower()):
            hosts = cl_data["hosts"]
            vms = cl_data["vms"]
            hosts_ok = sum(1 for h in hosts if h.status_value == "online")
            vms_ok = sum(1 for v in vms if v.status_value == "running")
            online_hosts = [h for h in hosts if h.status_value == "online"]
            if online_hosts:
                avg_cpu = round(sum(h.cpu_pct for h in online_hosts) / len(online_hosts), 1)
            else:
                avg_cpu = 0
            mem_total = sum(h.maxmem_bytes for h in hosts)
            mem_used = sum(h.mem_bytes for h in hosts)
            mem_total_gb = round(mem_total / (1024**3), 1)
            mem_used_gb = round(mem_used / (1024**3), 1)
            cluster_items.append({
                "name": cl_name,
                "hosts_text": f"{hosts_ok}/{len(cl_data['hosts'])}",
                "vms_text": f"{vms_ok}/{len(cl_data['vms'])}",
                "cpu_text": f"{avg_cpu}%",
                "ram_text": f"{mem_used_gb}/{mem_total_gb} GiB",
            })
        panel.cluster_summary_list.set_items(cluster_items)

    def _populate_node_compare(self):
        panel = self.panel
        card_items = []
        def _sort_key(n):
            host_name = n.host_name
            cfg = panel._cfg_by_name.get(host_name)
            cl = cfg.get("cluster") if cfg else None
            is_standalone = not cl or cl in (False, None, "Standalone")
            return (1 if is_standalone else 0, cl or "", n.node)
        # Only cluster nodes — standalone has its own folder
        cluster_nodes = []
        for node in panel.all_nodes:
            host_name = node.host_name
            cfg = panel._cfg_by_name.get(host_name)
            cl = cfg.get("cluster") if cfg else None
            if cl and cl not in (False, None, "Standalone"):
                cluster_nodes.append(node)
        for node in sorted(cluster_nodes, key=_sort_key):
            node_name = node.display_name or node.node or "?"
            host_name = node.host_name
            cfg = panel._cfg_by_name.get(host_name)
            cluster_name = cfg.get("cluster", "") if cfg else ""
            if cluster_name in (None, "Standalone"):
                cluster_name = tr("Standalone")
            status = node.status_value
            cpu_pct = node.cpu_pct
            vms_count = sum(
                1 for v in panel.all_vms
                if v.node == node.node
                and v.host_name == host_name
            )
            mem_gib = node.mem_gib
            maxmem_gib = node.maxmem_gib
            mem_pct = node.mem_pct
            disk_gib = node.disk_gib
            maxdisk_gib = node.maxdisk_gib
            uptime_str = node.uptime_str
            pve_text = node.pve_text
            card_items.append({
                "_key": f"{node.node}@{host_name}",
                "node": node.node,
                "name": node_name,
                "status": status,
                "cluster_text": cluster_name,
                "status_text": status_text(status),
                "cpu_text": f"{cpu_pct}%",
                "ram_text": f"{mem_gib}/{maxmem_gib} ({mem_pct}%)",
                "disk_text": f"{disk_gib}/{maxdisk_gib} GiB",
                "vms_text": str(vms_count),
                "uptime_text": uptime_str,
                "pve_text": pve_text,
            })
        panel.node_compare_list.set_items(card_items)

    def show_standalone_folder(self, name):
        panel = self.panel
        panel.detail_label.setText(tr("Standalone hosts"))
        panel.detail_sublabel.setText("")
        panel.detail_sublabel.setVisible(False)
        panel.cluster_summary_cards.setVisible(False)
        panel._cluster_view_toggle.setVisible(False)
        panel.tabs.setTabVisible(TabIndex.MONITOR, False)
        panel.tabs.setTabVisible(TabIndex.HARDWARE, False)
        panel.tabs.setTabVisible(TabIndex.SUMMARY, True)
        panel.tabs.setCurrentIndex(TabIndex.SUMMARY)
        standalone = []
        for node in panel.all_nodes:
            host_name = node.host_name
            cfg = panel._cfg_by_name.get(host_name)
            cl = cfg.get("cluster") if cfg else None
            if not cl or cl in (False, None, "Standalone"):
                standalone.append(node)
        self.populate_host_summary(standalone)

    def show_cluster(self, cluster_name):
        panel = self.panel
        hosts = []
        cluster_cfg = None
        for node in panel.all_nodes:
            host_name = node.host_name
            cfg = panel._cfg_by_name.get(host_name)
            if cfg and cfg.get("cluster") == cluster_name:
                hosts.append(node)
                if cfg.get("cluster_rep") or cluster_cfg is None:
                    cluster_cfg = cfg
        panel.detail_label.setText(cluster_name)
        hosts_count = len(hosts)
        running = sum(1 for h in hosts if h.status_value == "online")
        panel.detail_sublabel.setText(f"{hosts_count} {tr('hosts')} · {running} {tr('online')}")
        panel.detail_sublabel.setVisible(True)
        panel._cluster_view_toggle.setVisible(False)
        panel.tabs.setTabVisible(TabIndex.MONITOR, False)
        panel.tabs.setTabVisible(TabIndex.HARDWARE, False)
        panel.tabs.setTabVisible(TabIndex.HOST_VMS, True)
        panel.tabs.setTabVisible(TabIndex.SUMMARY, True)
        panel.tabs.setTabVisible(TabIndex.STORAGES, True)
        panel.tabs.setTabVisible(TabIndex.SNAPSHOTS, True)
        panel.tabs.setTabVisible(TabIndex.HEALTH, True)
        panel.tabs.setTabVisible(TabIndex.BACKUP_JOBS, True)
        panel.tabs.setTabVisible(TabIndex.ACCESS, True)
        panel.tabs.setTabVisible(TabIndex.HA, True)
        panel.tabs.setTabVisible(TabIndex.POOL_VMS, False)
        panel.tabs.setCurrentIndex(TabIndex.SUMMARY)
        panel._current_cluster_cfg = cluster_cfg
        self.populate_host_summary(hosts)
        self._populate_cluster_summary_cards(hosts)
        self._populate_cluster_vms(cluster_name, hosts)
        self._populate_cluster_storages(cluster_name)
        self._fetch_cluster_snapshots(hosts)
        self._fetch_cluster_health(hosts)
        self._fetch_backup_jobs(cluster_cfg, cluster_name)
        self._fetch_access_all(cluster_cfg)
        if cluster_cfg:
            self.fetch_ha(cluster_cfg)
            self._fetch_cluster_status(cluster_cfg)

    def show_group(self, group_name):
        """B16: aggregated summary for a user-defined host group."""
        panel = self.panel
        hosts = []
        for node in panel.all_nodes:
            cfg = panel._cfg_by_name.get(node.host_name)
            if cfg and (cfg.get("group") or "").strip() == group_name:
                hosts.append(node)
        panel.detail_label.setText(group_name)
        hosts_count = len(hosts)
        running = sum(1 for h in hosts if h.status_value == "online")
        panel.detail_sublabel.setText(f"{hosts_count} {tr('hosts')} · {running} {tr('online')}")
        panel.detail_sublabel.setVisible(True)
        panel._cluster_view_toggle.setVisible(False)
        panel.tabs.setTabVisible(TabIndex.MONITOR, False)
        panel.tabs.setTabVisible(TabIndex.HARDWARE, False)
        panel.tabs.setTabVisible(TabIndex.HOST_VMS, True)
        panel.tabs.setTabVisible(TabIndex.SUMMARY, True)
        panel.tabs.setTabVisible(TabIndex.STORAGES, False)
        panel.tabs.setTabVisible(TabIndex.SNAPSHOTS, False)
        panel.tabs.setTabVisible(TabIndex.HEALTH, False)
        panel.tabs.setTabVisible(TabIndex.BACKUP_JOBS, False)
        panel.tabs.setTabVisible(TabIndex.ACCESS, False)
        panel.tabs.setTabVisible(TabIndex.HA, False)
        panel.tabs.setTabVisible(TabIndex.POOL_VMS, False)
        panel.tabs.setCurrentIndex(TabIndex.SUMMARY)
        panel._current_cluster_cfg = None
        self.populate_host_summary(hosts)
        self._populate_cluster_summary_cards(hosts)
        self._populate_cluster_vms(group_name, hosts)

    def show_host_info(self, host_name, host_data):
        panel = self.panel
        panel.cluster_quorum_widget.setVisible(False)
        host_cfg_name = (host_data.host_name if host_data else "") or host_name
        node = panel._node_repo.get(host_cfg_name, host_name) if panel._node_repo else None
        if node is None:
            node = host_data if host_data else None
        display_name = node.display_name if node else host_name
        panel.detail_label.setText(display_name)
        panel.detail_sublabel.setText(" · ".join(self._host_subtitle(host_data, host_name)))
        panel.detail_sublabel.setVisible(True)
        panel._cluster_view_toggle.setVisible(False)
        panel.cluster_summary_cards.setVisible(False)

        if host_data and host_data.status_value == "error":
            from ..utils import parse_pve_error
            err = host_data.error or ""
            reason = parse_pve_error(err)
            panel.info_label.setStyleSheet(f"font-size: 13px; color: {Color.STATUS_ERR}; padding: 40px 16px;")
            panel.info_label.setText(
                "<div style='text-align: center;'>"
                "<span style='font-size: 22px; font-weight: 700;'>" + tr("❌ {} is unavailable").format(display_name) + "</span>"
                f"<br><br>"
                f"<span style='font-size: 14px; color: {Color.DANGER};'>{reason}</span>"
                f"</div>"
            )
            panel.info_stack.setCurrentIndex(0)
            panel.metrics_widget.setVisible(False)
            panel.metrics_widget.clear_curves()
            panel.tabs.setCurrentIndex(TabIndex.MONITOR)
            for t in range(panel.tabs.count()):
                panel.tabs.setTabVisible(t, t == TabIndex.MONITOR)
            return

        panel.metrics_widget.setVisible(True)
        panel.tabs.setTabVisible(TabIndex.MONITOR, True)
        panel.tabs.setTabVisible(TabIndex.HARDWARE, False)
        panel.tabs.setTabVisible(TabIndex.HOST_VMS, True)
        panel.tabs.setTabVisible(TabIndex.HOST_STORAGE, True)
        panel.tabs.setTabVisible(TabIndex.NETWORK, True)
        panel.tabs.setTabVisible(TabIndex.SERVICES, True)
        panel.tabs.setTabVisible(TabIndex.HOST_DISKS, True)
        panel.tabs.setTabVisible(TabIndex.SNAPSHOTS, True)
        panel.tabs.setTabVisible(TabIndex.HEALTH, True)
        panel.tabs.setTabVisible(TabIndex.BACKUP_JOBS, True)
        panel.tabs.setTabVisible(TabIndex.ACCESS, True)
        panel.tabs.setTabVisible(TabIndex.HA, False)
        panel.tabs.setCurrentIndex(TabIndex.MONITOR)

        panel.host_network_stack.setCurrentIndex(0)
        panel.host_network_stack.widget(0).setText(tr("Loading..."))
        panel.host_network_table.setRowCount(0)
        panel.host_services_stack.setCurrentIndex(0)
        panel.host_services_stack.widget(0).setText(tr("Loading..."))
        panel.host_services_table.setRowCount(0)
        panel.host_disks_stack.setCurrentIndex(0)
        panel.host_disks_stack.widget(0).setText(tr("Loading..."))
        panel.host_disks_table.setRowCount(0)
        panel.host_snapshots_stack.setCurrentIndex(0)
        panel.host_snapshots_stack.widget(0).setText(tr("Loading..."))
        panel.host_snapshots_tree.clear()
        panel.host_health_stack.setCurrentIndex(0)
        panel.host_health_loading.setText(tr("Loading..."))
        panel.host_health_list.set_items([])

        if host_data and host_data.status_value != "error":
            from ._constants import _fmt_pveversion
            host_cfg = panel._cfg_by_name.get(host_data.host_name)
            cpu_pct = host_data.cpu_pct
            mem_gb = host_data.mem_gib
            maxmem_gb = host_data.maxmem_gib
            status = host_data.status_value
            status_color = Color.STATUS_OK if status == "online" else Color.STATUS_ERR if status == "offline" else Color.STATUS_WARN

            panel.card_status.set_title(tr("Status"))
            panel.card_status.set_value(status_text(status))
            panel.card_status.set_value_color(status_color)
            panel.card_status.set_subtitle(
                tr("PVE") + " " + _fmt_pveversion(host_data.pve_version_raw or "?")
            )

            panel.card_cpu.set_value(f"{cpu_pct}%")
            cpu_sockets = host_data.cpu_sockets or ""
            if cpu_sockets:
                panel.card_cpu.set_subtitle(f"{cpu_sockets} {tr('sockets')}")
            else:
                panel.card_cpu.set_subtitle("")
            panel.card_cpu.set_progress(cpu_pct)

            panel.card_ram.set_value(f"{mem_gb} / {maxmem_gb} {tr('GiB')}")
            panel.card_ram.set_progress(host_data.mem_pct)

            host_cfg_name = (host_data.host_name if host_data else "") or host_name
            vms_count = sum(1 for v in panel.all_vms
                           if v.node == host_name
                           and v.host_name == host_cfg_name)
            vms_running = sum(1 for v in panel.all_vms
                              if v.node == host_name
                              and v.host_name == host_cfg_name
                              and v.status_value == "running")
            panel.card_disk.set_title(tr("VMs"))
            panel.card_disk.set_value(f"{vms_running}/{vms_count}")
            panel.card_disk.set_subtitle(f"{vms_count - vms_running} {tr('stopped')}" if vms_count != vms_running else "")
            panel.card_disk.set_progress(0)

            panel.card_net.set_title(tr("Uptime"))
            panel.card_net.set_value(host_data.uptime_str)
            panel.card_net.set_subtitle("")

            panel.card_uptime.set_title(tr("Address"))
            address = host_cfg.get("host", "") if host_cfg else ""
            panel.card_uptime.set_value(address)
            ssl_state = tr("trusted") if (host_cfg and host_cfg.get("trust_ssl", True)) else tr("untrusted")
            panel.card_uptime.set_subtitle(f"SSL {ssl_state}")

            panel.info_stack.setCurrentIndex(1)
        else:
            panel.info_label.setText(tr("No data"))
            panel.info_stack.setCurrentIndex(0)
            return

        host_cfg_name = (host_data.host_name if host_data else "") or host_name
        vms_of_host = [vm for vm in panel.all_vms
                       if vm.node == host_name
                       and vm.host_name == host_cfg_name]
        card_items = []
        for vm in vms_of_host:
            vm_status = vm.status_value
            cpu_str = str(vm.cpu_pct)
            mem = vm.mem_bytes or 0
            maxmem = vm.maxmem_bytes or 0
            if maxmem:
                mem_pct = round(mem / maxmem * 100, 1)
                mem_gb = vm.mem_gib
                maxmem_gb = vm.maxmem_gib
                ram_str = f"{mem_gb}/{maxmem_gb} ({mem_pct}%)"
            else:
                ram_str = "—"
            disk = vm.disk_bytes or 0
            maxdisk = vm.maxdisk_bytes or 0
            vm_type = vm.vm_type.value
            if maxdisk:
                maxdisk_gb = vm.maxdisk_gib
                if vm_type == "lxc" and disk:
                    disk_gb = vm.disk_gib
                    disk_str = f"{disk_gb}/{maxdisk_gb} GiB"
                else:
                    disk_str = f"{maxdisk_gb} GiB"
            else:
                disk_str = "—"
            card_items.append({
                "vmid": vm.vmid,
                "name": str(vm.name or ""),
                "status": vm_status,
                "status_text": status_text(vm_status),
                "cpu_text": cpu_str,
                "ram_text": ram_str,
                "disk_text": disk_str,
                "uptime_text": vm.uptime_str,
                "host_name": host_cfg_name,
                "node": vm.node or host_name,
            })
        panel.host_vm_list.set_items(card_items)
        self._populate_vm_stats(vms_of_host)

        host_storages = [s for s in panel.all_storages
                         if s.node == host_name
                         and s.host_name == (host_data.host_name if host_data else host_name)]
        self.populate_host_storage_table(host_storages)

        self.fetch_host_network(host_name, host_data)
        self.fetch_host_services(host_name, host_data)
        self.fetch_host_disks(host_name, host_data)
        self.fetch_host_snapshots(host_name, host_data)
        self.fetch_host_metrics(host_data)
        self.fetch_host_health(host_name, host_data)
        host_cfg = panel._cfg_by_name.get(host_data.host_name) if host_data else None
        if host_cfg:
            is_cluster_host = bool(host_cfg.get("cluster"))
            if not is_cluster_host:
                panel._backup_jobs_host_cfg = host_data.host_name if host_data else host_name
                self._fetch_backup_jobs(host_cfg, host_name)
            else:
                cluster_name = host_cfg.get("cluster", "")
                cluster_cfg = None
                for n in panel.all_nodes:
                    cn = panel._cfg_by_name.get(n.host_name)
                    if cn and cn.get("cluster") == cluster_name:
                        cluster_cfg = cn
                        break
                if cluster_cfg:
                    self._fetch_backup_jobs(cluster_cfg, cluster_name)
            access_cfg = host_cfg
            if is_cluster_host:
                cluster_name = host_cfg.get("cluster", "")
                for n in panel.all_nodes:
                    cn = panel._cfg_by_name.get(n.host_name)
                    if cn and cn.get("cluster") == cluster_name:
                        access_cfg = cn
                        break
            if access_cfg:
                self._fetch_access_all(access_cfg)

    def populate_host_storage_table(self, storages):
        panel = self.panel
        table = panel.host_storage_table
        table.setRowCount(len(storages))
        for i, st in enumerate(storages):
            name_item = QTableWidgetItem(st.storage or "")
            name_item.setIcon(get_icon("storage"))
            table.setItem(i, 0, name_item)
            table.setItem(i, 1, QTableWidgetItem(st.storage_type))
            content = st.content
            if isinstance(content, list):
                content = ", ".join(content)
            table.setItem(i, 2, QTableWidgetItem(content))
            used = st.used_bytes or 0
            total = st.total_bytes or 0
            used_gb = round(used / (1024**3), 1) if used else 0
            total_gb = round(total / (1024**3), 1) if total else 0
            pct = safe_pct(used, total)
            table.setItem(i, 3, QTableWidgetItem(f"{used_gb} GiB"))
            table.setItem(i, 4, QTableWidgetItem(f"{total_gb} GiB"))
            if total:
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(pct)
                bar.setStyleSheet(_progress_style(pct))
                bar.setFormat(f"{pct}%")
                table.setCellWidget(i, 5, bar)
            else:
                bi = QTableWidgetItem("")
                bi.setFlags(Qt.ItemIsEnabled)
                table.setItem(i, 5, bi)
        table.resizeRowsToContents()
        for r in range(table.rowCount()):
            if table.rowHeight(r) > 24:
                table.setRowHeight(r, 24)

    def update_host_cells(self, host_data):
        panel = self.panel
        if not host_data:
            return
        host_name = host_data.node or ""
        host_cfg_name = host_data.host_name or ""
        is_online = host_data.status_value != "error"

        if is_online:
            from ._constants import _fmt_pveversion
            host_cfg = panel._cfg_by_name.get(host_cfg_name)
            cpu_pct = host_data.cpu_pct
            mem_gb = host_data.mem_gib
            maxmem_gb = host_data.maxmem_gib
            status = host_data.status_value
            status_color = Color.STATUS_OK if status == "online" else Color.STATUS_ERR if status == "offline" else Color.STATUS_WARN

            panel.card_status.set_value(status_text(status))
            panel.card_status.set_value_color(status_color)
            panel.card_status.set_subtitle(
                tr("PVE") + " " + _fmt_pveversion(host_data.pve_version_raw or "?")
            )

            panel.card_cpu.set_value(f"{cpu_pct}%")
            panel.card_cpu.set_progress(cpu_pct)

            panel.card_ram.set_value(f"{mem_gb} / {maxmem_gb} {tr('GiB')}")
            panel.card_ram.set_progress(host_data.mem_pct)

            vms_count = sum(1 for v in panel.all_vms
                           if v.node == host_name
                           and v.host_name == host_cfg_name)
            vms_running = sum(1 for v in panel.all_vms
                              if v.node == host_name
                              and v.host_name == host_cfg_name
                              and v.status_value == "running")
            panel.card_disk.set_value(f"{vms_running}/{vms_count}")
            panel.card_disk.set_subtitle(f"{vms_count - vms_running} {tr('stopped')}" if vms_count != vms_running else "")

            panel.card_net.set_value(host_data.uptime_str)

            address = host_cfg.get("host", "") if host_cfg else ""
            panel.card_uptime.set_value(address)
            ssl_state = tr("trusted") if (host_cfg and host_cfg.get("trust_ssl", True)) else tr("untrusted")
            panel.card_uptime.set_subtitle(f"SSL {ssl_state}")

            panel.info_stack.setCurrentIndex(1)

        vms_of_host = [vm for vm in panel.all_vms
                       if vm.node == host_name
                       and vm.host_name == host_cfg_name]
        card_updates = []
        for vm in vms_of_host:
            vm_status = vm.status_value
            cpu_str = str(vm.cpu_pct)
            mem = vm.mem_bytes or 0
            maxmem = vm.maxmem_bytes or 0
            if maxmem:
                mem_pct = round(mem / maxmem * 100, 1)
                mem_gb = vm.mem_gib
                maxmem_gb = vm.maxmem_gib
                ram_str = f"{mem_gb}/{maxmem_gb} ({mem_pct}%)"
            else:
                ram_str = "—"
            disk = vm.disk_bytes or 0
            maxdisk = vm.maxdisk_bytes or 0
            vm_type = vm.vm_type.value
            if maxdisk:
                maxdisk_gb = vm.maxdisk_gib
                if vm_type == "lxc" and disk:
                    disk_gb = vm.disk_gib
                    disk_str = f"{disk_gb}/{maxdisk_gb} GiB"
                else:
                    disk_str = f"{maxdisk_gb} GiB"
            else:
                disk_str = "—"
            card_updates.append({
                "vmid": vm.vmid,
                "name": str(vm.name or ""),
                "status": vm_status,
                "status_text": status_text(vm_status),
                "cpu_text": cpu_str,
                "ram_text": ram_str,
                "disk_text": disk_str,
                "uptime_text": vm.uptime_str,
            })
        panel.host_vm_list.update_all(card_updates)

    def update_cluster_summary_cells(self, hosts):
        panel = self.panel
        if panel.summary_stack.currentIndex() != 0:
            return
        card_updates = []
        for node in hosts:
            node_name = node.display_name or node.node or "?"
            host_name = node.host_name
            cfg = panel._cfg_by_name.get(host_name)
            if cfg and cfg.get("cluster_rep"):
                node_name = "★ " + node_name
            status = node.status_value
            cpu_pct = node.cpu_pct
            mem_gb = node.mem_gib if hasattr(node, "mem_gib") else 0
            maxmem_gb = node.maxmem_gib if hasattr(node, "maxmem_gib") else 0
            uptime_str = node.uptime_str
            vms_count = sum(
                1 for v in panel.all_vms
                if v.node == node.node
                and v.host_name == host_name
            )
            card_updates.append({
                "_key": f"{node.node}@{host_name}",
                "node": node.node,
                "name": node_name,
                "status": status,
                "status_text": status_text(status),
                "address": cfg.get("host", "") if cfg else "",
                "cpu_text": f"{cpu_pct}%",
                "ram_text": f"{mem_gb}/{maxmem_gb} GiB",
                "vms_text": str(vms_count),
                "uptime_text": uptime_str,
            })
        panel.host_summary_list.update_all(card_updates)

    def fetch_host_network(self, host_name, host_data):
        panel = self.panel
        node_name = host_data.node or ""
        host_cfg_name = host_data.host_name or ""
        cfg = panel._cfg_by_name.get(host_cfg_name)
        if not cfg:
            panel.host_network_stack.widget(0).setText(tr("No data"))
            panel.host_network_stack.setCurrentIndex(0)
            return
        from ..api.metrics import HostNetworkWorker
        worker = HostNetworkWorker(cfg, node_name)
        worker.signals.network_ready.connect(
            lambda nn, data, h=host_cfg_name, w=worker: (
                self.on_host_network(nn, data, h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        worker.signals.network_error.connect(
            lambda nn, err, h=host_cfg_name, w=worker: (
                self.on_host_network(nn, [], h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def on_host_network(self, node_name, interfaces, host_cfg_name=""):
        panel = self.panel
        if panel.current_obj_type != "host" or panel.current_obj_id != HostId(host_cfg_name, node_name):
            return
        if interfaces:
            panel.host_network_stack.setCurrentIndex(1)
            self.populate_host_network_table(interfaces)
        else:
            panel.host_network_stack.widget(0).setText(tr("No data"))
            panel.host_network_stack.setCurrentIndex(0)

    def populate_host_network_table(self, interfaces):
        table = self.panel.host_network_table
        table.setSortingEnabled(False)
        table.setRowCount(len(interfaces))
        for i, iface in enumerate(interfaces):
            iface_name = iface.get("iface", "")
            iface_item = QTableWidgetItem(iface_name)
            iface_item.setIcon(get_icon("network"))
            table.setItem(i, 0, iface_item)
            table.setItem(i, 1, QTableWidgetItem(iface.get("type", "")))
            state = iface.get("active", 0)
            state_str = tr("on") if state == 1 else tr("off")
            table.setItem(i, 2, QTableWidgetItem(state_str))
            table.setItem(i, 3, QTableWidgetItem(iface.get("method", "")))
            address = iface.get("address", "")
            netmask = iface.get("netmask", "")
            if address and netmask:
                addr_str = f"{address}/{netmask}"
            elif address:
                addr_str = address
            else:
                addr_str = ""
            table.setItem(i, 4, QTableWidgetItem(addr_str))
            table.setItem(i, 5, QTableWidgetItem(iface.get("gateway", "")))
            table.setItem(i, 6, QTableWidgetItem(iface.get("bridge_ports", "")))
            vlan = iface.get("vlan_id", "")
            table.setItem(i, 7, QTableWidgetItem(str(vlan) if vlan else ""))
            mtu = iface.get("mtu", "")
            table.setItem(i, 8, QTableWidgetItem(str(mtu) if mtu else ""))
            pending = iface.get("pending", 0)
            pending_str = tr("Yes") if pending else ""
            pending_item = QTableWidgetItem(pending_str)
            if pending:
                pending_item.setForeground(QColor(Color.STATUS_WARN))
            table.setItem(i, 9, pending_item)
        table.resizeRowsToContents()
        for r in range(table.rowCount()):
            if table.rowHeight(r) > 24:
                table.setRowHeight(r, 24)
        table.setSortingEnabled(True)
        self._on_network_selection_changed()

    def fetch_host_services(self, host_name, host_data):
        panel = self.panel
        node_name = host_data.node or ""
        host_cfg_name = host_data.host_name or ""
        cfg = panel._cfg_by_name.get(host_cfg_name)
        if not cfg:
            panel.host_services_stack.widget(0).setText(tr("No data"))
            panel.host_services_stack.setCurrentIndex(0)
            return
        from ..api.metrics import HostServicesWorker
        worker = HostServicesWorker(cfg, node_name)
        worker.signals.services_ready.connect(
            lambda nn, data, h=host_cfg_name, w=worker: (
                self.on_host_services(nn, data, h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        worker.signals.services_error.connect(
            lambda nn, err, h=host_cfg_name, w=worker: (
                self.on_host_services(nn, [], h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def on_host_services(self, node_name, services, host_cfg_name=""):
        panel = self.panel
        if panel.current_obj_type != "host" or panel.current_obj_id != HostId(host_cfg_name, node_name):
            return
        if services:
            panel.host_services_stack.setCurrentIndex(1)
            self.populate_host_services_table(services)
        else:
            panel.host_services_stack.widget(0).setText(tr("No data"))
            panel.host_services_stack.setCurrentIndex(0)

    def populate_host_services_table(self, services):
        table = self.panel.host_services_table
        table.setRowCount(len(services))
        for i, svc in enumerate(services):
            name_item = QTableWidgetItem(svc.get("name", ""))
            name_item.setIcon(get_icon("services"))
            table.setItem(i, 0, name_item)
            state = svc.get("state", "")
            table.setItem(i, 1, QTableWidgetItem(state))
            table.setItem(i, 2, QTableWidgetItem(svc.get("desc", "")))
        table.resizeRowsToContents()
        for r in range(table.rowCount()):
            if table.rowHeight(r) > 24:
                table.setRowHeight(r, 24)
        table.setSortingEnabled(True)

    def fetch_host_health(self, host_name, host_data):
        panel = self.panel
        node_name = host_data.node or ""
        host_cfg_name = host_data.host_name or ""
        cfg = panel._cfg_by_name.get(host_cfg_name)
        if not cfg:
            panel.host_health_stack.widget(0).setText(tr("No data"))
            panel.host_health_stack.setCurrentIndex(0)
            return
        from ..api.metrics import HealthCheckWorker
        worker = HealthCheckWorker(cfg, node_name, host_data)
        worker.signals.health_ready.connect(
            lambda nn, data, h=host_cfg_name, w=worker: (
                self.on_host_health(nn, data, h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        worker.signals.health_error.connect(
            lambda nn, err, h=host_cfg_name, w=worker: (
                self.on_host_health(nn, {"status": "error", "issues": [err], "warnings": []}, h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def on_host_health(self, node_name, health, host_cfg_name=""):
        panel = self.panel
        if panel.current_obj_type != "host" or panel.current_obj_id != HostId(host_cfg_name, node_name):
            return
        issues = health.get("issues", [])
        warnings = health.get("warnings", [])
        items = []
        for idx, msg in enumerate(issues):
            items.append({
                "id": f"issue_{idx}",
                "severity": "error",
                "title": tr("Critical"),
                "message": msg,
            })
        for idx, msg in enumerate(warnings):
            items.append({
                "id": f"warn_{idx}",
                "severity": "warning",
                "title": tr("Warning"),
                "message": msg,
            })
        if not items:
            items.append({
                "id": "ok",
                "severity": "online",
                "title": tr("Healthy"),
                "message": tr("All checks passed"),
            })
        panel.host_health_stack.setCurrentIndex(1)
        panel.host_health_list.set_items(items)

    def fetch_host_disks(self, host_name, host_data):
        panel = self.panel
        node_name = host_data.node or ""
        host_cfg_name = host_data.host_name or ""
        cfg = panel._cfg_by_name.get(host_cfg_name)
        if not cfg:
            panel.host_disks_stack.widget(0).setText(tr("No data"))
            panel.host_disks_stack.setCurrentIndex(0)
            return
        from ..api.metrics import HostDisksWorker
        worker = HostDisksWorker(cfg, node_name)
        worker.signals.disks_ready.connect(
            lambda nn, data, h=host_cfg_name, w=worker: (
                self.on_host_disks(nn, data, h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        worker.signals.disks_error.connect(
            lambda nn, err, h=host_cfg_name, w=worker: (
                self.on_host_disks(nn, [], h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def on_host_disks(self, node_name, disks, host_cfg_name=""):
        panel = self.panel
        if panel.current_obj_type != "host" or panel.current_obj_id != HostId(host_cfg_name, node_name):
            return
        if disks:
            panel.host_disks_stack.setCurrentIndex(1)
            self.populate_host_disks_table(disks)
        else:
            panel.host_disks_stack.widget(0).setText(tr("No data"))
            panel.host_disks_stack.setCurrentIndex(0)

    def populate_host_disks_table(self, disks):
        from ._table_utils import format_volsize
        table = self.panel.host_disks_table
        seen_wwn = set()
        unique = []
        for d in disks:
            wwn = d.get("wwn", "") or d.get("serial", "")
            if wwn and wwn in seen_wwn:
                continue
            if wwn:
                seen_wwn.add(wwn)
            unique.append(d)
        table.setRowCount(len(unique))
        for i, d in enumerate(unique):
            model = d.get("model", "")
            devpath = d.get("devpath", "")
            dev_item = QTableWidgetItem(devpath)
            dev_item.setIcon(get_icon("disk"))
            table.setItem(i, 0, dev_item)
            table.setItem(i, 1, QTableWidgetItem(d.get("type", "")))
            table.setItem(i, 2, QTableWidgetItem(str(model)))
            table.setItem(i, 3, QTableWidgetItem(format_volsize(d.get("size", 0))))
            table.setItem(i, 4, QTableWidgetItem(d.get("wwn", "") or d.get("serial", "")))
        table.resizeRowsToContents()
        for r in range(table.rowCount()):
            if table.rowHeight(r) > 24:
                table.setRowHeight(r, 24)
        table.setSortingEnabled(True)

    def fetch_host_snapshots(self, host_name, host_data):
        panel = self.panel
        node_name = host_data.node or ""
        host_cfg_name = host_data.host_name or ""
        panel._snap_nav_ctx = (host_cfg_name, node_name)
        cfg = panel._cfg_by_name.get(host_cfg_name)
        if not cfg:
            panel.host_snapshots_stack.widget(0).setText(tr("No data"))
            panel.host_snapshots_stack.setCurrentIndex(0)
            return
        vms = [vm for vm in panel.all_vms if vm.node == host_name and vm.host_name == host_cfg_name]
        from ..api.metrics import HostSnapshotsWorker
        worker = HostSnapshotsWorker(cfg, node_name, vms)
        worker.signals.snapshots_ready.connect(
            lambda nn, data, h=host_cfg_name, w=worker: (
                self.on_host_snapshots(nn, data, h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        worker.signals.snapshots_error.connect(
            lambda nn, err, h=host_cfg_name, w=worker: (
                self.on_host_snapshots(nn, [], h),
                panel._workers_mgr.discard_worker(w)
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def on_host_snapshots(self, node_name, snapshots, host_cfg_name=""):
        panel = self.panel
        if panel.current_obj_type != "host" or panel.current_obj_id != HostId(host_cfg_name, node_name):
            return
        if snapshots:
            panel.host_snapshots_stack.setCurrentIndex(1)
            self.populate_host_snapshots_tree(snapshots)
        else:
            panel.host_snapshots_stack.widget(0).setText(tr("No snapshots"))
            panel.host_snapshots_stack.setCurrentIndex(0)

    def populate_host_snapshots_tree(self, snapshots):
        from PySide6.QtWidgets import QTreeWidgetItem
        tree = self.panel.host_snapshots_tree
        tree.clear()
        nav_ctx = getattr(self.panel, "_snap_nav_ctx", ("", ""))
        host_name, node = nav_ctx
        vms_map = {}
        for snap in snapshots:
            vmid = snap.get("vmid", 0)
            vms_map.setdefault(vmid, []).append(snap)

        def make_snap_item(snap):
            name = snap.get("name", "")
            desc = snap.get("description", "") or ""
            snaptime = snap.get("snaptime", 0)
            ts = datetime.fromtimestamp(snaptime).strftime("%Y-%m-%d %H:%M:%S") if snaptime else ""
            vm_state = tr("yes") if snap.get("vmstate", 0) else tr("no")
            size_val = snap.get("size", 0)
            if isinstance(size_val, (int, float)) and size_val > 0:
                gb = size_val / (1024 ** 3)
                size_str = f"{gb / 1024:.1f} TiB" if gb >= 1024 else f"{gb:.1f} GiB"
            else:
                size_str = "—"
            parent_name = snap.get("parent", "") or ""
            return QTreeWidgetItem([name, desc, ts, vm_state, size_str, parent_name])

        for vmid in sorted(vms_map.keys()):
            vm_snaps = vms_map[vmid]
            first = vm_snaps[0]
            vm_label = f"{vmid} {first.get('vm_name', '')}"
            vm_item = QTreeWidgetItem([vm_label, "", "", "", "", ""])
            if host_name and vmid:
                try:
                    vm_item.setData(0, Qt.UserRole, (host_name, int(vmid), node))
                except (ValueError, TypeError):
                    pass
            font = vm_item.font(0)
            font.setBold(True)
            vm_item.setFont(0, font)
            snap_by_name = {s.get("name", ""): s for s in vm_snaps}
            created_names = set()
            remaining = list(vm_snaps)

            for _ in range(len(vm_snaps) + 1):
                progress = False
                still = []
                for snap in remaining:
                    parent_name = snap.get("parent", "") or ""
                    if not parent_name or parent_name == "current" or parent_name not in snap_by_name:
                        item = make_snap_item(snap)
                        vm_item.addChild(item)
                        snap["_item"] = item
                        created_names.add(snap.get("name", ""))
                        progress = True
                    elif parent_name in created_names:
                        parent_snap = snap_by_name[parent_name]
                        parent_item = parent_snap.get("_item")
                        if parent_item:
                            item = make_snap_item(snap)
                            parent_item.addChild(item)
                            snap["_item"] = item
                            created_names.add(snap.get("name", ""))
                            progress = True
                        else:
                            still.append(snap)
                    else:
                        still.append(snap)
                remaining = still
                if not progress:
                    break

            tree.addTopLevelItem(vm_item)

        tree.expandAll()
        tree.resizeColumnToContents(0)

    def fetch_host_metrics(self, host_data):
        panel = self.panel
        node_name = host_data.node or ""
        host_cfg_name = host_data.host_name or ""
        cfg = panel._cfg_by_name.get(host_cfg_name)
        panel.metrics_widget.show_disk_io(False)
        if not cfg:
            panel.metrics_widget.clear_curves()
            panel.metrics_stack.setCurrentIndex(1)
            return
        timeframe, rng = panel.metrics_widget.fetch_timeframe()
        s, e = rng if rng else (None, None)
        cache_key = ("host", node_name, timeframe, s, e)
        if cache_key in panel.metrics_cache:
            panel.metrics_stack.setCurrentIndex(1)
            panel.metrics_widget.update_curves(panel.metrics_cache[cache_key])
            return
        panel.metrics_stack.setCurrentIndex(0)
        from ..api.metrics import HostMetricsWorker
        worker = HostMetricsWorker(cfg, node_name, timeframe)
        worker.signals.data_fetched.connect(lambda tf, nn, md, g=panel._generation, w=worker, s=s, e=e: (self.on_host_metrics_fetched(tf, nn, md, g, s, e), panel._workers_mgr.discard_worker(w)))
        worker.signals.error_occurred.connect(lambda err, w=worker: (
            panel.metrics_stack.setCurrentIndex(1),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def on_host_metrics_fetched(self, timeframe, node_name, metrics_dict, gen, s=None, e=None):
        panel = self.panel
        if gen != panel._generation:
            return
        panel.metrics_stack.setCurrentIndex(1)
        cache_key = ("host", node_name, timeframe, s, e)
        panel.metrics_cache[cache_key] = metrics_dict
        panel.metrics_widget.update_curves(metrics_dict)

    # ------------------------------------------------------------------
    # Backup Jobs tab
    # ------------------------------------------------------------------

    def build_backup_jobs_tab(self):
        panel = self.panel
        loading = loading_label()
        table = make_table(
            [tr("ID"), tr("Enabled"), tr("Schedule"), tr("Storage"),
             tr("VMIDs"), tr("Mode"), tr("Comment")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 60),
             (QHeaderView.Interactive, 100), (QHeaderView.Interactive, 100),
             (QHeaderView.Interactive, 120), (QHeaderView.Interactive, 80),
             (QHeaderView.Stretch, None)],
            sortable=True,
        )
        panel.backup_jobs_table = table
        table.doubleClicked.connect(lambda idx: self._on_edit_backup_job())
        toolbar = QWidget()
        btn_layout = QHBoxLayout(toolbar)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        add_btn = QPushButton(get_icon("add"), tr("Add"))
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._on_add_backup_job)
        btn_layout.addWidget(add_btn)
        edit_btn = QPushButton(tr("Edit"))
        edit_btn.setMinimumHeight(28)
        edit_btn.clicked.connect(self._on_edit_backup_job)
        btn_layout.addWidget(edit_btn)
        remove_btn = QPushButton(get_icon("remove"), tr("Remove"))
        remove_btn.setMinimumHeight(28)
        remove_btn.clicked.connect(self._on_remove_backup_job)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        panel.backup_job_add_btn = add_btn
        panel.backup_job_edit_btn = edit_btn
        panel.backup_job_remove_btn = remove_btn
        stack = QStackedWidget()
        stack.addWidget(loading)
        from ._table_utils import make_filterable_table
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.backup_jobs_loading = loading
        panel.backup_jobs_stack = stack
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

    # --- cluster tab population ---

    def _populate_cluster_vms(self, cluster_name, hosts):
        panel = self.panel
        host_names = {h.host_name for h in hosts}
        node_names = {h.node for h in hosts}
        vms = [vm for vm in panel.all_vms
               if vm.node in node_names
               and vm.host_name in host_names]
        card_items = []
        for vm in vms:
            vmid = vm.vmid
            name = vm.name or f"VM {vmid}"
            status = vm.status_value
            cpu_pct = vm.cpu_pct
            mem_gib = vm.mem_gib
            maxmem_gib = vm.maxmem_gib
            disk_gib = vm.disk_gib
            uptime_str = vm.uptime_str
            card_items.append({
                "vmid": vmid,
                "name": name,
                "status": status,
                "status_text": status_text(status),
                "cpu_text": f"{cpu_pct}%",
                "ram_text": f"{mem_gib}/{maxmem_gib} GiB",
                "disk_text": f"{disk_gib} GiB",
                "uptime_text": uptime_str,
                "host_name": vm.host_name or "",
                "node": vm.node or "",
            })
        panel.host_vm_list.set_items(card_items)
        self._populate_vm_stats(vms)

    def _populate_cluster_storages(self, cluster_name):
        panel = self.panel
        storages = [s for s in panel.all_storages if s.cluster == cluster_name]
        if not storages:
            cluster_host_names = {h.host_name for h in panel.all_nodes
                                  if (panel._cfg_by_name.get(h.host_name) or {}).get("cluster") == cluster_name}
            storages = [s for s in panel.all_storages
                        if not s.cluster
                        and s.node in {h.node for h in panel.all_nodes
                                              if h.host_name in cluster_host_names}
                        and s.host_name in cluster_host_names]
        card_items = []
        seen = set()
        for st in storages:
            name = st.storage or ""
            if not name or name in seen:
                continue
            seen.add(name)
            content = st.content
            if isinstance(content, list):
                content = ", ".join(content)
            used = st.used_bytes or 0
            total = st.total_bytes or 0
            used_gb = round(used / (1024**3), 1) if used else 0
            total_gb = round(total / (1024**3), 1) if total else 0
            pct = safe_pct(used, total)
            card_items.append({
                "name": name,
                "type_text": st.storage_type,
                "content_text": content,
                "location_text": cluster_name,
                "used_text": f"{used_gb} GiB",
                "total_text": f"{total_gb} GiB",
                "usage_text": f"{pct}%",
                "nav_key": ("storage", name, "cluster", cluster_name),
            })
        panel.storage_list.set_items(card_items)

    def _on_vm_card_nav(self, data):
        vmid = data.get("vmid")
        host_name = data.get("host_name")
        node = data.get("node", "")
        if vmid is not None and host_name:
            try:
                self.panel.navigate_requested.emit((host_name, int(vmid), node))
            except (ValueError, TypeError):
                pass

    def _on_host_card_nav(self, data):
        key = data.get("_key", "")
        node = data.get("node", "")
        if "@" in key and node:
            host_name = key.split("@", 1)[1]
            self.panel.navigate_requested.emit(("host", node, host_name))

    def _on_cluster_card_nav(self, data):
        name = data.get("name", "")
        if name:
            self.panel.navigate_requested.emit(("cluster", name))

    def _on_snap_tree_nav(self, item, _col):
        key = item.data(0, Qt.UserRole)
        if isinstance(key, tuple) and len(key) == 3:
            self.panel.navigate_requested.emit(key)

    def _fetch_cluster_snapshots(self, hosts):
        panel = self.panel
        panel.host_snapshots_stack.setCurrentIndex(0)
        panel.host_snapshots_loading.setText(tr("Loading..."))
        panel.host_snapshots_tree.clear()
        for host in hosts:
            node_name = host.node or ""
            host_cfg_name = host.host_name or ""
            cfg = panel._cfg_by_name.get(host_cfg_name)
            if not cfg:
                continue
            vms = [vm for vm in panel.all_vms
                   if vm.node == node_name and vm.host_name == host_cfg_name]
            from ..api.metrics import HostSnapshotsWorker
            worker = HostSnapshotsWorker(cfg, node_name, vms)
            worker.signals.snapshots_ready.connect(
                lambda nn, data, w=worker, gen=panel._generation: (
                    self._on_cluster_snapshots(nn, data, gen),
                    panel._workers_mgr.discard_worker(w),
                )
            )
            worker.signals.snapshots_error.connect(
                lambda nn, err, w=worker, gen=panel._generation: (
                    self._on_cluster_snapshots(nn, [], gen),
                    panel._workers_mgr.discard_worker(w),
                )
            )
            panel._workers_mgr.run_host_worker(worker)

    def _on_cluster_snapshots(self, node_name, data, gen=0):
        panel = self.panel
        if panel.current_obj_type != "cluster" or gen != panel._generation:
            return
        tree = panel.host_snapshots_tree
        vms_map = {}
        for snap in (data or []):
            vmid = snap.get("vmid", 0)
            vms_map.setdefault(vmid, []).append(snap)
        for vmid in sorted(vms_map.keys()):
            snaps = vms_map[vmid]
            vm_name = snaps[0].get("vm_name", "")
            vm_label = f"{vmid} {vm_name}".strip()
            vm_item = QTreeWidgetItem(tree, [vm_label, "", "", "", "", ""])
            vm_item.setIcon(0, get_icon("snapshot"))
            snap_host = snaps[0].get("host_name", "")
            snap_node = snaps[0].get("node", "")
            if snap_host and vmid:
                try:
                    vm_item.setData(0, Qt.UserRole, (snap_host, int(vmid), snap_node))
                except (ValueError, TypeError):
                    pass
            for snap in snaps:
                name = snap.get("name", "")
                desc = snap.get("description", "") or ""
                ctime = snap.get("snaptime", 0)
                created = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
                parent = snap.get("parent", "") or ""
                size = snap.get("size", 0) or 0
                if isinstance(size, (int, float)) and size > 0:
                    gb = size / (1024 ** 3)
                    size_text = f"{gb / 1024:.1f} TiB" if gb >= 1024 else f"{gb:.1f} GiB"
                else:
                    size_text = ""
                QTreeWidgetItem(vm_item, [name, desc, created, "", size_text, parent])
        tree.resizeColumnToContents(0)
        tree.expandAll()
        panel.host_snapshots_stack.setCurrentIndex(1)

    def _fetch_cluster_health(self, hosts):
        panel = self.panel
        panel.host_health_stack.setCurrentIndex(0)
        panel.host_health_loading.setText(tr("Loading..."))
        panel.host_health_list.set_items([])
        panel._cluster_health_collected = []
        panel._cluster_health_total = 0
        panel._cluster_health_done = 0
        pending = [h for h in hosts if h.status_value != "error"]
        if not pending:
            panel.host_health_loading.setText(tr("No data"))
            return
        panel._cluster_health_total = len(pending)
        for host in pending:
            node_name = host.node or ""
            host_cfg_name = host.host_name or ""
            cfg = panel._cfg_by_name.get(host_cfg_name)
            if not cfg:
                panel._cluster_health_done += 1
                continue
            from ..api.metrics import HealthCheckWorker
            worker = HealthCheckWorker(cfg, node_name, host)
            worker.signals.health_ready.connect(
                lambda nn, result, w=worker, gen=panel._generation: (
                    self._on_cluster_health(nn, result, gen),
                    panel._workers_mgr.discard_worker(w),
                )
            )
            worker.signals.health_error.connect(
                lambda nn, err, w=worker, gen=panel._generation: (
                    self._on_cluster_health(nn, {"status": "error", "issues": [err], "warnings": []}, gen),
                    panel._workers_mgr.discard_worker(w),
                )
            )
            panel._workers_mgr.run_host_worker(worker)
        if panel._cluster_health_done >= panel._cluster_health_total:
            panel.host_health_list.set_items([])
            panel.host_health_stack.setCurrentIndex(1)

    def _on_cluster_health(self, node_name, result, gen=0):
        panel = self.panel
        if panel.current_obj_type != "cluster" or gen != panel._generation:
            return
        collected = getattr(panel, "_cluster_health_collected", None)
        if collected is None:
            collected = []
            panel._cluster_health_collected = collected
        issues = result.get("issues", []) or []
        warnings = result.get("warnings", []) or []
        for issue in issues:
            collected.append({
                "id": f"{node_name}-err-{len(collected)}",
                "severity": "error",
                "title": node_name,
                "message": issue,
            })
        for warning in warnings:
            collected.append({
                "id": f"{node_name}-warn-{len(collected)}",
                "severity": "warning",
                "title": node_name,
                "message": warning,
            })
        if result.get("status") == "ok" and not issues and not warnings:
            collected.append({
                "id": f"{node_name}-ok",
                "severity": "online",
                "title": node_name,
                "message": tr("All checks passed"),
            })
        panel._cluster_health_done += 1
        if panel._cluster_health_done >= panel._cluster_health_total:
            panel.host_health_list.set_items(collected)
            panel.host_health_stack.setCurrentIndex(1)
            panel._cluster_health_collected = None

    # --- backup jobs fetch / populate ---

    def _detect_pve_major(self, cfg_or_host):
        """M0.5: major from pve_version_raw via the compat matrix.

        Unknown version -> 7 (the most compatible backup API route).
        """
        from ...domain.compat import parse_pve_version

        if isinstance(cfg_or_host, dict):
            for node in self.panel.all_nodes:
                if node.host_name == cfg_or_host.get("name", ""):
                    version = parse_pve_version(node.pve_version_raw)
                    if version is not None:
                        return version.major
        return 7

    def _fetch_backup_jobs(self, cfg, context_name):
        panel = self.panel
        if not cfg:
            panel.backup_jobs_loading.setText(tr("No data"))
            panel.backup_jobs_stack.setCurrentIndex(0)
            return
        panel.backup_jobs_loading.setText(tr("Loading..."))
        panel.backup_jobs_stack.setCurrentIndex(0)
        panel.backup_jobs_table.setRowCount(0)
        panel._backup_jobs_cfg = cfg
        panel._backup_jobs_context = context_name
        pve_major = self._detect_pve_major(cfg)
        panel._backup_jobs_pve_major = pve_major
        from ...backend import ClusterJobsWorker
        worker = ClusterJobsWorker(cfg, pve_major=pve_major)
        worker.signals.jobs_ready.connect(
            lambda jobs, w=worker: (
                self._on_backup_jobs_loaded(jobs),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.jobs_error.connect(
            lambda err, w=worker: (
                self._on_backup_jobs_error(err),
                panel._workers_mgr.discard_worker(w),
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def _on_backup_jobs_loaded(self, jobs):
        panel = self.panel
        table = panel.backup_jobs_table
        table.setSortingEnabled(False)
        table.setRowCount(len(jobs))
        for i, job in enumerate(jobs):
            job_id = job.get("id", "")
            id_item = QTableWidgetItem(job_id)
            id_item.setData(Qt.UserRole, job)
            id_item.setIcon(get_icon("backup"))
            table.setItem(i, 0, id_item)
            enabled = int(job.get("enabled", 1) or 0)
            en_text = tr("Yes") if enabled else tr("No")
            en_item = QTableWidgetItem(en_text)
            en_item.setForeground(QColor(Color.STATUS_OK if enabled else Color.TEXT_DIM))
            table.setItem(i, 1, en_item)
            table.setItem(i, 2, QTableWidgetItem(job.get("schedule", "")))
            table.setItem(i, 3, QTableWidgetItem(job.get("storage", "")))
            vmid = job.get("vmid", "")
            table.setItem(i, 4, QTableWidgetItem(str(vmid) if vmid else ""))
            table.setItem(i, 5, QTableWidgetItem(job.get("mode", "")))
            table.setItem(i, 6, QTableWidgetItem(job.get("comment", "") or ""))
        table.setSortingEnabled(True)
        if jobs:
            panel.backup_jobs_stack.setCurrentIndex(1)
        else:
            panel.backup_jobs_loading.setText(tr("No backup jobs"))
            panel.backup_jobs_stack.setCurrentIndex(0)

    def _on_backup_jobs_error(self, err):
        panel = self.panel
        from ..utils import parse_pve_error
        panel.backup_jobs_loading.setText(
            tr("Error loading jobs") + ": " + parse_pve_error(err))
        panel.backup_jobs_stack.setCurrentIndex(0)

    def _get_backup_jobs_storages(self):
        panel = self.panel
        ctx = getattr(panel, "_backup_jobs_context", "")
        if panel.current_obj_type == "cluster":
            return [s for s in panel.all_storages if s.cluster == ctx]
        elif panel.current_obj_type == "host":
            host_cfg = getattr(panel, "_backup_jobs_host_cfg", "") or ctx
            return [s for s in panel.all_storages
                    if s.node == ctx
                    and s.host_name == host_cfg]
        return panel.all_storages

    def _on_add_backup_job(self):
        panel = self.panel
        cfg = getattr(panel, "_backup_jobs_cfg", None)
        if not cfg:
            return
        pve_major = getattr(panel, "_backup_jobs_pve_major", 7)
        storages = self._get_backup_jobs_storages()
        from ..backup_job_dialog import BackupJobDialog
        dlg = BackupJobDialog(panel, storages=storages)
        if dlg.exec() != BackupJobDialog.Accepted:
            return
        params = dlg.get_params()
        from ...backend import ClusterJobCreateWorker
        worker = ClusterJobCreateWorker(cfg, params, pve_major=pve_major)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_backup_jobs(cfg, panel._backup_jobs_context),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("HA error: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    # ------------------------------------------------------------------
    # Cluster status (quorum, corosync)
    # ------------------------------------------------------------------

    def _fetch_cluster_status(self, cluster_cfg):
        panel = self.panel
        panel.card_cluster_quorum.start_loading()
        from ...backend import ClusterStatusWorker
        worker = ClusterStatusWorker(cluster_cfg)
        worker.signals.cluster_status_ready.connect(
            lambda data, w=worker: (
                self._on_cluster_status(data),
                self.panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.cluster_status_error.connect(
            lambda err, w=worker: (
                self._on_cluster_status_error(err),
                self.panel._workers_mgr.discard_worker(w),
            )
        )
        self.panel._workers_mgr.run_host_worker(worker)

    def _on_cluster_status(self, data):
        panel = self.panel
        info = data.info

        if info.quorum_state == QuorumState.OK:
            color = Color.STATUS_OK
            quorum_text = tr("Quorum: OK")
        elif info.quorum_state == QuorumState.LOST:
            color = Color.STATUS_ERR
            quorum_text = tr("Quorum: LOST")
        else:
            color = Color.STATUS_WARN
            quorum_text = tr("Quorum: unknown")

        quorum_votes = info.votes
        expected_votes = info.expected_votes

        panel.card_cluster_quorum.set_value(
            f"{quorum_votes}/{expected_votes}",
            subtitle=quorum_text,
        )
        panel.cluster_quorum_label.setText(
            f"<b>{quorum_text}</b> · {tr('Votes')}: {quorum_votes}/{expected_votes}"
        )
        panel.cluster_quorum_label.setStyleSheet(
            f"font-size: 12px; padding: 4px 8px; color: {color};"
        )

        table = panel.cluster_quorum_table
        table.setSortingEnabled(False)
        table.setRowCount(len(data.nodes))
        for i, node in enumerate(data.nodes):
            table.setItem(i, 0, QTableWidgetItem(node.name))
            table.setItem(i, 1, QTableWidgetItem(node.votes_display))
            table.setItem(i, 2, QTableWidgetItem(node.ring0_display))
            table.setItem(i, 3, QTableWidgetItem(node.ring1_addr))
        table.resizeRowsToContents()
        table.setSortingEnabled(True)
        # fit to content: unconstrained, the table ate half the page with
        # just a couple of nodes, squeezing the host list below it
        fit_table_height(table)

        panel.cluster_quorum_widget.setVisible(True)

    def _on_cluster_status_error(self, err):
        panel = self.panel
        panel.card_cluster_quorum.stop_loading()
        panel.cluster_quorum_label.setText(tr("Cluster status unavailable"))
        panel.cluster_quorum_label.setStyleSheet(
            f"font-size: 12px; padding: 4px 8px; color: {Color.STATUS_WARN};"
        )
        panel.cluster_quorum_table.setRowCount(0)
        fit_table_height(panel.cluster_quorum_table)
        panel.cluster_quorum_widget.setVisible(True)

    # ------------------------------------------------------------------
    # Network CRUD
    # ------------------------------------------------------------------

    def _on_network_selection_changed(self):
        panel = self.panel
        has_sel = panel.host_network_table.currentRow() >= 0
        panel.host_network_edit_btn.setEnabled(has_sel)
        panel.host_network_delete_btn.setEnabled(has_sel)

    def _get_network_cfg(self):
        panel = self.panel
        host_data = panel.current_obj_data
        if not host_data:
            return None, None
        host_name = host_data.host_name or host_data.node
        cfg = panel._cfg_by_name.get(host_name)
        node_name = host_data.node or host_name
        return cfg, node_name

    def _on_network_add(self):
        panel = self.panel
        cfg, node_name = self._get_network_cfg()
        if not cfg:
            return
        params = self._network_edit_dialog(panel, node_name, is_create=True)
        if params is None:
            return
        from ...backend import NetworkCreateWorker
        worker = NetworkCreateWorker(cfg, node_name, params)
        worker.signals.result.connect(lambda msg, w=worker, hd=panel.current_obj_data: (
            panel.config_update_result.emit(msg),
            self.fetch_host_network(hd.host_name, hd),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Network error: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_network_edit(self):
        panel = self.panel
        cfg, node_name = self._get_network_cfg()
        if not cfg:
            return
        table = panel.host_network_table
        row = table.currentRow()
        if row < 0:
            return
        iface_name = table.item(row, 0).text() if table.item(row, 0) else ""
        if not iface_name:
            return
        iface_data = {}
        for i, key in enumerate(["iface", "type", "state", "method", "address",
                                 "gateway", "bridge_ports", "vlan", "mtu", "pending"]):
            item = table.item(row, i)
            if item:
                iface_data[key] = item.text()
        params = self._network_edit_dialog(panel, node_name, is_create=False, iface_data=iface_data)
        if params is None:
            return
        from ...backend import NetworkUpdateWorker
        worker = NetworkUpdateWorker(cfg, node_name, iface_name, params)
        worker.signals.result.connect(lambda msg, w=worker, hd=panel.current_obj_data: (
            panel.config_update_result.emit(msg),
            self.fetch_host_network(hd.host_name, hd),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Network error: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_network_delete(self):
        panel = self.panel
        cfg, node_name = self._get_network_cfg()
        if not cfg:
            return
        table = panel.host_network_table
        row = table.currentRow()
        if row < 0:
            return
        iface_name = table.item(row, 0).text() if table.item(row, 0) else ""
        if not iface_name:
            return
        ret = QMessageBox.question(
            panel, tr("Delete interface"),
            tr("Delete network interface {iface}?").format(iface=iface_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        from ...backend import NetworkDeleteWorker
        worker = NetworkDeleteWorker(cfg, node_name, iface_name)
        worker.signals.result.connect(lambda msg, w=worker, hd=panel.current_obj_data: (
            panel.config_update_result.emit(msg),
            self.fetch_host_network(hd.host_name, hd),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Network error: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_network_apply(self):
        panel = self.panel
        cfg, node_name = self._get_network_cfg()
        if not cfg:
            return
        ret = QMessageBox.question(
            panel, tr("Apply network changes"),
            tr("Apply all pending network changes? This will reload network configuration on the node."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        from ...backend import NetworkApplyWorker
        worker = NetworkApplyWorker(cfg, node_name)
        worker.signals.result.connect(lambda msg, w=worker, hd=panel.current_obj_data: (
            panel.config_update_result.emit(msg),
            self.fetch_host_network(hd.host_name, hd),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Network error: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_network_revert(self):
        panel = self.panel
        cfg, node_name = self._get_network_cfg()
        if not cfg:
            return
        ret = QMessageBox.question(
            panel, tr("Revert network changes"),
            tr("Revert all pending network changes?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        from ...backend import NetworkRevertWorker
        worker = NetworkRevertWorker(cfg, node_name)
        worker.signals.result.connect(lambda msg, w=worker, hd=panel.current_obj_data: (
            panel.config_update_result.emit(msg),
            self.fetch_host_network(hd.host_name, hd),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Network error: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _network_edit_dialog(self, parent, node_name, is_create=True, iface_data=None):
        dlg = QDialog(parent)
        dlg.setWindowTitle(tr("Create interface") if is_create else tr("Edit interface"))
        dlg.setMinimumWidth(420)
        layout = QFormLayout(dlg)

        iface_edit = QLineEdit(iface_data.get("iface", "") if iface_data else "")
        iface_edit.setEnabled(is_create)
        layout.addRow(tr("Interface name:"), iface_edit)

        type_combo = QComboBox()
        type_combo.addItem("eth", "eth")
        type_combo.addItem("bridge", "bridge")
        type_combo.addItem("bond", "bond")
        type_combo.addItem("vlan", "vlan")
        type_combo.addItem("OVSBridge", "OVSBridge")
        type_combo.addItem("OVSPort", "OVSPort")
        type_combo.addItem("OVSBond", "OVSBond")
        if iface_data:
            idx = type_combo.findData(iface_data.get("type", "eth"))
            if idx >= 0:
                type_combo.setCurrentIndex(idx)
        layout.addRow(tr("Type:"), type_combo)

        method_combo = QComboBox()
        method_combo.addItem(tr("Static"), "static")
        method_combo.addItem(tr("DHCP"), "dhcp")
        method_combo.addItem(tr("Manual"), "manual")
        if iface_data:
            idx = method_combo.findData(iface_data.get("method", "manual"))
            if idx >= 0:
                method_combo.setCurrentIndex(idx)
        layout.addRow(tr("Method:"), method_combo)

        address_edit = QLineEdit(iface_data.get("address", "") if iface_data else "")
        layout.addRow(tr("Address:"), address_edit)

        netmask_edit = QLineEdit()
        layout.addRow(tr("Netmask:"), netmask_edit)

        gateway_edit = QLineEdit(iface_data.get("gateway", "") if iface_data else "")
        layout.addRow(tr("Gateway:"), gateway_edit)

        bridge_ports_edit = QLineEdit(iface_data.get("bridge_ports", "") if iface_data else "")
        layout.addRow(tr("Bridge ports:"), bridge_ports_edit)

        vlan_edit = QLineEdit(iface_data.get("vlan", "") if iface_data else "")
        layout.addRow(tr("VLAN ID:"), vlan_edit)

        mtu_edit = QLineEdit(iface_data.get("mtu", "") if iface_data else "")
        layout.addRow(tr("MTU:"), mtu_edit)

        comment_edit = QLineEdit()
        layout.addRow(tr("Comment:"), comment_edit)

        autostart_cb = QCheckBox(tr("Autostart"))
        autostart_cb.setChecked(True)
        layout.addRow(autostart_cb)

        btns = QHBoxLayout()
        ok_btn = QPushButton(tr("OK"))
        cancel_btn = QPushButton(tr("Cancel"))
        btns.addStretch()
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addRow(btns)
        cancel_btn.clicked.connect(dlg.reject)
        ok_btn.clicked.connect(dlg.accept)
        if is_create:
            iface_edit.textChanged.connect(lambda t: ok_btn.setEnabled(bool(t.strip())))
            ok_btn.setEnabled(False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        params = {"type": type_combo.currentData()}
        if is_create:
            iface = iface_edit.text().strip()
            if not iface:
                return None
            params["iface"] = iface
        method = method_combo.currentData()
        if method:
            params["method"] = method
        addr = address_edit.text().strip()
        if addr:
            params["address"] = addr
        nm = netmask_edit.text().strip()
        if nm:
            params["netmask"] = nm
        gw = gateway_edit.text().strip()
        if gw:
            params["gateway"] = gw
        bp = bridge_ports_edit.text().strip()
        if bp:
            params["bridge_ports"] = bp
        vlan = vlan_edit.text().strip()
        if vlan:
            params["vlan_id"] = vlan
        mtu = mtu_edit.text().strip()
        if mtu:
            try:
                params["mtu"] = int(mtu)
            except ValueError:
                pass
        cmt = comment_edit.text().strip()
        if cmt:
            params["comments"] = cmt
        if not autostart_cb.isChecked():
            params["autostart"] = 0
        return params

    def _on_edit_backup_job(self):
        panel = self.panel
        table = panel.backup_jobs_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Edit backup job"), tr("Select a job to edit"))
            return
        id_item = table.item(row, 0)
        if not id_item:
            return
        job = id_item.data(Qt.UserRole)
        if not job:
            return
        cfg = getattr(panel, "_backup_jobs_cfg", None)
        if not cfg:
            return
        pve_major = getattr(panel, "_backup_jobs_pve_major", 7)
        storages = self._get_backup_jobs_storages()
        from ..backup_job_dialog import BackupJobDialog
        dlg = BackupJobDialog(panel, storages=storages, job=job)
        if dlg.exec() != BackupJobDialog.Accepted:
            return
        params = dlg.get_params()
        job_id = job.get("id", "")
        from ...backend import ClusterJobUpdateWorker
        worker = ClusterJobUpdateWorker(cfg, job_id, params, pve_major=pve_major)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_backup_jobs(cfg, panel._backup_jobs_context),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Job update failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_remove_backup_job(self):
        panel = self.panel
        table = panel.backup_jobs_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Remove backup job"), tr("Select a job to remove"))
            return
        id_item = table.item(row, 0)
        if not id_item:
            return
        job = id_item.data(Qt.UserRole)
        if not job:
            return
        job_id = job.get("id", "")
        if not job_id:
            return
        reply = QMessageBox.question(
            panel, tr("Remove backup job"),
            tr("Delete backup job \"{id}\"?").format(id=job_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        cfg = getattr(panel, "_backup_jobs_cfg", None)
        if not cfg:
            return
        pve_major = getattr(panel, "_backup_jobs_pve_major", 7)
        from ...backend import ClusterJobDeleteWorker
        worker = ClusterJobDeleteWorker(cfg, job_id, pve_major=pve_major)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_backup_jobs(cfg, panel._backup_jobs_context),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Job delete failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    # ------------------------------------------------------------------
    # Access Management tab
    # ------------------------------------------------------------------

    def build_access_tab(self):
        panel = self.panel
        inner = QTabWidget()

        inner.addTab(self._build_access_users_page(), get_icon("user"), tr("Users"))
        inner.addTab(self._build_access_tokens_page(), get_icon("token"), tr("API Tokens"))
        inner.addTab(self._build_access_groups_page(), get_icon("group"), tr("Groups"))
        inner.addTab(self._build_access_roles_page(), get_icon("role"), tr("Roles"))
        inner.addTab(self._build_access_acl_page(), get_icon("acl"), tr("Permissions"))

        panel.access_inner = inner
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(inner)
        return tab

    # --- Users sub-page ---

    def _build_access_users_page(self):
        panel = self.panel
        loading = loading_label()
        table = make_table(
            [tr("User ID"), tr("Enabled"), tr("Expire"), tr("Groups"),
             tr("Comment"), tr("Tokens")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 60),
             (QHeaderView.Interactive, 100), (QHeaderView.Stretch, None),
             (QHeaderView.Stretch, None), (QHeaderView.Interactive, 60)],
            sortable=True,
        )
        panel.access_users_table = table
        table.doubleClicked.connect(lambda idx: self._on_edit_access_user())
        toolbar = QWidget()
        btn_layout = QHBoxLayout(toolbar)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        add_btn = QPushButton(get_icon("add"), tr("Add"))
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._on_add_access_user)
        btn_layout.addWidget(add_btn)
        edit_btn = QPushButton(tr("Edit"))
        edit_btn.setMinimumHeight(28)
        edit_btn.clicked.connect(self._on_edit_access_user)
        btn_layout.addWidget(edit_btn)
        remove_btn = QPushButton(get_icon("remove"), tr("Remove"))
        remove_btn.setMinimumHeight(28)
        remove_btn.clicked.connect(self._on_remove_access_user)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        stack = QStackedWidget()
        stack.addWidget(loading)
        from ._table_utils import make_filterable_table
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.access_users_loading = loading
        panel.access_users_stack = stack
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        return container

    # --- Tokens sub-page ---

    def _build_access_tokens_page(self):
        panel = self.panel
        loading = loading_label()
        table = make_table(
            [tr("Token ID"), tr("User"), tr("Comment"), tr("Priv. sep."),
             tr("Expire")],
            [(QHeaderView.Stretch, None), (QHeaderView.Stretch, None),
             (QHeaderView.Stretch, None), (QHeaderView.Interactive, 80),
             (QHeaderView.Interactive, 100)],
            sortable=True,
        )
        panel.access_tokens_table = table
        table.doubleClicked.connect(lambda idx: self._on_edit_access_token())
        toolbar = QWidget()
        btn_layout = QHBoxLayout(toolbar)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        add_btn = QPushButton(get_icon("add"), tr("Add"))
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._on_add_access_token)
        btn_layout.addWidget(add_btn)
        edit_btn = QPushButton(tr("Edit"))
        edit_btn.setMinimumHeight(28)
        edit_btn.clicked.connect(self._on_edit_access_token)
        btn_layout.addWidget(edit_btn)
        remove_btn = QPushButton(get_icon("remove"), tr("Remove"))
        remove_btn.setMinimumHeight(28)
        remove_btn.clicked.connect(self._on_remove_access_token)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        stack = QStackedWidget()
        stack.addWidget(loading)
        from ._table_utils import make_filterable_table
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.access_tokens_loading = loading
        panel.access_tokens_stack = stack
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        return container

    # --- Groups sub-page ---

    def _build_access_groups_page(self):
        panel = self.panel
        loading = loading_label()
        table = make_table(
            [tr("Group ID"), tr("Comment"), tr("Members")],
            [(QHeaderView.Stretch, None), (QHeaderView.Stretch, None),
             (QHeaderView.Stretch, None)],
            sortable=True,
        )
        panel.access_groups_table = table
        table.doubleClicked.connect(lambda idx: self._on_edit_access_group())
        toolbar = QWidget()
        btn_layout = QHBoxLayout(toolbar)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        add_btn = QPushButton(get_icon("add"), tr("Add"))
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._on_add_access_group)
        btn_layout.addWidget(add_btn)
        edit_btn = QPushButton(tr("Edit"))
        edit_btn.setMinimumHeight(28)
        edit_btn.clicked.connect(self._on_edit_access_group)
        btn_layout.addWidget(edit_btn)
        remove_btn = QPushButton(get_icon("remove"), tr("Remove"))
        remove_btn.setMinimumHeight(28)
        remove_btn.clicked.connect(self._on_remove_access_group)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        stack = QStackedWidget()
        stack.addWidget(loading)
        from ._table_utils import make_filterable_table
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.access_groups_loading = loading
        panel.access_groups_stack = stack
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        return container

    # --- Roles sub-page ---

    def _build_access_roles_page(self):
        panel = self.panel
        loading = loading_label()
        table = make_table(
            [tr("Role ID"), tr("Privileges"), tr("Built-in")],
            [(QHeaderView.Stretch, None), (QHeaderView.Stretch, None),
             (QHeaderView.Interactive, 70)],
            sortable=True,
        )
        panel.access_roles_table = table
        table.doubleClicked.connect(lambda idx: self._on_edit_access_role())
        toolbar = QWidget()
        btn_layout = QHBoxLayout(toolbar)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        add_btn = QPushButton(get_icon("add"), tr("Add"))
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._on_add_access_role)
        btn_layout.addWidget(add_btn)
        edit_btn = QPushButton(tr("Edit"))
        edit_btn.setMinimumHeight(28)
        edit_btn.clicked.connect(self._on_edit_access_role)
        btn_layout.addWidget(edit_btn)
        remove_btn = QPushButton(get_icon("remove"), tr("Remove"))
        remove_btn.setMinimumHeight(28)
        remove_btn.clicked.connect(self._on_remove_access_role)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        stack = QStackedWidget()
        stack.addWidget(loading)
        from ._table_utils import make_filterable_table
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.access_roles_loading = loading
        panel.access_roles_stack = stack
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        return container

    # --- ACL / Permissions sub-page ---

    def _build_access_acl_page(self):
        panel = self.panel
        loading = loading_label()
        table = make_table(
            [tr("Path"), tr("Type"), tr("ID"), tr("Role"), tr("Propagate")],
            [(QHeaderView.Stretch, None), (QHeaderView.Interactive, 80),
             (QHeaderView.Stretch, None), (QHeaderView.Stretch, None),
             (QHeaderView.Interactive, 80)],
            sortable=True,
        )
        panel.access_acl_table = table
        toolbar = QWidget()
        btn_layout = QHBoxLayout(toolbar)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        add_btn = QPushButton(get_icon("add"), tr("Add"))
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._on_add_access_acl)
        btn_layout.addWidget(add_btn)
        remove_btn = QPushButton(get_icon("remove"), tr("Remove"))
        remove_btn.setMinimumHeight(28)
        remove_btn.clicked.connect(self._on_remove_access_acl)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        stack = QStackedWidget()
        stack.addWidget(loading)
        from ._table_utils import make_filterable_table
        stack.addWidget(make_filterable_table(table))
        stack.setCurrentIndex(0)
        panel.access_acl_loading = loading
        panel.access_acl_stack = stack
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        return container

    # --- Fetch methods ---

    def _fetch_access_all(self, cfg):
        self._fetch_access_users(cfg)
        self._fetch_access_groups(cfg)
        self._fetch_access_roles(cfg)
        self._fetch_access_acl(cfg)

    def _fetch_access_users(self, cfg):
        panel = self.panel
        if not cfg:
            panel.access_users_loading.setText(tr("No data"))
            panel.access_users_stack.setCurrentIndex(0)
            return
        panel.access_users_loading.setText(tr("Loading..."))
        panel.access_users_stack.setCurrentIndex(0)
        panel.access_users_table.setRowCount(0)
        panel._access_cfg = cfg
        from ...backend import AccessUsersWorker
        worker = AccessUsersWorker(cfg)
        worker.signals.users_ready.connect(
            lambda data, w=worker: (
                self._on_access_users_loaded(data),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.users_error.connect(
            lambda err, w=worker: (
                self._on_access_users_error(err),
                panel._workers_mgr.discard_worker(w),
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def _on_access_users_loaded(self, data):
        panel = self.panel
        if panel.current_obj_type not in ("cluster", "host"):
            return
        panel._access_users_cache = data
        table = panel.access_users_table
        table.setSortingEnabled(False)
        table.setRowCount(len(data))
        for i, user in enumerate(data):
            uid = user.get("userid", "")
            id_item = QTableWidgetItem(uid)
            id_item.setIcon(get_icon("user"))
            id_item.setData(Qt.UserRole, user)
            table.setItem(i, 0, id_item)

            enable_val = user.get("enable", 1)
            if isinstance(enable_val, str):
                enable_val = int(enable_val)
            en_text = tr("Yes") if enable_val else tr("No")
            en_item = QTableWidgetItem(en_text)
            en_item.setForeground(QColor(
                Color.STATUS_OK if enable_val else Color.TEXT_DIM
            ))
            table.setItem(i, 1, en_item)

            expire = user.get("expire", 0)
            if isinstance(expire, str):
                expire = int(expire)
            if expire and expire > 0:
                from datetime import datetime as _dt
                expire_text = _dt.fromtimestamp(expire).strftime("%Y-%m-%d")
            else:
                expire_text = tr("Never")
            table.setItem(i, 2, QTableWidgetItem(expire_text))

            groups = user.get("groups", "")
            if isinstance(groups, list):
                groups = ", ".join(groups)
            table.setItem(i, 3, QTableWidgetItem(groups or ""))

            table.setItem(i, 4, QTableWidgetItem(user.get("comment", "") or ""))

            tokens = user.get("tokens", [])
            tokens_count = len(tokens) if isinstance(tokens, list) else 0
            table.setItem(i, 5, QTableWidgetItem(str(tokens_count)))

        table.setSortingEnabled(True)
        if data:
            panel.access_users_stack.setCurrentIndex(1)
        else:
            panel.access_users_loading.setText(tr("No users"))
            panel.access_users_stack.setCurrentIndex(0)
        cfg = getattr(panel, "_access_cfg", None)
        if cfg:
            self._fetch_access_tokens(cfg)

    def _on_access_users_error(self, err):
        panel = self.panel
        panel.access_users_loading.setText(tr("Error: {err}").format(err=err[:80]))
        panel.access_users_stack.setCurrentIndex(0)

    def _fetch_access_tokens(self, cfg):
        panel = self.panel
        if not cfg:
            panel.access_tokens_loading.setText(tr("No data"))
            panel.access_tokens_stack.setCurrentIndex(0)
            return
        panel.access_tokens_loading.setText(tr("Loading..."))
        panel.access_tokens_stack.setCurrentIndex(0)
        panel.access_tokens_table.setRowCount(0)
        users = getattr(panel, "_access_users_cache", [])
        if not users:
            panel.access_tokens_loading.setText(tr("No users"))
            panel.access_tokens_stack.setCurrentIndex(0)
            return
        user_ids = [u.get("userid") for u in users if u.get("userid")]
        if not user_ids:
            panel.access_tokens_loading.setText(tr("No users"))
            panel.access_tokens_stack.setCurrentIndex(0)
            return
        panel._access_tokens_epoch = getattr(panel, "_access_tokens_epoch", 0) + 1
        panel._access_tokens_pending = len(user_ids)
        this_epoch = panel._access_tokens_epoch
        from ...backend import AccessTokensWorker
        for uid in user_ids:
            worker = AccessTokensWorker(cfg, uid)
            worker.signals.tokens_ready.connect(
                lambda data, w=worker, u=uid, e=this_epoch: (
                    self._on_access_tokens_partial(data, u, e),
                    panel._workers_mgr.discard_worker(w),
                )
            )
            worker.signals.tokens_error.connect(
                lambda err, w=worker, e=this_epoch: (
                    self._on_access_tokens_done(e),
                    panel._workers_mgr.discard_worker(w),
                )
            )
            panel._workers_mgr.run_host_worker(worker)

    def _on_access_tokens_done(self, epoch=None):
        panel = self.panel
        cur = getattr(panel, "_access_tokens_epoch", 0)
        if epoch is not None and epoch != cur:
            return
        panel._access_tokens_pending = getattr(panel, "_access_tokens_pending", 0) - 1
        if panel._access_tokens_pending <= 0:
            if panel.access_tokens_table.rowCount() > 0:
                panel.access_tokens_stack.setCurrentIndex(1)
            else:
                panel.access_tokens_loading.setText(tr("No tokens"))
                panel.access_tokens_stack.setCurrentIndex(0)

    def _on_access_tokens_partial(self, data, userid, epoch=None):
        panel = self.panel
        cur = getattr(panel, "_access_tokens_epoch", 0)
        if epoch is not None and epoch != cur:
            return
        if panel.current_obj_type not in ("cluster", "host"):
            self._on_access_tokens_done(epoch)
            return
        if not isinstance(data, list):
            self._on_access_tokens_done(epoch)
            return
        table = panel.access_tokens_table
        table.setSortingEnabled(False)
        for token in data:
            row = table.rowCount()
            table.insertRow(row)
            tid = token.get("tokenid", "")
            id_item = QTableWidgetItem(tid)
            id_item.setIcon(get_icon("token"))
            id_item.setData(Qt.UserRole, {"userid": userid, **token})
            table.setItem(row, 0, id_item)
            table.setItem(row, 1, QTableWidgetItem(userid))
            table.setItem(row, 2, QTableWidgetItem(token.get("comment", "") or ""))
            privsep = token.get("privsep", 1)
            if isinstance(privsep, str):
                privsep = int(privsep)
            table.setItem(row, 3, QTableWidgetItem(tr("Yes") if privsep else tr("No")))
            expire = token.get("expire", 0)
            if isinstance(expire, str):
                expire = int(expire)
            if expire and expire > 0:
                from datetime import datetime as _dt
                expire_text = _dt.fromtimestamp(expire).strftime("%Y-%m-%d")
            else:
                expire_text = tr("Never")
            table.setItem(row, 4, QTableWidgetItem(expire_text))
        table.setSortingEnabled(True)
        if table.rowCount() > 0:
            panel.access_tokens_stack.setCurrentIndex(1)
        self._on_access_tokens_done(epoch)

    def _fetch_access_groups(self, cfg):
        panel = self.panel
        if not cfg:
            panel.access_groups_loading.setText(tr("No data"))
            panel.access_groups_stack.setCurrentIndex(0)
            return
        panel.access_groups_loading.setText(tr("Loading..."))
        panel.access_groups_stack.setCurrentIndex(0)
        panel.access_groups_table.setRowCount(0)
        from ...backend import AccessGroupsWorker
        worker = AccessGroupsWorker(cfg)
        worker.signals.groups_ready.connect(
            lambda data, w=worker: (
                self._on_access_groups_loaded(data),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.groups_error.connect(
            lambda err, w=worker: (
                panel.access_groups_loading.setText(tr("Error: {err}").format(err=err[:80])),
                panel.access_groups_stack.setCurrentIndex(0),
                panel._workers_mgr.discard_worker(w),
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def _on_access_groups_loaded(self, data):
        panel = self.panel
        if panel.current_obj_type not in ("cluster", "host"):
            return
        panel._access_groups_cache = data
        table = panel.access_groups_table
        table.setSortingEnabled(False)
        table.setRowCount(len(data))
        for i, group in enumerate(data):
            gid = group.get("groupid", "")
            id_item = QTableWidgetItem(gid)
            id_item.setIcon(get_icon("group"))
            id_item.setData(Qt.UserRole, group)
            table.setItem(i, 0, id_item)
            table.setItem(i, 1, QTableWidgetItem(group.get("comment", "") or ""))
            members = group.get("users", "")
            if isinstance(members, list):
                members = ", ".join(members)
            table.setItem(i, 2, QTableWidgetItem(members or ""))
        table.setSortingEnabled(True)
        if data:
            panel.access_groups_stack.setCurrentIndex(1)
        else:
            panel.access_groups_loading.setText(tr("No groups"))
            panel.access_groups_stack.setCurrentIndex(0)

    def _fetch_access_roles(self, cfg):
        panel = self.panel
        if not cfg:
            panel.access_roles_loading.setText(tr("No data"))
            panel.access_roles_stack.setCurrentIndex(0)
            return
        panel.access_roles_loading.setText(tr("Loading..."))
        panel.access_roles_stack.setCurrentIndex(0)
        panel.access_roles_table.setRowCount(0)
        from ...backend import AccessRolesWorker
        worker = AccessRolesWorker(cfg)
        worker.signals.roles_ready.connect(
            lambda data, w=worker: (
                self._on_access_roles_loaded(data),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.roles_error.connect(
            lambda err, w=worker: (
                panel.access_roles_loading.setText(tr("Error: {err}").format(err=err[:80])),
                panel.access_roles_stack.setCurrentIndex(0),
                panel._workers_mgr.discard_worker(w),
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def _on_access_roles_loaded(self, data):
        panel = self.panel
        if panel.current_obj_type not in ("cluster", "host"):
            return
        panel._access_roles_cache = data
        table = panel.access_roles_table
        table.setSortingEnabled(False)
        table.setRowCount(len(data))
        for i, role in enumerate(data):
            rid = role.get("roleid", "")
            id_item = QTableWidgetItem(rid)
            id_item.setIcon(get_icon("role"))
            id_item.setData(Qt.UserRole, role)
            table.setItem(i, 0, id_item)
            privs = role.get("privs", "") or ""
            if isinstance(privs, list):
                privs = ", ".join(privs)
            table.setItem(i, 1, QTableWidgetItem(privs))
            special = role.get("special", 0)
            if isinstance(special, str):
                special = int(special)
            sp_text = tr("Yes") if special else ""
            sp_item = QTableWidgetItem(sp_text)
            if special:
                sp_item.setForeground(QColor(Color.TEXT_DIM))
            table.setItem(i, 2, sp_item)
        table.setSortingEnabled(True)
        if data:
            panel.access_roles_stack.setCurrentIndex(1)
        else:
            panel.access_roles_loading.setText(tr("No roles"))
            panel.access_roles_stack.setCurrentIndex(0)

    def _fetch_access_acl(self, cfg):
        panel = self.panel
        if not cfg:
            panel.access_acl_loading.setText(tr("No data"))
            panel.access_acl_stack.setCurrentIndex(0)
            return
        panel.access_acl_loading.setText(tr("Loading..."))
        panel.access_acl_stack.setCurrentIndex(0)
        panel.access_acl_table.setRowCount(0)
        from ...backend import AccessAclWorker
        worker = AccessAclWorker(cfg)
        worker.signals.acl_ready.connect(
            lambda data, w=worker: (
                self._on_access_acl_loaded(data),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.acl_error.connect(
            lambda err, w=worker: (
                panel.access_acl_loading.setText(tr("Error: {err}").format(err=err[:80])),
                panel.access_acl_stack.setCurrentIndex(0),
                panel._workers_mgr.discard_worker(w),
            )
        )
        panel._workers_mgr.run_host_worker(worker)

    def _on_access_acl_loaded(self, data):
        panel = self.panel
        if panel.current_obj_type not in ("cluster", "host"):
            return
        table = panel.access_acl_table
        table.setSortingEnabled(False)
        table.setRowCount(len(data))
        for i, entry in enumerate(data):
            path = entry.get("path", "")
            path_item = QTableWidgetItem(path)
            path_item.setData(Qt.UserRole, entry)
            table.setItem(i, 0, path_item)
            table.setItem(i, 1, QTableWidgetItem(entry.get("type", "")))
            table.setItem(i, 2, QTableWidgetItem(entry.get("ugid", "")))
            table.setItem(i, 3, QTableWidgetItem(entry.get("roleid", "")))
            propagate = entry.get("propagate", 1)
            if isinstance(propagate, str):
                propagate = int(propagate)
            table.setItem(i, 4, QTableWidgetItem(tr("Yes") if propagate else tr("No")))
        table.setSortingEnabled(True)
        if data:
            panel.access_acl_stack.setCurrentIndex(1)
        else:
            panel.access_acl_loading.setText(tr("No permissions"))
            panel.access_acl_stack.setCurrentIndex(0)

    # --- User CRUD ---

    def _on_add_access_user(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        groups = getattr(panel, "_access_groups_cache", [])
        from ..user_dialog import UserDialog
        dlg = UserDialog(panel, groups=groups)
        if dlg.exec() != UserDialog.Accepted:
            return
        params = dlg.get_params()
        if not params:
            return
        from ...backend import AccessUserCreateWorker
        worker = AccessUserCreateWorker(cfg, params)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_users(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("User create failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_edit_access_user(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_users_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Edit user"), tr("Select a user to edit"))
            return
        item = table.item(row, 0)
        if not item:
            return
        user = item.data(Qt.UserRole)
        if not user:
            return
        groups = getattr(panel, "_access_groups_cache", [])
        from ..user_dialog import UserDialog
        dlg = UserDialog(panel, user=user, groups=groups)
        if dlg.exec() != UserDialog.Accepted:
            return
        params = dlg.get_params()
        if not params:
            return
        userid = user.get("userid", "")
        from ...backend import AccessUserUpdateWorker
        worker = AccessUserUpdateWorker(cfg, userid, params)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_users(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("User update failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_remove_access_user(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_users_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Remove user"), tr("Select a user to remove"))
            return
        item = table.item(row, 0)
        if not item:
            return
        user = item.data(Qt.UserRole)
        if not user:
            return
        userid = user.get("userid", "")
        reply = QMessageBox.question(
            panel, tr("Remove user"),
            tr("Delete user \"{id}\"?").format(id=userid),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        from ...backend import AccessUserDeleteWorker
        worker = AccessUserDeleteWorker(cfg, userid)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_users(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("User delete failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    # --- Token CRUD ---

    def _on_add_access_token(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        users = getattr(panel, "_access_users_cache", [])
        if not users:
            panel.config_update_result.emit(tr("No users found"))
            return
        from ..token_dialog import TokenDialog
        dlg = TokenDialog(panel, users=users)
        if dlg.exec() != TokenDialog.Accepted:
            return
        userid = dlg.get_userid()
        tokenid = dlg.get_tokenid()
        params = dlg.get_params()
        if not userid or not tokenid:
            return
        from ...backend import AccessTokenCreateWorker
        worker = AccessTokenCreateWorker(cfg, userid, tokenid, params)
        worker.signals.result.connect(
            lambda msg, full, value, w=worker: (
                panel.config_update_result.emit(msg),
                self._show_token_value(full, value) if full else None,
                self._fetch_access_tokens(cfg),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Token create failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_edit_access_token(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_tokens_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Edit token"), tr("Select a token to edit"))
            return
        item = table.item(row, 0)
        if not item:
            return
        token_data = item.data(Qt.UserRole)
        if not token_data:
            return
        userid = token_data.get("userid", "")
        from ..token_dialog import TokenDialog
        dlg = TokenDialog(panel, userid=userid, token=token_data)
        if dlg.exec() != TokenDialog.Accepted:
            return
        tokenid = dlg.get_tokenid()
        params = dlg.get_params()
        if not tokenid:
            return
        from ...backend import AccessTokenUpdateWorker
        worker = AccessTokenUpdateWorker(cfg, userid, tokenid, params)
        worker.signals.result.connect(
            lambda msg, full, value, w=worker: (
                panel.config_update_result.emit(msg),
                self._show_token_value(full, value) if full else None,
                self._fetch_access_tokens(cfg),
                panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Token update failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_remove_access_token(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_tokens_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Remove token"), tr("Select a token to remove"))
            return
        item = table.item(row, 0)
        if not item:
            return
        token_data = item.data(Qt.UserRole)
        if not token_data:
            return
        userid = token_data.get("userid", "")
        tokenid = token_data.get("tokenid", "")
        reply = QMessageBox.question(
            panel, tr("Remove token"),
            tr("Delete token \"{id}\" for user \"{user}\"?").format(id=tokenid, user=userid),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        from ...backend import AccessTokenDeleteWorker
        worker = AccessTokenDeleteWorker(cfg, userid, tokenid)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_tokens(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Token delete failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _show_token_value(self, full_tokenid, value):
        from ..token_dialog import TokenValueDialog
        dlg = TokenValueDialog(self.panel, full_tokenid, value)
        dlg.exec()

    # --- Group CRUD ---

    def _on_add_access_group(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        from ..group_dialog import GroupDialog
        dlg = GroupDialog(panel)
        if dlg.exec() != GroupDialog.Accepted:
            return
        params = dlg.get_params()
        if not params:
            return
        from ...backend import AccessGroupCreateWorker
        worker = AccessGroupCreateWorker(cfg, params)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_groups(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Group create failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_edit_access_group(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_groups_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Edit group"), tr("Select a group to edit"))
            return
        item = table.item(row, 0)
        if not item:
            return
        group = item.data(Qt.UserRole)
        if not group:
            return
        from ..group_dialog import GroupDialog
        dlg = GroupDialog(panel, group=group)
        if dlg.exec() != GroupDialog.Accepted:
            return
        params = dlg.get_params()
        if not params:
            return
        gid = group.get("groupid", "")
        from ...backend import AccessGroupUpdateWorker
        worker = AccessGroupUpdateWorker(cfg, gid, params)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_groups(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Group update failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_remove_access_group(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_groups_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Remove group"), tr("Select a group to remove"))
            return
        item = table.item(row, 0)
        if not item:
            return
        group = item.data(Qt.UserRole)
        if not group:
            return
        gid = group.get("groupid", "")
        reply = QMessageBox.question(
            panel, tr("Remove group"),
            tr("Delete group \"{id}\"?").format(id=gid),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        from ...backend import AccessGroupDeleteWorker
        worker = AccessGroupDeleteWorker(cfg, gid)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_groups(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Group delete failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    # --- Role CRUD ---

    def _on_add_access_role(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        from ..role_dialog import RoleDialog
        dlg = RoleDialog(panel)
        if dlg.exec() != RoleDialog.Accepted:
            return
        params = dlg.get_params()
        if not params:
            return
        from ...backend import AccessRoleCreateWorker
        worker = AccessRoleCreateWorker(cfg, params)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_roles(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Role create failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_edit_access_role(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_roles_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Edit role"), tr("Select a role to edit"))
            return
        item = table.item(row, 0)
        if not item:
            return
        role = item.data(Qt.UserRole)
        if not role:
            return
        rid = role.get("roleid", "")
        from ..role_dialog import RoleDialog
        dlg = RoleDialog(panel, role=role)
        if dlg.exec() != RoleDialog.Accepted:
            return
        params = dlg.get_params()
        if not params:
            return
        from ...backend import AccessRoleUpdateWorker
        worker = AccessRoleUpdateWorker(cfg, rid, params)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_roles(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Role update failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_remove_access_role(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_roles_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Remove role"), tr("Select a role to remove"))
            return
        item = table.item(row, 0)
        if not item:
            return
        role = item.data(Qt.UserRole)
        if not role:
            return
        special = role.get("special", 0)
        if isinstance(special, str):
            special = int(special)
        if special:
            QMessageBox.information(panel, tr("Remove role"), tr("Built-in roles cannot be deleted"))
            return
        rid = role.get("roleid", "")
        reply = QMessageBox.question(
            panel, tr("Remove role"),
            tr("Delete role \"{id}\"?").format(id=rid),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        from ...backend import AccessRoleDeleteWorker
        worker = AccessRoleDeleteWorker(cfg, rid)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_roles(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Role delete failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    # --- ACL CRUD ---

    def _on_add_access_acl(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        roles = getattr(panel, "_access_roles_cache", [])
        users = getattr(panel, "_access_users_cache", [])
        groups = getattr(panel, "_access_groups_cache", [])
        tokens = []
        table = panel.access_tokens_table
        for r in range(table.rowCount()):
            item = table.item(r, 0)
            if item:
                td = item.data(Qt.UserRole)
                if td:
                    tokens.append({
                        "full-tokenid": f"{td.get('userid', '')}!{td.get('tokenid', '')}"
                    })
        from ..acl_dialog import AclDialog
        dlg = AclDialog(panel, roles=roles, users=users, groups=groups, tokens=tokens)
        if dlg.exec() != AclDialog.Accepted:
            return
        params = dlg.get_params()
        if not params:
            return
        from ...backend import AccessAclUpdateWorker
        worker = AccessAclUpdateWorker(cfg, params)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_acl(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Permission add failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_remove_access_acl(self):
        panel = self.panel
        cfg = getattr(panel, "_access_cfg", None)
        if not cfg:
            return
        table = panel.access_acl_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("Remove permissions"), tr("Select an entry to remove"))
            return
        item = table.item(row, 0)
        if not item:
            return
        entry = item.data(Qt.UserRole)
        if not entry:
            return
        path = entry.get("path", "")
        roleid = entry.get("roleid", "")
        etype = entry.get("type", "")
        ugid = entry.get("ugid", "")
        reply = QMessageBox.question(
            panel, tr("Remove permissions"),
            tr("Remove permission: role \"{role}\" for \"{ugid}\" on \"{path}\"?").format(
                role=roleid, ugid=ugid, path=path),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        params = {"path": path, "roles": roleid, "delete": 1}
        if etype == "user":
            params["users"] = ugid
        elif etype == "group":
            params["groups"] = ugid
        elif etype == "token":
            params["tokens"] = ugid
        from ...backend import AccessAclUpdateWorker
        worker = AccessAclUpdateWorker(cfg, params)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self._fetch_access_acl(cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("Permission remove failed: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    # ------------------------------------------------------------------
    # HA tab
    # ------------------------------------------------------------------

    def build_ha_tab(self):
        panel = self.panel
        loading = loading_label()

        groups_table = make_table(
            [tr("Group"), tr("Nodes"), tr("Restricted"), tr("No failback"), tr("Comment")],
            [(QHeaderView.Interactive, 150), (QHeaderView.Stretch, None),
             (QHeaderView.Interactive, 80), (QHeaderView.Interactive, 90),
             (QHeaderView.Stretch, None)],
        )
        panel.ha_groups_table = groups_table

        resources_table = make_table(
            [tr("VM"), tr("Group"), tr("State"), tr("Max restart"), tr("Max relocate"),
             tr("Comment")],
            [(QHeaderView.Interactive, 120), (QHeaderView.Interactive, 150),
             (QHeaderView.Interactive, 80), (QHeaderView.Interactive, 80),
             (QHeaderView.Interactive, 80), (QHeaderView.Stretch, None)],
        )
        panel.ha_resources_table = resources_table

        ha_add_btn = QPushButton(get_icon("add"), tr("Add VM to HA"))
        ha_add_btn.setMinimumHeight(28)
        ha_add_btn.clicked.connect(self._on_ha_add_resource)
        ha_remove_btn = QPushButton(get_icon("remove"), tr("Remove from HA"))
        ha_remove_btn.setMinimumHeight(28)
        ha_remove_btn.clicked.connect(self._on_ha_remove_resource)
        ha_refresh_btn = QPushButton(tr("Refresh"))
        ha_refresh_btn.setMinimumHeight(28)
        ha_refresh_btn.clicked.connect(self._on_ha_refresh)

        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(0, 0, 0, 0)
        tb_layout.setSpacing(4)
        tb_layout.addWidget(ha_add_btn)
        tb_layout.addWidget(ha_remove_btn)
        tb_layout.addStretch()
        tb_layout.addWidget(ha_refresh_btn)
        panel.ha_add_btn = ha_add_btn
        panel.ha_remove_btn = ha_remove_btn

        stack = QStackedWidget()
        stack.addWidget(loading)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(6)
        inner_layout.addWidget(QLabel(tr("HA Groups")))
        inner_layout.addWidget(groups_table)
        inner_layout.addSpacing(8)
        inner_layout.addWidget(QLabel(tr("HA Resources")))
        inner_layout.addWidget(resources_table)
        stack.addWidget(inner)
        stack.setCurrentIndex(0)
        panel.ha_loading = loading
        panel.ha_stack = stack

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(stack)
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        tab.setWidget(container)
        return tab

    def fetch_ha(self, cfg):
        from ...backend import HaResourcesWorker
        worker = HaResourcesWorker(cfg)
        worker.signals.ha_resources_ready.connect(
            lambda data, w=worker: (
                self._on_ha_resources(data),
                self.panel._workers_mgr.discard_worker(w),
            )
        )
        worker.signals.ha_resources_error.connect(
            lambda err, w=worker: (
                self._on_ha_error(err),
                self.panel._workers_mgr.discard_worker(w),
            )
        )
        self.panel._workers_mgr.run_host_worker(worker)

    def _on_ha_resources(self, data):
        panel = self.panel
        panel.ha_stack.setCurrentIndex(1)

        ha_groups = []
        for groups in panel.all_ha_groups.values():
            ha_groups.extend(groups)
        ha_groups.sort(key=lambda g: g.group)
        groups_table = panel.ha_groups_table
        groups_table.setRowCount(len(ha_groups))
        for i, g in enumerate(ha_groups):
            groups_table.setItem(i, 0, QTableWidgetItem(g.group))
            groups_table.setItem(i, 1, QTableWidgetItem(g.nodes))
            restricted = tr("Yes") if g.restricted else tr("No")
            groups_table.setItem(i, 2, QTableWidgetItem(restricted))
            nofailback = tr("Yes") if g.nofailback else tr("No")
            groups_table.setItem(i, 3, QTableWidgetItem(nofailback))
            groups_table.setItem(i, 4, QTableWidgetItem(g.comment))
        groups_table.resizeRowsToContents()

        resources_table = panel.ha_resources_table
        resources_table.setRowCount(len(data))
        for i, r in enumerate(data):
            resources_table.setItem(i, 0, QTableWidgetItem(r.sid))
            resources_table.setItem(i, 1, QTableWidgetItem(r.group))
            resources_table.setItem(i, 2, QTableWidgetItem(r.state))
            resources_table.setItem(i, 3, QTableWidgetItem(str(r.max_restart)))
            resources_table.setItem(i, 4, QTableWidgetItem(str(r.max_relocate)))
            resources_table.setItem(i, 5, QTableWidgetItem(r.comment))
        resources_table.resizeRowsToContents()

        panel.ha_remove_btn.setEnabled(len(data) > 0)

    def _on_ha_error(self, err):
        panel = self.panel
        panel.ha_loading.setText(err)
        panel.ha_stack.setCurrentIndex(0)

    def _on_ha_refresh(self):
        panel = self.panel
        cluster_cfg = panel._current_cluster_cfg
        if not cluster_cfg:
            return
        self.fetch_ha(cluster_cfg)

    def _on_ha_add_resource(self):
        panel = self.panel
        cluster_cfg = panel._current_cluster_cfg
        if not cluster_cfg:
            return

        current_cluster = cluster_cfg.get("cluster", "")
        ha_groups_raw = []
        for h, groups in panel.all_ha_groups.items():
            h_cfg = panel._cfg_by_name.get(h, {})
            if h_cfg.get("cluster", "") != current_cluster:
                continue
            for g in groups:
                if g.group:
                    ha_groups_raw.append(g.group)
        if not ha_groups_raw:
            QMessageBox.information(panel, tr("HA"), tr("No HA groups available"))
            return

        vms = []
        for vm in panel.all_vms:
            host_name = vm.host_name or ""
            if host_name:
                cfg = panel._cfg_by_name.get(host_name)
                if cfg and cfg.get("cluster") == current_cluster:
                    vms.append(vm)
        if not vms:
            QMessageBox.information(panel, tr("HA"), tr("No VMs available"))
            return

        dlg = QDialog(panel)
        dlg.setWindowTitle(tr("Add VM to HA"))
        dlg.setMinimumWidth(400)
        layout = QFormLayout(dlg)

        vm_combo = QComboBox()
        for vm in sorted(vms, key=lambda v: v.vmid):
            vmid = vm.vmid or "?"
            name = vm.name or ""
            label = f"vm:{vmid}" if not name else f"{name} (vm:{vmid})"
            vm_combo.addItem(label, f"vm:{vmid}")
        layout.addRow(tr("VM:"), vm_combo)

        group_combo = QComboBox()
        for g in sorted(set(ha_groups_raw)):
            group_combo.addItem(g, g)
        layout.addRow(tr("HA group:"), group_combo)

        state_combo = QComboBox()
        state_combo.addItem(tr("Default"), "default")
        state_combo.addItem(tr("Started"), "started")
        state_combo.addItem(tr("Stopped"), "stopped")
        state_combo.addItem(tr("Enabled"), "enabled")
        state_combo.addItem(tr("Ignored"), "ignored")
        layout.addRow(tr("State:"), state_combo)

        max_restart_spin = QSpinBox()
        max_restart_spin.setRange(0, 10)
        max_restart_spin.setValue(1)
        layout.addRow(tr("Max restart:"), max_restart_spin)

        max_relocate_spin = QSpinBox()
        max_relocate_spin.setRange(0, 10)
        max_relocate_spin.setValue(1)
        layout.addRow(tr("Max relocate:"), max_relocate_spin)

        comment_edit = QLineEdit()
        layout.addRow(tr("Comment:"), comment_edit)

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

        sid = vm_combo.currentData()
        group = group_combo.currentData()
        state = state_combo.currentData()
        max_restart = max_restart_spin.value()
        max_relocate = max_relocate_spin.value()
        comment = comment_edit.text().strip()

        from ...backend import HaResourceAddWorker
        worker = HaResourceAddWorker(
            cluster_cfg, sid, group, state=state,
            max_restart=max_restart, max_relocate=max_relocate, comment=comment,
        )
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self.fetch_ha(cluster_cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("HA error: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)

    def _on_ha_remove_resource(self):
        panel = self.panel
        cluster_cfg = panel._current_cluster_cfg
        if not cluster_cfg:
            return
        table = panel.ha_resources_table
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(panel, tr("HA"), tr("Select a resource to remove"))
            return
        sid_item = table.item(row, 0)
        if not sid_item:
            return
        sid = sid_item.text()
        if not sid:
            return
        ret = QMessageBox.question(
            panel, tr("Remove from HA"),
            tr("Remove {sid} from HA?").format(sid=sid),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        from ...backend import HaResourceDeleteWorker
        worker = HaResourceDeleteWorker(cluster_cfg, sid)
        worker.signals.result.connect(lambda msg, w=worker: (
            panel.config_update_result.emit(msg),
            self.fetch_ha(cluster_cfg),
            panel._workers_mgr.discard_worker(w),
        ))
        worker.signals.error.connect(lambda err, w=worker: (
            panel.config_update_result.emit(tr("HA error: {err}").format(err=err)),
            panel._workers_mgr.discard_worker(w),
        ))
        panel._workers_mgr.run_host_worker(worker)
