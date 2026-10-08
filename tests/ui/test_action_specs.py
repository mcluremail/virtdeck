"""M2.3: action spec tests (register_tree_actions, build_registry).

Tree specs are the single source for the context menu and palette:
invoke emits TreePanel signals (or calls its context methods),
enabled holds predicates on status/template/multi-selection.
"""
from virtdeck.ui.action_registry import (
    SCOPE_CLUSTER,
    SCOPE_GROUP,
    SCOPE_HOST,
    SCOPE_STORAGE,
    SCOPE_VM,
    ActionRegistry,
    Selection,
)
from virtdeck.ui.action_specs import (
    VM_ACTION_IDS,
    VM_BULK_ACTION_IDS,
    build_registry,
    register_tree_actions,
)


class _FakeSignal:
    def __init__(self):
        self.log = []

    def emit(self, *args):
        self.log.append(args)


class _FakeTree:
    """TreePanel stub: invoke signals + context call records."""

    def __init__(self):
        self.vm_action_requested = _FakeSignal()
        self.bulk_vm_action_requested = _FakeSignal()
        self.console_requested = _FakeSignal()
        self.novnc_requested = _FakeSignal()
        self.vm_migrate_requested = _FakeSignal()
        self.vm_clone_requested = _FakeSignal()
        self.vm_convert_requested = _FakeSignal()
        self.vm_ha_add_requested = _FakeSignal()
        self.vm_ha_remove_requested = _FakeSignal()
        self.vm_delete_requested = _FakeSignal()
        self.vm_create_requested = _FakeSignal()
        self.vm_clone_from_template_requested = _FakeSignal()
        self.storage_create_requested = _FakeSignal()
        self.host_remove_requested = _FakeSignal()
        self.host_token_refresh_requested = _FakeSignal()
        self.cluster_create_requested = _FakeSignal()
        self.cluster_join_requested = _FakeSignal()
        self.group_delete_requested = _FakeSignal()
        self.calls = []
        self.action_registry = ActionRegistry()
        register_tree_actions(self.action_registry, self)

    # Context receivers (real TreePanel uses guarded helpers).
    def cluster_create_vm(self, name):
        self.calls.append(("cluster_create_vm", name))

    def cluster_create_storage(self, name):
        self.calls.append(("cluster_create_storage", name))

    def group_rename_request(self, name):
        self.calls.append(("group_rename_request", name))

    def storage_edit_request(self, key):
        self.calls.append(("storage_edit_request", key))

    def storage_delete_request(self, key):
        self.calls.append(("storage_delete_request", key))


class _FakeVm:
    def __init__(self, status="stopped", template=False):
        self.status_value = status
        self.template = template


def _sel(vm=None, vm_keys=(), **kw):
    base = dict(kind=SCOPE_VM, label="web-01", host_name="h1",
                node="pve01", vmid=101, vm=vm, vm_keys=vm_keys)
    base.update(kw)
    return Selection(**base)


def _spec(tree, action_id):
    by_id = {s.action_id: s for s in tree.action_registry.all()}
    return by_id[action_id]


def _enabled_map(tree, sel, ids=VM_ACTION_IDS):
    return {aid: (_spec(tree, aid).enabled(sel)
                  if _spec(tree, aid).enabled else None)
            for aid in ids}


