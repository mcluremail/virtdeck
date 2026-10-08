"""Regression from the 2026-09-09 audit: UI raw workers must build their
requests session via build_requests_session — otherwise per-host proxies
from cfg are ignored and in a proxy-only environment raw requests time out."""
from __future__ import annotations

from virtdeck.provider._session import build_requests_session


def test_explicit_proxy_sets_proxies_and_disables_env():
    s = build_requests_session({"proxy": "http://10.0.0.9:3128"})
    try:
        assert s.trust_env is False
        assert s.proxies["http"] == "http://10.0.0.9:3128"
        assert s.proxies["https"] == "http://10.0.0.9:3128"
    finally:
        s.close()


def test_empty_proxy_keeps_env_behaviour():
    s = build_requests_session({"proxy": ""})
    try:
        assert s.trust_env is True
        assert not s.proxies
    finally:
        s.close()


def test_missing_proxy_key_keeps_env_behaviour():
    s = build_requests_session({})
    try:
        assert s.trust_env is True
        assert not s.proxies
    finally:
        s.close()


def test_metrics_workers_use_factory(monkeypatch):
    """All metrics.py raw workers must build the session via the factory,
    not a bare requests.Session()."""
    from virtdeck.ui.api import metrics as m

    calls = []

    class _Resp:
        ok = True
        status_code = 200
        reason = "OK"

        def json(self):
            return {"data": []}

    class _Sess:
        verify = None

        def get(self, *a, **kw):
            return _Resp()

        def close(self):
            pass

    def _fake_build(cfg):
        calls.append(cfg)
        return _Sess()

    monkeypatch.setattr(m, "build_requests_session", _fake_build)

    cfg = {"host": "10.0.0.1", "proxy": "http://p:1", "user": "u@pam",
           "token_name": "t", "token_value": "s"}
    from types import SimpleNamespace

    vm = SimpleNamespace(vmid=100, node="n1", name="vm100", vm_type=SimpleNamespace(value="qemu"))
    workers = [
        m.StorageContentListWorker(cfg, "n1", "st", "iso"),
        m.StorageBackupWorker(cfg, "n1", "st"),
        m.HostNetworkWorker(cfg, "n1"),
        m.HostServicesWorker(cfg, "n1"),
        m.HostDisksWorker(cfg, "n1"),
        m.HostSnapshotsWorker(cfg, "n1", [vm]),
        m.StorageDisksWorker(cfg, "n1", "st", [vm]),
        m.HealthCheckWorker(cfg, "n1"),
    ]
    for w in workers:
        try:
            w.run()
        except Exception:
            pass

    assert len(calls) == len(workers)
    assert all(c is cfg for c in calls)
