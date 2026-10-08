"""Lazy tab building: DetailPanel must not build tab pages at startup.

MainWindow constructs DetailPanel immediately, but the panel stays hidden
until the user selects an object. Building 25 tab pages (~1s of widget
construction) is deferred: a chunked timer builds a couple of pages per
event-loop tick right after the window appears, and _ensure_tabs()
synchronously drains whatever is left on the first selection.
"""

from virtdeck.ui.detail_panel import DetailPanel
from virtdeck.ui.detail_panel._constants import TabIndex


def test_tabs_not_built_at_construction(qtbot):
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    assert panel._tabs_built is False
    assert panel.tabs.count() == 0


def test_refresh_current_view_noop_without_selection(qtbot):
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    panel.refresh_current_view()
    assert panel.tabs.count() == 0


def test_ensure_tabs_builds_all_pages(qtbot):
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    panel._ensure_tabs()
    assert panel._tabs_built is True
    assert panel.tabs.count() == 25
    assert panel.tabs.tabText(int(TabIndex.MONITOR)) == "Monitoring"


def test_ensure_tabs_is_idempotent(qtbot):
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    panel._ensure_tabs()
    first = panel.tabs.widget(int(TabIndex.MONITOR))
    panel._ensure_tabs()
    assert panel.tabs.widget(int(TabIndex.MONITOR)) is first


def test_chunked_build_drains_queue_in_order(qtbot):
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    for _ in range(50):
        if panel._tabs_built:
            break
        panel._build_tab_chunk()
    assert panel._tabs_built is True
    assert panel.tabs.count() == 25
    assert panel.tabs.tabText(int(TabIndex.HA)) == "HA"


def test_ensure_tabs_finishes_partial_chunked_build(qtbot):
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    panel._build_tab_chunk()  # one chunk: a couple of tabs only
    built_so_far = panel.tabs.count()
    assert 0 < built_so_far < 25
    panel._ensure_tabs()
    assert panel.tabs.count() == 25
    assert panel._tabs_built is True
    # a late chunk tick must not rebuild anything
    panel._build_tab_chunk()
    assert panel.tabs.count() == 25


def test_all_tabs_built_emitted_on_drain(qtbot):
    """Regression of the FREEZE startup hang: when the chunked-build queue
    drains, the panel emits all_tabs_built — MainWindow then runs the deferred
    first selection instead of a synchronous _ensure_tabs() on the worker thread."""
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    fired = []
    panel.all_tabs_built.connect(lambda: fired.append(True))
    panel._build_tab_chunk()  # one chunk only: queue not drained yet
    assert fired == []
    while not panel._tabs_built:
        panel._build_tab_chunk()
    assert fired == [True]


def test_do_first_selection_deferred_until_tabs_built(qtbot, monkeypatch, tmp_path):
    """First selection with tabs half-built is deferred (pending), not
    built out synchronously; _on_all_tabs_built performs it."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from virtdeck.domain.node import Node as DomainNode
    from virtdeck.domain.repositories import NodeRepository
    from virtdeck.ui.mainwindow import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw.tree_panel.set_servers([
        {"name": "pve1", "host": "h1", "port": 8006, "user": "u",
         "token_value": "t", "cluster": "", "cluster_rep": True},
    ])
    mw._node_repo = NodeRepository()
    mw._node_repo.add(DomainNode.from_pve(
        {"node": "n1", "status": "online"}, "pve1", "", True))
    # Tab build queue is still full (chunk timer has not fired yet).
    assert not mw.detail_panel._tabs_built
    mw.tree_panel.update_data(
        mw._node_repo.all(), [], [], final=True, node_repo=mw._node_repo,
    )
    mw._do_first_selection()
    assert mw._pending_first_selection is True
    assert mw.tree_panel.get_current_item_key() is None
    # Drain finishes -> all_tabs_built -> pending selection runs.
    while not mw.detail_panel._tabs_built:
        mw.detail_panel._build_tab_chunk()
    assert mw._pending_first_selection is False
    assert mw.tree_panel.get_current_item_key() is not None
