"""UI audit 2026-10-08: content fit in every locale.

Invariant (the 3.0 release decision): a widget must fit its content in
each of the 6 locales. Anything that caps the size from above
(setFixedWidth/Height, setMaximumWidth/Height) must let the sizeHint
through; otherwise content clips with no scroll (QScrollArea in code).

Behavioral check: for each dialog × locale we collect child widgets and
compare maximum constraints with sizeHint. setFixedWidth(N) shows up as
maximumWidth == N, so a "setFixedWidth on a text button" regression is
caught automatically.

seed_translations is mocked: set_language() in tests does not write to
the real config.sqlite (isolation — see AUDIT_PROCESS, the "Tests"
checklist).
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog, QWidget

from virtdeck.ui.i18n import set_language

LOCALES = ["en", "ru", "ar", "zh", "fr", "es"]


@pytest.fixture(autouse=True)
def _no_db_seeding(monkeypatch):
    import virtdeck.config as config

    monkeypatch.setattr(config, "seed_translations", lambda *a, **k: None)


@pytest.fixture()
def factories():
    """Dialogs buildable without network: factory → QDialog."""
    from virtdeck.ui.about_dialog import AboutDialog
    from virtdeck.ui.acl_dialog import AclDialog
    from virtdeck.ui.add_server_dialog import AddServerDialog
    from virtdeck.ui.backup_job_dialog import BackupJobDialog
    from virtdeck.ui.clone_vm_dialog import CloneVMDialog
    from virtdeck.ui.cluster_create_dialog import ClusterCreateDialog
    from virtdeck.ui.fleet_health import FleetHealthDialog
    from virtdeck.ui.group_dialog import GroupDialog
    from virtdeck.ui.migrate_vm_dialog import MigrateVMDialog
    from virtdeck.ui.role_dialog import RoleDialog
    from virtdeck.ui.storage_config_dialog import StorageConfigDialog
    from virtdeck.ui.token_dialog import TokenDialog
    from virtdeck.ui.user_dialog import UserDialog
    from virtdeck.ui.vm_config_editor_dialog import VmConfigEditorDialog
    from virtdeck.ui.vm_restore_dialog import VmRestoreDialog
    from virtdeck.ui.vzdump_dialog import VzdumpDialog

    return {
        "about": AboutDialog,
        "add_server": AddServerDialog,
        "acl": lambda: AclDialog(roles=[], users=[], groups=[], tokens=[]),
        "backup_job": lambda: BackupJobDialog(storages=[]),
        "clone_vm": CloneVMDialog,
        "cluster_create": lambda: ClusterCreateDialog("cfg"),
        "fleet_health": lambda: FleetHealthDialog([]),
        "group": GroupDialog,
        "migrate_vm": MigrateVMDialog,
        "role": RoleDialog,
        "storage_config": StorageConfigDialog,
        "token": lambda: TokenDialog(userid="", token=None, users=[]),
        "user": UserDialog,
        "vm_config_editor": lambda: VmConfigEditorDialog(
            "key", "Label", "str", ""),
        "vm_restore": VmRestoreDialog,
        "vzdump": VzdumpDialog,
    }


def _violations(widget: QWidget) -> list[str]:
    """Widgets whose maximum is tighter than their sizeHint wants.

    QFrame is skipped: decorative lines (1px separators) carry no
    content and their 3px hint is a false positive.
    """
    from PySide6.QtWidgets import QFrame, QScrollArea

    bad = []
    for w in [widget, *widget.findChildren(QWidget)]:
        if isinstance(w, QFrame) and not isinstance(w, QScrollArea):
            continue
        mw, mh = w.maximumWidth(), w.maximumHeight()
        hint = w.sizeHint()
        if mw < 16777215 and hint.width() > mw:
            bad.append(f"{type(w).__name__} width: hint {hint.width()} > max {mw}")
        if mh < 16777215 and hint.height() > mh:
            bad.append(f"{type(w).__name__} height: hint {hint.height()} > max {mh}")
    return bad


@pytest.mark.parametrize("locale", LOCALES)
def test_dialogs_fit_content_in_locale(qtbot, factories, locale):
    set_language(locale)
    problems = []
    for name, factory in factories.items():
        dlg = factory()
        qtbot.addWidget(dlg)
        assert isinstance(dlg, QDialog), name
        for line in _violations(dlg):
            problems.append(f"{name} [{locale}]: {line}")
    # widgets outside dialogs (detail panel tabs)
    from virtdeck.ui.widgets.cluster_tasks_widget import ClusterTasksWidget

    tasks = ClusterTasksWidget()
    qtbot.addWidget(tasks)
    for line in _violations(tasks):
        problems.append(f"cluster_tasks [{locale}]: {line}")
    set_language("en")
    assert not problems, "\n" + "\n".join(problems)


def test_i18n_parity():
    """Key parity of 5 locales (mechanics from AUDIT_PROCESS.md)."""
    import json
    import pathlib

    sets = [set(json.loads(pathlib.Path(
        f"virtdeck/ui/i18n/{lang}.json").read_text())) for lang in LOCALES[1:]]
    assert all(s == sets[0] for s in sets), "locales diverged by keys"
