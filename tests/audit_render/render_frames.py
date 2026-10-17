#!/usr/bin/env python3
"""Render the audit's key frames into docs/assets/ux_audit/ (GAP-1/R15).

From a clean clone, with no network and no live servers:

    QT_QPA_PLATFORM=offscreen .venv/bin/python tests/audit_render/render_frames.py

The frames are committed next to this script so the report's evidence
survives /tmp (GAP-1); re-running the command reproduces them (R15).
Data comes from tests/harness scenarios mounted on the real transport
seams — only the wire is fake, the widgets and async paths are the
production ones.

Frame            → audit evidence
main_light       → R5 honest status bar, L3 tree, empty states (stage 5)
main_graphite    → theme persistence (R5 / stage 4)
park200          → GAP-7 / DELIGHT-8: 200-VM park, duplicate names carry VMIDs
tree_filter      → GAP-7 (product part): live tree filter narrows the park to matches
palette          → GAP-10: disabled actions stay visible with the reason
delete_vm        → DELIGHT-5: purge is an explicit opt-in (not pre-checked)
backup_job       → Д8: dialog sections and terminology
pbs_healthy      → GAP-8 / R12: healthy datastore view with snapshots
fleet_health     → fleet report rendering (Д-семейство)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

OUT = ROOT / "docs" / "assets" / "ux_audit"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="vd-frames-")

# No XDG/theme persistence beyond this run.
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from tests.harness import fake_pve_cfg, pbs_session  # noqa: E402
from tests.harness.adapter import FakeApiAdapter  # noqa: E402
from tests.harness.fake_pbs import FakePbsApi  # noqa: E402
from tests.harness.scenarios import make_pve_cluster  # noqa: E402


def _install_pve(*apis) -> None:
    """install_fake_pve without pytest's monkeypatch (standalone run)."""
    import virtdeck.provider._session as session_mod

    by_host = {api.name: api for api in apis}
    real_proxmox_api = session_mod.ProxmoxAPI

    def factory(host, **kwargs):
        adapter = FakeApiAdapter(by_host[host].handle)
        prox = real_proxmox_api(host, **kwargs)
        sess = prox._store.get("session")
        if sess is not None:
            sess.mount("https://", adapter)
            sess.mount("http://", adapter)
        return prox

    session_mod.ProxmoxAPI = factory


