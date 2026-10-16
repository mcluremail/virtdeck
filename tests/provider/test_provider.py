"""Tests for the provider layer — errors, session, API modules.

Uses mock objects to simulate proxmoxer responses without real PVE connections.
"""

from __future__ import annotations

from types import SimpleNamespace
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
from virtdeck.provider._session import _q

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

    def test_status_code_wins_over_message_text(self):
        # FakeResourceException mimics proxmoxer: exact status attribute;
        # a message that merely CONTAINS "401" must not misclassify a 400
        exc = FakeResourceException(400, "Bad Request", "VM 401 not found")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxApiError)
        assert result.status_code == 400

    @pytest.mark.parametrize("status,cls", [
        (401, ProxmoxAuthError),
        (404, ProxmoxNotFoundError),
        (504, ProxmoxTimeoutError),
        (501, ProxmoxApiError),
        (500, ProxmoxApiError),
    ])
    def test_exact_status_classification(self, status, cls):
        result = from_exception(FakeResourceException(status, "msg"))
        assert isinstance(result, cls)
        assert result.status_code == status

    def test_403_permission_vs_auth(self):
        perm = from_exception(FakeResourceException(
            403, "Forbidden", "permission check failed"))
        assert isinstance(perm, ProxmoxPermissionError)
        assert perm.status_code == 403
        auth = from_exception(FakeResourceException(403, "Forbidden", "no"))
        assert isinstance(auth, ProxmoxAuthError)
        assert auth.status_code == 403

    def test_requests_exception_without_status_falls_back(self):
        # requests exceptions carry no status_code — regex path applies
        result = from_exception(Exception("404 Client Error: not found"))
        assert isinstance(result, ProxmoxNotFoundError)


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


