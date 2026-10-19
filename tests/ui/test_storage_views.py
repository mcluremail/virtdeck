"""Storages view + storage detail page regressions (2026-10-19).

Tree storages view: a host is a CONTAINER of its local storages — a
click expands it instead of opening the Hosts-view host page, and the
default note summarizes the attached local storages. Local storage keys
carry the PVE node (a cluster config shares one host_name across its
nodes, so the storage name alone is ambiguous).

Storage detail page: the params table is unfolded into labeled values
with pale API-value decodes (plugin type, content codes); a shared
backend (one row per member node, identical numbers) is NOT summed ×N;
the per-node table appears only when the per-node views actually
diverge (a node lost the mount).
"""

import pytest

from virtdeck.domain._format import format_volsize
from virtdeck.domain.enums import NodeStatus
from virtdeck.domain.node import Node
from virtdeck.domain.storage import Storage
from virtdeck.ui.i18n import tr
from virtdeck.ui.tree_panel import INFO_ROLE, ITEM_KEY_ROLE, TreePanel

G = 1024 ** 3


def _node(name, status=NodeStatus.ONLINE, cluster="rep1", group="PROD"):
    return Node(host_name=name, node=name, cluster=cluster,
                status=status, error="", cpu_fraction=0.3,
                cpu_sockets=2, mem_bytes=2 * G, maxmem_bytes=8 * G,
                disk_bytes=10 * G, maxdisk_bytes=100 * G, uptime_seconds=1,
                pve_version_raw="8.0", kernel_version="k", qemu_version="q",
                lxc_version="l", is_cluster=bool(cluster), conn_id=name)


def _stor(name, node, host, cluster="rep1", shared=False,
          used=10 * G, total=100 * G, content="images,iso", stype="nfs"):
    return Storage(storage=name, node=node, host_name=host, cluster=cluster,
                   storage_type=stype, content=content, used_bytes=used,
                   total_bytes=total, avail_bytes=total - used,
                   shared=shared)


CFG_CLUSTER = {"name": "pve-alpha", "host": "h1", "group": "PROD",
               "cluster": "rep1", "cluster_rep": True, "skip": False}
CFG_MEMBER = {"name": "pve-beta", "host": "h2", "group": "PROD",
              "cluster": "rep1", "skip": False}
CFG_ALONE = {"name": "solo", "host": "h3", "group": "", "skip": False}


def _fleet_storages():
    return [
        # Shared backend: one row per member node, identical numbers —
        # the same backend seen twice, not two backends.
        _stor("nfs-bkp", "pve-alpha", "pve-alpha", shared=True),
        _stor("nfs-bkp", "pve-beta", "pve-beta", shared=True),
        # Local storages (same names on both members, different nodes).
        _stor("local", "pve-alpha", "pve-alpha", stype="dir"),
        _stor("local-lvm", "pve-alpha", "pve-alpha", stype="lvmthin",
              content="images,rootdir"),
        _stor("local", "pve-beta", "pve-beta", stype="dir"),
        _stor("local-lvm", "pve-beta", "pve-beta", stype="lvmthin",
              content="images,rootdir"),
        # Standalone host.
        _stor("local", "solo", "solo", cluster="", stype="dir"),
    ]


def _walk(item):
    yield item
    for i in range(item.childCount()):
        yield from _walk(item.child(i))


def _all_items(tp):
    out = []
    for i in range(tp.tree.topLevelItemCount()):
        out += list(_walk(tp.tree.topLevelItem(i)))
    return out


