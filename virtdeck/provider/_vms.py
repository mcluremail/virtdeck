"""VmAPI — VM (QEMU) and container (LXC) PVE endpoints.

Covers: /nodes/{node}/qemu, /nodes/{node}/lxc, their status, config,
resize, move_disk/move_volume, clone, migrate, template, snapshots,
vncproxy/spiceproxy, and create/delete operations.
"""

from __future__ import annotations

from ._session import ProxmoxSession, _q


class VmAPI:
    """VM and container PVE API methods."""

    def __init__(self, session: ProxmoxSession) -> None:
        self._s = session

    def _resource(self, node: str, vmid: int | str, vm_type: str):
        n = self._s.proxmox.nodes(_q(node))
        return n.qemu(_q(vmid)) if vm_type == "qemu" else n.lxc(_q(vmid))

    # -- list --

    def list_qemu(self, node: str) -> list[dict]:
        """GET /nodes/{node}/qemu."""
        return self._s.call(self._s.proxmox.nodes(_q(node)).qemu.get)

    def list_lxc(self, node: str) -> list[dict]:
        """GET /nodes/{node}/lxc."""
        return self._s.call(self._s.proxmox.nodes(_q(node)).lxc.get)

    # -- status --

    def get_status(self, node: str, vmid: int | str, vm_type: str) -> dict:
        """GET /nodes/{node}/{qemu|lxc}/{vmid}/status/current."""
        return self._s.call(self._resource(node, vmid, vm_type).status.current.get)

    def start(self, node: str, vmid: int | str, vm_type: str) -> object:
        """POST .../status/start."""
        return self._s.call(self._resource(node, vmid, vm_type).status.start.post)

    def stop(self, node: str, vmid: int | str, vm_type: str) -> object:
        """POST .../status/stop."""
        return self._s.call(self._resource(node, vmid, vm_type).status.stop.post)

    def reboot(self, node: str, vmid: int | str, vm_type: str) -> object:
        """POST .../status/reboot."""
        return self._s.call(self._resource(node, vmid, vm_type).status.reboot.post)

    def shutdown(self, node: str, vmid: int | str, vm_type: str) -> object:
        """POST .../status/shutdown."""
        return self._s.call(self._resource(node, vmid, vm_type).status.shutdown.post)

    def suspend(self, node: str, vmid: int | str, vm_type: str) -> object:
        """POST .../status/suspend."""
        return self._s.call(self._resource(node, vmid, vm_type).status.suspend.post)

    def resume(self, node: str, vmid: int | str, vm_type: str) -> object:
        """POST .../status/resume."""
        return self._s.call(self._resource(node, vmid, vm_type).status.resume.post)

    def perform_action(self, node: str, vmid: int | str, vm_type: str, action: str) -> object:
        """POST .../status/{action} — generic action dispatch."""
        call = getattr(self._resource(node, vmid, vm_type).status, action)
        return self._s.call(call.post)

    # -- config --

    def get_config(self, node: str, vmid: int | str, vm_type: str) -> dict:
        """GET .../config."""
        return self._s.call(self._resource(node, vmid, vm_type).config.get)

    def update_config(self, node: str, vmid: int | str, vm_type: str, **params) -> object:
        """PUT .../config."""
        return self._s.call(self._resource(node, vmid, vm_type).config.put, **params)

    def post_config(self, node: str, vmid: int | str, vm_type: str, **params) -> object:
        """POST .../config — used for template=0 conversion."""
        return self._s.call(self._resource(node, vmid, vm_type).config.post, **params)

    # -- disk operations --

    def resize_disk(self, node: str, vmid: int | str, vm_type: str,
                    disk: str, size: str) -> object:
        """PUT .../resize (QEMU and LXC — the endpoint shape is the same).

        Body params are passed raw: requests form-encodes them, so
        pre-quoting with _q() would double-encode (e.g. "+10G" -> "%252B10G").
        """
        return self._s.call(
            self._resource(node, vmid, vm_type).resize.put,
            disk=disk, size=size,
        )

    def move_disk(self, node: str, vmid: int | str, vm_type: str,
                  disk: str, storage: str, delete: bool = False) -> object:
        """POST .../move_disk (QEMU) or .../move_volume (LXC)."""
        if vm_type == "qemu":
            params: dict = {"disk": disk, "storage": storage}
            if delete:
                params["delete"] = 1
            return self._s.call(self._resource(node, vmid, vm_type).move_disk.post, **params)
        params = {"volume": disk, "storage": storage}
        if delete:
            params["delete"] = 1
        return self._s.call(self._resource(node, vmid, vm_type).move_volume.post, **params)

    # -- lifecycle: create / delete / clone / migrate / template --

    def create_qemu(self, node: str, **params) -> object:
        """POST /nodes/{node}/qemu."""
        return self._s.call(self._s.proxmox.nodes(_q(node)).qemu.post, **params)

    def create_lxc(self, node: str, **params) -> object:
        """POST /nodes/{node}/lxc."""
        return self._s.call(self._s.proxmox.nodes(_q(node)).lxc.post, **params)

    def delete(self, node: str, vmid: int | str, vm_type: str, purge: bool = True) -> object:
        """DELETE /nodes/{node}/{qemu|lxc}/{vmid}."""
        params = {"purge": 1} if purge else {}
        return self._s.call(self._resource(node, vmid, vm_type).delete, **params)

    def clone(self, node: str, vmid: int | str, vm_type: str, **params) -> object:
        """POST .../clone."""
        return self._s.call(self._resource(node, vmid, vm_type).clone.post, **params)

    def migrate(self, node: str, vmid: int | str, vm_type: str, target: str,
                with_local_disks: bool = True, *, online: bool = False,
                restart: bool = False) -> object:
        """POST /nodes/{node}/{qemu|lxc}/{vmid}/migrate.

        Supported by PVE 7/8/9 for both guest types. A running QEMU VM
        needs ``online`` (live migration); a running LXC container needs
        ``online`` (CRIU) or ``restart`` (restart migration — the CT is
        rebooted on the target node). A stopped guest needs neither.
        """
        params: dict = {"target": target}
        if with_local_disks:
            params["with-local-disks"] = 1
        if online:
            params["online"] = 1
        if restart:
            params["restart"] = 1
        return self._s.call(
            self._resource(node, vmid, vm_type).migrate.post, **params
        )

    def convert_to_template(self, node: str, vmid: int | str) -> object:
        """POST /nodes/{node}/qemu/{vmid}/template (QEMU only)."""
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).qemu(_q(vmid)).template.post
        )

    # -- snapshots --

    def list_snapshots(self, node: str, vmid: int | str, vm_type: str) -> list[dict]:
        """GET .../snapshot."""
        return self._s.call(self._resource(node, vmid, vm_type).snapshot.get)

    def get_snapshot_config(self, node: str, vmid: int | str, vm_type: str,
                             snap_name: str) -> dict:
        """GET .../snapshot/{snap}/config."""
        return self._s.call(
            self._resource(node, vmid, vm_type).snapshot(snap_name).config.get
        )

    def create_snapshot(self, node: str, vmid: int | str, vm_type: str,
                        snap_name: str, description: str = "",
                        vmstate: bool = False) -> object:
        """POST .../snapshot."""
        return self._s.call(
            self._resource(node, vmid, vm_type).snapshot.post,
            snapname=snap_name,
            description=description,
            vmstate=1 if vmstate else 0,
        )

    def delete_snapshot(self, node: str, vmid: int | str, vm_type: str,
                         snap_name: str) -> object:
        """DELETE .../snapshot/{snap}."""
        return self._s.call(
            self._resource(node, vmid, vm_type).snapshot(snap_name).delete
        )

    def rollback_snapshot(self, node: str, vmid: int | str, vm_type: str,
                          snap_name: str) -> object:
        """POST .../snapshot/{snap}/rollback."""
        return self._s.call(
            self._resource(node, vmid, vm_type).snapshot(snap_name).rollback.post
        )

    # -- console proxies --

    def get_vnc_proxy(self, node: str, vmid: int | str, vm_type: str,
                      proxy_host: str | None = None) -> dict:
        """POST .../vncproxy. websocket=1 is required for the noVNC path:
        PVE raises a websocket-ready listener (qm vncproxy --websocket).
        proxy_host is optional: without it PVE picks the address itself."""
        if vm_type == "lxc":
            post = self._s.proxmox.nodes(_q(node)).lxc(_q(vmid)).vncproxy.post
        else:
            post = self._s.proxmox.nodes(_q(node)).qemu(_q(vmid)).vncproxy.post
        params: dict = {"websocket": 1}
        if proxy_host:
            params["proxy"] = proxy_host
        return self._s.call(post, **params)

    def get_spice_proxy(self, node: str, vmid: int | str,
                         proxy_host: str) -> object:
        """POST .../spiceproxy (QEMU only)."""
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).qemu(vmid).spiceproxy.post,
            proxy=proxy_host,
        )

    def get_vnc_websocket(self, node: str, vmid: int | str, vm_type: str,
                          port: int, vncticket: str) -> dict:
        """GET .../vncwebsocket — validates the VNC ticket and arms the
        websocket endpoint on the API port (used by the noVNC console)."""
        if vm_type == "lxc":
            return self._s.call(
                self._s.proxmox.nodes(_q(node)).lxc(vmid).vncwebsocket.get,
                port=port,
                vncticket=vncticket,
            )
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).qemu(vmid).vncwebsocket.get,
            port=port,
            vncticket=vncticket,
        )
