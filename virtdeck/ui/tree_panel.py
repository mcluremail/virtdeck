import json
import re
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from ..config import load_tree_notes, load_ui_state, save_tree_note, save_ui_state
from ..domain import Node, NodeStatus, VmStatus, VmType
from .action_registry import (
    SCOPE_CT,
    SCOPE_TEMPLATE,
    SCOPE_VM,
    ActionRegistry,
    Selection,
)
from .action_specs import VM_ACTION_IDS, VM_BULK_ACTION_IDS, register_tree_actions
from .i18n import tr
from .icons import base_size, get_icon, init_icons, make_loading_icon
from .theme import Color
from .utils import build_cfg_index, status_text

VM_KEY_ROLE = Qt.UserRole + 1
ITEM_KEY_ROLE = Qt.UserRole + 2

def _vm_count_str(vms):
    total = len(vms)
    running = sum(1 for v in vms if v.status is VmStatus.RUNNING)
    return f"[{running}/{total}]"


def _node_tooltip(node):
    cpu = node.cpu_pct
    mem_pct = node.mem_pct
    uptime_str = str(timedelta(seconds=int(node.uptime_seconds))) if node.uptime_seconds else "?"
    return tr("CPU") + f": {cpu}%\n" + tr("RAM") + f": {mem_pct}%\n" + tr("Uptime") + f": {uptime_str}"


GROUP_MIME = "application/x-virtdeck-hostgroup"


