#!/usr/bin/env python3
"""M0.4: perf baseline of a typical VirtDeck session.

Measures in offscreen mode (no network):
  1. startup  — MainWindow construction (show() under offscreen, network
     excluded by the fake pool of the M0.2 runtime contract);
  2. tree     — TreePanel.update_data/_build_tree on a volume ladder
     (hosts x VMs), median of 3 runs;
  3. ceiling  — prototype of QTreeWidget insertion strategies
     (baseline / updates-off / batch+lazy-expand) up to the first tens
     of thousands of items — "how far it goes before freezing";
  4. detail   — DetailPanel.show_details("vm", ...) first/repeat open.

Result: a table to stdout + a section between the markers
<!-- PERF:DATA --> ... <!-- /PERF:DATA --> in docs/PERF_BASELINE.md
(the rest of the file is untouched). Run from the repo root:

    .venv/bin/python scripts/perf_session.py
"""

from __future__ import annotations

import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem  # noqa: E402

from tests.ui.runtime_contract import install_fake_pool, install_guard  # noqa: E402


class _MP:
    """Minimal monkeypatch without pytest (setattr + undo)."""

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self):
        for t, n, v in reversed(self._undo):
            setattr(t, n, v)
        self._undo.clear()


def _timed(fn, repeats=1):
    """Returns (result, elapsed_ms)."""
    t0 = time.perf_counter()
    res = fn()
    return res, (time.perf_counter() - t0) * 1000.0


def _median_ms(fn, repeats=3):
    return statistics.median(_timed(fn)[1] for _ in range(repeats))


def section_startup(mp):
    """MainWindow construction time (network excluded)."""
    from virtdeck.ui.mainwindow import MainWindow

    violations = install_guard(mp)
    install_fake_pool(mp)
    with tempfile.TemporaryDirectory() as xdg:
        os.environ["XDG_CONFIG_HOME"] = xdg

        def build():
            mw = MainWindow()
            mw.close()

        _, ms = _timed(build)
    mp.undo()
    assert not violations, violations
    return ms


def _make_data(hosts, vms_per_host):
    from virtdeck.domain.enums import NodeStatus, VmStatus, VmType
    from virtdeck.domain.node import Node
    from virtdeck.domain.repositories import NodeRepository, VmRepository
    from virtdeck.domain.vm import Vm

    node_repo = NodeRepository()
    vm_repo = VmRepository()
    cfgs = []
    for h in range(hosts):
        host = f"h{h}"
        cfgs.append({"name": host, "cluster": "", "skip": False})
        node_repo.add(Node(
            host_name=host, node=f"n{h}", cluster="",
            status=NodeStatus.ONLINE, error="",
            cpu_fraction=0.4, cpu_sockets=2,
            mem_bytes=8 * 1024**3, maxmem_bytes=16 * 1024**3,
            disk_bytes=0, maxdisk_bytes=0, uptime_seconds=3600,
            pve_version_raw="pve-manager/8.2.4/abc", kernel_version="6.8.12",
            qemu_version="9.0.0", lxc_version="6.0.0", is_cluster=False,
        ))
        for k in range(vms_per_host):
            vm_repo.add(Vm(
                vmid=100 + k, name=f"vm-{h}-{k}", vm_type=VmType.QEMU,
                node=f"n{h}", host_name=host, pool="", status=VmStatus.RUNNING,
                hastate="", tags="", template=False,
                cpu_fraction=0.3, mem_bytes=2 * 1024**3,
                maxmem_bytes=4 * 1024**3, disk_bytes=0, maxdisk_bytes=0,
                netin_bytes=0, netout_bytes=0, diskread_bytes=0,
                diskwrite_bytes=0, uptime_seconds=600,
            ))
    return cfgs, node_repo, vm_repo


def section_tree(ladder):
    """TreePanel rebuild (update_data final=True) on the volume ladder."""
    from virtdeck.ui.tree_panel import TreePanel

    rows = []
    for hosts, vms_per_host in ladder:
        cfgs, node_repo, vm_repo = _make_data(hosts, vms_per_host)
        tp = TreePanel(cfgs)
        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)

        def rebuild(tp=tp, node_repo=node_repo, vm_repo=vm_repo):
            tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                           node_repo=node_repo, vm_repo=vm_repo)

        ms = _median_ms(rebuild)
        rows.append((hosts, hosts * vms_per_host, ms))
        tp.deleteLater()
    return rows


