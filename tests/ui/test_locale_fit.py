"""UI-аудит 2026-10-08: вместимость контента во всех локалях.

Инвариант (решение о выпуске 3.0): виджет должен вмещать свой контент
в каждой из 6 локалей. Всё, что ограничивает размер сверху
(setFixedWidth/Height, setMaximumWidth/Height), обязано пропускать
sizeHint; иначе — клип без скролла (QScrollArea в коде).

Проверка поведенческая: для каждого диалога × локали собираем дочерние
виджеты и сверяем maximum-ограничения с sizeHint. setFixedWidth(N)
выражается как maximumWidth == N, поэтому регрессия вида
«setFixedWidth на текстовой кнопке» ловится автоматически.

seed_translations замокан: set_language() в тестах не пишет в реальный
config.sqlite (изоляция — см. AUDIT_PROCESS, чеклист «Тесты»).
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
    """Диалоги, строимые без сети: фабрика → QDialog."""
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
    """Виджеты, которым теснее максимума, чем хочет их sizeHint.

    QFrame пропускается: декоративные линии (сепараторы 1px) не содержат
    контента, их hint 3px — ложное срабатывание.
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
    # виджеты вне диалогов (вкладки детальной панели)
    from virtdeck.ui.widgets.cluster_tasks_widget import ClusterTasksWidget

    tasks = ClusterTasksWidget()
    qtbot.addWidget(tasks)
    for line in _violations(tasks):
        problems.append(f"cluster_tasks [{locale}]: {line}")
    set_language("en")
    assert not problems, "\n" + "\n".join(problems)


def test_i18n_parity():
    """Паритет ключей 5 локалей (механика из AUDIT_PROCESS.md)."""
    import json
    import pathlib

    sets = [set(json.loads(pathlib.Path(
        f"virtdeck/ui/i18n/{lang}.json").read_text())) for lang in LOCALES[1:]]
    assert all(s == sets[0] for s in sets), "локали разошлись по ключам"
