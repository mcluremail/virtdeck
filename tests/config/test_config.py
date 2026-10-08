"""Tests for virtdeck/config.py (sqlite-backed config, caches, bundles)."""

from __future__ import annotations

import json
import sqlite3

import pytest

from virtdeck import config

# --- Fixtures ---


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    """Redirect the config directory to a temp dir for every test."""
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setattr(config, "_config_dir", lambda: str(d))
    return d


@pytest.fixture
def fake_keyring(monkeypatch):
    """Replace keyring-backed token storage with an in-memory dict."""
    store: dict[str, str] = {}
    monkeypatch.setattr(
        config, "_save_token",
        lambda name, value: store.__setitem__(name, value),
    )
    monkeypatch.setattr(
        config, "_load_token",
        lambda name: store.get(name),
    )
    monkeypatch.setattr(
        config, "_delete_token",
        lambda name: store.pop(name, None),
    )
    return store


def make_cfg(name, host, user="root@pam", token="secret-1", **extra):
    cfg = {"name": name, "host": host, "user": user,
           "token_name": "virtdeck", "token_value": token}
    cfg.update(extra)
    return cfg


# --- nodes config ---


class TestNodesConfig:
    def test_save_load_roundtrip(self, cfg_dir, fake_keyring):
        original = [
            make_cfg("h1", "10.0.0.1", cluster="ros", trust_ssl=True),
            make_cfg("h2", "10.0.0.2"),
        ]
        config.save_config(original)
        loaded = config.load_config()
        assert [c["name"] for c in loaded] == ["h1", "h2"]
        assert loaded[0]["cluster"] == "ros"
        assert loaded[0]["trust_ssl"] is True
        assert loaded[0]["token_value"] == "secret-1"
        assert loaded[1]["token_value"] == "secret-1"

    def test_token_value_not_stored_in_db(self, cfg_dir, fake_keyring):
        config.save_config([make_cfg("h1", "10.0.0.1")])
        conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
        (raw,) = conn.execute("SELECT data FROM nodes WHERE name='h1'").fetchone()
        conn.close()
        assert "token_value" not in json.loads(raw)
        assert "secret" not in raw

    def test_save_skips_entries_without_name(self, cfg_dir, fake_keyring):
        config.save_config([make_cfg("h1", "10.0.0.1"), {"host": "x"}])
        assert [c["name"] for c in config.load_config()] == ["h1"]

    def test_save_rejects_newline_in_host(self, cfg_dir, fake_keyring):
        with pytest.raises(ValueError, match="Invalid characters"):
            config.save_config([make_cfg("h1", "10.0.0.1\n10.0.0.2")])

    def test_save_rejects_nul_in_user(self, cfg_dir, fake_keyring):
        with pytest.raises(ValueError, match="Invalid characters"):
            config.save_config([make_cfg("h1", "10.0.0.1", user="root\x00")])

    def test_group_field_roundtrip(self, cfg_dir, fake_keyring):
        cfg = make_cfg("h1", "10.0.0.1")
        cfg["group"] = "Site A"
        config.save_config([cfg])
        loaded = config.load_config()
        assert loaded[0]["group"] == "Site A"

    def test_save_rejects_newline_in_group(self, cfg_dir, fake_keyring):
        cfg = make_cfg("h1", "10.0.0.1")
        cfg["group"] = "Site\nA"
        with pytest.raises(ValueError, match="Invalid characters in group"):
            config.save_config([cfg])

    def test_load_ignores_corrupt_rows(self, cfg_dir, fake_keyring):
        config.save_config([make_cfg("h1", "10.0.0.1")])
        conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
        conn.execute("INSERT INTO nodes (name, data) VALUES ('bad', '{not json')")
        conn.commit()
        conn.close()
        assert [c["name"] for c in config.load_config()] == ["h1"]

    def test_load_missing_token_is_empty_string(self, cfg_dir, monkeypatch):
        # No fake_keyring: token load returns None → token_value ""
        monkeypatch.setattr(config, "_load_token", lambda name: None)
        config._init_db()
        conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
        conn.execute(
            "INSERT INTO nodes (name, data) VALUES ('h1', ?)",
            (json.dumps({"name": "h1", "host": "10.0.0.1", "user": "root@pam"}),),
        )
        conn.commit()
        conn.close()
        (cfg,) = config.load_config()
        assert cfg["token_value"] == ""


# --- ui state / caches ---