class TestStoragesViewHostContainers:
    @pytest.fixture
    def tp(self, qapp):
        panel = TreePanel([CFG_CLUSTER, CFG_MEMBER, CFG_ALONE])
        nodes = [_node("pve-alpha"), _node("pve-beta"),
                 _node("solo", cluster="", group="")]
        panel.update_data(nodes, [], _fleet_storages(), final=True)
        panel.set_mode("storages")
        yield panel

    def test_host_container_note_sums_its_locals(self, tp):
        host = next(i for i in _all_items(tp)
                    if i.data(0, ITEM_KEY_ROLE)
                    and i.data(0, ITEM_KEY_ROLE)[0] == "host"
                    and i.data(0, ITEM_KEY_ROLE)[1] == "pve-alpha")
        expected = tr("Storages: {n} · {used}/{total}").format(
            n=2, used=format_volsize(20 * G), total=format_volsize(200 * G))
        assert host.data(0, INFO_ROLE) == expected

    def test_host_click_expands_instead_of_host_page(self, tp):
        host = next(i for i in _all_items(tp)
                    if i.data(0, ITEM_KEY_ROLE)
                    and i.data(0, ITEM_KEY_ROLE)[0] == "host"
                    and i.data(0, ITEM_KEY_ROLE)[1] == "pve-alpha")
        emitted = []
        tp.item_selected.connect(lambda *a: emitted.append(a))
        # The tree builds expanded — collapse first, then click.
        host.setExpanded(False)
        assert not host.isExpanded()
        tp._on_item_clicked(host, 0)
        assert host.isExpanded()
        tp._on_item_clicked(host, 0)
        assert not host.isExpanded()
        assert emitted == []

    def test_local_storage_key_carries_node(self, tp):
        host = next(i for i in _all_items(tp)
                    if i.data(0, ITEM_KEY_ROLE)
                    and i.data(0, ITEM_KEY_ROLE)[0] == "host"
                    and i.data(0, ITEM_KEY_ROLE)[1] == "pve-alpha")
        local = next(host.child(i) for i in range(host.childCount())
                     if host.child(i).text(0) == "local")
        key = local.data(0, ITEM_KEY_ROLE)
        assert key == ("storage", "local", "host", "pve-alpha", "pve-alpha")

    def test_shared_entry_keeps_cluster_scope_and_per_node_rows(self, tp):
        cluster = next(i for i in _all_items(tp)
                       if i.data(0, ITEM_KEY_ROLE) == ("cluster", "rep1"))
        shared = next(cluster.child(i) for i in range(cluster.childCount())
                      if cluster.child(i).text(0) == "nfs-bkp (@rep1)")
        # The shared entry itself is NOT a host-page replica either: the
        # per-node rows below it carry the node in the key.
        per_node = [shared.child(i).data(0, ITEM_KEY_ROLE)
                    for i in range(shared.childCount())]
        assert ("storage", "nfs-bkp", "host", "pve-alpha", "pve-alpha") \
            in per_node
        assert ("storage", "nfs-bkp", "host", "pve-beta", "pve-beta") \
            in per_node


def _info_texts(panel):
    lay = panel.storage_detail_info_layout
    return [lay.itemAt(i).widget().text()
            for i in range(lay.count())
            if lay.itemAt(i).widget() is not None]