class TestTransportClassificationD4:
    """Audit D4: requests transport errors are classified by TYPE, before
    any text heuristics — a VMID like 401/403/404 inside a quoted request
    URL must not turn a DNS/connection failure into auth/not-found."""

    @staticmethod
    def _dns_error(vmid):
        import requests.exceptions as rex
        return rex.ConnectionError(
            "HTTPSConnectionPool(host='pve1', port=8006): Max retries exceeded "
            f"with url: /api2/json/nodes/pve1/qemu/{vmid}/status/current "
            "(Caused by NameResolutionError(\"Failed to resolve 'pve1'\"))")

    @pytest.mark.parametrize("vmid", [401, 403, 404])
    def test_dns_failure_with_vmid_in_url_is_network(self, vmid):
        result = from_exception(self._dns_error(vmid))
        assert isinstance(result, ProxmoxNetworkError)
        assert not isinstance(result, (ProxmoxAuthError, ProxmoxNotFoundError))

    def test_timeout_with_vmid_url_is_timeout(self):
        import requests.exceptions as rex
        exc = rex.ConnectTimeout(
            "Connection to pve1 timed out "
            "(url: /api2/json/nodes/pve1/qemu/401/status/current)")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxTimeoutError)

    def test_ssl_error_with_vmid_url_is_network(self):
        import requests.exceptions as rex
        exc = rex.SSLError(
            "certificate verify failed (url: /api2/json/nodes/pve1/qemu/404/...)")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxNetworkError)

    def test_connection_reset_with_vmid_url_is_network(self):
        import requests.exceptions as rex
        exc = rex.ConnectionError(
            "Connection aborted (url: /api2/json/nodes/pve1/qemu/403/config)")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxNetworkError)

    def test_chunked_encoding_error_is_network(self):
        import requests.exceptions as rex
        exc = rex.ChunkedEncodingError(
            "Connection broken (url: /api2/json/nodes/pve1/qemu/401/...)")
        result = from_exception(exc)
        assert isinstance(result, ProxmoxNetworkError)

    def test_unknown_transport_error_is_not_auth(self):
        import requests.exceptions as rex
        for unknown in (
            rex.TooManyRedirects(
                "exceeded 30 redirects (url: /api2/json/nodes/pve1/qemu/401/...)"),
            rex.RequestException(
                "generic transport failure (/qemu/404/...)"),
        ):
            result = from_exception(unknown)
            assert not isinstance(result, (ProxmoxAuthError,
                                           ProxmoxNotFoundError))

    @staticmethod
    def _http_error(status, text):
        import requests.exceptions as rex
        resp = type("R", (), {"status_code": status})()
        return rex.HTTPError(f"{status} Client Error: {text}", response=resp)

    @pytest.mark.parametrize("status,cls", [
        (401, ProxmoxAuthError),
        (404, ProxmoxNotFoundError),
        (504, ProxmoxTimeoutError),
        (500, ProxmoxApiError),
    ])
    def test_real_http_responses_keep_classes(self, status, cls):
        err = from_exception(self._http_error(status, "Unauthorized for url"))
        assert isinstance(err, cls)
        assert err.status_code == status

    def test_real_http_403_without_permission_text_is_auth(self):
        err = from_exception(self._http_error(403, "Forbidden"))
        assert isinstance(err, ProxmoxAuthError)
        assert err.status_code == 403

    def test_real_http_403_permission_text_is_permission(self):
        import requests.exceptions as rex
        resp = type("R", (), {"status_code": 403})()
        exc = rex.HTTPError(
            "403 Client Error: permission check failed (/vms/401)",
            response=resp)
        err = from_exception(exc)
        assert isinstance(err, ProxmoxPermissionError)

    def test_anchored_regex_rejects_bare_numbers(self):
        # non-requests exceptions: numbers without an HTTP anchor are not
        # statuses (a VMID in an arbitrary error text)
        assert not isinstance(from_exception(Exception("VM 401 status current")),
                              ProxmoxAuthError)
        assert isinstance(from_exception(Exception("VM 401 status current")),
                          ProxmoxApiError)

    def test_anchored_regex_still_recognizes_http_forms(self):
        assert isinstance(from_exception(Exception("HTTP 401 Unauthorized")),
                          ProxmoxAuthError)
        assert isinstance(from_exception(Exception("HTTP 404 Not Found")),
                          ProxmoxNotFoundError)
        assert isinstance(from_exception(Exception("404 Client Error: not found")),
                          ProxmoxNotFoundError)
        assert isinstance(from_exception(Exception("HTTP 403 Forbidden")),
                          ProxmoxAuthError)

    # -- parse_pve_error mirrors the anchoring (audit D4) --

    def test_parse_pve_error_dns_with_vmid_url_is_dns(self):
        from virtdeck.ui.utils import parse_pve_error

        msg = parse_pve_error(self._dns_error(401).__str__())
        assert msg == "Cannot resolve DNS name"

    def test_parse_pve_error_vmid_in_url_is_not_auth(self):
        from virtdeck.ui.utils import parse_pve_error

        err = ("Max retries exceeded with url: "
               "/api2/json/nodes/pve1/qemu/401/status/current")
        assert parse_pve_error(err) != "API token authorization error (401)"
        assert parse_pve_error(err) == err  # unchanged passthrough

    def test_parse_pve_error_real_401_still_auth(self):
        from virtdeck.ui.utils import parse_pve_error

        assert parse_pve_error("401 Client Error: Unauthorized for url: ...") == \
            "API token authorization error (401)"
        assert parse_pve_error("HTTP 401 Unauthorized") == \
            "API token authorization error (401)"

    def test_parse_pve_error_real_403_still_permission(self):
        from virtdeck.ui.utils import parse_pve_error

        assert parse_pve_error("HTTP 403 Forbidden") == "PVE permission denied (403)"

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

    # --- audit 6.3.2b D17: the int() conversion must stay inside the
    # typed error hierarchy (no raw ValueError/TypeError leaks) --------

    def test_next_vmid_int(self, mock_session):
        mock_session.proxmox.cluster.nextid.get = MagicMock(return_value=103)
        api = ClusterAPI(mock_session)
        assert api.next_vmid() == 103

    def test_next_vmid_none_is_api_error(self, mock_session):
        mock_session.proxmox.cluster.nextid.get = MagicMock(return_value=None)
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxApiError, match="nextid"):
            api.next_vmid()

    def test_next_vmid_empty_string_is_api_error(self, mock_session):
        mock_session.proxmox.cluster.nextid.get = MagicMock(return_value="")
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxApiError, match="nextid"):
            api.next_vmid()

    def test_next_vmid_garbage_string_is_api_error(self, mock_session):
        mock_session.proxmox.cluster.nextid.get = MagicMock(return_value="abc")
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxApiError, match="nextid"):
            api.next_vmid()

    def test_next_vmid_dict_without_data_is_api_error(self, mock_session):
        mock_session.proxmox.cluster.nextid.get = MagicMock(
            return_value={"unexpected": "shape"})
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxApiError, match="nextid"):
            api.next_vmid()

    def test_next_vmid_error_does_not_produce_an_id(self, mock_session):
        # a broken response must never be silently converted to a valid id
        mock_session.proxmox.cluster.nextid.get = MagicMock(return_value=None)
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxError):
            api.next_vmid()

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
        # 404/501 from /cluster/jobs = endpoint absent (PVE7) → legacy path
        mock_session.proxmox.cluster.jobs.get = MagicMock(
            side_effect=ProxmoxApiError("no jobs", status_code=404))
        mock_session.proxmox.cluster.backup.get = MagicMock(return_value=[{"id": "bk1"}])
        api = ClusterAPI(mock_session)
        result = api.list_all_jobs(pve_major=8)
        assert len(result) == 1
        mock_session.proxmox.cluster.backup.get.assert_called_once()

    def test_list_all_jobs_pve8_501_fallback(self, mock_session):
        mock_session.proxmox.cluster.jobs.get = MagicMock(
            side_effect=ProxmoxApiError("not implemented", status_code=501))
        mock_session.proxmox.cluster.backup.get = MagicMock(return_value=[])
        api = ClusterAPI(mock_session)
        assert api.list_all_jobs(pve_major=8) == []

    @pytest.mark.parametrize("exc", [
        ProxmoxApiError("storage error", status_code=500),
        ProxmoxTimeoutError("read timed out"),
        ProxmoxAuthError("401 ticket invalid"),
    ])
    def test_list_all_jobs_pve8_no_fallback_on_other_errors(self, mock_session, exc):
        # a read failure on /cluster/jobs must surface, not silently
        # degrade to a legacy listing (which could look like "no jobs")
        mock_session.proxmox.cluster.jobs.get = MagicMock(side_effect=exc)
        api = ClusterAPI(mock_session)
        with pytest.raises(type(exc)):
            api.list_all_jobs(pve_major=8)
        mock_session.proxmox.cluster.backup.get.assert_not_called()

    def test_list_all_jobs_pve7(self, mock_session):
        mock_session.proxmox.cluster.backup.get = MagicMock(return_value=[{"id": "bk1"}])
        api = ClusterAPI(mock_session)
        result = api.list_all_jobs(pve_major=7)
        assert len(result) == 1

    def test_create_backup_job_pve8(self, mock_session):
        mock_session.proxmox.cluster.jobs.get = MagicMock(return_value=[])
        mock_session.proxmox.cluster.jobs.post = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.create_backup_job({"storage": "local"}, pve_major=8)
        mock_session.proxmox.cluster.jobs.post.assert_called_once_with(
            storage="local", type="vzdump"
        )

    def test_create_backup_job_pve8_endpoint_absent(self, mock_session):
        # probe says PVE7 → legacy path, /cluster/jobs never written
        mock_session.proxmox.cluster.jobs.get = MagicMock(
            side_effect=ProxmoxApiError("no jobs", status_code=404))
        mock_session.proxmox.cluster.backup.post = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.create_backup_job({"storage": "local"}, pve_major=8)
        mock_session.proxmox.cluster.backup.post.assert_called_once_with(
            storage="local"
        )
        mock_session.proxmox.cluster.jobs.post.assert_not_called()

    def test_create_backup_job_pve8_timeout_not_retried(self, mock_session):
        # D3: a timed-out create may have been applied — never silently
        # repeat it on the legacy path (duplicate job)
        mock_session.proxmox.cluster.jobs.get = MagicMock(return_value=[])
        mock_session.proxmox.cluster.jobs.post = MagicMock(
            side_effect=ProxmoxTimeoutError("read timed out"))
        mock_session.proxmox.cluster.backup.post = MagicMock()
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxTimeoutError, match="may still have been applied"):
            api.create_backup_job({"storage": "local"}, pve_major=8)
        mock_session.proxmox.cluster.backup.post.assert_not_called()

    def test_create_backup_job_pve8_validation_not_masked(self, mock_session):
        # D3: a 400 must reach the user, not be swallowed by a legacy retry
        mock_session.proxmox.cluster.jobs.get = MagicMock(return_value=[])
        mock_session.proxmox.cluster.jobs.post = MagicMock(
            side_effect=ProxmoxApiError("storage 'x' does not exist",
                                        status_code=400))
        mock_session.proxmox.cluster.backup.post = MagicMock()
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxApiError, match="storage 'x'"):
            api.create_backup_job({"storage": "x"}, pve_major=8)
        mock_session.proxmox.cluster.backup.post.assert_not_called()

    def test_backup_job_probe_cached(self, mock_session):
        # the availability probe runs once per session, writes reuse it
        mock_session.proxmox.cluster.jobs.get = MagicMock(return_value=[])
        mock_session.proxmox.cluster.jobs.post = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.create_backup_job({"storage": "local"}, pve_major=8)
        api.create_backup_job({"storage": "local"}, pve_major=8)
        assert mock_session.proxmox.cluster.jobs.get.call_count == 1
        assert mock_session.proxmox.cluster.jobs.post.call_count == 2

    def test_delete_backup_job_pve8_timeout_not_retried(self, mock_session):
        # D3: a timed-out delete may have been applied — re-raised with an
        # explicit "outcome unknown" hint, no automatic retry
        mock_session.proxmox.cluster.jobs.get = MagicMock(return_value=[])
        chain_j = mock_session.proxmox.cluster.jobs
        chain_j.return_value.delete = MagicMock(
            side_effect=ProxmoxTimeoutError("read timed out"))
        chain_b = mock_session.proxmox.cluster.backup
        chain_b.return_value.delete = MagicMock()
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxTimeoutError, match="may still have been applied"):
            api.delete_backup_job("job1", pve_major=8)
        chain_b.return_value.delete.assert_not_called()

    def test_delete_backup_job_pve8_endpoint_absent(self, mock_session):
        # probe says PVE7 → legacy path decides BEFORE any write attempt
        mock_session.proxmox.cluster.jobs.get = MagicMock(
            side_effect=ProxmoxApiError("no jobs", status_code=404))
        chain_b = mock_session.proxmox.cluster.backup
        chain_b.return_value.delete = MagicMock(return_value=None)
        api = ClusterAPI(mock_session)
        api.delete_backup_job("job1", pve_major=8)
        chain_b.assert_called_with("job1")
        chain_b.return_value.delete.assert_called_once()

    def test_delete_backup_job_pve8_404_job_absent(self, mock_session):
        # on a live PVE8+ endpoint a 404 means the job is absent —
        # must be raised as-is, not masked by a legacy re-delete
        mock_session.proxmox.cluster.jobs.get = MagicMock(return_value=[])
        chain_j = mock_session.proxmox.cluster.jobs
        chain_j.return_value.delete = MagicMock(
            side_effect=ProxmoxApiError("no such job", status_code=404))
        chain_b = mock_session.proxmox.cluster.backup
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxApiError, match="no such job"):
            api.delete_backup_job("job1", pve_major=8)
        chain_b.return_value.delete.assert_not_called()

    def test_update_backup_job_pve8(self, mock_session):
        mock_session.proxmox.cluster.jobs.get = MagicMock(return_value=[])
        chain = mock_session.proxmox.cluster.jobs
        chain.return_value.put = MagicMock(return_value="OK")
        api = ClusterAPI(mock_session)
        api.update_backup_job("job1", {"id": "job1", "schedule": "02:00"},
                              pve_major=8)
        chain.assert_called_with("job1")
        chain.return_value.put.assert_called_once_with(
            schedule="02:00", type="vzdump"
        )

    def test_update_backup_job_pve8_timeout_not_retried(self, mock_session):
        mock_session.proxmox.cluster.jobs.get = MagicMock(return_value=[])
        chain = mock_session.proxmox.cluster.jobs
        chain.return_value.put = MagicMock(
            side_effect=ProxmoxTimeoutError("read timed out"))
        mock_session.proxmox.cluster.backup.return_value.put = MagicMock()
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxTimeoutError, match="may still have been applied"):
            api.update_backup_job("job1", {"schedule": "03:00"}, pve_major=8)
        mock_session.proxmox.cluster.backup.return_value.put.assert_not_called()

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

    # --- audit 6.3.2b D12: the legacy /cluster/backup path must mark
    # "outcome unknown" symmetric to the /cluster/jobs path -------------

    def test_create_backup_job_pve7_timeout_outcome_unknown(self, mock_session):
        mock_session.proxmox.cluster.backup.post = MagicMock(
            side_effect=ProxmoxTimeoutError("read timed out"))
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxTimeoutError,
                           match="may still have been applied"):
            api.create_backup_job({"storage": "local"}, pve_major=7)
        # no automatic retry: the POST was issued exactly once
        assert mock_session.proxmox.cluster.backup.post.call_count == 1

    def test_update_backup_job_pve7_timeout_outcome_unknown(self, mock_session):
        chain = mock_session.proxmox.cluster.backup
        chain.return_value.put = MagicMock(
            side_effect=ProxmoxTimeoutError("read timed out"))
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxTimeoutError,
                           match="may still have been applied"):
            api.update_backup_job("job1", {"schedule": "03:00"}, pve_major=7)
        assert chain.return_value.put.call_count == 1

    def test_delete_backup_job_pve7_timeout_outcome_unknown(self, mock_session):
        chain = mock_session.proxmox.cluster.backup
        chain.return_value.delete = MagicMock(
            side_effect=ProxmoxTimeoutError("read timed out"))
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxTimeoutError,
                           match="may still have been applied"):
            api.delete_backup_job("job1", pve_major=7)
        assert chain.return_value.delete.call_count == 1

    def test_create_backup_job_pve7_validation_not_masked(self, mock_session):
        # only timeouts are re-framed; a 400 reaches the user as-is
        mock_session.proxmox.cluster.backup.post = MagicMock(
            side_effect=ProxmoxApiError("storage 'x' does not exist",
                                        status_code=400))
        api = ClusterAPI(mock_session)
        with pytest.raises(ProxmoxApiError, match="storage 'x'"):
            api.create_backup_job({"storage": "x"}, pve_major=7)


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
        api.migrate("n1", 100, "qemu", "n2", with_local_disks=True)
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