class TestCaches:
    def test_ui_state_roundtrip(self, cfg_dir):
        config.save_ui_state("splitter", "420")
        assert config.load_ui_state("splitter") == "420"
        config.save_ui_state("splitter", "500")
        assert config.load_ui_state("splitter") == "500"

    def test_ui_state_missing_key(self, cfg_dir):
        assert config.load_ui_state("never-saved") is None

    def test_tasks_cache_roundtrip(self, cfg_dir):
        tasks = [{"upid": "UPID:1", "status": "OK"}, {"upid": "UPID:2"}]
        config.save_tasks_cache(tasks)
        assert config.load_tasks_cache() == tasks

    def test_tasks_cache_empty(self, cfg_dir):
        assert config.load_tasks_cache() == []

    def test_resources_cache_roundtrip(self, cfg_dir):
        config.save_resources_cache(
            [{"node": "pve01"}], [{"vmid": 100}], [{"storage": "local"}],
        )
        data, ts = config.load_resources_cache()
        assert data is not None
        assert data["nodes"] == [{"node": "pve01"}]
        assert data["vms"] == [{"vmid": 100}]
        assert data["storages"] == [{"storage": "local"}]
        assert ts  # timestamp string present

    def test_resources_cache_empty(self, cfg_dir):
        assert config.load_resources_cache() == (None, None)


# --- translations seeding ---


class TestSeedTranslations:
    def _db(self, cfg_dir):
        conn = sqlite3.connect(str(cfg_dir / "config.sqlite"))
        return conn

    def test_seed_inserts(self, cfg_dir):
        config.seed_translations("ru", {"a": "А", "b": "Б"}, version=1)
        conn = self._db(cfg_dir)
        rows = conn.execute(
            "SELECT msgid, msgstr FROM translations WHERE lang='ru' ORDER BY msgid"
        ).fetchall()
        stored = conn.execute(
            "SELECT value FROM ui_state WHERE key='i18n_version'"
        ).fetchone()
        conn.close()
        assert rows == [("a", "А"), ("b", "Б")]
        assert stored == ("1",)

    def test_reseed_same_version_is_noop(self, cfg_dir):
        config.seed_translations("ru", {"a": "А"}, version=1)
        # Same version, different dict — existing rows must survive
        config.seed_translations("ru", {"a": "ИЗМЕНЕНО", "c": "В"}, version=1)
        conn = self._db(cfg_dir)
        rows = conn.execute(
            "SELECT msgid, msgstr FROM translations WHERE lang='ru' ORDER BY msgid"
        ).fetchall()
        conn.close()
        assert rows == [("a", "А"), ("c", "В")]

    def test_version_bump_clears_table(self, cfg_dir):
        config.seed_translations("ru", {"a": "А"}, version=1)
        config.seed_translations("ru", {"a": "НОВОЕ", "b": "Б"}, version=2)
        conn = self._db(cfg_dir)
        rows = conn.execute(
            "SELECT msgid, msgstr FROM translations WHERE lang='ru' ORDER BY msgid"
        ).fetchall()
        stored = conn.execute(
            "SELECT value FROM ui_state WHERE key='i18n_version'"
        ).fetchone()
        conn.close()
        assert rows == [("a", "НОВОЕ"), ("b", "Б")]
        assert stored == ("2",)

    def test_no_version_skips_clear(self, cfg_dir):
        config.seed_translations("ru", {"a": "А"})
        config.seed_translations("ru", {"b": "Б"})
        conn = self._db(cfg_dir)
        rows = conn.execute(
            "SELECT msgid FROM translations WHERE lang='ru' ORDER BY msgid"
        ).fetchall()
        conn.close()
        assert rows == [("a",), ("b",)]


# --- migration ---


class TestMigration:
    def test_old_db_migrated(self, cfg_dir):
        old = cfg_dir / "tasks_cache.sqlite"
        old.write_bytes(b"placeholder")
        config._migrate_old_db()
        assert not old.exists()
        assert (cfg_dir / "config.sqlite").exists()

    def test_old_db_removed_when_new_exists(self, cfg_dir):
        config.save_ui_state("x", "1")  # creates config.sqlite
        old = cfg_dir / "tasks_cache.sqlite"
        old.write_bytes(b"placeholder")
        config._migrate_old_db()
        assert not old.exists()
        assert (cfg_dir / "config.sqlite").exists()


