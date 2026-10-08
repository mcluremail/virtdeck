"""Tests for the provider layer — errors, session, API modules.

Uses mock objects to simulate proxmoxer responses without real PVE connections.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from virtdeck.provider import (
    AccessAPI,
    ClusterAPI,
    NodeAPI,
    PoolAPI,
    ProxmoxApiError,
    ProxmoxAuthError,
    ProxmoxError,
    ProxmoxNetworkError,
    ProxmoxNotFoundError,
    ProxmoxPermissionError,
    ProxmoxSession,
    ProxmoxTimeoutError,
    RrdAPI,
    StorageAPI,
    TaskAPI,
    VmAPI,
    from_exception,
)

# -- _errors tests --


class TestErrors:
    def test_hierarchy(self):
        assert issubclass(ProxmoxAuthError, ProxmoxError)
        assert issubclass(ProxmoxNetworkError, ProxmoxError)
        assert issubclass(ProxmoxTimeoutError, ProxmoxError)
        assert issubclass(ProxmoxNotFoundError, ProxmoxError)
        assert issubclass(ProxmoxPermissionError, ProxmoxError)
        assert issubclass(ProxmoxApiError, ProxmoxError)

    def test_codes(self):
        assert ProxmoxError().code == "unknown"
        assert ProxmoxAuthError().code == "auth"
        assert ProxmoxNetworkError().code == "network"
        assert ProxmoxTimeoutError().code == "timeout"
        assert ProxmoxNotFoundError().code == "not_found"
        assert ProxmoxPermissionError().code == "permission"
        assert ProxmoxApiError("msg").code == "api"

    def test_api_error_status_code(self):
        err = ProxmoxApiError("bad request", status_code=400)
        assert err.status_code == 400

    def test_from_exception_passthrough(self):
        err = ProxmoxAuthError("denied")
        assert from_exception(err) is err

    def test_from_exception_timeout(self):
        assert isinstance(from_exception(TimeoutError("timed out")), ProxmoxTimeoutError)

    def test_from_exception_401(self):
        assert isinstance(from_exception(Exception("HTTP 401 Unauthorized")), ProxmoxAuthError)

    def test_from_exception_403(self):
        assert isinstance(from_exception(Exception("HTTP 403 Forbidden")), ProxmoxAuthError)

    def test_from_exception_404(self):
        assert isinstance(from_exception(Exception("HTTP 404 Not Found")), ProxmoxNotFoundError)

    def test_from_exception_permission(self):
        exc = Exception("permission check failed for VM.Console")
        assert isinstance(from_exception(exc), ProxmoxPermissionError)

    def test_from_exception_connection(self):
        exc = Exception("Connection refused")
        assert isinstance(from_exception(exc), ProxmoxNetworkError)

    def test_from_exception_ssl(self):
        exc = Exception("SSL certificate verification failed")
        assert isinstance(from_exception(exc), ProxmoxNetworkError)

    def test_from_exception_dns(self):
        exc = Exception("name resolution failed")
        assert isinstance(from_exception(exc), ProxmoxNetworkError)

    def test_from_exception_generic(self):
        exc = Exception("something went wrong")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxApiError)
        assert result.code == "api"


class FakeResourceException(Exception):
    """Mimic of the proxmoxer ResourceException (status_code + message)."""

    def __init__(self, status_code, status_message, content=""):
        self.status_code = status_code
        super().__init__(f"{status_code} {status_message}: {content}".strip())


class TestAnyeventErrors:
    """595-599 — pveproxy replies: classified as network, with a hint."""

    def test_595_by_status_code_attr(self):
        exc = FakeResourceException(595, "Errors during connection establishment, proxy handshake", "ENXIO")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxNetworkError)
        assert "pvedaemon" in str(result)
        assert "HTTP 595" in str(result)

    def test_596_tls_hint(self):
        exc = FakeResourceException(596, "Errors during TLS negotiation, request sending and header processing")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxNetworkError)
        assert "certificates" in str(result)

    def test_all_codes_network_class(self):
        for code in range(595, 600):
            result = from_exception(FakeResourceException(code, "whatever"))
            assert isinstance(result, ProxmoxNetworkError), code

    def test_message_prefix_fallback_without_attr(self):
        exc = Exception("595 Errors during connection establishment, proxy handshake: ENXIO")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxNetworkError)
        assert "pvedaemon" in str(result)

    def test_no_false_positive_on_vmid(self):
        exc = Exception("VM 595 config not found")
        result = from_exception(exc)
        assert not isinstance(result, ProxmoxNetworkError)

    def test_parse_pve_error_anyevent(self):
        from virtdeck.ui.utils import parse_pve_error

        msg = parse_pve_error("595 Errors during connection establishment, proxy handshake: ENXIO")
        assert "pvedaemon" in msg or "pvedaemon" in msg.lower()
        assert "HTTP 595" in msg

    def test_parse_pve_error_no_false_positive(self):
        from virtdeck.ui.utils import parse_pve_error

        assert parse_pve_error("VM 595 config not found") == "VM 595 config not found"

# -- _session tests --


class TestSession:
    def _cfg(self, **overrides):
        cfg = {
            "host": "pve.example.com",
            "user": "root@pam",
            "token_name": "test",
            "token_value": "secret",
            "trust_ssl": False,
        }
        cfg.update(overrides)
        return cfg

    def test_session_init(self):
        s = ProxmoxSession(self._cfg(), timeout=10)
        assert s.timeout == 10
        assert s.host == "pve.example.com"
        assert s._proxmox is None

    def test_session_lazy_proxmox(self):
        with patch("virtdeck.provider._session.ProxmoxAPI") as mock_px:
            mock_inst = MagicMock()
            mock_store = {}
            mock_inst._store = mock_store
            mock_px.return_value = mock_inst

            s = ProxmoxSession(self._cfg(), timeout=10)
            _ = s.proxmox
            assert s._proxmox is mock_inst
            mock_px.assert_called_once()

    def test_session_no_proxy_by_default(self):
        with patch("virtdeck.provider._session.ProxmoxAPI") as mock_px:
            mock_inst = MagicMock()
            sess = MagicMock()
            sess.trust_env = True
            mock_inst._store = {"session": sess}
            mock_px.return_value = mock_inst

            s = ProxmoxSession(self._cfg())
            _ = s.proxmox
            assert mock_px.call_args.kwargs["proxies"] is None
            assert sess.trust_env is True  # default preserved
            sess.proxies.update.assert_not_called()

    def test_session_explicit_proxy(self):
        with patch("virtdeck.provider._session.ProxmoxAPI") as mock_px:
            mock_inst = MagicMock()
            sess = MagicMock()
            mock_inst._store = {"session": sess}
            mock_px.return_value = mock_inst

            s = ProxmoxSession(self._cfg(proxy="http://10.0.0.1:8888"))
            _ = s.proxmox
            expected = {"http": "http://10.0.0.1:8888", "https": "http://10.0.0.1:8888"}
            assert mock_px.call_args.kwargs["proxies"] == expected
            assert sess.trust_env is False
            sess.proxies.update.assert_called_once_with(expected)

    def test_session_request_proxies_default_none(self):
        s = ProxmoxSession(self._cfg())
        assert s.request_proxies is None

    def test_session_request_proxies_explicit(self):
        s = ProxmoxSession(self._cfg(proxy=" http://p:3128 "))
        assert s.request_proxies == {"http": "http://p:3128", "https": "http://p:3128"}

    def test_session_close_idempotent(self):
        s = ProxmoxSession(self._cfg())
        s._proxmox = MagicMock()
        s._proxmox._store = {"session": MagicMock()}
        s.close()
        s.close()
        assert s._closed

    def test_session_context_manager(self):
        s = ProxmoxSession(self._cfg())
        s._proxmox = MagicMock()
        s._proxmox._store = {"session": MagicMock()}
        with s:
            pass
        assert s._closed

    def test_session_auth_header(self):
        s = ProxmoxSession(self._cfg())
        assert s.auth_header == "PVEAPIToken=root@pam!test=secret"

    def test_session_verify_ssl_strict(self):
        s = ProxmoxSession(self._cfg(trust_ssl=False))
        assert s.verify is True

    def test_session_verify_ssl_trust(self):
        s = ProxmoxSession(self._cfg(trust_ssl=True))
        assert s.verify is False

    def test_session_base_url(self):
        s = ProxmoxSession(self._cfg())
        assert s.base_url == "https://pve.example.com:8006/api2/json"

    def test_session_call_passes_through(self):
        s = ProxmoxSession(self._cfg())
        mock_fn = MagicMock(return_value="ok")
        result = s.call(mock_fn, "arg", kw="val")
        assert result == "ok"
        mock_fn.assert_called_once_with("arg", kw="val")

    def test_session_call_converts_exception(self):
        s = ProxmoxSession(self._cfg())
        mock_fn = MagicMock(side_effect=Exception("HTTP 401 denied"))
        with pytest.raises(ProxmoxAuthError):
            s.call(mock_fn)

    def test_session_call_preserves_proxmox_error(self):
        s = ProxmoxSession(self._cfg())
        mock_fn = MagicMock(side_effect=ProxmoxNotFoundError("gone"))
        with pytest.raises(ProxmoxNotFoundError):
            s.call(mock_fn)


# -- API module tests (mocked session) --


@pytest.fixture
def mock_session():
    session = MagicMock(spec=ProxmoxSession)
    session.proxmox = MagicMock()
    session.call = MagicMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
    session._s = session
    return session


class TestClusterAPI:
    def test_list_resources(self, mock_session):
        mock_session.proxmox.cluster.resources.get = MagicMock(return_value=[{"type": "node"}])
        api = ClusterAPI(mock_session)
        result = api.list_resources()
        assert result == [{"type": "node"}]

    def test_get_status(self, mock_session):
        mock_session.proxmox.cluster.status.get = MagicMock(return_value=[{"name": "n1"}])
        api = ClusterAPI(mock_session)
        assert api.get_status() == [{"name": "n1"}]

    def test_next_vmid_str(self, mock_session):
        mock_session.proxmox.cluster.nextid.get = MagicMock(return_value="101")
        api = ClusterAPI(mock_session)
        assert api.next_vmid() == 101

    def test_next_vmid_dict(self, mock_session):
        mock_session.proxmox.cluster.nextid.get = MagicMock(return_value={"data": 102})
        api = ClusterAPI(mock_session)
        assert api.next_vmid() == 102

    def test_list_storage_configs(self, mock_session):
        mock_session.proxmox.storage.get = MagicMock(
            return_value=[{"storage": "local", "type": "dir"}]
        )
        api = ClusterAPI(mock_session)
        assert api.list_storage_configs() == [{"storage": "local", "type": "dir"}]

    def test_get_storage_config(self, mock_session):
        chain = mock_session.proxmox.storage
        chain.return_value.get = MagicMock(return_value={"storage": "local"})
        api = ClusterAPI(mock_session)
        assert api.get_storage_config("local") == {"storage": "local"}
        chain.assert_called_once_with("local")

    def test_create_storage(self, mock_session):
        mock_session.proxmox.storage.post = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.create_storage(storage="new1", type="dir", path="/mnt/x")
        mock_session.proxmox.storage.post.assert_called_once_with(
            storage="new1", type="dir", path="/mnt/x"
        )

    def test_update_storage(self, mock_session):
        chain = mock_session.proxmox.storage
        chain.return_value.put = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.update_storage("local", content="iso,vztmpl")
        chain.assert_called_once_with("local")
        chain.return_value.put.assert_called_once_with(content="iso,vztmpl")

    def test_delete_storage(self, mock_session):
        chain = mock_session.proxmox.storage
        chain.return_value.delete = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.delete_storage("old1")
        chain.assert_called_once_with("old1")
        chain.return_value.delete.assert_called_once()

    def test_get_join_info(self, mock_session):
        mock_session.proxmox.cluster.config.join.get = MagicMock(
            return_value={"ipAddress": "10.0.0.1", "fingerprint": "AA:BB"})
        api = ClusterAPI(mock_session)
        assert api.get_join_info() == {"ipAddress": "10.0.0.1", "fingerprint": "AA:BB"}
        mock_session.proxmox.cluster.config.join.get.assert_called_once_with()

    def test_get_join_info_with_node(self, mock_session):
        mock_session.proxmox.cluster.config.join.get = MagicMock(return_value={})
        api = ClusterAPI(mock_session)
        api.get_join_info(node="n2")
        mock_session.proxmox.cluster.config.join.get.assert_called_once_with(node="n2")

    def test_join_cluster_required_params(self, mock_session):
        post = MagicMock(return_value=None)
        mock_session.proxmox.cluster.config.join.post = post
        api = ClusterAPI(mock_session)
        api.join_cluster(hostname="10.0.0.1", password="secret")
        post.assert_called_once_with(hostname="10.0.0.1", password="secret")

    def test_join_cluster_optional_params(self, mock_session):
        post = MagicMock(return_value=None)
        mock_session.proxmox.cluster.config.join.post = post
        api = ClusterAPI(mock_session)
        api.join_cluster(hostname="pve1", password="s", fingerprint="AA",
                         link0="10.0.0.1", votes=2)
        post.assert_called_once_with(
            hostname="pve1", password="s", fingerprint="AA",
            link0="10.0.0.1", votes=2)

    def test_create_cluster(self, mock_session):
        post = MagicMock(return_value=None)
        mock_session.proxmox.cluster.config.post = post
        api = ClusterAPI(mock_session)
        api.create_cluster(clustername="prod")
        post.assert_called_once_with(clustername="prod")

    def test_create_cluster_with_link(self, mock_session):
        post = MagicMock(return_value=None)
        mock_session.proxmox.cluster.config.post = post
        api = ClusterAPI(mock_session)
        api.create_cluster(clustername="prod", link0="10.0.0.1")
        post.assert_called_once_with(clustername="prod", link0="10.0.0.1")

    def test_list_ha_groups(self, mock_session):
        mock_session.proxmox.cluster.ha.groups.get = MagicMock(return_value=[{"group": "g1"}])
        api = ClusterAPI(mock_session)
        assert api.list_ha_groups() == [{"group": "g1"}]

    def test_add_ha_resource(self, mock_session):
        mock_session.proxmox.cluster.ha.resources.post = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.add_ha_resource(sid="vm:100", group="g1")
        mock_session.proxmox.cluster.ha.resources.post.assert_called_once_with(
            sid="vm:100", group="g1"
        )

    def test_delete_ha_resource(self, mock_session):
        chain = mock_session.proxmox.cluster.ha.resources
        chain.return_value.delete = MagicMock(return_value=None)
        api = ClusterAPI(mock_session)
        api.delete_ha_resource("vm:100")
        chain.assert_called_with("vm%3A100")

    def test_list_all_jobs_pve8(self, mock_session):
        mock_session.proxmox.cluster.jobs.get = MagicMock(
            return_value=[{"type": "vzdump", "id": "job1"}]
        )
        api = ClusterAPI(mock_session)
        result = api.list_all_jobs(pve_major=8)
        assert len(result) == 1
        assert result[0]["type"] == "vzdump"

    def test_list_all_jobs_pve8_fallback(self, mock_session):
        mock_session.proxmox.cluster.jobs.get = MagicMock(side_effect=Exception("no jobs"))
        mock_session.proxmox.cluster.backup.get = MagicMock(return_value=[{"id": "bk1"}])
        api = ClusterAPI(mock_session)
        result = api.list_all_jobs(pve_major=8)
        assert len(result) == 1

    def test_list_all_jobs_pve7(self, mock_session):
        mock_session.proxmox.cluster.backup.get = MagicMock(return_value=[{"id": "bk1"}])
        api = ClusterAPI(mock_session)
        result = api.list_all_jobs(pve_major=7)
        assert len(result) == 1

    def test_create_backup_job_pve8(self, mock_session):
        mock_session.proxmox.cluster.jobs.post = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.create_backup_job({"storage": "local"}, pve_major=8)
        mock_session.proxmox.cluster.jobs.post.assert_called_once()

    def test_delete_backup_job_pve8_fallback(self, mock_session):
        chain_j = mock_session.proxmox.cluster.jobs
        chain_j.return_value.delete = MagicMock(side_effect=Exception("fail"))
        chain_b = mock_session.proxmox.cluster.backup
        chain_b.return_value.delete = MagicMock(return_value=None)
        api = ClusterAPI(mock_session)
        api.delete_backup_job("job1", pve_major=8)
        chain_b.assert_called_with("job1")

    def test_create_backup_job_pve7(self, mock_session):
        mock_session.proxmox.cluster.backup.post = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.create_backup_job({"storage": "local"}, pve_major=7)
        mock_session.proxmox.cluster.backup.post.assert_called_once_with(
            storage="local"
        )
        mock_session.proxmox.cluster.jobs.post.assert_not_called()

    def test_update_backup_job_pve7(self, mock_session):
        chain = mock_session.proxmox.cluster.backup
        chain.return_value.put = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.update_backup_job("job1", {"id": "job1", "schedule": "02:00"},
                              pve_major=7)
        chain.assert_called_with("job1")
        chain.return_value.put.assert_called_once_with(schedule="02:00")
        mock_session.proxmox.cluster.jobs.assert_not_called()

    def test_delete_backup_job_pve7(self, mock_session):
        chain = mock_session.proxmox.cluster.backup
        chain.return_value.delete = MagicMock(return_value=None)
        api = ClusterAPI(mock_session)
        api.delete_backup_job("job1", pve_major=7)
        chain.assert_called_with("job1")
        chain.return_value.delete.assert_called_once()
        mock_session.proxmox.cluster.jobs.assert_not_called()


class TestNodeAPI:
    def test_list(self, mock_session):
        mock_session.proxmox.nodes.get = MagicMock(return_value=[{"node": "n1"}])
        api = NodeAPI(mock_session)
        assert api.list() == [{"node": "n1"}]

    def test_get_status(self, mock_session):
        chain = mock_session.proxmox.nodes
        chain.return_value.status.get = MagicMock(return_value={"pveversion": "8.1"})
        api = NodeAPI(mock_session)
        result = api.get_status("n1")
        assert result["pveversion"] == "8.1"
        chain.assert_called_with("n1")

    def test_get_version(self, mock_session):
        chain = mock_session.proxmox.nodes
        chain.return_value.version.get = MagicMock(return_value={"qemu": "8.0"})
        api = NodeAPI(mock_session)
        assert api.get_version("n1") == {"qemu": "8.0"}

    def test_list_storage(self, mock_session):
        chain = mock_session.proxmox.nodes
        chain.return_value.storage.get = MagicMock(return_value=[{"storage": "local"}])
        api = NodeAPI(mock_session)
        assert api.list_storage("n1") == [{"storage": "local"}]

    def test_apply_network(self, mock_session):
        chain = mock_session.proxmox.nodes
        chain.return_value.network.put = MagicMock(return_value=None)
        api = NodeAPI(mock_session)
        api.apply_network("n1")
        chain.return_value.network.put.assert_called_once()


class TestVmAPI:
    def test_get_config_qemu(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.config.get = MagicMock(return_value={"name": "vm1"})
        api = VmAPI(mock_session)
        result = api.get_config("n1", 100, "qemu")
        assert result["name"] == "vm1"
        qemu_chain.assert_called_with("100")

    def test_get_config_lxc(self, mock_session):
        chain = mock_session.proxmox.nodes
        lxc_chain = chain.return_value.lxc
        lxc_chain.return_value.config.get = MagicMock(return_value={"hostname": "ct1"})
        api = VmAPI(mock_session)
        result = api.get_config("n1", 200, "lxc")
        assert result["hostname"] == "ct1"

    def test_perform_action(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        status_mock = qemu_chain.return_value.status
        status_mock.start.post = MagicMock(return_value="OK")
        api = VmAPI(mock_session)
        api.perform_action("n1", 100, "qemu", "start")
        status_mock.start.post.assert_called_once()

    def test_resize_disk_qemu(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.resize.put = MagicMock(return_value="OK")
        api = VmAPI(mock_session)
        api.resize_disk("n1", 100, "qemu", "scsi0", "+10G")
        # Body params must NOT be pre-quoted: requests form-encodes them,
        # so _q() would double-encode ("+10G" -> "%252B10G") and PVE would
        # reject the size.
        qemu_chain.return_value.resize.put.assert_called_once_with(
            disk="scsi0", size="+10G"
        )

    def test_resize_disk_lxc(self, mock_session):
        chain = mock_session.proxmox.nodes
        lxc_chain = chain.return_value.lxc
        lxc_chain.return_value.resize.put = MagicMock(return_value="OK")
        api = VmAPI(mock_session)
        api.resize_disk("n1", 200, "lxc", "rootfs", "20G")
        # PVE's LXC resize endpoint requires the parameter to be named
        # "disk" (same as QEMU); "volume" belongs to move_volume only.
        lxc_chain.return_value.resize.put.assert_called_once_with(
            disk="rootfs", size="20G"
        )

    def test_move_disk_qemu(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.move_disk.post = MagicMock(return_value="UPID:123")
        api = VmAPI(mock_session)
        api.move_disk("n1", 100, "qemu", "scsi0", "local-lvm", delete=True)
        qemu_chain.return_value.move_disk.post.assert_called_once_with(
            disk="scsi0", storage="local-lvm", delete=1
        )

    def test_create_qemu(self, mock_session):
        chain = mock_session.proxmox.nodes
        chain.return_value.qemu.post = MagicMock(return_value="UPID:123")
        api = VmAPI(mock_session)
        api.create_qemu("n1", vmid=100, name="test")
        chain.return_value.qemu.post.assert_called_once_with(vmid=100, name="test")

    def test_delete(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.delete = MagicMock(return_value=None)
        api = VmAPI(mock_session)
        api.delete("n1", 100, "qemu", purge=True)
        qemu_chain.return_value.delete.assert_called_once_with(purge=1)

    def test_migrate(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.migrate.post = MagicMock(return_value="UPID:123")
        api = VmAPI(mock_session)
        api.migrate("n1", 100, "n2", with_local_disks=True)
        qemu_chain.return_value.migrate.post.assert_called_once_with(
            target="n2", **{"with-local-disks": 1}
        )

    def test_list_snapshots(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.snapshot.get = MagicMock(
            return_value=[{"name": "snap1"}, {"name": "current"}]
        )
        api = VmAPI(mock_session)
        result = api.list_snapshots("n1", 100, "qemu")
        assert len(result) == 2

    def test_create_snapshot(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.snapshot.post = MagicMock(return_value="UPID:123")
        api = VmAPI(mock_session)
        api.create_snapshot("n1", 100, "qemu", "snap1", description="test", vmstate=True)
        qemu_chain.return_value.snapshot.post.assert_called_once_with(
            snapname="snap1", description="test", vmstate=1
        )

    def test_delete_snapshot(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.snapshot.return_value.delete = MagicMock(
            return_value="UPID:123"
        )
        api = VmAPI(mock_session)
        api.delete_snapshot("n1", 100, "qemu", "snap1")
        qemu_chain.return_value.snapshot.return_value.delete.assert_called_once_with()

    def test_rollback_snapshot(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.snapshot.return_value.rollback.post = MagicMock(
            return_value="UPID:123"
        )
        api = VmAPI(mock_session)
        api.rollback_snapshot("n1", 100, "qemu", "snap1")
        qemu_chain.return_value.snapshot.return_value.rollback.post.assert_called_once_with()

    def test_rollback_snapshot_lxc(self, mock_session):
        chain = mock_session.proxmox.nodes
        lxc_chain = chain.return_value.lxc
        lxc_chain.return_value.snapshot.return_value.rollback.post = MagicMock(
            return_value="UPID:123"
        )
        api = VmAPI(mock_session)
        api.rollback_snapshot("n1", 200, "lxc", "snap1")
        lxc_chain.return_value.snapshot.return_value.rollback.post.assert_called_once_with()

    def test_get_vnc_proxy_lxc(self, mock_session):
        chain = mock_session.proxmox.nodes
        lxc_chain = chain.return_value.lxc
        lxc_chain.return_value.vncproxy.post = MagicMock(return_value={"port": 5900})
        api = VmAPI(mock_session)
        result = api.get_vnc_proxy("n1", 200, "lxc", "pve.host")
        assert result["port"] == 5900
        lxc_chain.return_value.vncproxy.post.assert_called_once_with(
            websocket=1, proxy="pve.host")

    def test_get_spice_proxy(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.spiceproxy.post = MagicMock(return_value={"port": 6123})
        api = VmAPI(mock_session)
        result = api.get_spice_proxy("n1", 100, "pve.host")
        assert result["port"] == 6123


class TestStorageAPI:
    def test_list_content(self, mock_session):
        chain = mock_session.proxmox.nodes
        storage_chain = chain.return_value.storage
        storage_chain.return_value.content.get = MagicMock(
            return_value=[{"volid": "local:iso/test.iso"}]
        )
        api = StorageAPI(mock_session)
        result = api.list_content("n1", "local", content="iso")
        assert len(result) == 1
        storage_chain.return_value.content.get.assert_called_once_with(content="iso")

    def test_delete_content(self, mock_session):
        chain = mock_session.proxmox.nodes
        storage_chain = chain.return_value.storage
        content_chain = storage_chain.return_value.content
        content_chain.return_value.delete = MagicMock(return_value="UPID:123")
        api = StorageAPI(mock_session)
        api.delete_content("n1", "local", "local:iso/test.iso")
        content_chain.return_value.delete.assert_called_once()

    def test_move_content(self, mock_session):
        chain = mock_session.proxmox.nodes
        storage_chain = chain.return_value.storage
        content_chain = storage_chain.return_value.content
        content_chain.return_value.post = MagicMock(return_value="UPID:123")
        api = StorageAPI(mock_session)
        api.move_content(
            "n1", "local", "local:iso/test.iso", "fast", target_vmid=100, delete_source=True
        )
        content_chain.return_value.post.assert_called_once_with(
            target_storage="fast", target_vmid=100, delete=1
        )

    def test_download_url(self, mock_session):
        chain = mock_session.proxmox.nodes
        storage_chain = chain.return_value.storage
        storage_chain.return_value.post = MagicMock(return_value="UPID:123")
        api = StorageAPI(mock_session)
        api.download_url("n1", "local", url="http://test/iso", content="iso")
        storage_chain.return_value.post.assert_called_once()


class TestPoolAPI:
    def test_list(self, mock_session):
        mock_session.proxmox.pools.get = MagicMock(return_value=[{"poolid": "p1"}])
        api = PoolAPI(mock_session)
        assert api.list() == [{"poolid": "p1"}]

    def test_get(self, mock_session):
        chain = mock_session.proxmox.pools
        chain.return_value.get = MagicMock(return_value={"poolid": "p1", "members": []})
        api = PoolAPI(mock_session)
        result = api.get("p1")
        assert result["poolid"] == "p1"
        chain.assert_called_with("p1")


class TestTaskAPI:
    def test_list(self, mock_session):
        chain = mock_session.proxmox.nodes
        chain.return_value.tasks.get = MagicMock(return_value=[{"upid": "UPID:1"}])
        api = TaskAPI(mock_session)
        result = api.list("n1", limit=50)
        assert len(result) == 1
        chain.return_value.tasks.get.assert_called_once_with(limit=50)

    def test_get_status(self, mock_session):
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        tasks_chain.return_value.status.get = MagicMock(
            return_value={"data": {"status": "stopped", "exitstatus": "OK"}}
        )
        api = TaskAPI(mock_session)
        result = api.get_status("n1", "UPID:123")
        assert result["status"] == "stopped"

    def test_poll_finished(self, mock_session):
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        tasks_chain.return_value.status.get = MagicMock(
            return_value={"data": {"status": "stopped", "exitstatus": "OK"}}
        )
        api = TaskAPI(mock_session)
        status, exitstatus = api.poll("n1", "UPID:123", timeout=5, interval=0.01)
        assert status == "stopped"
        assert exitstatus == "OK"

    def test_poll_timeout(self, mock_session):
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        tasks_chain.return_value.status.get = MagicMock(
            return_value={"data": {"status": "running"}}
        )
        api = TaskAPI(mock_session)
        status, exitstatus = api.poll("n1", "UPID:123", timeout=0.1, interval=0.05)
        assert status == "timeout"


class TestRrdAPI:
    def test_get_vm_rrddata_qemu(self, mock_session):
        chain = mock_session.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.rrddata.get = MagicMock(return_value=[{"time": 1, "cpu": 0.5}])
        api = RrdAPI(mock_session)
        result = api.get_vm_rrddata("n1", 100, "qemu", "hour")
        assert len(result) == 1
        qemu_chain.return_value.rrddata.get.assert_called_once_with(
            timeframe="hour", cf="AVERAGE"
        )

    def test_get_node_rrddata(self, mock_session):
        chain = mock_session.proxmox.nodes
        chain.return_value.rrddata.get = MagicMock(return_value=[{"time": 1}])
        api = RrdAPI(mock_session)
        api.get_node_rrddata("n1", "hour")
        chain.return_value.rrddata.get.assert_called_once_with(
            timeframe="hour", cf="AVERAGE"
        )

    def test_get_storage_rrddata(self, mock_session):
        chain = mock_session.proxmox.nodes
        storage_chain = chain.return_value.storage
        storage_chain.return_value.rrddata.get = MagicMock(return_value=[{"time": 1}])
        api = RrdAPI(mock_session)
        api.get_storage_rrddata("n1", "local", "hour")
        storage_chain.return_value.rrddata.get.assert_called_once_with(
            timeframe="hour", cf="AVERAGE"
        )


class TestAccessAPI:
    def test_list_users(self, mock_session):
        mock_session.proxmox.access.users.get = MagicMock(return_value=[{"userid": "u1"}])
        api = AccessAPI(mock_session)
        api.list_users()
        mock_session.proxmox.access.users.get.assert_called_once_with(full=1)

    def test_create_user(self, mock_session):
        mock_session.proxmox.access.users.post = MagicMock(return_value=None)
        api = AccessAPI(mock_session)
        api.create_user(userid="u1@pam")
        mock_session.proxmox.access.users.post.assert_called_once_with(userid="u1@pam")

    def test_delete_user(self, mock_session):
        chain = mock_session.proxmox.access.users
        chain.return_value.delete = MagicMock(return_value=None)
        api = AccessAPI(mock_session)
        api.delete_user("u1@pam")
        chain.assert_called_with("u1%40pam")

    def test_list_tokens(self, mock_session):
        chain = mock_session.proxmox.access.users
        chain.return_value.token.get = MagicMock(return_value=[{"id": "t1"}])
        api = AccessAPI(mock_session)
        result = api.list_tokens("u1@pam")
        assert len(result) == 1

    def test_create_token(self, mock_session):
        chain = mock_session.proxmox.access.users
        token_chain = chain.return_value.token
        token_chain.return_value.post = MagicMock(
            return_value={"full-tokenid": "u1@pam!t1", "value": "secret"}
        )
        api = AccessAPI(mock_session)
        result = api.create_token("u1@pam", "t1", comment="test")
        assert result["value"] == "secret"

    def test_list_groups(self, mock_session):
        mock_session.proxmox.access.groups.get = MagicMock(return_value=[{"groupid": "g1"}])
        api = AccessAPI(mock_session)
        assert api.list_groups() == [{"groupid": "g1"}]

    def test_list_roles(self, mock_session):
        mock_session.proxmox.access.roles.get = MagicMock(return_value=[{"roleid": "r1"}])
        api = AccessAPI(mock_session)
        assert api.list_roles() == [{"roleid": "r1"}]

    def test_list_roles_mapping_normalized(self, mock_session):
        """PVE returns {roleid: {privs, special}}; it must be flattened to a
        list with a roleid key so the UI table and RoleDialog can consume it."""
        mock_session.proxmox.access.roles.get = MagicMock(return_value={
            "Administrator": {"privs": ["Permissions.Modify"], "special": 1},
            "PVEVMUser": {"privs": ["VM.Audit", "VM.PowerMgmt"], "special": 0},
        })
        api = AccessAPI(mock_session)
        roles = api.list_roles()
        assert {r["roleid"] for r in roles} == {"Administrator", "PVEVMUser"}
        admin = next(r for r in roles if r["roleid"] == "Administrator")
        assert admin["privs"] == ["Permissions.Modify"]
        assert admin["special"] == 1

    def test_list_acl(self, mock_session):
        mock_session.proxmox.access.acl.get = MagicMock(return_value=[{"path": "/"}])
        api = AccessAPI(mock_session)
        assert api.list_acl() == [{"path": "/"}]

    def test_update_acl(self, mock_session):
        mock_session.proxmox.access.acl.put = MagicMock(return_value=None)
        api = AccessAPI(mock_session)
        api.update_acl(path="/", roles="Administrator", delete=0)
        mock_session.proxmox.access.acl.put.assert_called_once_with(
            path="/", roles="Administrator", delete=0
        )
