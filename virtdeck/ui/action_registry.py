"""M2.1: единый реестр действий приложения + fuzzy-поиск для палитры.

Действие описывается декларативной спецификацией ActionSpec (id, подпись,
иконка, scope, shortcut, правило доступности, invoke-замыкание). Реестр —
единый источник действий: из него строится командная палитра (Ctrl+K);
контекст-меню дерева переводится на него инкрементально (M2.2), чтобы
подписи, иконки и правила доступности жили в одном месте.

Модуль Qt не импортирует: Selection/ActionSpec — чистые данные,
invoke/enabled — замыкания, которые создаёт UI-слой.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Scope'ы — типы объектов дерева (ITEM_KEY_ROLE[0]) и глобальный контекст.
SCOPE_GLOBAL = "global"
SCOPE_VM = "vm"
SCOPE_CT = "ct"
SCOPE_TEMPLATE = "template"
SCOPE_HOST = "host"
SCOPE_CLUSTER = "cluster"
SCOPE_STORAGE = "storage"
SCOPE_PBS = "pbs"
SCOPE_POOL = "pool"
SCOPE_GROUP = "group"


@dataclass(frozen=True)
class Selection:
    """Дескриптор выделенного объекта дерева (или пустой).

    Заполняется TreePanel.current_selection(); используется и для
    фильтрации действий (scope + enabled), и как аргумент invoke.
    """

    kind: str = ""
    """Тип объекта: один из SCOPE_*; "" — ничего не выделено."""

    label: str = ""
    """Человекочитаемое имя объекта (для заголовков палитры)."""

    host_name: str = ""
    """virtdeck config-имя хоста (для VM — хост подключения)."""

    node: str = ""
    """Имя PVE-ноды (если известно)."""

    vmid: int = -1
    """VMID для VM/CT, иначе -1."""

    vm: object = None
    """Объект domain.Vm, если выделена VM/CT (list-level данные)."""

    key: tuple = ()
    """Ключ элемента дерева: VM_KEY_ROLE-кортеж или ITEM_KEY_ROLE-кортеж."""

    vm_keys: tuple = ()
    """Мульти-выделение VM: ((host_name, vmid, node), …)."""

    @property
    def is_empty(self) -> bool:
        return not self.kind


EMPTY_SELECTION = Selection()


@dataclass(frozen=True)
class ActionSpec:
    """Декларативное описание действия (единый источник для палитры и меню)."""

    action_id: str
    label: str
    icon: str = ""
    scopes: frozenset = frozenset({SCOPE_GLOBAL})
    shortcut: str = ""
    keywords: tuple = ()
    """Дополнительные термины поиска (не показываются)."""

    enabled: Callable[[Selection], bool] | None = None
    """None — всегда доступно; иначе предикат над выделением."""

    invoke: Callable[[Selection], None] | None = None
    """Выполняющее замыкание (аргумент — выделение на момент вызова)."""

    dangerous: bool = False
    """Деструктивное действие — палитра подсвечивает красным."""

    section: str = ""
    """Порядковая группа (сортировка внутри совпадений): меньше — выше."""


class ActionRegistry:
    """Плоский реестр ActionSpec (порядок регистрации = порядок в палитре)."""

    def __init__(self) -> None:
        self._specs: list[ActionSpec] = []

    def register(self, spec: ActionSpec) -> ActionSpec:
        self._specs.append(spec)
        return spec

    def all(self) -> tuple[ActionSpec, ...]:
        return tuple(self._specs)

    def actions_for(self, selection: Selection) -> list[ActionSpec]:
        """Спеки, применимые к выделению: по scope и правилу enabled.

        Спеки с SCOPE_GLOBAL применимы всегда (в том числе при пустом
        выделении); остальные — при совпадении типа объекта.
        """
        out = []
        for spec in self._specs:
            if SCOPE_GLOBAL not in spec.scopes and selection.kind not in spec.scopes:
                continue
            if spec.enabled is not None and not spec.enabled(selection):
                continue
            out.append(spec)
        return out

    def search(
        self, query: str, selection: Selection, limit: int = 30
    ) -> list[ActionSpec]:
        """Fuzzy-поиск по подписи и ключевым словам; пустой запрос — все."""
        specs = self.actions_for(selection)
        query = query.strip()
        if not query:
            return specs[:limit]
        entries: list[tuple[int, int, ActionSpec]] = []
        for order, spec in enumerate(specs):
            score = fuzzy_score(query, spec.label)
            for kw in spec.keywords:
                score = max(score, int(fuzzy_score(query, kw) * 0.9))
            if score > 0:
                entries.append((-score, order, spec))
        entries.sort()
        return [spec for _, _, spec in entries[:limit]]


def fuzzy_score(query: str, text: str) -> int:
    """Оценка совпадения 0–100: префикс > начало слова > подстрока > подпосл."""
    if not query:
        return 1
    q = query.lower()
    t = text.lower()
    idx = t.find(q)
    if idx == 0:
        return 100
    if idx > 0:
        return 80 if t[idx - 1] in " -_./:(" else 60
    # Подпоследовательность: штраф за «дырки» и поздний старт.
    pos = 0
    first = -1
    prev = -1
    gaps = 0
    for ch in q:
        found = t.find(ch, pos)
        if found < 0:
            return 0
        if first < 0:
            first = found
        if prev >= 0 and found > prev + 1:
            gaps += 1
        prev = found
        pos = found + 1
    return max(10, 40 - gaps * 5 - first)