class TestLegacyDirMigration:
    def test_legacy_dir_renamed_on_config_dir(self, tmp_path, monkeypatch):
        base = tmp_path / "xdg"
        legacy = base / "pve-center"
        legacy.mkdir(parents=True)
        (legacy / "config.sqlite").write_bytes(b"old-db")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(base))

        d = config._config_dir()
        assert d == str(base / "virtdeck")
        assert (base / "virtdeck" / "config.sqlite").read_bytes() == b"old-db"
        assert not legacy.exists()

    def test_no_migration_when_new_dir_exists(self, tmp_path, monkeypatch):
        base = tmp_path / "xdg"
        (base / "pve-center").mkdir(parents=True)
        (base / "virtdeck").mkdir(parents=True)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(base))

        config._config_dir()
        assert (base / "pve-center").exists()  # left untouched

    def test_noop_without_legacy_dir(self, tmp_path, monkeypatch):
        base = tmp_path / "xdg"
        base.mkdir(parents=True)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(base))
        config._config_dir()
        assert (base / "virtdeck").exists()


# --- encrypted bundle ---


class TestBundle:
    def test_encrypt_decrypt_roundtrip(self):
        data = [make_cfg("h1", "10.0.0.1")]
        raw = config._encrypt_bundle(data, "password123")
        assert config._decrypt_bundle(raw, "password123") == data

    def test_wrong_password_raises(self):
        from cryptography.fernet import InvalidToken

        raw = config._encrypt_bundle([{"a": 1}], "password123")
        with pytest.raises(InvalidToken):
            config._decrypt_bundle(raw, "wrong-password")

    def test_salt_is_random(self):
        d = [{"a": 1}]
        assert config._encrypt_bundle(d, "p")[:16] != \
            config._encrypt_bundle(d, "p")[:16]

    def test_validate_imported_filters_fields(self):
        imported = [
            {"name": "h1", "host": "10.0.0.1", "user": "root@pam",
             "token_value": "t", "evil_field": "x", "trust_ssl": True},
            {"name": "", "host": "10.0.0.2", "user": "u"},      # no name
            {"name": "h2", "host": "", "user": "u"},            # no host
            {"name": "h3", "host": "10.0.0.3", "user": ""},     # no user
            "not a dict",
        ]
        result = config._validate_imported(imported)
        assert len(result) == 1
        assert result[0]["name"] == "h1"
        assert "evil_field" not in result[0]
        assert result[0]["trust_ssl"] is True

    def test_validate_imported_rejects_newline(self):
        imported = [{"name": "h1", "host": "a\nb", "user": "u"}]
        with pytest.raises(ValueError):
            config._validate_imported(imported)

    def test_export_import_roundtrip(self, cfg_dir, fake_keyring, monkeypatch):
        monkeypatch.setattr(config, "_ask_password", lambda mode="enter": "password123")
        config.save_config([make_cfg("h1", "10.0.0.1", cluster="ros"),
                            make_cfg("h2", "10.0.0.2")])
        bundle = cfg_dir / "bundle.enc"
        assert config.export_config(str(bundle)) is True
        assert bundle.exists()

        # Wipe local config, then import with merge=False
        config.save_config([])
        imported = config.import_config(str(bundle), merge=False)
        assert imported is not None
        names = sorted(c["name"] for c in imported)
        assert names == ["h1", "h2"]
        assert config.load_config()[0]["cluster"] == "ros"
        assert config.load_config()[0]["token_value"] == "secret-1"

    def test_import_preserves_type_port_proxy(self, cfg_dir, fake_keyring, monkeypatch):
        """Regression: import must not lose type/port/proxy — otherwise the PBS
        server turns into a broken PVE host after a bundle move."""
        monkeypatch.setattr(config, "_ask_password", lambda mode="enter": "password123")
        pbs = make_cfg("pbs1", "10.1.0.1", type="pbs", port=8007,
                       proxy="http://squid:3128")
        config.save_config([pbs])
        bundle = cfg_dir / "bundle.enc"
        assert config.export_config(str(bundle)) is True

        config.save_config([])
        imported = config.import_config(str(bundle), merge=False)
        assert imported is not None
        cfg = imported[0]
        assert cfg["type"] == "pbs"
        assert cfg["port"] == 8007
        assert cfg["proxy"] == "http://squid:3128"

    def test_import_merge_replaces_by_host_user(self, cfg_dir, fake_keyring, monkeypatch):
        monkeypatch.setattr(config, "_ask_password", lambda mode="enter": "password123")
        config.save_config([make_cfg("h1", "10.0.0.1", cluster="old")])
        bundle = cfg_dir / "bundle.enc"
        raw = config._encrypt_bundle(
            [make_cfg("h1", "10.0.0.1", cluster="new")], "password123",
        )
        bundle.write_bytes(raw)
        merged = config.import_config(str(bundle), merge=True)
        assert merged is not None
        assert len(merged) == 1
        assert merged[0]["cluster"] == "new"

    def test_import_cancelled(self, cfg_dir, monkeypatch):
        monkeypatch.setattr(config, "_ask_password", lambda mode="enter": None)
        raw = config._encrypt_bundle([make_cfg("h1", "10.0.0.1")], "p12345678")
        bundle = cfg_dir / "bundle.enc"
        bundle.write_bytes(raw)
        assert config.import_config(str(bundle)) is None

    def test_import_missing_file(self, cfg_dir):
        assert config.import_config(str(cfg_dir / "nope.enc")) is None

    def test_import_rejects_oversized(self, cfg_dir, monkeypatch):
        bundle = cfg_dir / "big.enc"
        bundle.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
        assert config.import_config(str(bundle)) is None

    def test_export_symlink_rejected(self, cfg_dir, fake_keyring):
        target = cfg_dir / "real.enc"
        target.write_bytes(b"")
        link = cfg_dir / "link.enc"
        link.symlink_to(target)
        assert config.export_config(str(link)) is False

    def test_export_empty_config(self, cfg_dir, fake_keyring):
        config.save_config([])
        assert config.export_config(str(cfg_dir / "b.enc")) is False


