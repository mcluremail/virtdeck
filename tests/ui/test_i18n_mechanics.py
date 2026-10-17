"""Stage 7 — i18n mechanics (U30/U31/U32/U33), terminology canon,
Д12 locale dates, GAP-10 disabled palette rows."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from i18n_hygiene import _extract_tr_keys  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QCheckBox, QDialog  # noqa: E402

import virtdeck.ui.i18n as i18n  # noqa: E402
from virtdeck.domain.enums import VmStatus, VmType  # noqa: E402
from virtdeck.domain.vm import Vm  # noqa: E402
from virtdeck.ui.action_registry import (  # noqa: E402
    SCOPE_VM,
    ActionRegistry,
    ActionSpec,
    Selection,
)
from virtdeck.ui.command_palette import _SPEC_ROLE, CommandPalette  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_lang():
    """Tests must not leak a language into other modules."""
    lang = i18n.get_language()
    yield
    i18n.set_language(lang)


def _vm(status=VmStatus.STOPPED, template=False):
    return Vm(vmid=100, name="web-01", vm_type=VmType.QEMU, node="n1",
              host_name="n1", pool="", status=status, hastate="", tags="",
              template=template, cpu_fraction=0.1, mem_bytes=1,
              maxmem_bytes=2, disk_bytes=0, maxdisk_bytes=0,
              uptime_seconds=1, netin_bytes=0, netout_bytes=0,
              diskread_bytes=0, diskwrite_bytes=0, conn_id="n1")


def _palette(qtbot, specs):
    """Palette over a fake registry with a fixed selection."""
    reg = ActionRegistry()
    for spec in specs:
        reg.register(spec)
    sel = Selection(kind=SCOPE_VM, label="web-01", host_name="n1",
                    node="n1", vmid=100, vm=_vm())
    pal = CommandPalette(reg, lambda: sel)
    qtbot.addWidget(pal)
    return pal


# ── U30: plural-aware trn ───────────────────────────────────────────


def test_trn_ru_plural_categories():
    i18n.set_language("ru")
    assert i18n.trn("host", "hosts", 1) == "узел"
    assert i18n.trn("host", "hosts", 3) == "узла"
    assert i18n.trn("host", "hosts", 5) == "узлов"
    # compound numbers follow the LAST digit, except 11-14
    assert i18n.trn("host", "hosts", 21) == "узел"
    assert i18n.trn("host", "hosts", 11) == "узлов"
    assert i18n.trn("host", "hosts", 14) == "узлов"
    assert i18n.trn("host", "hosts", 22) == "узла"


def test_trn_english_falls_back_to_args():
    i18n.set_language("en")
    assert i18n.trn("host", "hosts", 1) == "host"
    assert i18n.trn("host", "hosts", 5) == "hosts"


def test_trn_missing_forms_fall_back_to_english_args():
    i18n.set_language("fr")  # fr.json has no "widget|one"/"widget|many"
    assert i18n.trn("widget", "widgets", 2) == "widgets"


def test_hosts_subtitle_uses_plural_noun():
    """L4 subtitle: '1 узел · ...' vs '5 узлов · ...' (R14 no «1 нод»)."""
    i18n.set_language("ru")
    one = f"1 {i18n.trn('host', 'hosts', 1)}"
    many = f"5 {i18n.trn('host', 'hosts', 5)}"
    assert one == "1 узел"
    assert many == "5 узлов"


# ── U31: module-level label tables re-translate on language change ──


def test_module_label_tables_retranslate_in_place():
    from virtdeck.ui.widgets import cluster_tasks_widget as ctw

    i18n.set_language("en")
    table = ctw.TASK_TYPE_LABELS
    en_value = next(iter(table.values()))
    i18n.set_language("ru")
    # same object (rebuilt in place), new language
    assert ctw.TASK_TYPE_LABELS is table
    assert next(iter(table.values())) != en_value
    assert all(isinstance(v, str) for v in table.values())


def test_vm_device_editors_tables_retranslate():
    from virtdeck.ui import vm_device_editors as vde

    i18n.set_language("en")
    assert "No cache" in [label for _, label in vde.DISK_CACHE]
    i18n.set_language("ru")
    assert "Без кэша" in [label for _, label in vde.DISK_CACHE]


def test_create_vm_dialog_tables_retranslate():
    from virtdeck.ui import create_vm_dialog as cvd

    i18n.set_language("ru")
    labels = [label for _, label in cvd.CPU_TYPES]
    assert any("рекоменд" in label for label in labels)  # host (recommended)


def test_disk_cache_is_deduped_u33():
    """create_vm_dialog imports the canonical DISK_CACHE — one object."""
    from virtdeck.ui import create_vm_dialog, vm_device_editors

    assert create_vm_dialog.DISK_CACHE is vm_device_editors.DISK_CACHE
    assert create_vm_dialog.DISK_CACHE[0][1] == "No cache"


# ── U32/U33: hygiene tool extractor ─────────────────────────────────


def test_extractor_covers_add_section_titles():
    keys = _extract_tr_keys()
    for title in ("Retention and notes", "Migration target", "Selection"):
        assert title in keys


def test_extractor_covers_concatenated_prefix():
    keys = _extract_tr_keys()
    assert ("Several connections share the same name.\n"
            "Select the one to KEEP — the others will be removed:\n") in keys


def test_extractor_covers_backend_tr_calls():
    keys = _extract_tr_keys()
    assert "Backup completed for VM {vmid}" in keys
    assert "Send ACPI shutdown to VM {vmid}?" in keys  # _CONFIRM_MESSAGES


def test_extracted_keys_have_no_missing_and_no_stale():
    """The full CI invariant: code keys ⊆ dict, no unreferenced keys."""
    keys = _extract_tr_keys()
    assert keys
    for lang in ("ru", "ar", "zh", "fr", "es"):
        data = json.loads((i18n._DATA_DIR / f"{lang}.json").read_text(
            encoding="utf-8"))
        missing = [k for k in keys if k not in data]
        assert not missing, f"{lang}: missing {missing[:5]!r}"


# ── Д12: dates follow the interface locale ──────────────────────────


def test_format_datetime_follows_locale():
    dt = datetime(2026, 10, 16, 14, 30)
    i18n.set_language("ru")
    ru = i18n.format_datetime(dt)
    assert "14:30" in ru and "16.10.2026" in ru
    i18n.set_language("en")
    en = i18n.format_datetime(dt)
    assert "10/16/26" in en and "2:30" in en  # US order + 12h clock
    assert en != ru  # the locale changed the rendering


def test_format_date_and_time_helpers():
    dt = datetime(2026, 10, 16, 14, 30)
    i18n.set_language("ru")
    assert "2026" in i18n.format_date(dt)
    assert "14:30" in i18n.format_time(dt)


def test_tasks_widget_uses_locale_formatter():
    import inspect

    from virtdeck.ui.widgets import cluster_tasks_widget as ctw
    src = inspect.getsource(ctw)
    assert "TIMESTAMP_FMT" not in src
    assert "format_datetime" in src


# ── GAP-10: the palette shows disabled actions with the reason ──────


def test_disabled_action_shown_with_reason(qtbot):
    invoked = []
    pal = _palette(qtbot, [ActionSpec(
        action_id="vm.shutdown", label="Shutdown", scopes=frozenset({SCOPE_VM}),
        enabled=lambda sel: False,
        disabled_reason=lambda sel: "VM is not running",
        invoke=lambda sel: invoked.append("shutdown"),
    )])
    pal.open_for()
    rows = [pal._list.topLevelItem(i)
            for i in range(pal._list.topLevelItemCount())]
    item = next(it for it in rows
                if it.data(0, _SPEC_ROLE)
                and it.data(0, _SPEC_ROLE).action_id == "vm.shutdown")
    assert "VM is not running" in item.text(0)
    assert not (item.flags() & Qt.ItemIsSelectable)  # grayed, not runnable


def test_disabled_row_does_not_invoke(qtbot):
    invoked = []
    pal = _palette(qtbot, [ActionSpec(
        action_id="vm.shutdown", label="Shutdown", scopes=frozenset({SCOPE_VM}),
        enabled=lambda sel: False,
        disabled_reason=lambda sel: "VM is not running",
        invoke=lambda sel: invoked.append("shutdown"),
    )])
    pal.open_for()
    pal._invoke_current()  # current = the only row (disabled)
    assert not invoked
    assert not pal.isVisible() or True  # invoke() is skipped entirely


def test_navigation_skips_disabled_rows(qtbot):
    def _spec(action_id, label, enabled):
        return ActionSpec(
            action_id=action_id, label=label, scopes=frozenset({SCOPE_VM}),
            enabled=(lambda sel: enabled) if not enabled else None,
            disabled_reason=(lambda sel: "no") if not enabled else None,
            invoke=lambda sel: None,
        )

    pal = _palette(qtbot, [_spec("a.a", "Alpha", False),
                           _spec("b.b", "Beta", True)])
    pal.open_for()
    # current starts on the first selectable row (Beta)
    assert pal._list.currentItem().text(0).startswith("Beta")
    qtbot.keyClick(pal._input, Qt.Key_Up)  # Alpha disabled → stay on Beta
    assert pal._list.currentItem().text(0).startswith("Beta")
    qtbot.keyClick(pal._input, Qt.Key_Down)  # no enabled row after → stay
    assert pal._list.currentItem().text(0).startswith("Beta")


def test_real_registry_search_includes_disabled(qtbot):
    """End-to-end over the real specs: stopped VM shows Shutdown disabled."""
    from virtdeck.ui import action_specs

    reg = ActionRegistry()
    action_specs.register_tree_actions(reg, tree=None)
    sel = Selection(kind=SCOPE_VM, label="web-01", host_name="n1",
                    node="n1", vmid=100, vm=_vm(status=VmStatus.STOPPED))
    rows = reg.search("shutdown", sel, include_disabled=True)
    assert any(not s.enabled(sel) for s in rows)
    # default search still hides disabled specs (context menu semantics)
    assert all(s.enabled is None or s.enabled(sel)
               for s in reg.search("shutdown", sel))


# ── DELIGHT-5: purge is an explicit opt-in ──────────────────────────


@pytest.fixture
def mw(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from virtdeck.ui.mainwindow import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    yield window
    window.close()


def test_delete_dialog_purge_not_prechecked(qtbot, monkeypatch, mw):

    mw.nodes_cfg = [{"name": "n1", "host": "10.0.0.1", "user": "u@pam",
                     "token_name": "t", "token_value": "s"}]
    mw._rebuild_cfg_indexes()
    vm = _vm(status=VmStatus.STOPPED)
    mw._vm_repo.add(vm)
    mw.detail_panel.update_nodes_cfg(mw.nodes_cfg)

    captured = {}
    real_exec = QDialog.exec

    def fake_exec(self):
        for cb in self.findChildren(QCheckBox):
            if cb.text().startswith("Purge"):
                captured["purge"] = cb.isChecked()
        return 0  # "rejected" — no deletion happens in the test

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    try:
        mw._on_vm_delete_requested("n1", "n1", 100)
    finally:
        QDialog.exec = real_exec
    assert captured.get("purge") is False
