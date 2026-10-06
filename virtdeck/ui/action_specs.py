"""M2.3: спецификации действий приложения.

Действия дерева принадлежат TreePanel (invoke эмитит его сигналы или
вызывает его методы — те же пути, что у контекст-меню; меню и палитра
берут подписи, иконки и правила доступности из одних ActionSpec).
Глобальные действия — mainwindow: build_registry(window) собирает их
вместе с реестром TreePanel.

Подписи — существующие tr()-ключи: смена языка = рестарт, поэтому
запекаются при создании реестра. Иконки — имена Breeze-набора; отрисовка
в слотах base_size(). Динамическое присутствие (режим дерева, наличие
шаблонов, api-host хранилища) и действия с динамическими подписями
(Trust SSL, Edit note…) остаются в меню — там их контекст.
"""

from .action_registry import (
    SCOPE_CLUSTER,
    SCOPE_CT,
    SCOPE_GROUP,
    SCOPE_HOST,
    SCOPE_PBS,
    SCOPE_POOL,
    SCOPE_STORAGE,
    SCOPE_TEMPLATE,
    SCOPE_VM,
    ActionRegistry,
    ActionSpec,
)
from .i18n import tr

# Объектные scope'ы дерева — для действий над произвольным элементом.
_ALL_OBJECT_SCOPES = frozenset({
    SCOPE_VM, SCOPE_CT, SCOPE_TEMPLATE, SCOPE_HOST, SCOPE_CLUSTER,
    SCOPE_STORAGE, SCOPE_PBS, SCOPE_POOL, SCOPE_GROUP,
})

_VM_SCOPES = frozenset({SCOPE_VM, SCOPE_CT})

# Порядок VM-блока контекст-меню (и палитры).
VM_ACTION_IDS = (
    "vm.start", "vm.shutdown", "vm.reboot", "vm.stop",
    "vm.reset", "vm.resume", "vm.console",
)
VM_BULK_ACTION_IDS = (
    "vm.bulk_start", "vm.bulk_shutdown", "vm.bulk_reboot", "vm.bulk_stop",
)


def _vm_ok(sel, *, need_status=None, forbid_running=False):
    """Доступность одиночного действия над ВМ: не шаблон, статус подходит,
    без мульти-выделения (тогда доступны массовые «* all»)."""
    if len(sel.vm_keys) > 1:
        return False
    vm = sel.vm
    if vm is None or vm.template:
        return False
    status = vm.status_value
    if need_status is not None and status != need_status:
        return False
    if forbid_running and status == "running":
        return False
    return True