class TestStorageDetailPage:
    def _show(self, mw, storages, data, name="nfs-bkp"):
        tabs = mw.detail_panel
        tabs._workers_mgr.run_worker = lambda w: None
        tabs.all_storages.clear()
        tabs.all_storages.extend(storages)
        tabs.show_details("storage", name, data)
        return tabs

    def test_shared_aggregate_is_not_inflated(self, main_window):
        mw = main_window
        mw.nodes_cfg = [CFG_CLUSTER, CFG_MEMBER]
        mw.detail_panel.update_nodes_cfg(mw.nodes_cfg)
        tabs = self._show(mw, _fleet_storages(), {"cluster": "rep1"})
        # Two rows of the same backend: the page shows ONE backend's
        # numbers (the old code summed them ×N).
        expected = tr("{used} of {total} ({pct}%)").format(
            used=format_volsize(10 * G), total=format_volsize(100 * G),
            pct="10%")
        assert tabs.storage_detail_capacity_value.text() == expected
        # N identical rows carry no additional information — the
        # per-node table stays hidden.
        assert tabs.storage_detail_nodes_table.isHidden()
        assert tabs.storage_detail_nodes_label.isHidden()

    def test_degraded_rows_reveal_per_node_table(self, main_window):
        mw = main_window
        mw.nodes_cfg = [CFG_CLUSTER, CFG_MEMBER]
        mw.detail_panel.update_nodes_cfg(mw.nodes_cfg)
        storages = _fleet_storages()
        # pve-beta lost the mount: its view is zeroed — the per-node
        # views now differ and the table earns its place.
        storages[1] = _stor("nfs-bkp", "pve-beta", "pve-beta", shared=True,
                            used=0, total=0)
        tabs = self._show(mw, storages, {"cluster": "rep1"})
        assert not tabs.storage_detail_nodes_table.isHidden()
        assert tabs.storage_detail_nodes_table.rowCount() == 2
        # The aggregate is the mounted node's view, not the sum with
        # the zeroed row (10.0 GiB, not 10.0+0).
        expected = tr("{used} of {total} ({pct}%)").format(
            used=format_volsize(10 * G), total=format_volsize(100 * G),
            pct="10%")
        assert tabs.storage_detail_capacity_value.text() == expected

    def test_per_node_click_filters_row_and_titles(self, main_window):
        mw = main_window
        mw.nodes_cfg = [CFG_CLUSTER, CFG_MEMBER]
        mw.detail_panel.update_nodes_cfg(mw.nodes_cfg)
        tabs = self._show(mw, _fleet_storages(),
                          {"cluster": "rep1", "host_name": "pve-alpha",
                           "node": "pve-alpha"})
        assert tabs.detail_label.text() == "nfs-bkp @ rep1 · pve-alpha"
        # A single node's view — no per-node table to show.
        assert tabs.storage_detail_nodes_table.isHidden()
        expected = tr("{used} of {total} ({pct}%)").format(
            used=format_volsize(10 * G), total=format_volsize(100 * G),
            pct="10%")
        assert tabs.storage_detail_capacity_value.text() == expected

    def test_api_values_are_decoded(self, main_window):
        mw = main_window
        mw.nodes_cfg = [CFG_CLUSTER, CFG_MEMBER]
        mw.detail_panel.update_nodes_cfg(mw.nodes_cfg)
        tabs = self._show(mw, _fleet_storages(), {"cluster": "rep1"})
        texts = _info_texts(tabs)
        # The raw API values are present as reported…
        assert "nfs" in texts
        assert "images, iso" in texts
        # …and each carries its human meaning (the content decode is
        # one joined line).
        assert tr("NFS network share, shared between nodes") in texts
        assert any(tr("VM disks") in t for t in texts)
        assert any(tr("ISO images") in t for t in texts)
        assert tr("One backend available from every listed node") in texts

    def test_unknown_type_passes_through_without_decode(self, main_window):
        mw = main_window
        mw.nodes_cfg = [CFG_CLUSTER]
        mw.detail_panel.update_nodes_cfg(mw.nodes_cfg)
        storages = [_stor("weird", "pve-alpha", "pve-alpha",
                          stype="mystery")]
        tabs = self._show(mw, storages, {"cluster": "rep1"}, name="weird")
        texts = _info_texts(tabs)
        assert "mystery" in texts
        assert tr("NFS network share, shared between nodes") not in texts
        # Unknown content codes pass through raw as well.
        assert any(tr("VM disks") in t for t in texts)

    def test_empty_selection_clears_blocks(self, main_window):
        mw = main_window
        mw.nodes_cfg = [CFG_CLUSTER]
        mw.detail_panel.update_nodes_cfg(mw.nodes_cfg)
        tabs = self._show(mw, [], {"cluster": "rep1"})
        assert _info_texts(tabs) == []
        assert tabs.storage_detail_capacity_value is None
        assert tabs.storage_detail_nodes_table.isHidden()