def section_ceiling(sizes, batch=500):
    """Prototype of QTreeWidget insertion strategies: up to the
    ceiling.

    Strategies:
      baseline    — addTopLevelItem one by one + expandAll (as now);
      updates_off — setUpdatesEnabled(False) around insertion +
                    expandAll;
      batch_lazy  — setUpdatesEnabled(False) + insertTopLevelItems in
                    batches + expand top level only.
    """

    def build(widget, top, per_top, strategy):
        def add_children(parent):
            for k in range(per_top):
                it = QTreeWidgetItem(parent)
                it.setText(0, f"vm-{k}")

        if strategy == "baseline":
            for i in range(top):
                host = QTreeWidgetItem(widget)
                host.setText(0, f"h{i}")
                add_children(host)
            widget.expandAll()
        else:
            widget.setUpdatesEnabled(False)
            if strategy == "batch_lazy":
                made = []
                for i in range(top):
                    host = QTreeWidgetItem()
                    host.setText(0, f"h{i}")
                    add_children(host)
                    made.append(host)
                for s in range(0, len(made), batch):
                    widget.insertTopLevelItems(s, made[s:s + batch])
                widget.expandToDepth(0)
            else:
                for i in range(top):
                    host = QTreeWidgetItem(widget)
                    host.setText(0, f"h{i}")
                    add_children(host)
                widget.expandAll()
            widget.setUpdatesEnabled(True)

    rows = []
    for n in sizes:
        top, per_top = 50, max(1, n // 50)
        row = [top * per_top]
        for strategy in ("baseline", "updates_off", "batch_lazy"):
            w = QTreeWidget()
            w.setColumnCount(1)
            _, ms = _timed(lambda: build(w, top, per_top, strategy))
            QApplication.processEvents()
            row.append(ms)
            w.deleteLater()
        rows.append(tuple(row))
    return rows


def section_detail(cfgs):
    """DetailPanel.show_details('vm', ...) — first and repeat open."""
    from virtdeck.ui.detail_panel import DetailPanel

    cfgs_, node_repo, vm_repo = _make_data(1, 50)
    dp = DetailPanel(cfgs_)
    vm = vm_repo.all()[0]
    first = _median_ms(lambda: dp.show_details("vm", vm.name, vm), repeats=1)
    second = _median_ms(lambda: dp.show_details("vm", vm.name, vm))
    dp.deleteLater()
    return first, second


def _fmt(rows, headers):
    rows = [tuple(round(c, 1) if isinstance(c, float) else c for c in r)
            for r in rows]
    widths = [max(len(str(r[i])) for r in rows + [headers])
              for i in range(len(headers))]
    out = [" | ".join(str(h).ljust(w) for h, w in zip(headers, widths, strict=False))]
    out.append("-+-".join("-" * w for w in widths))
    for r in rows:
        out.append(" | ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=False)))
    return "\n".join(out)


def write_report(data_md):
    """Writes the section between the markers into docs/PERF_BASELINE.md."""
    path = ROOT / "docs" / "PERF_BASELINE.md"
    begin, end = "<!-- PERF:DATA -->", "<!-- /PERF:DATA -->"
    block = f"{begin}\n{data_md}\n{end}"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if begin in text and end in text:
            head, _, rest = text.partition(begin)
            _, _, tail = rest.partition(end)
            path.write_text(head + block + tail, encoding="utf-8")
            return path
        text += "\n\n" + block + "\n"
        path.write_text(text, encoding="utf-8")
        return path
    path.write_text(
        "# Perf baseline (M0.4)\n\n"
        "Absolute numbers — from a dev machine, not a CI gate (see "
        "ROADMAP M0.4). Re-run: `.venv/bin/python scripts/perf_session.py`.\n\n"
        + block + "\n",
        encoding="utf-8",
    )
    return path


def main():
    _ = QApplication.instance() or QApplication([])

    ladder = [(5, 20), (10, 100), (10, 200), (20, 250)]
    ceiling_sizes = [1000, 5000, 10000, 20000]

    mp = _MP()
    print("== startup ==")
    startup_ms = section_startup(mp)
    print(f"MainWindow construction: {startup_ms:.0f} ms")

    print("== tree ladder (median of 3) ==")
    tree_rows = section_tree(ladder)
    print(_fmt(tree_rows, ["hosts", "items", "rebuild_ms"]))

    print("== QTreeWidget ceiling prototype ==")
    ceil_rows = section_ceiling(ceiling_sizes)
    print(_fmt(ceil_rows, ["items", "baseline_ms", "updates_off_ms", "batch_lazy_ms"]))

    print("== detail panel ==")
    first, second = section_detail([(1, "")])
    print(f"show_details vm: first {first:.0f} ms, repeat {second:.0f} ms")

    startup_ms = round(startup_ms, 1)
    first, second = round(first, 1), round(second, 1)

    sysinfo = (f"{platform.system()} {platform.release()}, "
               f"Python {platform.python_version()}, offscreen")
    date = time.strftime("%Y-%m-%d %H:%M")
    data_md = (
        f"Last run: {date} ({sysinfo})\n\n"
        "### Startup\n\n"
        f"- MainWindow construction: **{startup_ms:.0f} ms**\n\n"
        "### Tree (TreePanel rebuild, median of 3)\n\n"
        + "```\n" + _fmt(tree_rows, ["hosts", "items", "rebuild_ms"]) + "\n```\n\n"
        "### QTreeWidget ceiling (insertion strategy prototype)\n\n"
        + "```\n"
        + _fmt(ceil_rows, ["items", "baseline_ms", "updates_off_ms", "batch_lazy_ms"])
        + "\n```\n\n"
        "### DetailPanel.show_details (vm)\n\n"
        f"- first open: **{first:.0f} ms**, repeat: **{second:.0f} ms**\n"
    )
    path = write_report(data_md)
    print(f"\nReport: {path}")


if __name__ == "__main__":
    main()