def register_tree_actions(registry, tree):
    """Действия над объектами дерева в реестр: invoke эмитит сигналы
    TreePanel (или вызывает его методы-хелперы для контекстных кейсов)."""
    def vm_action(action):
        return lambda sel: tree.vm_action_requested.emit(
            sel.host_name, sel.node, sel.vmid, action)

    def bulk_action(action):
        return lambda sel: tree.bulk_vm_action_requested.emit(
            list(sel.vm_keys), action)

    # ── Действия над ВМ/CT ──────────────────────────────────────────
    registry.register(ActionSpec(
        action_id="vm.start", label=tr("Start"), icon="start",
        scopes=_VM_SCOPES, keywords=("boot", "power on"),
        enabled=lambda sel: _vm_ok(sel, forbid_running=True),
        invoke=vm_action("start"),
    ))
    registry.register(ActionSpec(
        action_id="vm.shutdown", label=tr("Shutdown"), icon="shutdown",
        scopes=_VM_SCOPES,
        enabled=lambda sel: _vm_ok(sel, need_status="running"),
        invoke=vm_action("shutdown"),
    ))
    registry.register(ActionSpec(
        action_id="vm.reboot", label=tr("Reboot"), icon="reboot",
        scopes=_VM_SCOPES,
        enabled=lambda sel: _vm_ok(sel, need_status="running"),
        invoke=vm_action("reboot"),
    ))
    registry.register(ActionSpec(
        action_id="vm.stop", label=tr("Stop"), icon="stop",
        scopes=_VM_SCOPES, dangerous=True,
        enabled=lambda sel: _vm_ok(sel, need_status="running"),
        invoke=vm_action("stop"),
    ))
    registry.register(ActionSpec(
        action_id="vm.reset", label=tr("Reset"), icon="reset",
        scopes=_VM_SCOPES, dangerous=True,
        enabled=lambda sel: _vm_ok(sel, need_status="running"),
        invoke=vm_action("reset"),
    ))
    registry.register(ActionSpec(
        action_id="vm.resume", label=tr("Resume"), icon="resume",
        scopes=_VM_SCOPES,
        enabled=lambda sel: _vm_ok(sel, need_status="paused"),
        invoke=vm_action("resume"),
    ))
    registry.register(ActionSpec(
        action_id="vm.console", label=tr("Console"), icon="console",
        scopes=_VM_SCOPES,
        enabled=lambda sel: _vm_ok(sel, need_status="running"),
        invoke=lambda sel: tree.console_requested.emit(
            sel.host_name, sel.node, sel.vmid),
    ))
    registry.register(ActionSpec(
        action_id="vm.novnc", label=tr("noVNC console"), icon="console",
        scopes=_VM_SCOPES,
        enabled=lambda sel: _vm_ok(sel, need_status="running"),
        invoke=lambda sel: tree.novnc_requested.emit(
            sel.host_name, sel.node, sel.vmid),
    ))
    registry.register(ActionSpec(
        action_id="vm.migrate", label=tr("Migrate"), icon="migrate",
        scopes=_VM_SCOPES,
        enabled=lambda sel: sel.vm is not None and not sel.vm.template,
        invoke=lambda sel: tree.vm_migrate_requested.emit(
            sel.host_name, sel.node, sel.vmid),
    ))
    registry.register(ActionSpec(
        action_id="vm.clone", label=tr("Clone"), icon="clone",
        scopes=_VM_SCOPES,
        invoke=lambda sel: tree.vm_clone_requested.emit(
            sel.host_name, sel.node, sel.vmid),
    ))
    registry.register(ActionSpec(
        action_id="vm.convert_to_vm", label=tr("Convert to VM"), icon="vm",
        scopes=_VM_SCOPES,
        enabled=lambda sel: sel.vm is not None and sel.vm.template,
        invoke=lambda sel: tree.vm_convert_requested.emit(
            sel.host_name, sel.node, sel.vmid, "to_vm"),
    ))
    registry.register(ActionSpec(
        action_id="vm.convert_to_template", label=tr("Convert to Template"),
        icon="template", scopes=_VM_SCOPES,
        enabled=lambda sel: (sel.vm is not None and not sel.vm.template
                             and sel.vm.status_value != "running"),
        invoke=lambda sel: tree.vm_convert_requested.emit(
            sel.host_name, sel.node, sel.vmid, "to_template"),
    ))
    registry.register(ActionSpec(
        action_id="vm.ha_add", label=tr("Add to HA"), icon="ha",
        scopes=_VM_SCOPES,
        enabled=lambda sel: sel.vm is not None and not sel.vm.template,
        invoke=lambda sel: tree.vm_ha_add_requested.emit(
            sel.host_name, sel.node, sel.vmid),
    ))
    registry.register(ActionSpec(
        action_id="vm.ha_remove", label=tr("Remove from HA"), icon="ha",
        scopes=_VM_SCOPES,
        invoke=lambda sel: tree.vm_ha_remove_requested.emit(
            sel.host_name, sel.node, sel.vmid),
    ))
    registry.register(ActionSpec(
        action_id="vm.delete", label=tr("Delete VM"), icon="remove",
        scopes=_VM_SCOPES, dangerous=True,
        keywords=("remove", "destroy"),
        invoke=lambda sel: tree.vm_delete_requested.emit(
            sel.host_name, sel.node, sel.vmid),
    ))

    # ── Массовые (мульти-выделение) ─────────────────────────────────
    registry.register(ActionSpec(
        action_id="vm.bulk_start", label=tr("Start all"), icon="start",
        scopes=_VM_SCOPES,
        enabled=lambda sel: len(sel.vm_keys) > 1,
        invoke=bulk_action("start"),
    ))
    registry.register(ActionSpec(
        action_id="vm.bulk_shutdown", label=tr("Shutdown all"),
        icon="shutdown", scopes=_VM_SCOPES,
        enabled=lambda sel: len(sel.vm_keys) > 1,
        invoke=bulk_action("shutdown"),
    ))
    registry.register(ActionSpec(
        action_id="vm.bulk_reboot", label=tr("Reboot all"), icon="reboot",
        scopes=_VM_SCOPES,
        enabled=lambda sel: len(sel.vm_keys) > 1,
        invoke=bulk_action("reboot"),
    ))
    registry.register(ActionSpec(
        action_id="vm.bulk_stop", label=tr("Stop all"), icon="stop",
        scopes=_VM_SCOPES, dangerous=True,
        enabled=lambda sel: len(sel.vm_keys) > 1,
        invoke=bulk_action("stop"),
    ))

    # ── Хост ────────────────────────────────────────────────────────
    registry.register(ActionSpec(
        action_id="host.create_vm", label=tr("Create VM"), icon="vm",
        scopes=frozenset({SCOPE_HOST}),
        invoke=lambda sel: tree.vm_create_requested.emit(
            sel.node, sel.host_name),
    ))
    registry.register(ActionSpec(
        action_id="host.create_storage", label=tr("Create storage…"),
        scopes=frozenset({SCOPE_HOST}),
        invoke=lambda sel: tree.storage_create_requested.emit(sel.host_name),
    ))
    registry.register(ActionSpec(
        action_id="host.clone_from_template", label=tr("Clone from Template"),
        icon="template", scopes=frozenset({SCOPE_HOST}),
        invoke=lambda sel: tree.vm_clone_from_template_requested.emit(
            sel.host_name, sel.node),
    ))
    registry.register(ActionSpec(
        action_id="host.delete", label=tr("Delete host"), icon="remove",
        scopes=frozenset({SCOPE_HOST}), dangerous=True,
        invoke=lambda sel: tree.host_remove_requested.emit(
            "host", sel.host_name),
    ))
    registry.register(ActionSpec(
        action_id="host.refresh_token", label=tr("Refresh token"),
        icon="refresh", scopes=frozenset({SCOPE_HOST}),
        invoke=lambda sel: tree.host_token_refresh_requested.emit(
            sel.host_name),
    ))
    registry.register(ActionSpec(
        action_id="host.create_cluster", label=tr("Create cluster…"),
        scopes=frozenset({SCOPE_HOST}),
        invoke=lambda sel: tree.cluster_create_requested.emit(sel.host_name),
    ))

    # ── Кластер ─────────────────────────────────────────────────────
    registry.register(ActionSpec(
        action_id="cluster.create_vm", label=tr("Create VM"), icon="vm",
        scopes=frozenset({SCOPE_CLUSTER}),
        invoke=lambda sel: tree.cluster_create_vm(sel.key[1]),
    ))
    registry.register(ActionSpec(
        action_id="cluster.create_storage", label=tr("Create storage…"),
        scopes=frozenset({SCOPE_CLUSTER}),
        invoke=lambda sel: tree.cluster_create_storage(sel.key[1]),
    ))
    registry.register(ActionSpec(
        action_id="cluster.add_node", label=tr("Add node to cluster…"),
        scopes=frozenset({SCOPE_CLUSTER}),
        invoke=lambda sel: tree.cluster_join_requested.emit(sel.key[1]),
    ))
    registry.register(ActionSpec(
        action_id="cluster.delete", label=tr("Delete cluster"), icon="remove",
        scopes=frozenset({SCOPE_CLUSTER}), dangerous=True,
        invoke=lambda sel: tree.host_remove_requested.emit(
            "cluster", sel.key[1]),
    ))

    # ── Группа ──────────────────────────────────────────────────────
    registry.register(ActionSpec(
        action_id="group.rename", label=tr("Rename group…"),
        scopes=frozenset({SCOPE_GROUP}),
        invoke=lambda sel: tree.group_rename_request(sel.key[1]),
    ))
    registry.register(ActionSpec(
        action_id="group.delete", label=tr("Delete group"), icon="remove",
        scopes=frozenset({SCOPE_GROUP}), dangerous=True,
        invoke=lambda sel: tree.group_delete_requested.emit(sel.key[1]),
    ))

    # ── Хранилище ───────────────────────────────────────────────────
    registry.register(ActionSpec(
        action_id="storage.edit", label=tr("Edit storage…"),
        scopes=frozenset({SCOPE_STORAGE}),
        invoke=lambda sel: tree.storage_edit_request(sel.key),
    ))
    registry.register(ActionSpec(
        action_id="storage.delete", label=tr("Delete storage"), icon="remove",
        scopes=frozenset({SCOPE_STORAGE}), dangerous=True,
        invoke=lambda sel: tree.storage_delete_request(sel.key),
    ))