class TestContentUrlEncoding:
    """URL construction for content delete/move — against the REAL proxmoxer.

    proxmoxer splits a resource-id string on "/" and inserts the parts raw
    into the URL (proxmoxer/core.py ProxmoxResource.__call__), so a volid
    like ``local:iso/debian-12.iso`` MUST be percent-encoded via ``_q()``
    before it goes into the resource chain — otherwise it breaks the API
    path into an extra segment and PVE answers 404.  Mock-based call
    assertions cannot catch this (a MagicMock accepts anything); only the
    real URL builder can.  No network: token auth defers login, and
    ``ProxmoxSession.call`` is intercepted before the verb fires.
    """

    @pytest.fixture()
    def url_capture(self, monkeypatch):
        """Real ProxmoxSession whose call() records the request URL."""
        session = ProxmoxSession({
            "host": "h.example", "user": "root@pam",
            "token_name": "t", "token_value": "v", "trust_ssl": True,
        })
        captured: dict = {}

        def fake_call(fn, **kwargs):
            captured["url"] = fn.__self__._store["base_url"]
            captured["kwargs"] = kwargs
            return "UPID:test"

        monkeypatch.setattr(session, "call", fake_call)
        return session, captured

    @staticmethod
    def _path(url: str) -> str:
        prefix = "https://h.example:8006/api2/json"
        assert url.startswith(prefix), url
        return url[len(prefix):]

    # -- delete_content --

    @pytest.mark.parametrize("volid", [
        "local:iso/debian-12.iso",
        "local:iso/deb+12 (1).iso",
        "local:iso/50%off (1).iso",
        "pbs:backup/vm/100/2026-01-01T00:00:00Z",
        "local-zfs:subvol-101-disk-0",  # no slash — must stay one segment
    ])
    def test_delete_content_volid_single_segment(self, url_capture, volid):
        session, captured = url_capture
        api = StorageAPI(session)
        api.delete_content("pve01", "local", volid)
        path = self._path(captured["url"])
        # exactly one segment after /content/, percent-encoded
        assert path.count("/content/") == 1, path
        tail = path.rsplit("/content/", 1)[1]
        assert "/" not in tail, f"volid broke the path: {path}"
        assert tail == _q(volid), path
        assert path == (f"/nodes/pve01/storage/local/content/{_q(volid)}")

    def test_delete_content_storage_encoded(self, url_capture):
        session, captured = url_capture
        api = StorageAPI(session)
        api.delete_content("pve01", "my storage", "local:iso/x.iso")
        assert self._path(captured["url"]).startswith(
            "/nodes/pve01/storage/my%20storage/content/")

    # -- move_content --

    def test_move_content_volid_single_segment(self, url_capture):
        session, captured = url_capture
        api = StorageAPI(session)
        api.move_content("pve01", "local", "local:iso/debian-12.iso",
                         "nfs1", target_vmid=100, delete_source=True)
        path = self._path(captured["url"])
        tail = path.rsplit("/content/", 1)[1]
        assert "/" not in tail, f"volid broke the path: {path}"
        assert tail == _q("local:iso/debian-12.iso"), path
        # form params passed untouched (requests encodes them)
        assert captured["kwargs"] == {
            "target_storage": "nfs1", "target_vmid": 100, "delete": 1,
        }

    def test_move_content_form_params_untouched(self, url_capture):
        session, captured = url_capture
        api = StorageAPI(session)
        api.move_content("pve01", "local", "local:iso/x.iso", "nfs1")
        assert captured["kwargs"] == {"target_storage": "nfs1"}