def pump(cond, timeout=20.0, what="state"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise SystemExit(f"timeout waiting for {what}")


def shoot(widget, name):
    png = OUT / f"{name}.png"
    widget.grab().save(str(png))
    print(f"  {png.relative_to(ROOT)} ({png.stat().st_size // 1024} KiB)")


# ── main window, populated, light theme ─────────────────────────────
print("main window:")
from virtdeck.ui.mainwindow import MainWindow  # noqa: E402

api = make_pve_cluster("fake1")
api.add_qemu("pve01", 105, "idle", status="stopped")
_install_pve(api)

mw = MainWindow()
mw.resize(1280, 800)
mw.nodes_cfg = [fake_pve_cfg("fake1")]
mw.refresh_data()
pump(lambda: mw._vm_repo.get("fake1", 105) is not None, what="tree data")
pump(lambda: mw.tree_panel.tree.topLevelItemCount() > 0, what="tree build")
app.processEvents()
shoot(mw, "main_light")

# ── graphite theme (persistence + retheme contract) ─────────────────
from virtdeck.ui.theme import load_theme  # noqa: E402


def _switch_theme(tid):
    """Drive the REAL switcher path (combo → load_theme → repolish)."""
    combo = mw._theme_combo
    idx = combo.findData(tid)
    combo.setCurrentIndex(idx)
    mw._on_theme_changed(idx)


_switch_theme("graphite")
mw.tree_panel.tree.viewport().update()
mw.tree_panel.repaint()
mw.repaint()
app.processEvents()
app.processEvents()
shoot(mw, "main_graphite")
_switch_theme("light")
app.processEvents()

# ── park of 200 VMs with duplicate names (GAP-7 / DELIGHT-8) ────────
from virtdeck.domain.enums import NodeStatus, VmStatus, VmType  # noqa: E402
from virtdeck.domain.node import Node  # noqa: E402
from virtdeck.domain.repositories import NodeRepository, VmRepository  # noqa: E402
from virtdeck.domain.vm import Vm  # noqa: E402

G = 1024 ** 3


def _node(name):
    return Node(host_name=name, node=name, cluster="",
                status=NodeStatus.ONLINE, error="", cpu_fraction=0.3,
                cpu_sockets=2, mem_bytes=2 * G, maxmem_bytes=8 * G,
                disk_bytes=10 * G, maxdisk_bytes=100 * G, uptime_seconds=1,
                pve_version_raw="8.0", kernel_version="k", qemu_version="q",
                lxc_version="l", is_cluster=False, conn_id=name)


def _vm(vmid, name, node, status=VmStatus.RUNNING):
    return Vm(vmid=vmid, name=name, vm_type=VmType.QEMU, node=node,
              host_name=node, pool="", status=status, hastate="", tags="",
              template=False, cpu_fraction=0.1, mem_bytes=G,
              maxmem_bytes=2 * G, disk_bytes=0, maxdisk_bytes=0,
              uptime_seconds=1, netin_bytes=0, netout_bytes=0,
              diskread_bytes=0, diskwrite_bytes=0, conn_id=node)


nr, vr = NodeRepository(), VmRepository()
nr.add(_node("alpha"))
nr.add(_node("beta"))
vmid = 100
for node in ("alpha", "beta"):
    for i in range(100):
        # 10 names shared across the nodes (get VMIDs), the rest unique
        name = f"web-{i}" if i < 10 else f"{node}-web-{i}"
        vr.add(_vm(vmid, name, node))
        vmid += 1
mw.tree_panel.update_data(nr.all(), vr.all(), [], final=True, node_repo=nr,
                          vm_repo=vr)
app.processEvents()
shoot(mw, "park200")

# ── GAP-7 (product part): the live tree filter at park scale ────────
mw.tree_panel._filter_edit.setText("web-9")
app.processEvents()
shoot(mw, "tree_filter")
mw.tree_panel._filter_edit.clear()
app.processEvents()

# ── command palette: a stopped VM, disabled rows carry reasons ──────
from virtdeck.ui import action_specs  # noqa: E402
from virtdeck.ui.action_registry import (  # noqa: E402
    SCOPE_VM,
    ActionRegistry,
    Selection,
)
from virtdeck.ui.command_palette import CommandPalette  # noqa: E402

reg = ActionRegistry()
action_specs.register_tree_actions(reg, tree=None)
sel = Selection(kind=SCOPE_VM, label="idle", host_name="fake1",
                node="pve01", vmid=105,
                vm=_vm(105, "idle", "pve01", VmStatus.STOPPED),
                key=("fake1", 105, "pve01"))
pal = CommandPalette(reg, lambda: sel)
pal.resize(560, 10)
pal.open_for()
app.processEvents()
shoot(pal, "palette")
pal.close()

# ── delete VM confirmation: purge is an explicit opt-in ─────────────
from PySide6.QtWidgets import QDialog  # noqa: E402

captured = {}
_real_exec = QDialog.exec


def _capture_exec(self):
    """Capture the inline delete dialog at exec time, then reject."""
    captured["widget"] = self
    return QDialog.DialogCode.Rejected


mw._vm_repo.add(_vm(105, "idle", "pve01", VmStatus.STOPPED))
QDialog.exec = _capture_exec
try:
    mw._on_vm_delete_requested("fake1", "pve01", 105)
finally:
    QDialog.exec = _real_exec
dlg = captured.get("widget")
if dlg is None:
    raise SystemExit("delete dialog did not open")
app.processEvents()
shoot(dlg, "delete_vm")
dlg.close()

# ── backup job dialog (Д8 sections) ─────────────────────────────────
from types import SimpleNamespace  # noqa: E402

from virtdeck.ui.backup_job_dialog import BackupJobDialog  # noqa: E402

storages = [
    SimpleNamespace(storage="local", content_list=["backup", "images"]),
    SimpleNamespace(storage="pbs1", content_list=["backup"]),
]
bj = BackupJobDialog(None, storages=storages, job=api.backup_jobs[0],
                     pools=["prod"])
bj.resize(520, 10)
app.processEvents()
shoot(bj, "backup_job")
bj.close()

# ── PBS healthy render (GAP-8 / R12) ────────────────────────────────
from virtdeck.pbs.client import PbsClient  # noqa: E402
from virtdeck.ui.pbs_panel import PbsPanel  # noqa: E402

pbs = FakePbsApi()
pbs.add_datastore("tank", total=1000 * 10**9, used=430 * 10**9)
pbs.add_datastore("vault", total=500 * 10**9, used=40 * 10**9)
pbs.add_snapshot("tank", 100, backup_time=1727740800)
pbs.add_snapshot("tank", 101, backup_time=1727827200)
pbs.add_snapshot("tank", 301, backup_type="ct", backup_time=1727830000)
_orig_client_init = PbsClient.__init__


def _patched_client_init(self, cfg, timeout=15, http=None):
    _orig_client_init(self, cfg, timeout=timeout,
                      http=http or pbs_session(pbs))


PbsClient.__init__ = _patched_client_init
panel = mw.pbs_panel
panel.update_nodes_cfg([{
    "name": "pbs1", "type": "pbs", "host": "pbs.local", "port": 8007,
    "user": "root@pam", "token_value": "secret", "trust_ssl": True}])
panel.show_server("pbs1")
pump(lambda: panel._ds_table.rowCount() >= 2, what="pbs datastores")
panel.show_datastore("pbs1", "tank")
pump(lambda: panel._snap_table.rowCount() >= 3, what="pbs snapshots")
panel._tabs.setCurrentIndex(1)  # Snapshots tab — the R12 evidence frame
app.processEvents()
shoot(panel, "pbs_healthy")

# ── fleet health report ─────────────────────────────────────────────
from virtdeck.backend.fleet import FleetTarget  # noqa: E402
from virtdeck.ui.fleet_health import FleetHealthDialog  # noqa: E402

fh = FleetHealthDialog([FleetTarget("fake1", "fake1", fake_pve_cfg("fake1"))])
fh.resize(880, 620)
fh.show()
pump(lambda: fh._worker is None and fh._tree.topLevelItemCount() > 0,
     what="fleet scan")
for c in range(fh._tree.columnCount()):
    fh._tree.resizeColumnToContents(c)
app.processEvents()
shoot(fh, "fleet_health")
fh.close()

mw.close()
print(f"done → {OUT}")