def build_registry(window) -> ActionRegistry:
    """Реестр палитры: глобальные действия окна + спеки TreePanel."""
    reg = ActionRegistry()

    # ── Глобальные (доступны при любом выделении) ───────────────────
    reg.register(ActionSpec(
        action_id="global.add_server", label=tr("Add server"), icon="add",
        shortcut="Ctrl+N",
        keywords=("create", "host", "server", "connect"),
        invoke=lambda sel: window._on_add_server(),
    ))
    reg.register(ActionSpec(
        action_id="global.refresh", label=tr("Refresh data"), icon="refresh",
        shortcut="Ctrl+R",
        keywords=("reload", "update", "f5"),
        invoke=lambda sel: window.refresh_data(),
    ))
    reg.register(ActionSpec(
        action_id="global.search", label=tr("Global search"), icon="search",
        shortcut="Ctrl+F",
        keywords=("find", "jump", "goto", "vmid", "ip", "owner"),
        invoke=lambda sel: window._open_global_search(),
    ))
    reg.register(ActionSpec(
        action_id="global.export", label=tr("Export configuration"),
        icon="export",
        keywords=("backup", "config", "save"),
        invoke=lambda sel: window._on_export_config(),
    ))
    reg.register(ActionSpec(
        action_id="global.import", label=tr("Import configuration"),
        icon="import",
        keywords=("restore", "config", "load"),
        invoke=lambda sel: window._on_import_config(),
    ))
    reg.register(ActionSpec(
        action_id="global.about", label=tr("About"), icon="about",
        invoke=lambda sel: window._on_about(),
    ))
    reg.register(ActionSpec(
        action_id="global.quit", label=tr("Quit"), dangerous=True,
        shortcut="Ctrl+Q",
        keywords=("exit", "close"),
        invoke=lambda sel: window._tray_quit(),
    ))
    reg.register(ActionSpec(
        action_id="object.delete", label=tr("Delete"), icon="remove",
        scopes=_ALL_OBJECT_SCOPES, shortcut="Del", dangerous=True,
        keywords=("remove", "destroy"),
        enabled=lambda sel: not sel.is_empty,
        invoke=lambda sel: window.tree_panel.request_delete_current(),
    ))

    # ── Действия дерева — единый источник с контекст-меню ───────────
    for spec in window.tree_panel.action_registry.all():
        reg.register(spec)
    return reg
