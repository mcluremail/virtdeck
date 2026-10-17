"""Stage 5 (state primitives) gates: Д6 empty-state component, Д7 detail
skeleton, DELIGHT-3 neutral informational rows, U5/U6/U7/U9/U10/U11/U12,
L3/L4 denominators, U17 dangerous menu items.

Audit refs: Д6/Д7 (S4), U3/U5/U6/U7/U9/U10/U11/U12, S4, DELIGHT-3/10/11,
L3/L4/L10, U17 (red text of destructive items).
"""

import pytest
from PySide6.QtGui import QColor

from virtdeck.domain.enums import NodeStatus, VmStatus, VmType
from virtdeck.domain.node import Node
from virtdeck.domain.repositories import NodeRepository, VmRepository
from virtdeck.domain.vm import Vm
from virtdeck.ui import theme
from virtdeck.ui.theme import Color
from virtdeck.ui.widgets.empty_state import EmptyState, SkeletonDetail

G = 1024 ** 3


def _node(name, status=NodeStatus.ONLINE, error="", cluster="rep1",
          group="PROD"):
    return Node(host_name=name, node=name, cluster=cluster,
                status=status, error=error, cpu_fraction=0.3,
                cpu_sockets=2, mem_bytes=2 * G, maxmem_bytes=8 * G,
                disk_bytes=10 * G, maxdisk_bytes=100 * G, uptime_seconds=1,
                pve_version_raw="8.0", kernel_version="k", qemu_version="q",
                lxc_version="l", is_cluster=bool(cluster), conn_id=name)


def _vm(vmid, name, node):
    return Vm(vmid=vmid, name=name, vm_type=VmType.QEMU, node=node,
              host_name=node, pool="", status=VmStatus.RUNNING,
              hastate="", tags="", template=False, cpu_fraction=0.1,
              mem_bytes=G, maxmem_bytes=2 * G, disk_bytes=0,
              maxdisk_bytes=0, uptime_seconds=1, netin_bytes=0,
              netout_bytes=0, diskread_bytes=0, diskwrite_bytes=0,
              conn_id=node)


# ── Д6: the empty-state primitive itself ────────────────────────────


class TestEmptyStatePrimitive:
    def test_has_icon_title_hint_and_action(self, qapp):
        clicked = []
        w = EmptyState("search", "No results", "Try another query",
                       action_text="Open settings",
                       on_action=lambda: clicked.append(1))
        w.show()
        qapp.processEvents()
        # labels styled through the global QSS — no inline hex (A7/Д4)
        from PySide6.QtWidgets import QLabel, QPushButton
        title = next(c for c in w.findChildren(QLabel)
                     if c.objectName() == "emptyStateTitle")
        hint = next(c for c in w.findChildren(QLabel)
                    if c.objectName() == "emptyStateHint")
        btn = w.findChild(QPushButton)
        assert "color" not in title.styleSheet()
        assert "color" not in hint.styleSheet()
        assert btn is not None
        btn.click()
        assert clicked == [1]

    def test_qss_styles_the_primitive_live(self):
        load_theme = theme.load_theme
        try:
            load_theme("light", persist=False)
            assert "QLabel#emptyStateTitle" in theme.QSS
            load_theme("graphite", persist=False)
            assert f"color: {Color.TEXT_SEC};" in theme.QSS
        finally:
            load_theme("light", persist=False)

    def test_set_state_swaps_content(self, qapp):
        from PySide6.QtWidgets import QLabel
        w = EmptyState("search", "Start typing to search", "hint")
        w.set_state("No results", "new hint")
        title = next(c for c in w.findChildren(QLabel)
                     if c.objectName() == "emptyStateTitle")
        assert title.text() == "No results"

    def test_unknown_icon_is_tolerated(self, qapp):
        w = EmptyState("no-such-icon", "t", "h")
        w.show()
        qapp.processEvents()


# ── U11: global search empty states ─────────────────────────────────