class TestVMActionSpecs:
    def test_stopped_vm_only_start_enabled(self):
        tree = _FakeTree()
        enabled = _enabled_map(tree, _sel(_FakeVm(status="stopped")))
        assert enabled == {
            "vm.start": True, "vm.shutdown": False, "vm.reboot": False,
            "vm.stop": False, "vm.reset": False, "vm.resume": False,
            "vm.console": False,
        }

    def test_running_vm(self):
        tree = _FakeTree()
        enabled = _enabled_map(
            tree, _sel(_FakeVm(status="running")),
            ids=VM_ACTION_IDS + ("vm.novnc",))
        assert enabled["vm.start"] is False
        assert enabled["vm.console"] is True
        assert enabled["vm.novnc"] is True
        assert all(enabled[a] for a in ("vm.shutdown", "vm.reboot",
                                        "vm.stop", "vm.reset"))
        assert enabled["vm.resume"] is False

    def test_paused_vm(self):
        tree = _FakeTree()
        enabled = _enabled_map(tree, _sel(_FakeVm(status="paused")))
        assert enabled["vm.resume"] is True
        # parity with the old menu: Start forbidden only for running
        assert enabled["vm.start"] is True
        assert enabled["vm.console"] is False

    def test_template_migrate_convert_disabled(self):
        tree = _FakeTree()
        enabled = _enabled_map(
            tree, _sel(_FakeVm(status="stopped", template=True)),
            ids=("vm.migrate", "vm.clone", "vm.convert_to_vm",
                 "vm.convert_to_template", "vm.ha_add", "vm.ha_remove"))
        assert enabled["vm.migrate"] is False
        assert enabled["vm.ha_add"] is False
        assert enabled["vm.clone"] is None          # no predicate
        assert enabled["vm.ha_remove"] is None
        assert enabled["vm.convert_to_vm"] is True  # template → VM
        assert enabled["vm.convert_to_template"] is False

    def test_running_vm_convert_to_template_disabled(self):
        tree = _FakeTree()
        enabled = _enabled_map(
            tree, _sel(_FakeVm(status="running")),
            ids=("vm.convert_to_template",))
        assert enabled["vm.convert_to_template"] is False

    def test_unknown_vm_disables_all(self):
        tree = _FakeTree()
        enabled = _enabled_map(tree, _sel(None))
        assert all(v is False for v in enabled.values())

    def test_multi_selection_hides_singles(self):
        tree = _FakeTree()
        keys = (("h1", 100, "pve01"), ("h1", 101, "pve01"))
        enabled = _enabled_map(tree, _sel(_FakeVm(status="stopped"),
                                          vm_keys=keys))
        assert all(v is False for v in enabled.values())

    def test_power_invoke_emits_signal(self):
        tree = _FakeTree()
        _spec(tree, "vm.start").invoke(_sel(_FakeVm()))
        assert tree.vm_action_requested.log == [("h1", "pve01", 101, "start")]

    def test_console_and_novnc_invoke(self):
        tree = _FakeTree()
        _spec(tree, "vm.console").invoke(_sel(_FakeVm(status="running")))
        _spec(tree, "vm.novnc").invoke(_sel(_FakeVm(status="running")))
        assert tree.console_requested.log == [("h1", "pve01", 101)]
        assert tree.novnc_requested.log == [("h1", "pve01", 101)]

    def test_vm_tools_invoke(self):
        tree = _FakeTree()
        for aid, sig in (("vm.migrate", "vm_migrate_requested"),
                         ("vm.clone", "vm_clone_requested"),
                         ("vm.ha_add", "vm_ha_add_requested"),
                         ("vm.ha_remove", "vm_ha_remove_requested")):
            _spec(tree, aid).invoke(_sel(_FakeVm()))
            assert getattr(tree, sig).log == [("h1", "pve01", 101)], aid
        _spec(tree, "vm.convert_to_template").invoke(_sel(_FakeVm()))
        assert tree.vm_convert_requested.log == [
            ("h1", "pve01", 101, "to_template")]
        _spec(tree, "vm.delete").invoke(_sel(_FakeVm()))
        assert tree.vm_delete_requested.log == [("h1", "pve01", 101)]

    def test_bulk_enabled_and_invoke(self):
        tree = _FakeTree()
        keys = (("h1", 100, "pve01"), ("h1", 101, "pve01"))
        assert _spec(tree, "vm.bulk_start").enabled(_sel(_FakeVm(),
                                                         vm_keys=keys))
        assert not _spec(tree, "vm.bulk_start").enabled(_sel(_FakeVm()))
        _spec(tree, "vm.bulk_stop").invoke(_sel(_FakeVm(), vm_keys=keys))
        assert tree.bulk_vm_action_requested.log == [(list(keys), "stop")]


