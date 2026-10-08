"""M0.3: optimistic UI skeleton "apply immediately -> confirm/rollback".

The UI shows the target state right away, without waiting for the
worker response or the next refresh cycle:

1. apply(): VmRepository is patched (frozen Vm replaced by a copy with
   the target status), the entry goes into pending;
2. worker success -> confirm(): pending is cleared, the target status
   stays until real data arrives (refresh_data);
3. worker failure -> rollback(): the previous status is restored in
   the repository, the tree is redrawn.

The tree shows pending items with a spinner (TreePanel.
set_pending_vm_keys), so the UI state is visible at every moment.
The skeleton is domain-dependent in one place: POWER_TARGET_STATUS
defines the target status for a power action; actions outside the
dict (migrate, clone, snapshot) are not applied optimistically.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from ..domain.enums import VmStatus
from ..domain.repositories import VmRepository

POWER_TARGET_STATUS: dict[str, VmStatus] = {
    "start": VmStatus.RUNNING,
    "resume": VmStatus.RUNNING,
    "reboot": VmStatus.RUNNING,
    "reset": VmStatus.RUNNING,
    "shutdown": VmStatus.STOPPED,
    "stop": VmStatus.STOPPED,
}


@dataclass(frozen=True)
class _Pending:
    """One in-flight change (original status kept for rollback)."""

    host_name: str
    vmid: int
    action: str
    prev_status: VmStatus


class OptimisticVMs:
    """Manager of optimistic VM status changes on top of VmRepository.

    Flow: apply() returns a token (or None — not a power action / VM
    not found / template); token.confirm() or token.rollback() finishes
    the change. Every step fires on_change (redraw).
    """

    def __init__(
        self,
        vm_repo: VmRepository,
        on_change: Callable[[], None] | None = None,
    ):
        self._repo = vm_repo
        self._on_change = on_change or (lambda: None)
        self._pending: dict[tuple[str, int], _Pending] = {}

    def apply(self, host_name: str, vmid: int, action: str) -> "OptimisticToken | None":
        target = POWER_TARGET_STATUS.get(action)
        if target is None:
            return None
        vm = self._repo.get(host_name, vmid)
        if vm is None or vm.template:
            return None
        key = (host_name, vmid)
        # A repeated action on top of pending: keep the original status,
        # rollback restores it, not the intermediate optimistic one.
        prev = self._pending[key].prev_status if key in self._pending else vm.status
        self._repo.add(replace(vm, status=target))
        self._pending[key] = _Pending(host_name, vmid, action, prev)
        self._on_change()
        return OptimisticToken(self, key)

    def confirm(self, host_name: str, vmid: int) -> None:
        if self._pending.pop((host_name, vmid), None) is not None:
            self._on_change()

    def rollback(self, host_name: str, vmid: int) -> None:
        pending = self._pending.pop((host_name, vmid), None)
        if pending is None:
            return
        vm = self._repo.get(host_name, vmid)
        if vm is not None:
            self._repo.add(replace(vm, status=pending.prev_status))
        self._on_change()

    def pending_keys(self) -> set[tuple[str, int]]:
        return set(self._pending)

    def pending_action(self, host_name: str, vmid: int) -> str | None:
        pending = self._pending.get((host_name, vmid))
        return pending.action if pending else None


class OptimisticToken:
    """Handle of one optimistic change: confirm/rollback based on the reply."""

    __slots__ = ("_manager", "_host_name", "_vmid")

    def __init__(self, manager: OptimisticVMs, key: tuple[str, int]):
        self._manager = manager
        self._host_name, self._vmid = key

    def confirm(self) -> None:
        self._manager.confirm(self._host_name, self._vmid)

    def rollback(self) -> None:
        self._manager.rollback(self._host_name, self._vmid)