class TestSearchEmptyState:
    def test_no_results_shows_empty_state(self, qtbot, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from virtdeck.domain.repositories import (
            NodeRepository,
            PoolRepository,
            StorageRepository,
            VmRepository,
        )
        from virtdeck.ui.search_dialog import GlobalSearchDialog

        repos = (NodeRepository(), VmRepository(),
                 StorageRepository(), PoolRepository())
        dlg = GlobalSearchDialog(lambda: repos)
        qtbot.addWidget(dlg)
        dlg._input.setText("zzz-no-such-object")
        dlg._run_search()
        assert dlg._empty.isVisibleTo(dlg)
        assert dlg._empty._title_lbl.text() == "No results"
        assert not dlg._results

    def test_empty_query_hints_typing(self, qtbot, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from virtdeck.domain.repositories import (
            NodeRepository,
            PoolRepository,
            StorageRepository,
            VmRepository,
        )
        from virtdeck.ui.search_dialog import GlobalSearchDialog

        repos = (NodeRepository(), VmRepository(),
                 StorageRepository(), PoolRepository())
        dlg = GlobalSearchDialog(lambda: repos)
        qtbot.addWidget(dlg)
        dlg._run_search()
        assert dlg._empty.isVisibleTo(dlg)
        assert "typing" in dlg._empty._title_lbl.text().lower()

    def test_results_hide_the_empty_state(self, qtbot, monkeypatch,
                                          tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from virtdeck.ui.search_dialog import GlobalSearchDialog

        nr, vr = NodeRepository(), VmRepository()
        nr.add(_node("pve-alpha"))
        vr.add(_vm(100, "web-01", "pve-alpha"))
        from virtdeck.domain.repositories import PoolRepository, StorageRepository

        repos = (nr, vr, StorageRepository(), PoolRepository())
        dlg = GlobalSearchDialog(lambda: repos)
        qtbot.addWidget(dlg)
        dlg._input.setText("web")
        dlg._run_search()
        assert dlg._results
        assert not dlg._empty.isVisibleTo(dlg)


# ── U12/L10: tasks dock ─────────────────────────────────────────────


class TestTasksDockEmptyState:
    def test_zero_tasks_show_the_empty_state(self, qapp):
        from virtdeck.ui.widgets.cluster_tasks_widget import ClusterTasksWidget

        w = ClusterTasksWidget()
        w.show()
        qapp.processEvents()
        w.set_tasks([])
        qapp.processEvents()
        assert w._empty.isVisibleTo(w)

    def test_tasks_hide_the_empty_state(self, qapp):
        from virtdeck.ui.widgets.cluster_tasks_widget import ClusterTasksWidget

        w = ClusterTasksWidget()
        w.show()
        qapp.processEvents()
        w.set_tasks([])
        w.set_placeholder()
        qapp.processEvents()
        # loading placeholder wins over the empty state
        assert not w._empty.isVisibleTo(w)


# ── U6 + DELIGHT-3: Fleet Health ────────────────────────────────────


class TestFleetHealthStates:
    tr_loading = "Loading fleet data..."

    def _dialog(self, qtbot, monkeypatch, tmp_path, bundles):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from virtdeck.ui.fleet_health import FleetHealthDialog

        d = FleetHealthDialog([])
        qtbot.addWidget(d)
        d.show()
        # the initial async scan (0 targets) finishes and renders once
        qtbot.waitUntil(
            lambda: d._status.text() != self.tr_loading, timeout=5000)
        if bundles is not None:
            d._bundles = bundles
            d._render()
        return d

    def _bundle(self, cluster, complete, generated_at=1700000000):
        from virtdeck.backend.fleet import ClusterBundle
        from virtdeck.domain.backup_coverage import Coverage
        from virtdeck.domain.fleet import ClusterFleetReport

        report = ClusterFleetReport(
            cluster=cluster, generated_at=generated_at, complete=complete,
            errors=(), guests=(),
            coverage=Coverage(frozenset(), frozenset(), frozenset(), {},
                              {}) if complete else None,
            backup_states={}, node_versions={}, storage_usage=())
        return ClusterBundle(report=report, runway=(), display=cluster)

    def test_zero_targets_never_reads_clean(self, qtbot, monkeypatch,
                                            tmp_path):
        d = self._dialog(qtbot, monkeypatch, tmp_path, [])
        assert d._empty.isVisibleTo(d)
        assert "No issues" not in d._status.text()
        assert d._status.text() == "No clusters configured"

    def test_incomplete_data_is_informational_not_amber(self, qtbot,
                                                        monkeypatch,
                                                        tmp_path):
        d = self._dialog(qtbot, monkeypatch, tmp_path,
                         [self._bundle("rep1", complete=False,
                                       generated_at=0)])
        # DELIGHT-3: the row text is neutral TEXT_SEC, not WARNING
        item = d._tree.topLevelItem(0)
        assert item is not None
        brush = item.foreground(0)
        assert QColor(brush.color()) == QColor(Color.TEXT_SEC)
        # ...and the footer does not claim a check that did not happen
        assert "No issues found" not in d._status.text()
        assert "No issues in 0 of 1 clusters" in d._status.text()
        assert "1 with incomplete data" in d._status.text()

    def test_clean_complete_still_says_no_issues(self, qtbot, monkeypatch,
                                                 tmp_path):
        d = self._dialog(qtbot, monkeypatch, tmp_path,
                         [self._bundle("rep1", complete=True)])
        assert not d._empty.isVisibleTo(d)
        assert d._status.text() == "No issues found"


# ── U7: PBS panel before a server is selected ───────────────────────


class TestPbsEmptyState:
    def test_initial_state_hints_selection(self, qapp):
        from virtdeck.ui.pbs_panel import PbsPanel

        p = PbsPanel()
        p.update_nodes_cfg([])
        p.show()
        qapp.processEvents()
        assert p._empty.isVisibleTo(p)
        assert p._title_lbl.text() == "Backup server"

    def test_show_server_hides_it(self, qapp):
        from virtdeck.ui.pbs_panel import PbsPanel

        cfg = [{"name": "pbs1", "host": "h", "type": "pbs", "skip": False}]
        p = PbsPanel()
        p.update_nodes_cfg(cfg)
        p.show_server("pbs1")
        qapp.processEvents()
        assert not p._empty.isVisibleTo(p)


# ── U5 / L3: status-bar summary ─────────────────────────────────────


class TestStatusBarSummary:
    def test_empty_app_hides_the_summary(self, main_window):
        mw = main_window
        mw.nodes_cfg = []
        mw._update_status_bar()
        assert mw.status_label.text() == ""

    def test_denominator_is_configured_hosts(self, main_window):
        mw = main_window
        # 3 configured, only 1 answered (the repo holds responders only):
        # the counter must show 1/3, not 1/1
        mw.nodes_cfg = [{"name": f"pve-{c}", "host": "h", "skip": False}
                        for c in "abc"]
        nr = NodeRepository()
        nr.add(_node("pve-a"))
        mw._node_repo = nr
        mw._update_status_bar()
        assert "Hosts: 1/3" in mw.status_label.text()

    def test_answered_all_keeps_hosts_count(self, main_window):
        mw = main_window
        mw.nodes_cfg = [{"name": "pve-a", "host": "h", "skip": False}]
        nr = NodeRepository()
        nr.add(_node("pve-a"))
        mw._node_repo = nr
        mw._update_status_bar()
        assert "Hosts: 1/1" in mw.status_label.text()


# ── U10: node tooltip leads with the error reason ───────────────────


class TestNodeTooltip:
    def test_offline_node_shows_the_reason_first(self):
        from virtdeck.ui.tree_panel import _node_tooltip

        n = _node("pve-x", status=NodeStatus.ERROR,
                  error="connection refused")
        tip = _node_tooltip(n)
        assert tip.startswith("Unavailable: connection refused")
        assert "CPU" not in tip

    def test_online_node_keeps_metrics(self):
        from virtdeck.ui.tree_panel import _node_tooltip

        n = _node("pve-a", status=NodeStatus.ONLINE)
        assert "CPU" in _node_tooltip(n)


# ── U9: stable tree skeleton ────────────────────────────────────────


class TestTreeSkeleton:
    def test_loading_structure_matches_loaded(self, qapp):
        """start_loading() builds the same hierarchy from the config
        (groups -> clusters -> hosts) that data arrival will fill."""
        from virtdeck.ui.tree_panel import TreePanel

        cfgs = [
            {"name": "pve-alpha", "host": "h1", "group": "PROD",
             "cluster": "rep1", "cluster_rep": True, "skip": False},
            {"name": "pve-beta", "host": "h2", "group": "PROD",
             "cluster": "rep1", "skip": False},
            {"name": "pve-standalone", "host": "h3", "group": "",
             "skip": False},
        ]
        tp = TreePanel(cfgs)
        tp.start_loading()

        def texts(item, d=0):
            out = ["  " * d + item.text(0)]
            for i in range(item.childCount()):
                out += texts(item.child(i), d + 1)
            return out

        skeleton = []
        for i in range(tp.tree.topLevelItemCount()):
            skeleton += texts(tp.tree.topLevelItem(i))
        assert skeleton == [
            "PROD  [0/0]",
            "  rep1  [0/0]",
            "    pve-alpha  [0/0]",
            "    pve-beta  [0/0]",
            "pve-standalone",
        ]
        # spinner runs while the stubs are loading
        assert tp._spin_timer.isActive()
        tp._spin_timer.stop()

    def test_data_arrival_keeps_the_shape(self, qapp):
        from virtdeck.ui.tree_panel import TreePanel

        cfgs = [
            {"name": "pve-alpha", "host": "h1", "group": "PROD",
             "cluster": "rep1", "cluster_rep": True, "skip": False},
            {"name": "pve-beta", "host": "h2", "group": "PROD",
             "cluster": "rep1", "skip": False},
        ]
        tp = TreePanel(cfgs)
        tp.start_loading()
        tp.update_data([_node("pve-alpha"), _node("pve-beta")],
                       [_vm(100, "web-01", "pve-alpha")], [], final=True)
        top = tp.tree.topLevelItem(0)
        assert top.text(0).startswith("PROD")
        cluster = top.child(0)
        assert cluster.text(0).startswith("rep1")
        child_texts = [cluster.child(i).text(0)
                       for i in range(cluster.childCount())]
        assert any(t.startswith("pve-alpha@rep1") for t in child_texts)
        assert any(t.startswith("pve-beta@rep1") for t in child_texts)
        assert "web-01" in child_texts


# ── Д7: detail skeleton ─────────────────────────────────────────────


class TestDetailSkeleton:
    def test_skeleton_renders(self, qapp):
        from PySide6.QtGui import QPixmap

        sk = SkeletonDetail()
        sk.resize(400, 300)
        pm = QPixmap(400, 300)
        sk.render(pm)
        assert not pm.isNull()
        # painted from live tokens, no inline stylesheet (A7/Д4)
        assert sk.styleSheet() == ""

    def test_cache_miss_shows_skeleton_not_text(self, main_window):
        mw = main_window
        nr, vr = NodeRepository(), VmRepository()
        nr.add(_node("pve-alpha"))
        vm = _vm(100, "web-01", "pve-alpha")
        vr.add(vm)
        mw._node_repo, mw._vm_repo = nr, vr
        mw.nodes_cfg = [{"name": "pve-alpha", "host": "10.0.0.5",
                         "skip": False}]
        mw.detail_panel.update_nodes_cfg(mw.nodes_cfg)
        mw.tree_panel.update_data([nr.all()[0]], [vm], [], final=True,
                                  node_repo=nr, vm_repo=vr)
        tabs = mw.detail_panel
        # keep the detail worker from completing: the skeleton must stay
        tabs._workers_mgr.run_worker = lambda w: None
        tabs.show_details("vm", "web-01", vm)
        # Д7/DELIGHT-10: the info area is the skeleton page (index 2),
        # the "Loading detailed info..." text label is gone
        assert tabs.info_stack.currentIndex() == 2
        assert not tabs.info_label.isVisible()


# ── U17: destructive menu items ─────────────────────────────────────


class TestDangerousMenuItems:
    def test_qss_rule_exists(self):
        theme.load_theme("light", persist=False)
        assert 'QMenu::item[dangerous="true"]' in theme.QSS

    def test_context_menu_marks_dangerous_actions(self, main_window,
                                                  qtbot):
        mw = main_window
        nr, vr = NodeRepository(), VmRepository()
        nr.add(_node("pve-alpha"))
        vm = _vm(100, "web-01", "pve-alpha")
        vr.add(vm)
        mw._node_repo, mw._vm_repo = nr, vr
        mw.tree_panel.update_data([nr.all()[0]], [vm], [], final=True,
                                  node_repo=nr, vm_repo=vr)
        item = mw.tree_panel.find_item_by_key(("pve-alpha", 100,
                                               "pve-alpha"))
        if item is None:
            pytest.skip("tree layout differs")
        mw.tree_panel.tree.setCurrentItem(item)
        menu = mw.tree_panel._build_context_menu(item)
        assert menu is not None
        dangerous = [a for a in menu.actions()
                     if a.property("dangerous")]
        assert dangerous, "no dangerous-marked actions in the VM menu"
        for a in dangerous:
            assert a.isEnabled() or a.toolTip()

    def test_palette_colors_dangerous_red(self, main_window):
        from virtdeck.ui.action_specs import build_registry
        from virtdeck.ui.command_palette import _SPEC_ROLE, CommandPalette

        mw = main_window
        nr, vr = NodeRepository(), VmRepository()
        nr.add(_node("pve-alpha"))
        vm = _vm(100, "web-01", "pve-alpha")
        vr.add(vm)
        mw._node_repo, mw._vm_repo = nr, vr
        mw.tree_panel.update_data([nr.all()[0]], [vm], [], final=True,
                                  node_repo=nr, vm_repo=vr)
        item = mw.tree_panel.find_item_by_key(("pve-alpha", 100,
                                               "pve-alpha"))
        if item is None:
            pytest.skip("tree layout differs")
        mw.tree_panel.tree.setCurrentItem(item)
        palette = CommandPalette(build_registry(mw),
                                 mw.tree_panel.current_selection)
        palette.open_for()
        palette._input.setText("stop")
        palette._refresh("stop")
        items = []
        for i in range(palette._list.topLevelItemCount()):
            it = palette._list.topLevelItem(i)
            spec = it.data(0, _SPEC_ROLE)
            if spec is not None and getattr(spec, "dangerous", False):
                items.append(it)
        assert items
        assert all(it.foreground(0).color() == QColor(Color.DANGER)
                   for it in items)
