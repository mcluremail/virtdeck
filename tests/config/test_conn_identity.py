"""Stage 5.1.2: connection identity (conn_id), name normalization,
ambiguous legacy conflicts and the identity-aware import contract."""

from __future__ import annotations

import json
import sqlite3
import uuid

import pytest

from virtdeck import config


def _cfg(name, host, user="root@pam", **extra):
    cfg = {"name": name, "host": host, "user": user,
           "token_name": f"t-{name}", "token_value": f"secret-{name}"}
    cfg.update(extra)
    return cfg


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setattr(config, "_config_dir", lambda: str(d))
    return d


@pytest.fixture
def mem_keyring(monkeypatch):
    """In-memory keyring replacement covering get/set/delete."""
    store: dict[str, str] = {}

    class _KR:
        def get_password(self, service, key):
            return store.get(f"{service}/{key}")

        def set_password(self, service, key, value):
            store[f"{service}/{key}"] = value

        def delete_password(self, service, key):
            store.pop(f"{service}/{key}", None)

    monkeypatch.setattr(config, "_get_keyring", lambda: _KR())
    return store


@pytest.fixture(autouse=True)
def _reset_pending():
    """Isolate the module-level conn_ids_pending flag between tests."""
    yield
    config._conn_ids_pending = False


# --- 1. conn_id migration at load ----------------------------------------


def test_load_assigns_and_persists_conn_id(cfg_dir, mem_keyring):
    config.save_config([_cfg("h1", "10.0.0.1")])
    # simulate a pre-5.1 database row: strip the id from the stored JSON
    conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
    (raw,) = conn.execute("SELECT data FROM nodes WHERE name='h1'").fetchone()
    data = json.loads(raw)
    data.pop("conn_id")
    conn.execute("UPDATE nodes SET data=? WHERE name='h1'",
                 (json.dumps(data),))
    conn.commit()
    conn.close()

    loaded = config.load_config()
    cid = loaded[0]["conn_id"]
    assert cid and len(cid) == 32

    # the assigned id is persisted: the next load returns the SAME id
    assert [c["conn_id"] for c in config.load_config()] == [cid]


def test_load_preserves_existing_conn_id(cfg_dir, mem_keyring):
    config.save_config([_cfg("h1", "10.0.0.1", conn_id="fixed-id")])
    loaded = config.load_config()
    assert loaded[0]["conn_id"] == "fixed-id"


def test_migration_write_is_idempotent(cfg_dir, mem_keyring):
    """A load without missing ids performs no writes (mtime-stable rows)."""
    config.save_config([_cfg("h1", "10.0.0.1"), _cfg("h2", "10.0.0.2")])
    conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
    before = dict(conn.execute("SELECT name, data FROM nodes").fetchall())
    conn.close()
    config.load_config()
    conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
    after = dict(conn.execute("SELECT name, data FROM nodes").fetchall())
    conn.close()
    assert before == after


def test_migration_does_not_touch_tokens(cfg_dir, mem_keyring, monkeypatch):
    """The migration write must never rewrite keyring secrets."""
    config.save_config([_cfg("h1", "10.0.0.1")])
    conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
    (raw,) = conn.execute("SELECT data FROM nodes WHERE name='h1'").fetchone()
    data = json.loads(raw)
    data.pop("conn_id")
    conn.execute("UPDATE nodes SET data=? WHERE name='h1'",
                 (json.dumps(data),))
    conn.commit()
    conn.close()

    writes = []
    monkeypatch.setattr(config, "_save_token",
                        lambda name, value: writes.append(name))
    config.load_config()
    assert writes == []
    assert config.load_config()[0]["token_value"] == "secret-h1"