class TestObjectActionSpecs:
    def test_host_create_vm_uses_node_and_host(self):
        tree = _FakeTree()
        sel = _sel(kind=SCOPE_HOST, key=("host", "pve01", "h1"))
        _spec(tree, "host.create_vm").invoke(sel)
        assert tree.vm_create_requested.log == [("pve01", "h1")]

    def test_host_delete_and_token(self):
        tree = _FakeTree()
        sel = _sel(kind=SCOPE_HOST, key=("host", "pve01", "h1"))
        _spec(tree, "host.delete").invoke(sel)
        _spec(tree, "host.refresh_token").invoke(sel)
        assert tree.host_remove_requested.log == [("host", "h1")]
        assert tree.host_token_refresh_requested.log == [("h1",)]

    def test_host_clone_from_template(self):
        tree = _FakeTree()
        sel = _sel(kind=SCOPE_HOST, key=("host", "pve01", "h1"))
        _spec(tree, "host.clone_from_template").invoke(sel)
        assert tree.vm_clone_from_template_requested.log == [("h1", "pve01")]

    def test_cluster_context_calls(self):
        tree = _FakeTree()
        sel = _sel(kind=SCOPE_CLUSTER, key=("cluster", "cl1"))
        _spec(tree, "cluster.create_vm").invoke(sel)
        _spec(tree, "cluster.create_storage").invoke(sel)
        _spec(tree, "cluster.add_node").invoke(sel)
        _spec(tree, "cluster.delete").invoke(sel)
        assert tree.calls == [
            ("cluster_create_vm", "cl1"),
            ("cluster_create_storage", "cl1"),
        ]
        assert tree.cluster_join_requested.log == [("cl1",)]
        assert tree.host_remove_requested.log == [("cluster", "cl1")]

    def test_group_rename_and_delete(self):
        tree = _FakeTree()
        sel = _sel(kind=SCOPE_GROUP, key=("group", "g1"))
        _spec(tree, "group.rename").invoke(sel)
        _spec(tree, "group.delete").invoke(sel)
        assert tree.calls == [("group_rename_request", "g1")]
        assert tree.group_delete_requested.log == [("g1",)]

    def test_storage_edit_delete_pass_key(self):
        tree = _FakeTree()
        key = ("storage", "local", "host", "h1")
        sel = _sel(kind=SCOPE_STORAGE, key=key)
        _spec(tree, "storage.edit").invoke(sel)
        _spec(tree, "storage.delete").invoke(sel)
        assert tree.calls == [
            ("storage_edit_request", key),
            ("storage_delete_request", key),
        ]


class _StubWindow:
    """Mainwindow stub: recorder handlers + tree_panel stub."""

    def __init__(self):
        self.log = []
        self.tree_panel = _FakeTree()
        self.tree_panel.request_delete_current = (
            lambda: self.log.append("delete"))
        self._handlers = {
            "global.add_server": "_on_add_server",
            "global.refresh": "refresh_data",
            "global.search": "_open_global_search",
            "global.export": "_on_export_config",
            "global.import": "_on_import_config",
            "global.about": "_on_about",
            "global.quit": "_tray_quit",
        }

    def __getattr__(self, name):
        # Lazy recorder handlers: each action logs its own id.
        if name in self._handlers.values() or name.startswith("_on_"):
            return lambda *a, n=name: self.log.append(n)
        raise AttributeError(name)


class TestBuildRegistry:
    def test_globals_and_tree_specs_merged(self):
        win = _StubWindow()
        reg = build_registry(win)
        ids = [s.action_id for s in reg.all()]
        assert ids[:len(win._handlers)] == list(win._handlers)
        assert set(VM_ACTION_IDS) <= set(ids)
        assert set(VM_BULK_ACTION_IDS) <= set(ids)
        for aid in ("host.delete", "cluster.add_node", "group.rename",
                    "storage.edit", "vm.novnc", "vm.migrate", "vm.delete"):
            assert aid in ids, aid

    def test_global_invoke_records_handler(self):
        win = _StubWindow()
        reg = build_registry(win)
        by_id = {s.action_id: s for s in reg.all()}
        by_id["global.refresh"].invoke(Selection())
        assert "refresh_data" in win.log

    def test_delete_invoke_uses_tree(self):
        win = _StubWindow()
        reg = build_registry(win)
        by_id = {s.action_id: s for s in reg.all()}
        by_id["object.delete"].invoke(_sel(_FakeVm()))
        assert win.log == ["delete"]

    def test_registry_specs_shared_with_tree(self):
        """Specs in the palette registry are the same objects as TreePanel's."""
        win = _StubWindow()
        reg = build_registry(win)
        tree_specs = {s.action_id: s for s in win.tree_panel.action_registry.all()}
        pal_specs = {s.action_id: s for s in reg.all()}
        for aid in VM_ACTION_IDS:
            assert pal_specs[aid] is tree_specs[aid]
