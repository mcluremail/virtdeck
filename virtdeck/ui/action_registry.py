"""M2.1: single action registry of the application + fuzzy search for the palette.

An action is described by a declarative ActionSpec (id, label, icon,
scope, shortcut, enabled rule, invoke closure). The registry is the
single source of actions: the command palette (Ctrl+K) is built from
it; the tree context menu is migrated onto it incrementally (M2.2), so
labels, icons and enabled rules live in one place.

The module does not import Qt: Selection/ActionSpec are pure data,
invoke/enabled are closures created by the UI layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Scopes — tree object types (ITEM_KEY_ROLE[0]) and the global context.
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
    """Descriptor of the selected tree object (or empty).

    Filled by TreePanel.current_selection(); used both for action
    filtering (scope + enabled) and as the invoke argument.
    """

    kind: str = ""
    """Object type: one of SCOPE_*; "" — nothing selected."""

    label: str = ""
    """Human-readable object name (for palette headers)."""

    host_name: str = ""
    """virtdeck config host name (for a VM — the connection host)."""

    node: str = ""
    """PVE node name (if known)."""

    vmid: int = -1
    """VMID for VM/CT, otherwise -1."""

    vm: object = None
    """domain.Vm object if a VM/CT is selected (list-level data)."""

    key: tuple = ()
    """Tree item key: VM_KEY_ROLE tuple or ITEM_KEY_ROLE tuple."""

    vm_keys: tuple = ()
    """VM multi-selection: ((host_name, vmid, node), ...)."""

    @property
    def is_empty(self) -> bool:
        return not self.kind


EMPTY_SELECTION = Selection()


@dataclass(frozen=True)
class ActionSpec:
    """Declarative action description (single source for palette and menu)."""

    action_id: str
    label: str
    icon: str = ""
    scopes: frozenset = frozenset({SCOPE_GLOBAL})
    shortcut: str = ""
    keywords: tuple = ()
    """Extra search terms (not displayed)."""

    enabled: Callable[[Selection], bool] | None = None
    """None — always enabled; otherwise a predicate over the selection."""

    invoke: Callable[[Selection], None] | None = None
    """Invoking closure (argument — the selection at call time)."""

    dangerous: bool = False
    """Destructive action — the palette highlights it in red."""

    section: str = ""
    """Ordering group (sorting within matches): lower is higher."""


class ActionRegistry:
    """Flat registry of ActionSpec (registration order = palette order)."""

    def __init__(self) -> None:
        self._specs: list[ActionSpec] = []

    def register(self, spec: ActionSpec) -> ActionSpec:
        self._specs.append(spec)
        return spec

    def all(self) -> tuple[ActionSpec, ...]:
        return tuple(self._specs)

    def actions_for(self, selection: Selection) -> list[ActionSpec]:
        """Specs applicable to the selection: by scope and the enabled rule.

        Specs with SCOPE_GLOBAL are always applicable (including with an
        empty selection); the others — when the object type matches.
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
        """Fuzzy search over the label and keywords; empty query — all."""
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
    """Match score 0-100: prefix > word start > substring > subsequence."""
    if not query:
        return 1
    q = query.lower()
    t = text.lower()
    idx = t.find(q)
    if idx == 0:
        return 100
    if idx > 0:
        return 80 if t[idx - 1] in " -_./:(" else 60
    # Subsequence: penalty for "holes" and a late start.
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
