"""M4.0: record/replay — фиксстуры-контракты PVE API.

Запись: реальные ответы (в CI — сцена FakePveApi, на машине с кластером —
RecordingAdapter) сохраняются в JSON-фикстуру. Replay: тот же
ProxmoxProvider обслуживается из фиксстуры — контракт живого API
замораживается в репозитории. Совпадение entry — по (method, path,
params): параметры входят в ключ.
"""

from __future__ import annotations

import json

import pytest

from tests.harness import (
    fake_pve_cfg,
    install_fake_pve,
    install_replay_pve,
    load_fixture,
    save_fixture,
)
from tests.harness.scenarios import make_pve_cluster
from virtdeck.provider import ProxmoxError, ProxmoxProvider


def _drive(provider) -> tuple:
    """Дороги, которые Fleet Health (M4.1–M4.3) будет фиксировать."""
    return (
        provider.cluster.list_backup_jobs(),
        provider.nodes.get_version("pve01"),
        provider.vms.list_snapshots("pve01", 101, "qemu"),
        provider.rrd.get_storage_rrddata("pve01", "local", timeframe="day"),
    )


def test_record_then_replay_roundtrip(tmp_path, monkeypatch):
    api = make_pve_cluster("alpha")
    entries: list[dict] = []
    install_fake_pve(monkeypatch, api, record_into=entries)
    with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
        live = _drive(provider)
    assert entries[0]["path"] == "/cluster/backup"
    assert len(entries) >= 4

    fixture = tmp_path / "alpha.json"
    save_fixture(fixture, entries, host="alpha",
                 recorded_at="2026-10-07T12:00:00+00:00")
    loaded = load_fixture(fixture)
    assert len(loaded) == len(entries)
    assert loaded == entries

    install_replay_pve(monkeypatch, loaded)
    with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
        replayed = _drive(provider)
    assert replayed == live


def test_replay_miss_on_unknown_path(monkeypatch):
    install_replay_pve(monkeypatch, [])
    with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
        with pytest.raises(ProxmoxError, match="replay miss"):
            provider.cluster.list_backup_jobs()


def test_replay_is_param_sensitive(monkeypatch):
    """rrddata с другим timeframe — другой ключ entry, а не чужой ответ."""
    entries = [{"method": "GET", "path": "/nodes/pve01/rrddata",
                "params": {"timeframe": "hour", "cf": "AVERAGE"},
                "status": 200, "data": []}]
    install_replay_pve(monkeypatch, entries)
    with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
        with pytest.raises(ProxmoxError, match="replay miss"):
            provider.rrd.get_node_rrddata("pve01", timeframe="day")


def test_fixture_format_shape(tmp_path):
    entries = [{"method": "GET", "path": "/nodes", "params": {},
                "status": 200, "data": []}]
    fixture = tmp_path / "f.json"
    save_fixture(fixture, entries, host="pve1.corp",
                 recorded_at="2026-10-07T00:00:00+00:00")
    doc = json.loads(fixture.read_text(encoding="utf-8"))
    assert doc["kind"] == "virtdeck-recording"
    assert doc["version"] == 1
    assert doc["host"] == "pve1.corp"
    assert doc["entries"] == entries

    bad = tmp_path / "bad.json"
    bad.write_text('{"kind": "other"}', encoding="utf-8")
    with pytest.raises(ValueError, match="virtdeck-recording"):
        load_fixture(bad)