# --- tree notes (B19) ---


class TestTreeNotes:
    def test_empty_and_roundtrip(self, cfg_dir):
        assert config.load_tree_notes() == {}
        config.save_tree_note("host:h1", "Main host")
        config.save_tree_note("cluster:c1", "Prod")
        config.save_tree_note("vm:h1:100", "web")
        assert config.load_tree_notes() == {
            "host:h1": "Main host",
            "cluster:c1": "Prod",
            "vm:h1:100": "web",
        }

    def test_overwrite(self, cfg_dir):
        config.save_tree_note("host:h1", "a")
        config.save_tree_note("host:h1", "b")
        assert config.load_tree_notes() == {"host:h1": "b"}

    def test_empty_note_removes_entry(self, cfg_dir):
        config.save_tree_note("host:h1", "a")
        config.save_tree_note("host:h1", "")
        assert config.load_tree_notes() == {}
        config.save_tree_note("host:h2", "keep")
        config.save_tree_note("host:h2", "   ")
        assert config.load_tree_notes() == {}


# --- keyring legacy service migration (VirtDeck rename) ---


class _FakeKeyring:
    """Minimal keyring module double: per-(service, key) in-memory store."""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, key, value):
        self.store[(service, key)] = value

    def get_password(self, service, key):
        return self.store.get((service, key))

    def delete_password(self, service, key):
        self.store.pop((service, key), None)


@pytest.fixture
def live_keyring(monkeypatch):
    """Inject a real (fake) keyring module so _load/_delete run their logic."""
    kr = _FakeKeyring()
    monkeypatch.setattr(config, "_keyring_available", True)
    monkeypatch.setattr(config, "_keyring_module", kr)
    return kr


class TestKeyringLegacyMigration:
    def test_load_migrates_legacy_token(self, live_keyring):
        live_keyring.set_password("pvecenter", "node:h1", "tok-legacy")
        assert config._load_token("h1") == "tok-legacy"
        assert live_keyring.get_password("virtdeck", "node:h1") == "tok-legacy"

    def test_current_service_takes_precedence(self, live_keyring):
        live_keyring.set_password("pvecenter", "node:h1", "tok-old")
        live_keyring.set_password("virtdeck", "node:h1", "tok-new")
        assert config._load_token("h1") == "tok-new"

    def test_missing_token_returns_none(self, live_keyring):
        assert config._load_token("nope") is None

    def test_delete_cleans_both_services(self, live_keyring):
        live_keyring.set_password("pvecenter", "node:h1", "tok-old")
        live_keyring.set_password("virtdeck", "node:h1", "tok-new")
        config._delete_token("h1")
        assert live_keyring.get_password("virtdeck", "node:h1") is None
        assert live_keyring.get_password("pvecenter", "node:h1") is None