def test_persist_failure_sets_pending_and_blocks_cache(cfg_dir, mem_keyring,
                                                      monkeypatch):
    """When the migration write fails, ids stay in memory and the
    resource cache is blocked until a successful save anchors them."""
    config.save_config([_cfg("h1", "10.0.0.1")])
    conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
    (raw,) = conn.execute("SELECT data FROM nodes WHERE name='h1'").fetchone()
    data = json.loads(raw)
    data.pop("conn_id")
    conn.execute("UPDATE nodes SET data=? WHERE name='h1'",
                 (json.dumps(data),))
    conn.commit()
    conn.close()

    class _BrokenConn:
        """Fails every write but serves reads (simulates a locked db)."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a, **kw):
            if sql.lstrip().upper().startswith("SELECT"):
                return self._real.execute(sql, *a, **kw)
            raise sqlite3.OperationalError("db is locked")

        def commit(self):
            return self._real.commit()

        def rollback(self):
            return self._real.rollback()

        def close(self):
            return self._real.close()

    real_init = config._init_db
    monkeypatch.setattr(config, "_init_db", lambda: _BrokenConn(real_init()))
    loaded = config.load_config()
    monkeypatch.setattr(config, "_init_db", real_init)
    assert loaded[0]["conn_id"]
    assert config.conn_ids_pending() is True

    # cache writes are a no-op while the ids are not anchored
    config.save_resources_cache(
        nodes=[{"host_name": "h1", "node": "pve1", "status": "online",
                "conn_id": loaded[0]["conn_id"]}],
        vms=[], storages=[])
    # the write was skipped entirely: no cache row exists
    assert config.load_resources_cache() == (None, None)

    # a successful save_config anchors the ids and unblocks the cache
    config.save_config(loaded)
    assert config.conn_ids_pending() is False
    config.save_resources_cache(
        nodes=[{"host_name": "h1", "node": "pve1", "status": "online",
                "conn_id": loaded[0]["conn_id"]}],
        vms=[], storages=[])
    cache, _ts = config.load_resources_cache()
    assert [n["host_name"] for n in cache["nodes"]] == ["h1"]


def test_cache_rejects_rows_without_conn_id(cfg_dir, mem_keyring):
    """Rows without conn_id are never stored — the cache is identity-
    keyed from day one (legacy rows cannot be attached at restore)."""
    config.save_resources_cache(
        nodes=[{"host_name": "h1", "node": "pve1", "status": "online"}],
        vms=[], storages=[])
    cache, _ts = config.load_resources_cache()
    assert cache["nodes"] == []


# --- 2. name normalization and ambiguity ---------------------------------


def test_names_normalized_on_save(cfg_dir, mem_keyring):
    config.save_config([_cfg("  h1  ", "10.0.0.1")])
    loaded = config.load_config()
    assert loaded[0]["name"] == "h1"


def _insert_raw_row(cfg_dir, name, data):
    """Insert a raw pre-5.1-style row (bypassing save_config)."""
    conn = config._init_db()
    conn.execute(
        "INSERT OR REPLACE INTO nodes (name, data) VALUES (?, ?)",
        (name, json.dumps(data)))
    conn.commit()
    conn.close()


def test_case_insensitive_conflict_detected_at_load(cfg_dir, mem_keyring):
    """Legacy databases may contain 'Web' and 'web' — both load, both are
    flagged _ambiguous, nothing is merged or removed."""
    for name in ("Web", "web"):
        _insert_raw_row(cfg_dir, name,
                        {"name": name, "host": "10.0.0.1", "user": "u",
                         "conn_id": uuid.uuid4().hex})
    loaded = config.load_config()
    assert len(loaded) == 2
    assert all(c.get("_ambiguous") for c in loaded)


def test_save_raises_on_new_conflict(cfg_dir, mem_keyring):
    with pytest.raises(ValueError):
        config.save_config([_cfg("Web", "10.0.0.1"), _cfg("web", "10.0.0.2")])


def test_save_allows_known_ambiguous_group(cfg_dir, mem_keyring):
    """A grandfathered conflict group persists verbatim. Without the
    allowance any new conflict raises; growth of an existing group is
    prevented at the entry points (dialog + flow-level uniqueness)."""
    group = [_cfg("Web", "10.0.0.1", conn_id=uuid.uuid4().hex),
             _cfg("web", "10.0.0.2", conn_id=uuid.uuid4().hex)]
    known = frozenset({config.name_key("web")})
    config.save_config(group, known_ambiguous=known)
    loaded = config.load_config()
    assert {c["name"] for c in loaded} == {"Web", "web"}

    # the same list without the allowance must raise
    with pytest.raises(ValueError):
        config.save_config(list(group))


def test_save_config_unrelated_ops_work_during_conflict(cfg_dir, mem_keyring):
    """While an ambiguous group exists, changing an unrelated connection
    must keep the group verbatim (full-replace save)."""
    group = [_cfg("Web", "10.0.0.1", conn_id=uuid.uuid4().hex),
             _cfg("web", "10.0.0.2", conn_id=uuid.uuid4().hex)]
    known = frozenset({config.name_key("web")})
    config.save_config(group, known_ambiguous=known)

    loaded = config.load_config()
    loaded.append(_cfg("other", "10.0.0.9", token_value=""))
    config.save_config(loaded, known_ambiguous=known)
    names = {c["name"] for c in config.load_config()}
    assert names == {"Web", "web", "other"}


def test_ambiguous_flag_not_persisted(cfg_dir, mem_keyring):
    for name in ("Web", "web"):
        _insert_raw_row(cfg_dir, name,
                        {"name": name, "host": "10.0.0.1", "user": "u",
                         "conn_id": uuid.uuid4().hex})
    loaded = config.load_config()
    assert all(c.get("_ambiguous") for c in loaded)
    conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
    raws = [r for (r,) in conn.execute("SELECT data FROM nodes")]
    conn.close()
    assert all("_ambiguous" not in json.loads(r) for r in raws)


def test_whitespace_conflict_detected_at_load(cfg_dir, mem_keyring):
    """Scenario 8: 'web' and 'web ' (outer space) are the same name after
    normalization — a legacy pair like this is flagged ambiguous."""
    _insert_raw_row(cfg_dir, "web",
                    {"name": "web", "host": "10.0.0.1", "user": "u",
                     "conn_id": uuid.uuid4().hex})
    _insert_raw_row(cfg_dir, "web ",
                    {"name": "web ", "host": "10.0.0.2", "user": "u",
                     "conn_id": uuid.uuid4().hex})
    loaded = config.load_config()
    assert len(loaded) == 2
    assert all(c.get("_ambiguous") for c in loaded)


def test_nfc_nfd_conflict_detected_at_load(cfg_dir, mem_keyring):
    """Scenario 8: the same text in NFC and NFD (e.g. 'é' composed vs
    decomposed) collides after normalization."""
    nfc = "cafe\u0301"          # decomposed form (NFD-ish source)
    nfd_normalized = config.normalize_name(nfc)
    other = "cafe\u0301"
    assert nfd_normalized == config.normalize_name(other)
    # two rows whose names only differ in Unicode composition
    _insert_raw_row(cfg_dir, "café-composed",
                    {"name": "caf\u00e9", "host": "10.0.0.1", "user": "u",
                     "conn_id": uuid.uuid4().hex})
    _insert_raw_row(cfg_dir, "café-decomposed",
                    {"name": "cafe\u0301", "host": "10.0.0.2", "user": "u",
                     "conn_id": uuid.uuid4().hex})
    loaded = config.load_config()
    assert len(loaded) == 2
    assert all(c.get("_ambiguous") for c in loaded)


# --- 3. keyring churn -----------------------------------------------------


def test_token_not_rewritten_when_unchanged(cfg_dir, mem_keyring):
    config.save_config([_cfg("h1", "10.0.0.1")])
    key = f"{config._KEYRING_SERVICE}/node:h1"
    assert mem_keyring[key] == "secret-h1"
    # same value again — the keyring entry object must not be replaced
    config.save_config([_cfg("h1", "10.0.0.1")])
    assert mem_keyring[key] == "secret-h1"
    # a changed value IS written
    config.save_config([_cfg("h1", "10.0.0.1", token_value="new-secret")])
    assert mem_keyring[key] == "new-secret"


# --- 4. import contract ---------------------------------------------------


@pytest.fixture
def no_password(monkeypatch):
    monkeypatch.setattr(config, "_ask_password", lambda mode: "pw")


def _write_bundle(path, entries, password="pw"):
    blob = config._encrypt_bundle(entries, password)
    with open(path, "wb") as f:
        f.write(blob)
    return str(path)


def test_import_merge_keeps_local_identity(cfg_dir, mem_keyring,
                                           no_password, tmp_path):
    """A matched connection keeps its local name and conn_id; only
    credential/option fields are imported."""
    config.save_config([_cfg("old-name", "10.0.0.1",
                             conn_id="local-id-1", trust_ssl=False)])
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        _cfg("bundle-name", "10.0.0.1", trust_ssl=True, port=8006)])
    report: list[str] = []
    merged = config.import_config(bundle, merge=True, report=report)
    assert len(merged) == 1
    entry = merged[0]
    assert entry["name"] == "old-name"          # local name wins
    assert entry["conn_id"] == "local-id-1"     # local identity wins
    assert entry["trust_ssl"] is True           # attributes imported
    assert entry["port"] == 8006
    assert "Updated old-name" in report


def test_import_ignores_bundle_conn_id_for_new_entries(
        cfg_dir, mem_keyring, no_password, tmp_path):
    """A file-borne conn_id is never accepted: new entries get fresh
    local ids, so a foreign bundle cannot attach local cache rows."""
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        _cfg("fresh", "10.0.0.5", conn_id="attacker-id")])
    merged = config.import_config(bundle, merge=True)
    entry = merged[-1]
    assert entry["name"] == "fresh"
    assert entry["conn_id"] != "attacker-id"
    assert len(entry["conn_id"]) == 32


def test_import_pbs_does_not_collapse_pve_at_same_address(
        cfg_dir, mem_keyring, no_password, tmp_path):
    """The latent defect fix: the match key includes the connection type —
    a PBS entry at the same address as a PVE entry is a different
    connection and must be ADDED, not silently replace the PVE entry."""
    config.save_config([_cfg("pve1", "10.0.0.1", conn_id="pve-id")])
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        _cfg("backup", "10.0.0.1", user="root@pam", type="pbs",
             port=8007)])
    report: list[str] = []
    merged = config.import_config(bundle, merge=True, report=report)
    assert len(merged) == 2
    pve = [c for c in merged if c.get("type", "pve") == "pve"]
    pbs = [c for c in merged if c.get("type") == "pbs"]
    assert len(pve) == 1 and pve[0]["conn_id"] == "pve-id"
    assert len(pbs) == 1 and "Added backup" in report


def test_import_host_case_insensitive_match(cfg_dir, mem_keyring,
                                            no_password, tmp_path):
    """host compares case-insensitively (DNS names), user exactly."""
    config.save_config([_cfg("h1", "PVE.Office.lan", conn_id="id-1")])
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        _cfg("h1", "pve.office.LAN", token_value="rotated")])
    merged = config.import_config(bundle, merge=True)
    assert len(merged) == 1
    assert merged[0]["conn_id"] == "id-1"
    assert merged[0]["token_value"] == "rotated"


def test_import_port_change_is_an_attribute_update(cfg_dir, mem_keyring,
                                                   no_password, tmp_path):
    """port/proxy are attributes, not identity: a port change still
    matches the same connection."""
    config.save_config([_cfg("h1", "10.0.0.1", port=8006,
                             conn_id="id-1")])
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        _cfg("h1", "10.0.0.1", port=8006, proxy="socks://x")])
    merged = config.import_config(bundle, merge=True)
    assert len(merged) == 1
    assert merged[0]["conn_id"] == "id-1"
    assert merged[0]["proxy"] == "socks://x"


def test_import_name_conflict_skipped_with_reason(cfg_dir, mem_keyring,
                                                  no_password, tmp_path):
    """A bundle entry whose name collides with an existing connection is
    skipped with an explicit reason, not silently dropped."""
    config.save_config([_cfg("taken", "10.0.0.9", conn_id="id-1")])
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        _cfg("TAKEN", "10.0.0.8")])
    report: list[str] = []
    merged = config.import_config(bundle, merge=True, report=report)
    assert [c["name"] for c in merged] == ["taken"]
    assert any("Skipped" in line and "TAKEN" in line for line in report)


def test_import_invalid_entry_skipped_with_reason(cfg_dir, mem_keyring,
                                                  no_password, tmp_path):
    """One bad entry no longer aborts the whole import."""
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        {"name": "bad", "host": "a\nb", "user": "u"},
        _cfg("good", "10.0.0.3"),
    ])
    report: list[str] = []
    merged = config.import_config(bundle, merge=True, report=report)
    assert [c["name"] for c in merged] == ["good"]
    assert any("bad" in line and "Invalid characters" in line
               for line in report)


def test_import_duplicate_bundle_entries_first_wins(cfg_dir, mem_keyring,
                                                    no_password, tmp_path):
    """Two bundle entries matching the same local connection: the first
    updates, the second is skipped with a reason."""
    config.save_config([_cfg("h1", "10.0.0.1", conn_id="id-1")])
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        _cfg("h1", "10.0.0.1", trust_ssl=True),
        _cfg("h1", "10.0.0.1", trust_ssl=False),
    ])
    report: list[str] = []
    merged = config.import_config(bundle, merge=True, report=report)
    assert len(merged) == 1
    assert merged[0]["trust_ssl"] is True
    assert any("already matched" in line for line in report)


def test_import_replace_mode_fresh_ids(cfg_dir, mem_keyring, no_password,
                                       tmp_path):
    """merge=False is a full replace with FRESH local conn_ids: a
    restored backup can never attach the cache of another installation."""
    config.save_config([_cfg("h1", "10.0.0.1", conn_id="old-id")])
    bundle = _write_bundle(tmp_path / "b.vdeck", [
        _cfg("h1", "10.0.0.1", conn_id="bundle-id"),
        _cfg("h2", "10.0.0.2", conn_id="bundle-id-2"),
    ])
    merged = config.import_config(bundle, merge=False)
    assert [c["name"] for c in merged] == ["h1", "h2"]
    assert all(c["conn_id"] not in ("old-id", "bundle-id", "bundle-id-2")
               for c in merged)
    assert all(len(c["conn_id"]) == 32 for c in merged)


def test_import_merge_of_same_backup_is_idempotent(cfg_dir, mem_keyring,
                                                   no_password, tmp_path):
    """Re-importing the same bundle must not duplicate or churn: names,
    conn_ids and keyring values stay stable."""
    entries = [_cfg("h1", "10.0.0.1", token_value="secret-h1")]
    bundle = _write_bundle(tmp_path / "b.vdeck", entries)
    first = config.import_config(bundle, merge=True)
    ids = {c["name"]: c["conn_id"] for c in first}
    second = config.import_config(bundle, merge=True)
    assert len(second) == 1
    assert second[0]["conn_id"] == ids["h1"]
    key = f"{config._KEYRING_SERVICE}/node:h1"
    assert mem_keyring[key] == "secret-h1"