class GroupTreeWidget(QTreeWidget):
    """QTreeWidget with drag&drop for host groups (B16).

    Dragging a host/cluster item onto a group item emits
    group_move_requested(kind, name, group).
    The tree is never mutated directly — the panel rebuilds it.
    """

    def __init__(self, panel):
        super().__init__()
        self._panel = panel
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def _drag_payload(self, item):
        """Payload dict for a draggable item, or None if not draggable."""
        if item is None:
            return None
        key = item.data(0, ITEM_KEY_ROLE)
        if not isinstance(key, tuple):
            return None
        if key[0] == "host" and len(key) > 2:
            return {"kind": "host", "name": key[2]}
        if key[0] == "cluster" and len(key) > 1:
            return {"kind": "cluster", "name": key[1]}
        return None

    def startDrag(self, supported_actions):
        payload = self._drag_payload(self.currentItem())
        if not payload:
            return
        mime = QMimeData()
        mime.setData(GROUP_MIME, json.dumps(payload).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def _decode(self, event):
        mime = event.mimeData()
        if mime is None or not mime.hasFormat(GROUP_MIME):
            return None
        try:
            payload = json.loads(bytes(mime.data(GROUP_MIME)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if payload.get("kind") not in ("host", "cluster") or not payload.get("name"):
            return None
        return payload

    def _drop_group(self, item):
        """Group name for the drop target item:
        group item -> its name; host/cluster directly inside a group -> that
        group; anything else -> None (drop not allowed)."""
        while item is not None:
            key = item.data(0, ITEM_KEY_ROLE)
            if isinstance(key, tuple):
                if key[0] == "group":
                    return key[1]
                if key[0] in ("host", "cluster"):
                    parent = item.parent()
                    if parent is not None:
                        pkey = parent.data(0, ITEM_KEY_ROLE)
                        if isinstance(pkey, tuple) and pkey[0] == "group":
                            return pkey[1]
                    return None
            item = item.parent()
        return None

    def dragEnterEvent(self, event):
        if self._decode(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._decode(event):
            event.ignore()
            return
        if self._drop_group(self.itemAt(event.position().toPoint())) is None:
            event.ignore()
        else:
            event.acceptProposedAction()

    def dropEvent(self, event):
        payload = self._decode(event)
        if not payload:
            event.ignore()
            return
        group = self._drop_group(self.itemAt(event.position().toPoint()))
        if group is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self._panel.group_move_requested.emit(payload["kind"], payload["name"], group)


class TreePanel(QWidget):
    item_selected = Signal(str, str, object)
    host_remove_requested = Signal(str, str)
    host_token_refresh_requested = Signal(str)
    host_trust_ssl_changed = Signal(str, bool)
    vm_create_requested = Signal(str, str)
    vm_delete_requested = Signal(str, str, int)
    vm_action_requested = Signal(str, str, int, str)
    vm_migrate_requested = Signal(str, str, int)
    vm_clone_requested = Signal(str, str, int)
    vm_convert_requested = Signal(str, str, int, str)  # (host_name, node, vmid, direction)
    vm_clone_from_template_requested = Signal(str, str)  # (host_name, node)
    vm_ha_add_requested = Signal(str, str, int)  # (host_name, node, vmid)
    vm_ha_remove_requested = Signal(str, str, int)  # (host_name, node, vmid)
    console_requested = Signal(str, str, int)
    novnc_requested = Signal(str, str, int)
    bulk_vm_action_requested = Signal(list, str)  # ([(host_name, vmid, node)], action)
    group_move_requested = Signal(str, str, str)  # kind ("host"|"cluster"), name, group ("" = none)
    group_rename_requested = Signal(str, str)     # old group name, new group name
    group_delete_requested = Signal(str)          # group name
    storage_create_requested = Signal(str)        # host_name (any member host)
    storage_edit_requested = Signal(str, str)     # (host_name, storage)
    storage_delete_requested = Signal(str, str)   # (host_name, storage)
    cluster_join_requested = Signal(str)          # cluster name
    cluster_create_requested = Signal(str)        # host_name (first member)

    def __init__(self, nodes_cfg):
        super().__init__()
        self.nodes_cfg = nodes_cfg
        self._cfg_by_name = build_cfg_index(self.nodes_cfg)
        self._tree_notes = load_tree_notes()
        self.all_nodes = []
        self._node_repo = None
        self.all_vms = []
        self._vm_repo = None
        self.all_storages = []
        # M2: реестр действий над объектами дерева — единый источник для
        # контекст-меню и палитры (invoke эмитит сигналы ниже).
        self.action_registry = ActionRegistry()
        register_tree_actions(self.action_registry, self)

        self._building = False
        self._nav_timer = QTimer()
        self._nav_timer.setSingleShot(True)
        self._nav_timer.setInterval(300)
        self._nav_timer.timeout.connect(self._flush_nav)

        self._rebuild_timer = QTimer()
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(150)
        self._rebuild_timer.timeout.connect(self._do_rebuild)

        self._loading_hosts = set()
        # M0.3: VM в optimistic-pending (host_name, vmid) — спиннер.
        self._pending_vm_keys: set[tuple[str, int]] = set()
        # B17: datastore child to re-select after datastores refill post-rebuild
        self._pending_ds_key = None
        self._spinner_angle = 0
        self._spin_timer = QTimer()
        self._spin_timer.setInterval(150)
        self._spin_timer.timeout.connect(self._tick_spinner)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        init_icons()

        # B20: tree view mode switcher (hosts / storages / pbs)
        self._tree_mode = load_ui_state("treeMode") or "hosts"
        if self._tree_mode not in ("hosts", "storages", "pbs"):
            self._tree_mode = "hosts"
        self._mode_combo = QComboBox()
        self._mode_combo.addItem(get_icon("host"), tr("Hosts view"), "hosts")
        self._mode_combo.addItem(get_icon("storage"), tr("Storages view"), "storages")
        self._mode_combo.addItem(get_icon("backup"), tr("Backup servers view"), "pbs")
        mode_idx = self._mode_combo.findData(self._tree_mode)
        self._mode_combo.setCurrentIndex(max(mode_idx, 0))
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(4, 4, 4, 0)
        mode_row.addWidget(self._mode_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setIcon(get_icon("expand"))
        self._toggle_btn.setFixedSize(30, 30)
        self._toggle_btn.setIconSize(QSize(base_size(), base_size()))
        self._toggle_btn.setToolTip(tr("Expand all"))
        self._toggle_btn.setAutoRaise(True)
        self._toggled = False
        self._toggle_btn.clicked.connect(self._toggle_expand)

        self._empty_label = QLabel(tr("No servers added.\nPress + to add"))
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(f"color: {Color.TEXT_DIM}; font-size: 13px; padding: 40px 20px;")
        layout.addWidget(self._empty_label)

        self.tree = GroupTreeWidget(self)
        self.tree.setColumnCount(2)
        # Заголовок нужен, чтобы колонки можно было двигать/растягивать
        self.tree.setHeaderLabels([tr("Name"), tr("Info")])
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setMinimumSectionSize(48)
        header.setSectionsMovable(True)
        header.setStyleSheet(
            "QHeaderView::section { padding: 3px 6px; border: none;"
            f" border-bottom: 1px solid {Color.BORDER_LIGHT}; font-size: 11px; }}")
        self.tree.setColumnWidth(0, 170)
        self._last_saved_header_state = None
        self._restore_tree_columns()
        # Сохраняем ширины/порядок колонок дерева (debounce при изменении).
        self._col_save_timer = QTimer(self)
        self._col_save_timer.setSingleShot(True)
        self._col_save_timer.setInterval(400)
        self._col_save_timer.timeout.connect(self._save_tree_columns)
        header.sectionResized.connect(lambda *_: self._col_save_timer.start())
        header.sectionMoved.connect(lambda *_: self._col_save_timer.start())
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setIndentation(20)
        self.tree.setIconSize(QSize(base_size(), base_size()))
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(True)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

        layout.addWidget(self.tree)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(4, 2, 4, 2)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self._toggle_btn)
        layout.addLayout(bottom_layout)

        self.setLayout(layout)

    def _restore_tree_columns(self):
        """Восстанавливает ширины/порядок колонок дерева из ui_state."""
        header = self.tree.header()
        raw = load_ui_state("tree_header_state")
        if raw:
            try:
                state = QByteArray.fromHex(str(raw).encode("ascii"))
            except (ValueError, TypeError):
                state = QByteArray()
            if not state.isEmpty() and header.restoreState(state):
                self._last_saved_header_state = str(raw)
                return
        # Фолбэк на старый ключ (сохранялась только ширина колонки 0).
        raw = load_ui_state("tree_col_widths")
        if not raw:
            return
        try:
            widths = json.loads(raw)
        except (ValueError, TypeError):
            return
        if isinstance(widths, list):
            for i, w in enumerate(widths[:1]):
                self.tree.setColumnWidth(i, int(w))

    def _save_tree_columns(self):
        current = bytes(self.tree.header().saveState().toHex()).decode("ascii")
        if current == self._last_saved_header_state:
            # Ранние sectionResized при раскладке не должны затирать
            # сохранённое состояние промежуточными (дефолтными) значениями.
            return
        self._last_saved_header_state = current
        save_ui_state("tree_header_state", current)

    def set_servers(self, nodes_cfg):
        self.nodes_cfg = nodes_cfg
        self._cfg_by_name = build_cfg_index(self.nodes_cfg)
        self._build_tree()

    def set_pbs_datastores(self, server_name, stores):
        """B17 stage 2: fill datastore children of a PBS server item.

        ``stores`` — list of domain PbsDatastore (or dicts with "name").
        """
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            key = item.data(0, ITEM_KEY_ROLE)
            if not (isinstance(key, tuple) and key[0] == "pbs"
                    and key[1] == server_name):
                continue
            expanded = item.isExpanded()
            cur_key = self.get_current_item_key()
            self._building = True
            try:
                item.takeChildren()
                for st in stores:
                    name = st.name if hasattr(st, "name") else st.get("name", "")
                    if not name:
                        continue
                    child = QTreeWidgetItem(item)
                    child.setText(0, name)
                    child.setIcon(0, get_icon("backup"))
                    child.setData(0, ITEM_KEY_ROLE,
                                  ("pbs_datastore", server_name, name))
                    if hasattr(st, "usage_pct"):
                        usage = st.usage_pct()
                    elif hasattr(st, "usage"):
                        usage = int(round(st.usage * 100))
                    else:
                        usage = 0
                    child.setText(1, f"{usage}%")
                if expanded and item.childCount():
                    item.setExpanded(True)
                # takeChildren()/refill may have destroyed the current item
                # and let Qt hop selection elsewhere: bring it back. Done
                # while _building=True so the restore does not re-emit
                # item_selected (the detail panel already shows this item).
                target = None
                if self._pending_ds_key is not None:
                    target = self.find_item_by_key(self._pending_ds_key)
                    if target is not None:
                        self._pending_ds_key = None
                if target is None and cur_key is not None \
                        and self.get_current_item_key() != cur_key:
                    target = self.find_item_by_key(cur_key)
                if target is not None:
                    self.tree.setCurrentItem(target)
            finally:
                self._building = False
            return

    def set_mode(self, mode):
        """B20: switch the tree view mode ('hosts'/'storages'/'pbs')."""
        if mode == self._tree_mode:
            return
        idx = self._mode_combo.findData(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)

    def _on_mode_changed(self, index):
        mode = self._mode_combo.itemData(index)
        if not mode or mode == self._tree_mode:
            return
        self._tree_mode = mode
        save_ui_state("treeMode", mode)
        self._build_tree()
        self._sync_toggle_button()
        self._update_empty_visibility()

    def reveal_key(self, key_data):
        """B20: jump to a tree item, switching the view mode if needed
        (storage objects live in the 'storages' view, PBS servers in
        the 'pbs' view)."""
        if isinstance(key_data, tuple):
            if key_data[0] == "storage" and self._tree_mode != "storages":
                self.set_mode("storages")
            elif key_data[0] in ("pbs", "pbs_datastore") and self._tree_mode != "pbs":
                self.set_mode("pbs")
        self.find_and_select(key_data)

    def _toggle_expand(self):
        self._toggled = not self._toggled
        if self._toggled:
            self.tree.expandAll()
            self._toggle_btn.setIcon(get_icon("collapse"))
            self._toggle_btn.setToolTip(tr("Collapse all"))
        else:
            self.tree.collapseAll()
            self._toggle_btn.setIcon(get_icon("expand"))
            self._toggle_btn.setToolTip(tr("Expand all"))

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        menu = self._build_context_menu(item)
        if menu is None:
            return
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ── M2: контекстные хелперы реестра ─────────────────────────────

    def _cluster_members(self, cluster_name):
        """Host-конфиги — члены кластера (для присутствия и invoke)."""
        return [c for c in self.nodes_cfg if c.get("cluster") == cluster_name]

    def _storage_api_host(self, key):
        """API-host для storage-ключа: host → сам хост, cluster → первый
        активный член. "" — разрешить не удалось."""
        scope = key[3] if len(key) > 3 else ""
        kind = key[2] if len(key) > 2 else ""
        if kind == "host":
            return scope
        if kind == "cluster":
            first = next((c for c in self.nodes_cfg
                          if c.get("cluster") == scope
                          and c.get("type") != "pbs" and not c.get("skip")), None)
            return first.get("name", "") if first else ""
        return ""

    # Приёмники invoke из реестра (палитра/меню); контекстные кейсы.

    def cluster_create_vm(self, cluster_name):
        members = self._cluster_members(cluster_name)
        if members:
            self.vm_create_requested.emit(members[0].get("node", ""),
                                          members[0].get("name", ""))

    def cluster_create_storage(self, cluster_name):
        members = self._cluster_members(cluster_name)
        if members:
            self.storage_create_requested.emit(members[0].get("name", ""))

    def group_rename_request(self, group_name):
        self._rename_group_dialog(group_name)

    def storage_edit_request(self, key):
        api_host = self._storage_api_host(key)
        if api_host:
            self.storage_edit_requested.emit(api_host, key[1])

    def storage_delete_request(self, key):
        api_host = self._storage_api_host(key)
        if api_host:
            self.storage_delete_requested.emit(api_host, key[1])

    def _add_action_specs(self, menu, sel, action_ids):
        """QAction'ы реестра в контекст-меню: подписи, иконки и правила
        доступности — из ActionSpec. Выключенные действия показываются
        (семантика меню), а не скрываются, как в палитре."""
        by_id = {s.action_id: s for s in self.action_registry.all()}
        for aid in action_ids:
            spec = by_id[aid]
            act = QAction(spec.label, self.tree)
            if spec.icon:
                act.setIcon(get_icon(spec.icon))
            if spec.enabled is not None and not spec.enabled(sel):
                act.setEnabled(False)
            if spec.invoke is not None:
                act.triggered.connect(
                    lambda checked=False, sp=spec: sp.invoke(sel))
            menu.addAction(act)

    def _build_context_menu(self, item):
        """Построить контекст-меню для элемента дерева; None — не строится.

        Выделено из _on_context_menu (M0.2 runtime-контракт): тесты
        обходят actions построенного меню, не заходя в модальный exec.
        """
        vm_key = item.data(0, VM_KEY_ROLE)
        if vm_key is not None:
            host_name, vmid, node = vm_key
            vm = self._vm_repo.get(host_name, vmid) if self._vm_repo else None
            menu = QMenu(self.tree)
            menu.setStyleSheet(
                "QMenu { font-size: 12px; padding: 2px; }"
                "QMenu::item { padding: 4px 12px; }"
                f"QMenu::item:selected {{ background: {Color.BORDER}; }}"
            )
            is_template = bool(vm and vm.template)
            is_qemu = vm is not None and vm.vm_type is VmType.QEMU
            sel = self.selection_for_item(item)
            # M2: подписи, иконки и доступность VM-действий — из реестра
            # (тот же источник, что у палитры Ctrl+K).
            if len(sel.vm_keys) > 1:
                self._add_action_specs(menu, sel, VM_BULK_ACTION_IDS)
                menu.addSeparator()
            # Одиночные действия в меню оцениваются по самому элементу,
            # без учёта мульти-выделения (как раньше).
            vm_sel = replace(sel, vm_keys=())
            self._add_action_specs(menu, vm_sel, VM_ACTION_IDS)
            self._add_action_specs(menu, vm_sel, ("vm.novnc",))
            menu.addSeparator()
            self._add_action_specs(menu, vm_sel, ("vm.migrate", "vm.clone"))
            if is_qemu:
                menu.addSeparator()
                self._add_action_specs(
                    menu, vm_sel,
                    ("vm.convert_to_vm",) if is_template
                    else ("vm.convert_to_template",))
            menu.addSeparator()
            self._add_action_specs(menu, vm_sel, ("vm.ha_add", "vm.ha_remove"))
            menu.addSeparator()
            vm_note_act = QAction(tr("Edit note…"), self.tree)
            vm_note_act.triggered.connect(
                lambda checked, it=item, ks=f"vm:{host_name}:{vmid}":
                    self._edit_note_dialog(it, ks)
            )
            menu.addAction(vm_note_act)
            self._add_action_specs(menu, vm_sel, ("vm.delete",))
            return menu

        key = item.data(0, ITEM_KEY_ROLE)
        if not key or not isinstance(key, tuple):
            return None
        item_type = key[0]
        item_name = key[1] if len(key) > 1 else ""

        menu = QMenu(self.tree)
        menu.setStyleSheet(
            "QMenu { font-size: 12px; padding: 2px; }"
            "QMenu::item { padding: 4px 12px; }"
            f"QMenu::item:selected {{ background: {Color.BORDER}; }}"
        )

        if item_type == "host":
            host_name = key[2] if len(key) > 2 else ""
            if not host_name:
                host = next((n for n in self.all_nodes if n.node == item_name), None)
                host_name = host.host_name if host else ""
            if host_name:
                sel = self.selection_for_item(item)
                # M2: подписи/иконки/доступность — из реестра; присутствие
                # пунктов (режим дерева, шаблоны, тип хоста) — контекст меню.
                host_ids = ["host.create_vm"]
                if self._tree_mode == "storages":
                    host_ids.append("host.create_storage")
                templates = [vm for vm in self.all_vms
                             if vm.template and vm.host_name == host_name]
                if templates:
                    host_ids.append("host.clone_from_template")
                self._add_action_specs(menu, sel, tuple(host_ids))
                menu.addSeparator()
                self._add_action_specs(
                    menu, sel, ("host.delete", "host.refresh_token"))
                host_cfg = next(
                    (c for c in self.nodes_cfg if c.get("name") == host_name),
                    None)
                if (host_cfg and not host_cfg.get("cluster")
                        and host_cfg.get("type") != "pbs"):
                    self._add_action_specs(menu, sel, ("host.create_cluster",))
                menu.addSeparator()
                trust_ssl_current = bool(host_cfg.get("trust_ssl", True)) if host_cfg else True
                if trust_ssl_current:
                    trust_action = QAction(tr("Trust SSL certificate") + " — " + tr("trusted"), self.tree)
                    trust_action.setIcon(get_icon("lock"))
                else:
                    trust_action = QAction(tr("Trust SSL certificate") + " — " + tr("untrusted"), self.tree)
                    trust_action.setIcon(get_icon("unlock"))
                trust_action.triggered.connect(
                    lambda checked, hn=host_name: self.host_trust_ssl_changed.emit(hn, not trust_ssl_current)
                )
                menu.addAction(trust_action)
                self._add_group_menu(menu, "host", host_name)
                note_act = QAction(tr("Edit note…"), self.tree)
                note_default = self._host_default_note(host_name)
                note_act.triggered.connect(
                    lambda checked, it=item, ks=f"host:{host_name}", df=note_default:
                        self._edit_note_dialog(it, ks, df)
                )
                menu.addAction(note_act)

        elif item_type == "cluster":
            sel = self.selection_for_item(item)
            if self._cluster_members(item_name):
                self._add_action_specs(menu, sel, ("cluster.create_vm",))
                if self._tree_mode == "storages":
                    self._add_action_specs(menu, sel, ("cluster.create_storage",))
                menu.addSeparator()
            if self._tree_mode == "hosts":
                self._add_action_specs(menu, sel, ("cluster.add_node",))
            self._add_action_specs(menu, sel, ("cluster.delete",))
            self._add_group_menu(menu, "cluster", item_name)
            note_act = QAction(tr("Edit note…"), self.tree)
            note_act.triggered.connect(
                lambda checked, it=item, ks=f"cluster:{item_name}":
                    self._edit_note_dialog(it, ks)
            )
            menu.addAction(note_act)

        elif item_type == "group":
            sel = self.selection_for_item(item)
            self._add_action_specs(menu, sel, ("group.rename", "group.delete"))
            note_act = QAction(tr("Edit note…"), self.tree)
            note_act.triggered.connect(
                lambda checked, it=item, ks=f"group:{item_name}":
                    self._edit_note_dialog(it, ks)
            )
            menu.addAction(note_act)

        elif item_type == "storage":
            sel = self.selection_for_item(item)
            scope = key[3] if len(key) > 3 else ""
            if self._storage_api_host(key):
                self._add_action_specs(menu, sel, ("storage.edit", "storage.delete"))
                menu.addSeparator()
            note_act = QAction(tr("Edit note…"), self.tree)
            note_act.triggered.connect(
                lambda checked, it=item, ks=f"storage:{item_name}:{scope}":
                    self._edit_note_dialog(it, ks)
            )
            menu.addAction(note_act)

        if not menu.actions():
            return None
        return menu

    def _tick_spinner(self):
        self._spinner_angle = (self._spinner_angle + 45) % 360
        icon = make_loading_icon(self._spinner_angle)
        def spin(item):
            key = item.data(0, ITEM_KEY_ROLE)
            if key and isinstance(key, tuple):
                if key[0] == "host" and key[1] in self._loading_hosts:
                    item.setIcon(0, icon)
                elif key[0] == "cluster" and f"cluster:{key[1]}" in self._loading_hosts:
                    item.setIcon(0, icon)
            # M0.3: optimistic power-действия — VM в pending крутится.
            vm_key = item.data(0, VM_KEY_ROLE)
            if vm_key and (vm_key[0], vm_key[1]) in self._pending_vm_keys:
                item.setIcon(0, icon)
            for i in range(item.childCount()):
                spin(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            spin(self.tree.topLevelItem(i))

    def set_pending_vm_keys(self, keys):
        """M0.3: множество (host_name, vmid) в optimistic-pending.

        Спиннер на этих элементах дерева; при выходе из pending иконка
        восстанавливается из репозитория (текущий/откатанный статус)."""
        old = self._pending_vm_keys
        self._pending_vm_keys = set(keys)
        changed = old.symmetric_difference(self._pending_vm_keys)
        if changed:
            self._refresh_vm_items(changed)
        self._sync_spinner()

    def _sync_spinner(self):
        if self._loading_hosts or self._pending_vm_keys:
            self._spin_timer.start()
        else:
            self._spin_timer.stop()

    def _refresh_vm_items(self, keys):
        def refresh(item):
            vm_key = item.data(0, VM_KEY_ROLE)
            if vm_key and (vm_key[0], vm_key[1]) in keys:
                vm = (
                    self._vm_repo.get(vm_key[0], vm_key[1])
                    if self._vm_repo else None
                )
                if vm is not None:
                    if vm.template:
                        item.setIcon(0, get_icon("template"))
                    elif (vm.host_name, vm.vmid) in self._pending_vm_keys:
                        item.setIcon(0, make_loading_icon(self._spinner_angle))
                    else:
                        item.setIcon(0, get_icon("vm", vm.status_value))
            for i in range(item.childCount()):
                refresh(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            refresh(self.tree.topLevelItem(i))

    def update_data(self, all_nodes, all_vms, all_storages=None, final=False, node_repo=None, vm_repo=None):
        self.all_nodes = all_nodes
        self.all_vms = all_vms
        self._node_repo = node_repo
        self._vm_repo = vm_repo
        self.all_storages = all_storages or []
        if final:
            self._loading_hosts.clear()
            self._rebuild_timer.stop()
            self._build_tree()
            self._sync_toggle_button()
            self._update_empty_visibility()
            self._sync_spinner()
        else:
            self._rebuild_timer.start()

    def _do_rebuild(self):
        self._build_tree()
        self._sync_toggle_button()
        self._update_empty_visibility()

    def reapply_theme(self):
        """Перестройка дерева новыми цветами (движок тем, смена темы)."""
        if getattr(self, "all_nodes", None) is None:
            return
        self.tree.setIconSize(QSize(base_size(), base_size()))
        self._toggle_btn.setIconSize(QSize(base_size(), base_size()))
        self._do_rebuild()

    def start_loading(self):
        self.tree.clear()
        self._empty_label.setVisible(False)
        self.tree.setVisible(True)
        self._toggle_btn.setVisible(True)
        self._building = True
        self._loading_hosts.clear()

        hosts_by_cluster = {}
        standalone = []
        pbs_servers = []
        for cfg in self.nodes_cfg:
            if cfg.get("skip", False):
                continue
            if cfg.get("type") == "pbs":
                # PBS servers only appear in the 'pbs' view (and in the
                # loading stubs for that view); hosts/storages views are
                # PVE-only.
                if self._tree_mode == "pbs":
                    name = cfg.get("name", "")
                    if name:
                        pbs_servers.append(name)
                continue
            name = cfg.get("name", "")
            cluster = cfg.get("cluster")
            if cluster and cluster not in (False, None, "Standalone"):
                hosts_by_cluster.setdefault(cluster, []).append(name)
            else:
                standalone.append(name)

        # B20: clusters + standalone hosts flat (no sections); PBS servers
        # (B17 stage 2) join the same flat list with their own item kind.
        if self._tree_mode == "pbs":
            # 'Backup servers' mode: PBS servers only, no PVE hosts.
            entries = [(n.lower(), "pbs", n) for n in pbs_servers]
        else:
            entries = [(cl.lower(), "cluster", cl) for cl in hosts_by_cluster]
            entries += [(h.lower(), "host", h) for h in standalone]
        entries.sort(key=lambda e: e[0])
        for _, kind, name in entries:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, name)
            item.setIcon(0, make_loading_icon(0) if kind != "pbs"
                         else get_icon("storage"))
            if kind == "cluster":
                item.setData(0, ITEM_KEY_ROLE, ("cluster", name))
                item.setExpanded(True)
                self._loading_hosts.add(f"cluster:{name}")
            elif kind == "pbs":
                item.setData(0, ITEM_KEY_ROLE, ("pbs", name))
                item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            else:
                item.setData(0, ITEM_KEY_ROLE, ("host", name))
                self._loading_hosts.add(name)

        self.tree.expandAll()
        self._building = False
        self._spin_timer.start()

    def _sync_toggle_button(self):
        if self.tree.topLevelItemCount() == 0:
            return
        expanded = all(self._subtree_expanded(self.tree.topLevelItem(i))
                       for i in range(self.tree.topLevelItemCount()))
        self._toggled = expanded
        if expanded:
            self._toggle_btn.setIcon(get_icon("collapse"))
            self._toggle_btn.setToolTip(tr("Collapse all"))
        else:
            self._toggle_btn.setIcon(get_icon("expand"))
            self._toggle_btn.setToolTip(tr("Expand all"))

    @staticmethod
    def _subtree_expanded(item):
        if not item.isExpanded() and item.childCount() > 0:
            return False
        for i in range(item.childCount()):
            if not TreePanel._subtree_expanded(item.child(i)):
                return False
        return True

    def _on_current_item_changed(self, current, previous):
        if self._building or not current:
            return
        self._nav_timer.start()

    def _flush_nav(self):
        item = self.tree.currentItem()
        if item:
            self._on_item_clicked(item, 0)

    # ── B19: per-item notes ─────────────────────────────────────────

    def _host_default_note(self, host_name):
        """Default note for a host item: the FQDN/address from its config."""
        cfg = self._cfg_by_name.get(host_name)
        return (cfg.get("host") or "") if cfg else ""

    def _refresh_note(self, item, key_str, default=""):
        """Show the note in column 1 (muted); fall back to default when unset."""
        note = self._tree_notes.get(key_str, "") or default
        if note:
            item.setText(1, note if len(note) <= 60 else note[:59] + "…")
            item.setForeground(1, QBrush(QColor(Color.TEXT_DIM)))
            item.setToolTip(1, note)
        else:
            item.setText(1, "")
            item.setToolTip(1, "")

    def _edit_note_dialog(self, item, key_str, default=""):
        current = self._tree_notes.get(key_str, "")
        text, ok = QInputDialog.getMultiLineText(self, tr("Edit note"), tr("Note"), current)
        if not ok:
            return
        note = text.strip()
        if note:
            self._tree_notes[key_str] = note
        else:
            self._tree_notes.pop(key_str, None)
        save_tree_note(key_str, note)
        self._refresh_note(item, key_str, default)

    def _add_vm_item(self, parent, vm):
        vm_item = QTreeWidgetItem(parent)
        vm_name = vm.name or f"VM {vm.vmid}"
        vm_item.setText(0, vm_name)
        if vm.template:
            vm_item.setIcon(0, get_icon("template"))
        elif (vm.host_name, vm.vmid) in self._pending_vm_keys:
            vm_item.setIcon(0, make_loading_icon(self._spinner_angle))
        else:
            vm_item.setIcon(0, get_icon("vm", vm.status_value))
        vm_item.setData(0, VM_KEY_ROLE, (vm.host_name, vm.vmid, vm.node))
        self._refresh_note(vm_item, f"vm:{vm.host_name}:{vm.vmid}")
        cpu_pct = vm.cpu_pct
        mem_pct = vm.mem_pct
        status = vm.status_value
        vm_item.setToolTip(0, tr("Status") + f": {status_text(status)}\n" + tr("CPU") + f": {cpu_pct}%\n" + tr("RAM") + f": {mem_pct}%")
        return vm_item

    def _add_group_menu(self, menu, kind, name):
        """B16: 'Move to group' submenu for host/cluster items."""
        groups = sorted({(c.get("group") or "").strip() for c in self.nodes_cfg
                         if (c.get("group") or "").strip()}, key=str.lower)
        current = ""
        if kind == "host":
            cfg = next((c for c in self.nodes_cfg if c.get("name") == name), None)
            current = (cfg.get("group") or "").strip() if cfg else ""
        else:
            current = next(((c.get("group") or "").strip() for c in self.nodes_cfg
                            if c.get("cluster") == name and (c.get("group") or "").strip()), "")
        submenu = menu.addMenu(tr("Move to group"))
        none_act = submenu.addAction(tr("Remove from group"))
        none_act.setEnabled(bool(current))
        none_act.triggered.connect(
            lambda checked=False, k=kind, n=name: self.group_move_requested.emit(k, n, ""))
        submenu.addSeparator()
        for g in groups:
            act = submenu.addAction(g)
            act.setCheckable(True)
            act.setChecked(g == current)
            act.triggered.connect(
                lambda checked=False, gg=g, k=kind, n=name:
                    self.group_move_requested.emit(k, n, gg))
        submenu.addSeparator()
        new_act = submenu.addAction(tr("New group…"))
        new_act.triggered.connect(
            lambda checked=False, k=kind, n=name: self._new_group_dialog(k, n))

    def _new_group_dialog(self, kind, name):
        text, ok = QInputDialog.getText(self, tr("New group…"), tr("Group name"))
        if not ok:
            return
        group = text.strip()
        if group:
            self.group_move_requested.emit(kind, name, group)

    def _rename_group_dialog(self, old_name):
        text, ok = QInputDialog.getText(self, tr("Rename group…"), tr("Group name"),
                                        text=old_name)
        if not ok:
            return
        new_name = text.strip()
        if new_name and new_name != old_name:
            self.group_rename_requested.emit(old_name, new_name)

    def _make_cluster_item(self, parent, cluster_name, nodes_in_cl):
        """Create a cluster item (with hosts, pools and VMs) under parent."""
        cl_item = QTreeWidgetItem(parent)
        if not nodes_in_cl:
            cl_item.setText(0, cluster_name)
            cl_item.setIcon(0, make_loading_icon(self._spinner_angle))
            cl_item.setData(0, ITEM_KEY_ROLE, ("cluster", cluster_name))
            self._refresh_note(cl_item, f"cluster:{cluster_name}")
            return cl_item
        cluster_host_names = {n.host_name for n in nodes_in_cl}
        vms_in_cl = [vm for vm in self.all_vms
                     if vm.node in {n.node for n in nodes_in_cl}
                     and vm.host_name in cluster_host_names]
        cl_item.setText(0, f"{cluster_name}  {_vm_count_str(vms_in_cl)}")
        cl_item.setIcon(0, get_icon("cluster"))
        cl_item.setData(0, ITEM_KEY_ROLE, ("cluster", cluster_name))
        self._refresh_note(cl_item, f"cluster:{cluster_name}")

        for node in sorted(nodes_in_cl, key=lambda n: (n.display_name or n.node).lower()):
            node_name = node.node
            display_name = node.display_name or node_name
            vms_on_node = [vm for vm in vms_in_cl if vm.node == node_name and vm.host_name == node.host_name]
            host_item = QTreeWidgetItem(cl_item)
            host_item.setText(0, f"{display_name}  {_vm_count_str(vms_on_node)}")
            host_item.setIcon(0, get_icon("host", node.status_value))
            host_item.setData(0, ITEM_KEY_ROLE, ("host", node_name, node.host_name))
            host_item.setToolTip(0, _node_tooltip(node))
            self._refresh_note(host_item, f"host:{node.host_name}",
                               self._host_default_note(node.host_name))

        pool_groups = defaultdict(list)
        no_pool_vms = []
        for vm in vms_in_cl:
            pool = vm.pool
            if pool and pool not in ("", "No pool"):
                pool_groups[pool].append(vm)
            else:
                no_pool_vms.append(vm)

        for pool_name in sorted(pool_groups.keys(), key=str.lower):
            vms_list = pool_groups[pool_name]
            pool_item = QTreeWidgetItem(cl_item)
            pool_item.setText(0, f"{pool_name}  {_vm_count_str(vms_list)}")
            pool_item.setIcon(0, get_icon("pool"))
            pool_item.setData(0, ITEM_KEY_ROLE, ("pool", pool_name))

            for vm in sorted(vms_list, key=lambda v: (v.name or f"VM {v.vmid}").lower()):
                self._add_vm_item(pool_item, vm)

        for vm in sorted(no_pool_vms, key=lambda v: (v.name or f"VM {v.vmid}").lower()):
            self._add_vm_item(cl_item, vm)
        return cl_item

    def _make_host_item(self, parent, node):
        """Create a standalone host item (with pools and VMs) under parent."""
        node_name = node.node
        display_name = node.display_name or node_name
        host_name = node.host_name
        vms_on_host = [vm for vm in self.all_vms
                       if vm.node == node_name
                       and vm.host_name == host_name]
        host_item = QTreeWidgetItem(parent)
        if node.status is NodeStatus.LOADING:
            host_item.setText(0, display_name)
            host_item.setIcon(0, make_loading_icon(self._spinner_angle))
            host_item.setData(0, ITEM_KEY_ROLE, ("host", node_name, host_name))
            self._refresh_note(host_item, f"host:{host_name}",
                               self._host_default_note(host_name))
            return host_item
        host_item.setText(0, f"{display_name}  {_vm_count_str(vms_on_host)}")
        host_item.setIcon(0, get_icon("host", node.status_value))
        host_item.setData(0, ITEM_KEY_ROLE, ("host", node_name, host_name))
        host_item.setToolTip(0, _node_tooltip(node))
        self._refresh_note(host_item, f"host:{host_name}",
                           self._host_default_note(host_name))

        pool_groups = defaultdict(list)
        no_pool_vms = []
        for vm in vms_on_host:
            pool = vm.pool
            if pool and pool not in ("", "No pool"):
                pool_groups[pool].append(vm)
            else:
                no_pool_vms.append(vm)

        for pool_name in sorted(pool_groups.keys(), key=str.lower):
            pool_item = QTreeWidgetItem(host_item)
            pool_item.setText(0, f"{pool_name}  {_vm_count_str(pool_groups[pool_name])}")
            pool_item.setIcon(0, get_icon("pool"))
            pool_item.setData(0, ITEM_KEY_ROLE, ("pool", pool_name))

            for vm in sorted(pool_groups[pool_name], key=lambda v: (v.name or f"VM {v.vmid}").lower()):
                self._add_vm_item(pool_item, vm)

        for vm in sorted(no_pool_vms, key=lambda v: (v.name or f"VM {v.vmid}").lower()):
            self._add_vm_item(host_item, vm)
        return host_item

    def _build_tree(self):
        self._building = True
        saved_key = self.get_current_item_key()
        scroll_val = self.tree.verticalScrollBar().value()
        self.tree.clear()

        grouping = self._compute_grouping()
        group_names = sorted(set(grouping["group_clusters"]) | set(grouping["group_standalone"]),
                             key=str.lower)
        if self._tree_mode == "storages":
            self._build_storages_view(grouping, group_names)
        elif self._tree_mode == "pbs":
            self._build_pbs_view()
        else:
            self._build_hosts_view(grouping, group_names)

        raw = load_ui_state("expandedTreePaths")
        if raw:
            self._restore_expanded_state()
        else:
            self.tree.expandAll()
        if saved_key is not None:
            item = self.find_item_by_key(saved_key)
            if item is None and isinstance(saved_key, tuple) \
                    and saved_key[0] == "pbs_datastore":
                # Datastore children are not present right after a rebuild
                # (they arrive later via set_pbs_datastores): fall back to the
                # parent PBS server and re-select the child on refill.
                item = self.find_item_by_key(("pbs", saved_key[1]))
                self._pending_ds_key = saved_key
            if item is not None:
                self.tree.setCurrentItem(item)
        self.tree.verticalScrollBar().setValue(scroll_val)
        self._building = False

    def _compute_grouping(self):
        """B16/B20: split hosts into cluster/standalone/group buckets."""
        host_group = {}
        cluster_group = {}
        for cfg in self.nodes_cfg:
            g = (cfg.get("group") or "").strip()
            if not g or not cfg.get("name"):
                continue
            host_group[cfg["name"]] = g
            cl = cfg.get("cluster")
            if cl and cl not in (False, None, "Standalone"):
                cluster_group.setdefault(cl, g)

        cluster_nodes = defaultdict(list)
        standalone_nodes = []
        group_clusters = defaultdict(dict)     # group -> {cluster_name: [nodes]}
        group_standalone = defaultdict(list)   # group -> [nodes]

        for node in self.all_nodes:
            host_name = node.host_name
            cfg = self._cfg_by_name.get(host_name)
            cluster_name = cfg.get("cluster") if cfg else None
            if cluster_name and cluster_name not in (False, None, "Standalone"):
                g = cluster_group.get(cluster_name)
                if g:
                    group_clusters[g].setdefault(cluster_name, []).append(node)
                else:
                    cluster_nodes[cluster_name].append(node)
            else:
                g = host_group.get(host_name)
                if g:
                    group_standalone[g].append(node)
                else:
                    standalone_nodes.append(node)

        for cfg in self.nodes_cfg:
            if cfg.get("skip"):
                continue
            cluster_name = cfg.get("cluster")
            if cluster_name and cluster_name not in (False, None, "Standalone"):
                g = cluster_group.get(cluster_name)
                if g:
                    if cluster_name not in group_clusters[g]:
                        group_clusters[g][cluster_name] = []
                        if f"cluster:{cluster_name}" not in self._loading_hosts:
                            self._loading_hosts.add(f"cluster:{cluster_name}")
                elif cluster_name not in cluster_nodes:
                    cluster_nodes[cluster_name] = []
                    if f"cluster:{cluster_name}" not in self._loading_hosts:
                        self._loading_hosts.add(f"cluster:{cluster_name}")

        standalone_names = {n.host_name for n in standalone_nodes}
        grouped_standalone_names = {n.host_name for nodes in group_standalone.values() for n in nodes}
        for cfg in self.nodes_cfg:
            if cfg.get("skip") or cfg.get("type") == "pbs":
                continue
            host_name = cfg.get("name", "")
            cluster = cfg.get("cluster")
            if cluster and cluster not in (False, None, "Standalone"):
                continue
            g = host_group.get(host_name)
            if g:
                if host_name not in grouped_standalone_names:
                    group_standalone[g].append(Node.loading_stub(host_name))
                    self._loading_hosts.add(host_name)
                    grouped_standalone_names.add(host_name)
                continue
            if host_name not in standalone_names:
                standalone_nodes.append(Node.loading_stub(host_name))
                self._loading_hosts.add(host_name)

        for node in self.all_nodes:
            hn = node.host_name
            self._loading_hosts.discard(hn)
            if node.is_cluster:
                cfg = self._cfg_by_name.get(hn)
                if cfg:
                    cl_name = cfg.get("cluster", "")
                    if cl_name:
                        self._loading_hosts.discard(f"cluster:{cl_name}")

        return {
            "cluster_nodes": cluster_nodes,
            "standalone_nodes": standalone_nodes,
            "group_clusters": group_clusters,
            "group_standalone": group_standalone,
        }

    @staticmethod
    def _flat_entries(cluster_nodes, standalone_nodes):
        """B20: clusters + standalone hosts merged flat, sorted by name."""
        entries = [(name.lower(), "cluster", name) for name in cluster_nodes]
        entries += [((n.display_name or n.node).lower(), "host", n) for n in standalone_nodes]
        entries.sort(key=lambda e: e[0])
        return entries

    def _build_hosts_view(self, grouping, group_names):
        """B20 'Hosts' mode: groups, then clusters + standalone hosts flat."""
        cluster_nodes = grouping["cluster_nodes"]
        standalone_nodes = grouping["standalone_nodes"]
        group_clusters = grouping["group_clusters"]
        group_standalone = grouping["group_standalone"]

        for g in group_names:
            g_item = QTreeWidgetItem(self.tree)
            g_item.setData(0, ITEM_KEY_ROLE, ("group", g))
            g_nodes = group_standalone.get(g, [])
            g_cl_nodes = [n for nodes in group_clusters.get(g, {}).values() for n in nodes]
            g_host_names = {n.host_name for n in g_nodes + g_cl_nodes}
            g_vms = [vm for vm in self.all_vms if vm.host_name in g_host_names]
            g_item.setText(0, f"{g}  {_vm_count_str(g_vms)}")
            g_item.setIcon(0, get_icon("folder"))
            self._refresh_note(g_item, f"group:{g}")
            for cl_name in sorted(group_clusters.get(g, {}), key=str.lower):
                self._make_cluster_item(g_item, cl_name, group_clusters[g][cl_name])
            for node in sorted(g_nodes, key=lambda n: (n.display_name or n.node).lower()):
                self._make_host_item(g_item, node)

        for _, kind, obj in self._flat_entries(cluster_nodes, standalone_nodes):
            if kind == "cluster":
                self._make_cluster_item(self.tree, obj, cluster_nodes[obj])
            else:
                self._make_host_item(self.tree, obj)

    def _build_pbs_view(self):
        """B17 stage 2: 'Backup servers' mode — PBS servers flat with
        their datastores (children are filled by set_pbs_datastores)."""
        for cfg in self.nodes_cfg:
            if cfg.get("skip") or cfg.get("type") != "pbs":
                continue
            name = cfg.get("name", "")
            if not name:
                continue
            item = QTreeWidgetItem(self.tree)
            item.setText(0, name)
            item.setIcon(0, get_icon("storage"))
            item.setData(0, ITEM_KEY_ROLE, ("pbs", name))
            item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            self._refresh_note(item, f"pbs:{name}", default=cfg.get("host", ""))

    def _build_storages_view(self, grouping, group_names):
        """B20 'Storages' mode: shared storages under the cluster, local
        storages under each host; clusters + standalone hosts flat."""
        cluster_nodes = grouping["cluster_nodes"]
        standalone_nodes = grouping["standalone_nodes"]
        group_clusters = grouping["group_clusters"]
        group_standalone = grouping["group_standalone"]

        for g in group_names:
            g_item = QTreeWidgetItem(self.tree)
            g_item.setData(0, ITEM_KEY_ROLE, ("group", g))
            g_nodes = group_standalone.get(g, [])
            g_cl_nodes = [n for nodes in group_clusters.get(g, {}).values() for n in nodes]
            g_host_names = {n.host_name for n in g_nodes + g_cl_nodes}
            g_storages = [st for st in self.all_storages if st.host_name in g_host_names]
            g_item.setText(0, f"{g}  [{len({st.storage for st in g_storages})}]")
            g_item.setIcon(0, get_icon("folder"))
            self._refresh_note(g_item, f"group:{g}")
            for cl_name in sorted(group_clusters.get(g, {}), key=str.lower):
                self._make_cluster_storage_item(g_item, cl_name, group_clusters[g][cl_name])
            for node in sorted(g_nodes, key=lambda n: (n.display_name or n.node).lower()):
                self._make_host_storage_item(g_item, node)

        for _, kind, obj in self._flat_entries(cluster_nodes, standalone_nodes):
            if kind == "cluster":
                self._make_cluster_storage_item(self.tree, obj, cluster_nodes[obj])
            else:
                self._make_host_storage_item(self.tree, obj)

    def _make_cluster_storage_item(self, parent, cluster_name, nodes_in_cl):
        """B20 storages mode: cluster with shared storages and member hosts."""
        cl_item = QTreeWidgetItem(parent)
        cl_item.setText(0, cluster_name)
        cl_item.setIcon(0, get_icon("cluster"))
        cl_item.setData(0, ITEM_KEY_ROLE, ("cluster", cluster_name))
        self._refresh_note(cl_item, f"cluster:{cluster_name}")

        seen_names = set()
        node_display = {n.node: (n.display_name or n.node) for n in nodes_in_cl}
        for st in self.all_storages:
            if st.cluster != cluster_name or not st.shared:
                continue
            sname = st.storage
            if sname in seen_names:
                continue
            seen_names.add(sname)
            si = QTreeWidgetItem(cl_item)
            si.setText(0, f"{sname} (@{cluster_name})")
            si.setIcon(0, get_icon("storage"))
            si.setData(0, ITEM_KEY_ROLE, ("storage", sname, "cluster", cluster_name))
            self._refresh_note(si, f"storage:{sname}:{cluster_name}")
            # Per-node rows under the shared storage: the same storage as
            # seen by each member node (usage may differ per node).
            for ps in sorted((s for s in self.all_storages
                              if s.cluster == cluster_name and s.shared
                              and s.storage == sname),
                             key=lambda s: (node_display.get(s.node, s.node) or s.node).lower()):
                child = QTreeWidgetItem(si)
                child.setText(0, f"{sname} ({node_display.get(ps.node, ps.node)})")
                child.setIcon(0, get_icon("storage"))
                child.setData(0, ITEM_KEY_ROLE,
                              ("storage", sname, "host", ps.host_name, ps.node))
                child.setText(1, f"{ps.usage_pct}%")

        for node in sorted(nodes_in_cl, key=lambda n: (n.display_name or n.node).lower()):
            self._make_host_storage_item(cl_item, node)
        return cl_item

    def _make_host_storage_item(self, parent, node):
        """B20 storages mode: host with its local storages."""
        host_name = node.host_name
        cluster_scope = node.cluster or ""
        host_item = QTreeWidgetItem(parent)
        host_item.setText(0, node.display_name or node.node)
        host_item.setIcon(0, get_icon("host", node.status_value))
        host_item.setData(0, ITEM_KEY_ROLE, ("host", node.node, host_name))
        host_item.setToolTip(0, _node_tooltip(node))
        self._refresh_note(host_item, f"host:{host_name}",
                           self._host_default_note(host_name))

        for st in sorted((s for s in self.all_storages
                          if s.host_name == host_name and s.cluster == cluster_scope
                          and (not cluster_scope or not s.shared)),
                         key=lambda s: s.storage.lower()):
            si = QTreeWidgetItem(host_item)
            si.setText(0, st.storage)
            si.setIcon(0, get_icon("storage"))
            si.setData(0, ITEM_KEY_ROLE, ("storage", st.storage, "host", host_name))
            self._refresh_note(si, f"storage:{st.storage}:{host_name}")
        return host_item

    def update_node_statuses(self, all_nodes, all_vms, node_repo=None, vm_repo=None):
        self.all_nodes = all_nodes
        self._node_repo = node_repo or self._node_repo
        self._vm_repo = vm_repo or self._vm_repo
        for node in list(all_nodes):
            hn = node.host_name
            self._loading_hosts.discard(hn)
            if node.is_cluster:
                cfg = self._cfg_by_name.get(hn)
                if cfg:
                    cluster_name = cfg.get("cluster", "")
                    if cluster_name:
                        self._loading_hosts.discard(f"cluster:{cluster_name}")
        if not self._loading_hosts:
            self._spin_timer.stop()

        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            item = it.value()
            vm_key = item.data(0, VM_KEY_ROLE)
            if vm_key is not None:
                host_name, vmid, _node = vm_key
                vm = self._vm_repo.get(host_name, vmid) if self._vm_repo else None
                if vm:
                    if vm.template:
                        item.setIcon(0, get_icon("template"))
                    else:
                        item.setIcon(0, get_icon("vm", vm.status_value))
            else:
                key = item.data(0, ITEM_KEY_ROLE)
                if key and isinstance(key, tuple) and key[0] == "host":
                    hn = key[2] if len(key) > 2 else None
                    node_name = key[1]
                    if hn:
                        host = self._node_repo.get(hn, node_name) if self._node_repo else None
                    else:
                        host = next((n for n in self.all_nodes if n.node == node_name), None)
                    if host:
                        item.setIcon(0, get_icon("host", host.status_value))
            it += 1

    @staticmethod
    def _strip_count(text):
        """Remove VM count suffix like '[3/5]' for stable paths."""
        return re.sub(r'\s+\[\d+/\d+\]$', '', text)

    def _save_expanded_state(self):
        paths = []
        def collect_paths(item, path=""):
            label = self._strip_count(item.text(0))
            current = path + "|" + label if path else label
            if item.isExpanded():
                paths.append(current)
            for i in range(item.childCount()):
                collect_paths(item.child(i), current)
        for i in range(self.tree.topLevelItemCount()):
            collect_paths(self.tree.topLevelItem(i))
        save_ui_state("expandedTreePaths", json.dumps(paths))

    def _restore_expanded_state(self):
        raw = load_ui_state("expandedTreePaths")
        if not raw:
            return
        try:
            saved_paths = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if not saved_paths:
            return
        def match_and_expand(item, path=""):
            label = self._strip_count(item.text(0))
            current = path + "|" + label if path else label
            if current in saved_paths:
                item.setExpanded(True)
            for i in range(item.childCount()):
                match_and_expand(item.child(i), current)
        for i in range(self.tree.topLevelItemCount()):
            match_and_expand(self.tree.topLevelItem(i))

    def save_state(self):
        self._save_expanded_state()

    def _update_empty_visibility(self):
        """Show/hide the hint when the tree is empty."""
        has_items = self.tree.topLevelItemCount() > 0
        self._empty_label.setVisible(not has_items)
        self.tree.setVisible(has_items)
        self._toggle_btn.setVisible(has_items)

    def select_first_item(self):
        if self.tree.topLevelItemCount() > 0:
            item = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(item)
            self._on_item_clicked(item, 0)

    def find_item_by_key(self, key_data):
        if not isinstance(key_data, tuple) or len(key_data) < 2:
            return None
        is_vm_key = isinstance(key_data[1], int)
        def search(item):
            if is_vm_key:
                if item.data(0, VM_KEY_ROLE) == key_data:
                    return item
            else:
                if item.data(0, ITEM_KEY_ROLE) == key_data:
                    return item
            for i in range(item.childCount()):
                found = search(item.child(i))
                if found:
                    return found
            return None
        for i in range(self.tree.topLevelItemCount()):
            found = search(self.tree.topLevelItem(i))
            if found:
                return found
        return None

    def get_current_item_key(self):
        item = self.tree.currentItem()
        if not item:
            return None
        vm_key = item.data(0, VM_KEY_ROLE)
        if vm_key is not None:
            return vm_key
        return item.data(0, ITEM_KEY_ROLE)

    def selected_vm_keys(self):
        """Return VM keys (host_name, vmid, node) for all selected VM items."""
        keys = []
        for item in self.tree.selectedItems():
            vm_key = item.data(0, VM_KEY_ROLE)
            if vm_key is not None:
                keys.append(vm_key)
        return keys

    def selection_for_item(self, item):
        """Selection-дескриптор произвольного элемента дерева
        (палитра действий и контекст-меню, M2)."""
        if item is None:
            return Selection()
        text = item.text(0)
        vm_key = item.data(0, VM_KEY_ROLE)
        if vm_key is not None:
            host_name, vmid, node = vm_key
            vm = self._vm_repo.get(host_name, vmid) if self._vm_repo else None
            if vm is not None and vm.template:
                kind = SCOPE_TEMPLATE
            elif vm is not None and vm.vm_type is VmType.QEMU:
                kind = SCOPE_VM
            else:
                kind = SCOPE_CT
            return Selection(kind=kind, label=text, host_name=host_name,
                             node=node, vmid=vmid, vm=vm, key=vm_key,
                             vm_keys=tuple(self.selected_vm_keys()))
        key = item.data(0, ITEM_KEY_ROLE)
        if key is None:
            return Selection()
        kind = key[0]
        node = ""
        host_name = ""
        if kind == "host" and len(key) >= 3:
            node, host_name = key[1], key[2]
        elif kind == "storage" and len(key) >= 4 and key[2] == "host":
            host_name = key[3]
        if kind == "host" and not host_name:
            # Скелетон первичной загрузки («host», имя, без node/host_name):
            # паритет с контекст-меню — действий нет (аудит 2026-10-06, E1).
            return Selection()
        return Selection(kind=kind, label=text, host_name=host_name,
                         node=node, key=tuple(key))

    def current_selection(self):
        """Selection-дескриптор текущего элемента (палитра действий)."""
        return self.selection_for_item(self.tree.currentItem())

    def find_and_select(self, key_data):
        """Find a tree item by key tuple, expand parents, scroll to it, and select it."""
        item = self.find_item_by_key(key_data)
        if not item:
            return
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.scrollToItem(item)
        self.tree.setCurrentItem(item)
        self._on_item_clicked(item, 0)

    def request_delete_current(self):
        """Trigger delete on currently selected item (for Del shortcut)."""
        item = self.tree.currentItem()
        if not item:
            return
        vm_key = item.data(0, VM_KEY_ROLE)
        if vm_key is not None:
            host_name, vmid, node = vm_key
            self.vm_delete_requested.emit(host_name, node, vmid)
            return
        key = item.data(0, ITEM_KEY_ROLE)
        if not key or not isinstance(key, tuple):
            return
        item_type = key[0]
        item_name = key[1] if len(key) > 1 else ""
        if item_type == "host":
            host_name = key[2] if len(key) > 2 else ""
            if not host_name:
                host = next((n for n in self.all_nodes if n.node == item_name), None)
                host_name = host.host_name if host else ""
            if host_name:
                self.host_remove_requested.emit("host", host_name)
        elif item_type == "cluster":
            self.host_remove_requested.emit(item_type, item_name)

    def _on_item_clicked(self, item, column):
        self._nav_timer.stop()

        vm_key = item.data(0, VM_KEY_ROLE)
        if vm_key is not None:
            host_name, vmid, _node = vm_key
            vm = self._vm_repo.get(host_name, vmid) if self._vm_repo else None
            if vm is not None:
                self.item_selected.emit("vm", vm.name or f"VM {vmid}", vm)
                return
            self.item_selected.emit("unknown", str(vmid), {})
            return

        key = item.data(0, ITEM_KEY_ROLE)
        if key is None or not isinstance(key, tuple):
            self.item_selected.emit("unknown", "", {})
            return

        item_type = key[0]
        item_name = key[1] if len(key) > 1 else ""

        if item_type == "cluster":
            self.item_selected.emit("cluster", item_name, {})
            return

        if item_type == "group":
            self.item_selected.emit("group", item_name, {})
            return

        if item_type == "pbs":
            self.item_selected.emit("pbs", item_name, {})
            return

        if item_type == "pbs_datastore":
            store = key[2] if len(key) > 2 else ""
            self.item_selected.emit("pbs_datastore", item_name,
                                    {"server": item_name, "store": store})
            return

        if item_type == "host":
            host_name_key = key[2] if len(key) > 2 else None
            if host_name_key:
                host_data = self._node_repo.get(host_name_key, item_name) if self._node_repo else None
                if host_data is None:
                    host_data = next((n for n in self.all_nodes
                                      if n.host_name == host_name_key), None)
            else:
                host_data = next((n for n in self.all_nodes if n.node == item_name), None)
            self.item_selected.emit("host", item_name, host_data or {})
            return

        if item_type == "pool":
            self.item_selected.emit("pool", item_name, {})
            return

        if item_type == "storage":
            data = {"storage_name": item_name}
            if len(key) >= 4:
                kind = key[2]
                val = key[3]
                if kind == "cluster":
                    data["cluster"] = val
                elif kind == "host":
                    data["host_name"] = val
            if len(key) >= 5:
                # Per-node row under a shared "@cluster" storage: the 5th
                # element carries the PVE node name.
                data["node"] = key[4]
            self.item_selected.emit("storage", item_name, data)
            return

        self.item_selected.emit("unknown", item_name, {})
