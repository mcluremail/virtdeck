"""StorageAPI — storage content PVE endpoints.

Covers: /nodes/{node}/storage, /nodes/{node}/storage/{storage}/content,
upload (multipart), download-url, and content move/delete.
"""

from __future__ import annotations

import os

from ._session import ProxmoxSession, _q


class StorageAPI:
    """Storage content PVE API methods."""

    def __init__(self, session: ProxmoxSession) -> None:
        self._s = session

    def list_node_storage(self, node: str) -> list[dict]:
        """GET /nodes/{node}/storage — usage по хранилищам ноды (Fleet Health)."""
        return self._s.call(self._s.proxmox.nodes(_q(node)).storage.get)

    def list_content(self, node: str, storage: str, content: str | None = None) -> list[dict]:
        """GET /nodes/{node}/storage/{storage}/content."""
        params: dict = {}
        if content:
            params["content"] = content
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).storage(_q(storage)).content.get, **params
        )

    def delete_content(self, node: str, storage: str, volid: str) -> object:
        """DELETE /nodes/{node}/storage/{storage}/content/{volid}."""
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).storage(storage).content(volid).delete
        )

    def move_content(self, node: str, storage: str, volid: str,
                     target_storage: str, target_vmid: int = 0,
                     delete_source: bool = False) -> object:
        """POST /nodes/{node}/storage/{storage}/content/{volid} — move."""
        params: dict = {"target_storage": target_storage}
        if target_vmid:
            params["target_vmid"] = target_vmid
        if delete_source:
            params["delete"] = 1
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).storage(_q(storage)).content(volid).post,
            **params,
        )

    def download_url(self, node: str, storage: str, **params) -> object:
        """POST /nodes/{node}/storage/{storage}/download-url."""
        return self._s.call(
            self._s.proxmox.nodes(_q(node)).storage(_q(storage)).post,
            "download-url", **params,
        )

    def upload_file(self, node: str, storage: str, content_type: str,
                    file_path: str, timeout: int = 300,
                    progress_callback=None) -> str:
        """POST /nodes/{node}/storage/{storage}/upload (multipart).

        Uses raw requests because proxmoxer doesn't support multipart upload.
        Returns UPID string on success.
        """
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        url = (
            f"{self._s.base_url}/nodes/{_q(node)}/storage/{_q(storage)}/upload"
        )
        headers = {"Authorization": self._s.auth_header}

        class _ProgressReader:
            def __init__(self, fp, total, cb):
                self._fp = fp
                self._total = total
                self._sent = 0
                self._cb = cb
                self._last_pct = -1

            def read(self, size=-1):
                chunk = self._fp.read(size)
                if chunk:
                    self._sent += len(chunk)
                    pct = int(self._sent * 100 / self._total) if self._total else 0
                    if pct != self._last_pct:
                        self._last_pct = pct
                        if self._cb:
                            self._cb(pct)
                return chunk

            def __iter__(self):
                return self

            def __next__(self):
                chunk = self._fp.read(8192)
                if not chunk:
                    raise StopIteration
                self._sent += len(chunk)
                pct = int(self._sent * 100 / self._total) if self._total else 0
                if pct != self._last_pct:
                    self._last_pct = pct
                    if self._cb:
                        self._cb(pct)
                return chunk

            def close(self):
                self._fp.close()

            def seek(self, pos, whence=0):
                return self._fp.seek(pos, whence)

            def tell(self):
                return self._fp.tell()

            def fileno(self):
                return self._fp.fileno()

        import requests
        with open(file_path, "rb") as fp:
            wrapper = _ProgressReader(fp, file_size, progress_callback)
            files = {"filename": (file_name, wrapper, "application/octet-stream")}
            data = {"content": content_type}
            resp = requests.post(
                url, headers=headers, data=data, files=files,
                verify=self._s.verify, timeout=timeout, allow_redirects=False,
                proxies=self._s.request_proxies,
            )
            if not resp.ok:
                try:
                    body = resp.json()
                    d = body.get("data", body)
                    msg = d.get("message", "") if isinstance(d, dict) else str(d)
                    if not msg:
                        msg = body.get("message", "")
                except Exception:
                    msg = ""
                raise Exception(f"HTTP {resp.status_code}: {msg or resp.reason}"[:500])
            return resp.json().get("data", "")