class TestStorageUploadErrors:
    """D4: upload_file failures must be classified ProxmoxApiError with the
    HTTP status preserved, and parsing must never raise by itself."""

    @pytest.fixture()
    def api(self):
        session = ProxmoxSession({
            "host": "h.example", "user": "root@pam",
            "token_name": "t", "token_value": "v", "trust_ssl": True,
        })
        return StorageAPI(session)

    @staticmethod
    def _fake_post(resp):
        return MagicMock(return_value=resp)

    @staticmethod
    def _resp(ok=True, status=200, body=None, text="", reason=None):
        r = SimpleNamespace(ok=ok, status_code=status, text=text,
                            reason=reason)
        if body is None:
            r.json = MagicMock(side_effect=ValueError("no json"))
        else:
            r.json = MagicMock(return_value=body)
        return r

    def _upload(self, api, monkeypatch, resp=None, exc=None, tmp_path=None):
        import requests as requests_mod
        f = tmp_path / "test.iso"
        f.write_bytes(b"x" * 1024)
        if exc is not None:
            monkeypatch.setattr(requests_mod, "post",
                                MagicMock(side_effect=exc))
        else:
            monkeypatch.setattr(requests_mod, "post",
                                self._fake_post(resp))
        return api.upload_file("n1", "local", "iso", str(f))

    # -- error classification --

    def test_401_classified(self, api, monkeypatch, tmp_path):
        resp = self._resp(ok=False, status=401,
                          body={"data": {"message": "ticket invalid"}})
        with pytest.raises(ProxmoxApiError) as ei:
            self._upload(api, monkeypatch, resp, tmp_path=tmp_path)
        assert ei.value.status_code == 401
        assert "ticket invalid" in str(ei.value)

    def test_403_classified(self, api, monkeypatch, tmp_path):
        resp = self._resp(ok=False, status=403,
                          body={"data": {"message": "permission check failed"}})
        with pytest.raises(ProxmoxApiError) as ei:
            self._upload(api, monkeypatch, resp, tmp_path=tmp_path)
        assert ei.value.status_code == 403
        assert "permission" in str(ei.value)

    def test_413_classified(self, api, monkeypatch, tmp_path):
        resp = self._resp(ok=False, status=413,
                          body={"data": {"message": "file too large"}})
        with pytest.raises(ProxmoxApiError) as ei:
            self._upload(api, monkeypatch, resp, tmp_path=tmp_path)
        assert ei.value.status_code == 413

    def test_500_invalid_json_body(self, api, monkeypatch, tmp_path):
        # pveproxy-style HTML/plain error: no JSON — fall back to
        # reason/body snippet without raising during parsing
        resp = self._resp(ok=False, status=500, body=None,
                          text="<html>oops</html>", reason="Internal Error")
        with pytest.raises(ProxmoxApiError) as ei:
            self._upload(api, monkeypatch, resp, tmp_path=tmp_path)
        assert ei.value.status_code == 500
        assert "Internal Error" in str(ei.value)

    def test_599_anyevent_hint(self, api, monkeypatch, tmp_path):
        resp = self._resp(ok=False, status=599, body=None,
                          text="garbled", reason=None)
        with pytest.raises(ProxmoxApiError) as ei:
            self._upload(api, monkeypatch, resp, tmp_path=tmp_path)
        assert ei.value.status_code == 599
        assert "pveproxy" in str(ei.value)

    def test_network_error_classified(self, api, monkeypatch, tmp_path):
        import requests as requests_mod
        with pytest.raises(ProxmoxTimeoutError):
            self._upload(api, monkeypatch, exc=requests_mod.exceptions.ConnectTimeout(
                "Read timed out. (read timeout=300)"), tmp_path=tmp_path)

    # -- success paths --

    def test_success_returns_upid(self, api, monkeypatch, tmp_path):
        resp = self._resp(ok=True, status=200, body={"data": "UPID:n1:1"})
        upid = self._upload(api, monkeypatch, resp, tmp_path=tmp_path)
        assert upid == "UPID:n1:1"

    def test_success_invalid_json_no_crash(self, api, monkeypatch, tmp_path):
        resp = self._resp(ok=True, status=200, body=None, text="junk")
        with pytest.raises(ProxmoxApiError, match="not valid JSON"):
            self._upload(api, monkeypatch, resp, tmp_path=tmp_path)

    def test_success_non_dict_json_no_crash(self, api, monkeypatch, tmp_path):
        resp = self._resp(ok=True, status=200, body=["unexpected"])
        with pytest.raises(ProxmoxApiError, match="unexpected upload response"):
            self._upload(api, monkeypatch, resp, tmp_path=tmp_path)

    def test_read_capped_no_whole_file_in_ram(self, api, monkeypatch, tmp_path):
        # D4/R5: a read(-1) caller must not pull the whole file into memory
        import requests as requests_mod
        f = tmp_path / "big.iso"
        f.write_bytes(b"\0" * (1024 * 1024))
        sizes = []

        def reading_post(url, **kwargs):
            wrapper = kwargs["files"]["filename"][1]
            while True:
                chunk = wrapper.read(-1)
                if not chunk:
                    break
                sizes.append(len(chunk))
            return self._resp(ok=True, status=200, body={"data": "UPID:x"})

        monkeypatch.setattr(requests_mod, "post", reading_post)
        upid = api.upload_file("n1", "local", "iso", str(f))
        assert upid == "UPID:x"
        assert sizes and max(sizes) <= 262144
        assert sum(sizes) == 1024 * 1024  # the file is streamed fully


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

    def test_poll_transient_error_tolerated(self, mock_session):
        # D2: one network blip mid-poll must not fail the operation —
        # the task completed fine on the server
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        tasks_chain.return_value.status.get = MagicMock(side_effect=[
            {"data": {"status": "running"}},
            ProxmoxNetworkError("connection reset by peer"),
            {"data": {"status": "stopped", "exitstatus": "OK"}},
        ])
        api = TaskAPI(mock_session)
        status, exitstatus = api.poll("n1", "UPID:123", timeout=5, interval=0.01)
        assert (status, exitstatus) == ("stopped", "OK")

    def test_poll_budget_exhausted_poll_failed(self, mock_session):
        # 4 consecutive transport failures with budget 3 → outcome UNKNOWN
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        tasks_chain.return_value.status.get = MagicMock(
            side_effect=ProxmoxNetworkError("connection reset by peer"))
        api = TaskAPI(mock_session)
        status, detail = api.poll("n1", "UPID:123", timeout=5, interval=0.01)
        assert status == "poll_failed"
        assert "connection reset" in detail
        # all reads attempted (not a fast bail-out), none succeeded
        assert tasks_chain.return_value.status.get.call_count == 4

    def test_poll_success_resets_budget(self, mock_session):
        # alternating error/success never exhausts the consecutive budget
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        err = ProxmoxNetworkError("blip")
        tasks_chain.return_value.status.get = MagicMock(side_effect=[
            {"data": {"status": "running"}},
            err,
            {"data": {"status": "running"}},
            err,
            {"data": {"status": "stopped", "exitstatus": "OK"}},
        ])
        api = TaskAPI(mock_session)
        status, exitstatus = api.poll("n1", "UPID:123", timeout=5, interval=0.01)
        assert (status, exitstatus) == ("stopped", "OK")

    def test_poll_nontransport_fails_fast(self, mock_session):
        # auth/permission errors cannot heal — fail immediately, no budget
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        tasks_chain.return_value.status.get = MagicMock(
            side_effect=ProxmoxAuthError("401 ticket invalid"))
        api = TaskAPI(mock_session)
        status, detail = api.poll("n1", "UPID:123", timeout=5, interval=0.01)
        assert status == "poll_failed"
        assert "401" in detail
        assert tasks_chain.return_value.status.get.call_count == 1

    def test_poll_empty_payloads_poll_failed(self, mock_session):
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        tasks_chain.return_value.status.get = MagicMock(return_value={})
        api = TaskAPI(mock_session)
        status, detail = api.poll("n1", "UPID:123", timeout=5, interval=0.01,
                                  max_poll_failures=2)
        assert status == "poll_failed"
        assert "empty" in detail

    def test_poll_task_failure_distinct_from_poll_failure(self, mock_session):
        # a FAILED task is a definite result, not an unknown outcome
        chain = mock_session.proxmox.nodes
        tasks_chain = chain.return_value.tasks
        tasks_chain.return_value.status.get = MagicMock(
            return_value={"data": {"status": "stopped",
                                   "exitstatus": "TASK ERROR: volume full"}})
        api = TaskAPI(mock_session)
        status, detail = api.poll("n1", "UPID:123", timeout=5, interval=0.01)
        assert status == "stopped"
        assert detail == "TASK ERROR: volume full"


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
