"""Tests for virtdeck.pbs.client — ticket auth, endpoints, error paths."""
from __future__ import annotations

import pytest
import requests

from virtdeck.pbs.client import PBS_PORT, PbsClient, PbsError

_CFG = {
    "name": "pbs1", "type": "pbs", "host": "pbs.local",
    "port": 8007, "user": "root@pam", "token_value": "secret",
}


class FakeResponse:
    def __init__(self, status_code=200, data=None, errors=None, raw=None):
        self.status_code = status_code
        self._data = data
        self._errors = errors
        self._raw = raw

    def json(self):
        if self._raw is not None:
            raise ValueError("no json")
        body = {}
        if self._data is not None:
            body["data"] = self._data
        if self._errors is not None:
            body["errors"] = self._errors
        return body


class FakeSession:
    """Scripted requests.Session replacement."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.verify = True
        self.calls = []  # (method, url, kwargs)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


def make_client(session, cfg=None):
    c = PbsClient(cfg or _CFG)
    c._http = session
    return c


def ticket_response():
    return FakeResponse(200, data={
        "ticket": "TICKET", "CSRFPreventionToken": "CSRF",
    })


class TestAuth:
    def test_login_success(self):
        s = FakeSession([ticket_response()])
        c = make_client(s)
        c.login()
        method, url, kwargs = s.calls[0]
        assert url == f"https://pbs.local:{PBS_PORT}/api2/json/access/ticket"
        assert kwargs["data"] == {"username": "root@pam", "password": "secret"}
        assert c._ticket == "TICKET"
        assert c._csrf == "CSRF"

    def test_login_bad_credentials(self):
        s = FakeSession([FakeResponse(401)])
        c = make_client(s)
        with pytest.raises(PbsError, match="auth failed"):
            c.login()
        assert c._ticket == ""

    def test_request_login_on_demand(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data=[1])])
        c = make_client(s)
        assert c.get("/version") == [1]
        assert len(s.calls) == 2
        # second request reuses the ticket — no extra login
        s.responses.append(FakeResponse(200, data={"a": 1}))
        assert c.get("/version") == {"a": 1}
        assert len(s.calls) == 3

    def test_relogin_once_on_401(self):
        s = FakeSession([
            ticket_response(),
            FakeResponse(401),
            ticket_response(),
            FakeResponse(200, data="ok"),
        ])
        c = make_client(s)
        assert c.get("/version") == "ok"

    def test_401_twice_raises(self):
        s = FakeSession([
            ticket_response(),
            FakeResponse(401),
            ticket_response(),
            FakeResponse(401),
        ])
        c = make_client(s)
        with pytest.raises(PbsError, match="401"):
            c.get("/version")

    def test_headers_and_cookies(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data={})])
        c = make_client(s)
        c.post("/admin/sync/j1/run")
        method, url, kwargs = s.calls[1]
        assert method == "POST"
        assert kwargs["headers"] == {"CSRFPreventionToken": "CSRF"}
        assert kwargs["cookies"] == {"PBSAuthCookie": "TICKET"}

    def test_trust_ssl_disables_verify(self):
        c = PbsClient({**_CFG, "trust_ssl": True})
        assert c._http.verify is False

    # --- audit 6.3.2b D11: non-JSON body on HTTP 200 must not leak a
    # raw ValueError through the login contract -------------------------

    def test_login_html_body_raises_pbs_error(self):
        s = FakeSession([FakeResponse(200, raw="<html>gateway error</html>")])
        c = make_client(s)
        with pytest.raises(PbsError, match="auth failed") as exc:
            c.login()
        assert exc.value.status_code == 200

    def test_login_invalid_json_raises_pbs_error(self):
        s = FakeSession([FakeResponse(200, raw="{broken json")])
        c = make_client(s)
        with pytest.raises(PbsError, match="auth failed"):
            c.login()

    def test_login_non_dict_json_raises_pbs_error(self):
        # valid JSON that is not an object must not leak AttributeError
        class _ListResponse:
            status_code = 200

            def json(self):
                return ["unexpected"]

        s = FakeSession([_ListResponse()])
        c = make_client(s)
        with pytest.raises(PbsError, match="auth failed"):
            c.login()

    def test_login_empty_body_is_controlled_no_ticket(self):
        # 200 with an empty JSON object: the contract error is the
        # existing "no ticket" case, not an exception type mismatch
        s = FakeSession([FakeResponse(200)])
        c = make_client(s)
        with pytest.raises(PbsError, match="no ticket"):
            c.login()

    def test_login_parse_error_message_has_no_secrets(self):
        s = FakeSession([FakeResponse(200, raw="<html>gateway</html>")])
        c = make_client(s)
        with pytest.raises(PbsError) as exc:
            c.login()
        text = str(exc.value)
        assert "gateway" not in text      # no raw response body
        assert "secret" not in text        # no credentials
        assert "root@pam" not in text
        assert "TICKET" not in text


class TestEndpoints:
    def test_datastores(self):
        s = FakeSession([
            ticket_response(),
            FakeResponse(200, data=[{"store": "main", "path": "/d"}]),
        ])
        c = make_client(s)
        assert c.datastores() == [{"store": "main", "path": "/d"}]
        assert s.calls[1][1].endswith("/config/datastore")

    def test_datastore_status_encodes_name(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data={})])
        c = make_client(s)
        c.datastore_status("my store")
        assert "/admin/datastore/my%20store/status" in s.calls[1][1]

    def test_snapshots_with_ns(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data=[])])
        c = make_client(s)
        c.snapshots("main", ns="t1")
        assert s.calls[1][2]["params"] == {"ns": "t1"}

    def test_snapshots_without_ns(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data=[])])
        c = make_client(s)
        c.snapshots("main")
        assert s.calls[1][2]["params"] is None

    def test_namespaces_parent_param(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data=[])])
        c = make_client(s)
        c.namespaces("main", parent="base")
        assert s.calls[1][2]["params"] == {"parent": "base"}

    def test_jobs_kind_validation(self):
        c = PbsClient(_CFG)
        with pytest.raises(ValueError):
            c.jobs("bogus")

    def test_jobs_endpoint(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data=[])])
        c = make_client(s)
        c.jobs("sync")
        assert s.calls[1][1].endswith("/admin/sync")

    def test_run_job_returns_upid(self):
        s = FakeSession([ticket_response(),
                         FakeResponse(200, data="UPID:abc")])
        c = make_client(s)
        assert c.run_job("verify", "v1") == "UPID:abc"
        assert s.calls[1][1].endswith("/admin/verify/v1/run")

    def test_verify_datastore(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data="UPID:v")])
        c = make_client(s)
        assert c.verify_datastore("main") == "UPID:v"
        assert s.calls[1][1].endswith("/admin/datastore/main/verify")

    def test_forget_snapshot_params(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data=None)])
        c = make_client(s)
        c.forget_snapshot("main", "vm", "100", 1700000000, ns="t1")
        method, url, kwargs = s.calls[1]
        assert method == "DELETE"
        assert kwargs["params"] == {
            "backup-type": "vm", "backup-id": "100",
            "backup-time": "1700000000", "ns": "t1",
        }

    def test_forget_snapshot_no_ns(self):
        s = FakeSession([ticket_response(), FakeResponse(200, data=None)])
        c = make_client(s)
        c.forget_snapshot("main", "vm", "100", 1700000000)
        assert "ns" not in s.calls[1][2]["params"]

    def test_error_response_raises(self):
        s = FakeSession([
            ticket_response(),
            FakeResponse(400, errors={"param": "bad"}),
        ])
        c = make_client(s)
        with pytest.raises(PbsError, match="HTTP 400"):
            c.get("/config/datastore")


class TestConnectionErrors:
    def test_timeout(self, monkeypatch):
        import requests as real_requests

        class TimeoutSession(FakeSession):
            def post(self, url, **kwargs):
                raise real_requests.exceptions.Timeout("too slow")

        c = make_client(TimeoutSession())
        with pytest.raises(PbsError, match="timeout"):
            c.login()

    def test_connection_error(self, monkeypatch):
        import requests as real_requests

        class DeadSession(FakeSession):
            def post(self, url, **kwargs):
                raise real_requests.exceptions.ConnectionError("refused")

        c = make_client(DeadSession())
        with pytest.raises(PbsError, match="connection failed"):
            c.login()

    def test_non_json_response(self):
        s = FakeSession([ticket_response(), FakeResponse(200, raw="<html>")])
        c = make_client(s)
        assert c.get("/version") is None


# ── audit 6.3.3 D16: honest task start + task status tracking ──────────


def _with_ticket(c):
    c._ticket = "TICKET"
    c._csrf = "CSRF"
    return c


class TestTaskStart:
    """run_job/verify_datastore: HTTP 200 alone is not a confirmed start."""

    def test_run_job_confirmed_upid(self):
        s = FakeSession([FakeResponse(200, data="UPID:pbs:1:2:3:syncjob:j1:root@pam")])
        c = _with_ticket(make_client(s))
        assert c.run_job("sync", "j1") == "UPID:pbs:1:2:3:syncjob:j1:root@pam"

    def test_run_job_null_data_is_outcome_unknown(self):
        # degraded 200 (data:null): the server may have accepted the
        # request — this must never read as "job started"
        s = FakeSession([FakeResponse(200, data=None)])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="outcome unknown") as exc:
            c.run_job("sync", "j1")
        assert exc.value.status_code == 200
        assert "check the task list" in str(exc.value)

    def test_run_job_empty_upid_is_outcome_unknown(self):
        s = FakeSession([FakeResponse(200, data="")])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="outcome unknown"):
            c.run_job("sync", "j1")

    def test_run_job_non_string_data_is_outcome_unknown(self):
        s = FakeSession([FakeResponse(200, data=42)])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="outcome unknown"):
            c.run_job("sync", "j1")

    def test_run_job_transport_failure_is_outcome_unknown_no_retry(self):
        # the request was sent (or may have been) — the outcome is
        # unknown and the start is never repeated automatically
        s = FakeSession([requests.exceptions.Timeout("too slow")])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="outcome unknown") as exc:
            c.run_job("sync", "j1")
        assert exc.value.status_code == 0
        start_calls = [m for m, _u, _k in s.calls if m == "POST"
                       and "/run" in _u]
        assert len(start_calls) == 1  # no automatic retry

    def test_run_job_auth_failure_is_definitive_not_unknown(self):
        # 401 after relogin: the request was never executed — a plain
        # auth error, not an "outcome unknown"
        s = FakeSession([FakeResponse(401), FakeResponse(401)])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="auth failed") as exc:
            c.run_job("sync", "j1")
        assert exc.value.status_code == 401
        assert "outcome unknown" not in str(exc.value)

    def test_verify_datastore_confirmed_upid(self):
        s = FakeSession([FakeResponse(200, data="UPID:pbs:1:2:3:verificationjob:main:root@pam")])
        c = _with_ticket(make_client(s))
        assert c.verify_datastore("main").startswith("UPID:")

    def test_verify_datastore_null_data_is_outcome_unknown(self):
        s = FakeSession([FakeResponse(200, data=None)])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="outcome unknown"):
            c.verify_datastore("main")

    def test_start_error_has_no_secrets_or_raw_body(self):
        s = FakeSession([FakeResponse(200, raw="<html>gateway</html>")])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError) as exc:
            c.run_job("sync", "j1")
        text = str(exc.value)
        assert "gateway" not in text
        assert "secret" not in text

    def test_run_job_upid_url_encoded(self):
        s = FakeSession([FakeResponse(200, data="UPID:x")])
        c = _with_ticket(make_client(s))
        c.run_job("sync", "weird id/1")
        method, url, _k = s.calls[-1]
        assert method == "POST"
        assert "/admin/sync/weird%20id%2F1/run" in url


class TestTaskStatus:
    """GET /nodes/{node}/tasks/{upid}/status (PBS tasks.rs: status is
    'running'|'stopped', stopped tasks carry exitstatus
    'OK' / 'Error: <msg>' / 'unknown')."""

    def test_running_status(self):
        s = FakeSession([FakeResponse(200, data={"status": "running"})])
        c = _with_ticket(make_client(s))
        assert c.task_status("pbs1", "UPID:x") == {"status": "running"}

    def test_upid_url_encoded(self):
        # colons and slashes must not break the path
        s = FakeSession([FakeResponse(200, data={"status": "running"})])
        c = _with_ticket(make_client(s))
        c.task_status("pbs1", "UPID:pbs:1:2:3:syncjob:weird/id:root@pam")
        _m, url, _k = s.calls[-1]
        assert "/nodes/pbs1/tasks/UPID%3Apbs%3A1%3A2%3A3%3Asyncjob%3A" \
            "weird%2Fid%3Aroot%40pam/status" in url

    def test_non_dict_response_raises(self):
        s = FakeSession([FakeResponse(200, data=None)])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="unexpected task status"):
            c.task_status("pbs1", "UPID:x")

    def test_auth_error_propagates_with_status(self):
        s = FakeSession([FakeResponse(403)])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError) as exc:
            c.task_status("pbs1", "UPID:x")
        assert exc.value.status_code == 403

    def test_transport_error_propagates(self):
        s = FakeSession([requests.exceptions.ConnectionError("refused")])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="connection failed"):
            c.task_status("pbs1", "UPID:x")


class TestNodeName:
    def test_node_name_from_nodes_list(self):
        s = FakeSession([FakeResponse(200, data=[{"name": "pbs1"}])])
        c = _with_ticket(make_client(s))
        assert c.node_name() == "pbs1"
        # cached: no second HTTP call
        c.node_name()
        assert len(s.calls) == 1

    def test_node_name_skips_malformed_entries(self):
        s = FakeSession([FakeResponse(200, data=[{"nope": 1}, {"name": "pbs1"}])])
        c = _with_ticket(make_client(s))
        assert c.node_name() == "pbs1"

    def test_node_name_empty_list_raises(self):
        s = FakeSession([FakeResponse(200, data=[])])
        c = _with_ticket(make_client(s))
        with pytest.raises(PbsError, match="node name"):
            c.node_name()

    def test_forget_node_invalidates_cache(self):
        s = FakeSession([
            FakeResponse(200, data=[{"name": "pbs1"}]),
            FakeResponse(200, data=[{"name": "pbs2"}]),
        ])
        c = _with_ticket(make_client(s))
        assert c.node_name() == "pbs1"
        c.forget_node()
        assert c.node_name() == "pbs2"
