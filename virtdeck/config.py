import base64
import json
import logging
import os
import sqlite3
import sys
import threading

logger = logging.getLogger(__name__)

CONFIG_DB = "config.sqlite"
_OLD_DB = "tasks_cache.sqlite"
_OLD_ENC = "nodes.enc"
_OLD_SALT = "nodes.salt"
_OLD_JSON = "nodes.json"

_KEYRING_SERVICE = "virtdeck"
_KEYRING_SERVICE_LEGACY = "pvecenter"  # pre-3.0 name (PVECenter era)
_DB_LOCK = threading.RLock()

# ── paths ──────────────────────────────────────────────────────

def _base_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        home = os.path.expanduser("~")
        base = os.path.join(home, "Library", "Application Support")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        base = xdg
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), base)
    _migrate_legacy_dir(base)
    d = os.path.join(base, "virtdeck")
    os.makedirs(d, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


_LEGACY_DIRNAME = "pve-center"  # pre-3.0 config directory (PVECenter era)


def _migrate_legacy_dir(base):
    """Rename the pre-3.0 config directory (pve-center → virtdeck) on
    first start, so hosts/tokens/UI state survive the rename."""
    old = os.path.join(base, _LEGACY_DIRNAME)
    new = os.path.join(base, "virtdeck")
    if not os.path.isdir(old) or os.path.exists(new):
        return
    try:
        os.rename(old, new)
        logger.info("migrated config dir %s → %s", old, new)
    except OSError as e:
        logger.warning("config dir migration failed: %s", e)


def _migrate_file(name):
    src = os.path.join(_base_dir(), name)
    dst = os.path.join(_config_dir(), name)
    if os.path.exists(src) and not os.path.exists(dst):
        import shutil
        shutil.move(src, dst)


def _db_path():
    return os.path.join(_config_dir(), CONFIG_DB)


# ── keyring ────────────────────────────────────────────────────

_keyring_available: bool | None = None
_keyring_module = None


def _get_keyring():
    global _keyring_available, _keyring_module
    if _keyring_available is False:
        return None
    if _keyring_module is not None:
        return _keyring_module
    try:
        import keyring as _kr
        _kr.get_keyring()
        _keyring_module = _kr
        _keyring_available = True
        return _kr
    except Exception:
        _keyring_available = False
        return None


def _keyring_key(name: str) -> str:
    return f"node:{name}"


def _save_token(name: str, token_value: str):
    kr = _get_keyring()
    if kr is None:
        logger.warning("keyring not available, token for %s not saved", name)
        return
    try:
        kr.set_password(_KEYRING_SERVICE, _keyring_key(name), token_value)
    except Exception as e:
        logger.error("keyring set_password failed for %s: %s", name, e)


def _load_token(name: str) -> str | None:
    kr = _get_keyring()
    if kr is None:
        return None
    try:
        value = kr.get_password(_KEYRING_SERVICE, _keyring_key(name))
        if value is None:
            # Migration: tokens saved before the VirtDeck rename live under
            # the legacy service name — read them and re-store under the
            # current service so the legacy entry can be retired.
            value = kr.get_password(_KEYRING_SERVICE_LEGACY, _keyring_key(name))
            if value is not None:
                _save_token(name, value)
        return value
    except Exception as e:
        logger.error("keyring get_password failed for %s: %s", name, e)
        return None


def _delete_token(name: str):
    kr = _get_keyring()
    if kr is None:
        return
    try:
        kr.delete_password(_KEYRING_SERVICE, _keyring_key(name))
    except Exception:
        pass
    try:
        kr.delete_password(_KEYRING_SERVICE_LEGACY, _keyring_key(name))
    except Exception:
        pass


# ── sqlite init ─────────────────────────────────────────────────

def _init_db():
    path = _db_path()
    conn = sqlite3.connect(path, timeout=5)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            name TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS tasks_cache (id INTEGER PRIMARY KEY, data TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS ui_state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS tree_notes (key TEXT PRIMARY KEY, note TEXT NOT NULL)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resources_cache (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            ts TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS translations (
            lang  TEXT NOT NULL,
            msgid TEXT NOT NULL,
            msgstr TEXT NOT NULL,
            PRIMARY KEY (lang, msgid)
        )
    """)
    conn.commit()
    return conn


def _migrate_old_db():
    """tasks_cache.sqlite → config.sqlite"""
    old = os.path.join(_config_dir(), _OLD_DB)
    new = _db_path()
    if not os.path.exists(old):
        return
    if os.path.exists(new):
        try:
            os.remove(old)
            logger.info("removed orphaned %s", _OLD_DB)
        except Exception:
            pass
        return
    try:
        import shutil
        shutil.move(old, new)
        logger.info("migrated %s → %s", _OLD_DB, CONFIG_DB)
    except Exception as e:
        logger.warning("db migration failed: %s", e)


# ── nodes config (public API) ───────────────────────────────────

_NODE_FIELDS = ("name", "host", "user", "token_name", "cluster", "cluster_rep", "skip")


def _validate_field(value):
    if not isinstance(value, str):
        return True
    return "\r" not in value and "\n" not in value and "\x00" not in value


def _sanitize_cfg(cfg):
    for field in ("host", "user", "token_name", "token_value", "group"):
        val = cfg.get(field, "")
        if val and not _validate_field(val):
            raise ValueError(f"Invalid characters in {field}")


def load_config() -> list[dict]:
    """Load nodes from sqlite, attach token_value from keyring.
    Returns list of node dicts (never None — no password dialog needed)."""
    for fn in (_OLD_DB,):
        _migrate_file(fn)
    _migrate_old_db()

    with _DB_LOCK:
        conn = _init_db()
        cur = conn.execute("SELECT data FROM nodes")
        rows = cur.fetchall()
        conn.close()

    config = []
    for (raw,) in rows:
        try:
            cfg = json.loads(raw)
        except Exception:
            continue
        name = cfg.get("name", "")
        if name:
            token = _load_token(name)
            cfg["token_value"] = token or ""
        config.append(cfg)
    return config


def save_config(config_list: list[dict]):
    """Save nodes to sqlite, token_value to keyring."""
    tokens = []
    with _DB_LOCK:
        conn = _init_db()
        conn.execute("DELETE FROM nodes")
        for cfg in config_list:
            name = cfg.get("name", "")
            if not name:
                continue
            _sanitize_cfg(cfg)
            store = {k: v for k, v in cfg.items() if k != "token_value"}
            conn.execute("INSERT OR REPLACE INTO nodes (name, data) VALUES (?, ?)",
                         (name, json.dumps(store, ensure_ascii=False)))
            token_value = cfg.get("token_value")
            if token_value:
                tokens.append((name, token_value))
        conn.commit()
        conn.close()
    for name, token_value in tokens:
        _save_token(name, token_value)


def delete_node_tokens(names: list[str]):
    """Delete token secrets from keyring for given node names."""
    for name in names:
        _delete_token(name)


# ── encrypted bundle (export/import) ────────────────────────────

def _derive_key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def _encrypt_bundle(data: list[dict], password: str) -> bytes:
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    plain = json.dumps(data, ensure_ascii=False, indent=2).encode()
    token = Fernet(key).encrypt(plain)
    return salt + token


def _decrypt_bundle(raw: bytes, password: str) -> list[dict]:
    from cryptography.fernet import Fernet
    salt, token = raw[:16], raw[16:]
    key = _derive_key(password, salt)
    plain = Fernet(key).decrypt(token)
    return json.loads(plain.decode())


def _ask_password(mode="enter"):
    """Show password input dialog for export/import bundle.
    mode='enter' — existing password, mode='set' — set new password.
    Returns password or None (cancelled)."""
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

    from .ui.i18n import tr
    from .ui.theme import Color
    dialog = QDialog()
    dialog.setWindowTitle(tr("VirtDeck — Password"))
    dialog.setMinimumSize(380, 160)
    layout = QVBoxLayout(dialog)

    if mode == "set":
        layout.addWidget(QLabel(tr("Set password to encrypt configuration:")))
        min_len_label = QLabel(tr("Minimum 8 characters"))
        min_len_label.setStyleSheet(f"color: {Color.TEXT_DIM}; font-size: 11px;")
        layout.addWidget(min_len_label)
    else:
        layout.addWidget(QLabel(tr("Enter password:")))

    pwd_input = QLineEdit()
    pwd_input.setEchoMode(QLineEdit.Password)
    layout.addWidget(pwd_input)

    if mode == "set":
        layout.addWidget(QLabel(tr("Repeat password:")))
        confirm_input = QLineEdit()
        confirm_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(confirm_input)
    else:
        confirm_input = None

    error_label = QLabel("")
    error_label.setStyleSheet(f"color: {Color.TEXT_DIM};")
    layout.addWidget(error_label)

    btn_layout = QHBoxLayout()
    ok_btn = QPushButton(tr("OK"))
    cancel_btn = QPushButton(tr("Cancel"))
    btn_layout.addStretch()
    btn_layout.addWidget(ok_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    result = [None]

    def on_ok():
        pwd = pwd_input.text()
        if not pwd:
            error_label.setText(tr("Password cannot be empty"))
            return
        if mode == "set" and len(pwd) < 8:
            error_label.setText(tr("Password must be at least 8 characters"))
            return
        if confirm_input is not None and pwd != confirm_input.text():
            error_label.setText(tr("Passwords do not match"))
            return
        result[0] = pwd
        dialog.accept()

    ok_btn.clicked.connect(on_ok)
    cancel_btn.clicked.connect(dialog.reject)
    pwd_input.returnPressed.connect(on_ok)
    if confirm_input:
        confirm_input.returnPressed.connect(on_ok)

    if dialog.exec() == QDialog.Accepted:
        return result[0]
    return None


def export_config(dest_path: str) -> bool:
    """Export all nodes (with token_value) as encrypted bundle."""
    if os.path.islink(dest_path):
        return False
    dest_path = os.path.realpath(dest_path)
    config = load_config()
    if not config:
        return False
    missing = [c.get("name", "?") for c in config if not c.get("token_value")]
    if missing:
        from PySide6.QtWidgets import QMessageBox

        from .ui.i18n import tr
        QMessageBox.warning(
            None, tr("Export"),
            tr("Tokens missing for {count} host(s): {names}. They will not be included in the export.").format(
                count=len(missing), names=", ".join(missing[:5]))
        )
    password = _ask_password("set")
    if password is None:
        return False
    raw = _encrypt_bundle(config, password)
    with open(dest_path, "wb") as f:
        f.write(raw)
    try:
        os.chmod(dest_path, 0o600)
    except OSError:
        pass
    return True


_ALLOWED_IMPORT_FIELDS = frozenset({
    "name", "host", "user", "token_name", "token_value",
    "cluster", "cluster_rep", "skip", "trust_ssl",
    "type", "port", "proxy",
})


def _validate_imported(imported):
    result = []
    for cfg in imported:
        if not isinstance(cfg, dict):
            continue
        name = cfg.get("name", "")
        host = cfg.get("host", "")
        user = cfg.get("user", "")
        if not name or not host or not user:
            continue
        _sanitize_cfg(cfg)
        clean = {k: v for k, v in cfg.items() if k in _ALLOWED_IMPORT_FIELDS}
        result.append(clean)
    return result


def import_config(src_path: str, merge: bool = True) -> list[dict] | None:
    """Import encrypted bundle, merge with existing config."""
    from PySide6.QtWidgets import QMessageBox

    from .ui.i18n import tr
    if not os.path.exists(src_path) or os.path.islink(src_path):
        return None
    if os.path.getsize(src_path) > 10 * 1024 * 1024:
        return None

    while True:
        password = _ask_password("enter")
        if password is None:
            return None
        try:
            with open(src_path, "rb") as f:
                raw = f.read()
            imported = _decrypt_bundle(raw, password)
            break
        except Exception:
            QMessageBox.warning(None, tr("Error"),
                                 tr("Wrong password. Try again."))

    imported = _validate_imported(imported)
    if not imported:
        QMessageBox.warning(None, tr("Error"),
                             tr("No valid server entries found in the bundle."))
        return None

    if not merge:
        save_config(imported)
        return imported

    current = load_config()
    current_map = {(c.get("host"), c.get("user")): c for c in current}
    for imp_cfg in imported:
        key = (imp_cfg.get("host"), imp_cfg.get("user"))
        current_map[key] = imp_cfg
    merged = list(current_map.values())
    save_config(merged)
    return merged


# ── tasks cache ─────────────────────────────────────────────────



def save_tasks_cache(tasks: list[dict]):
    try:
        data = json.dumps(tasks, ensure_ascii=False, default=str)
        with _DB_LOCK:
            conn = _init_db()
            conn.execute("INSERT OR REPLACE INTO tasks_cache (id, data) VALUES (1, ?)", (data,))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning("save_tasks_cache: %s", e)


def load_tasks_cache() -> list[dict]:
    try:
        with _DB_LOCK:
            conn = _init_db()
            cur = conn.execute("SELECT data FROM tasks_cache WHERE id = 1")
            row = cur.fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
    except Exception as e:
        logger.warning("load_tasks_cache: %s", e)
    return []


# ── resources cache (offline mode) ───────────────────────────────



def save_resources_cache(nodes, vms, storages):
    try:
        # Error stubs of the current session (status="error") are not cached:
        # the cache holds "last successful data", and load-time stubs
        # create duplicates in the tree (the real host node arrives with
        # a short name while the stub is created with the config's FQDN).
        nodes = [
            dict(o) if not isinstance(o, dict) else o
            for o in nodes
            if (o.get("status") if isinstance(o, dict)
                else getattr(o, "status_value", "")) != "error"
        ]
        data = json.dumps(
            {
                "nodes": [dict(o) if not isinstance(o, dict) else o for o in nodes],
                "vms": [dict(o) if not isinstance(o, dict) else o for o in vms],
                "storages": [dict(o) if not isinstance(o, dict) else o for o in storages],
            },
            ensure_ascii=False, default=str,
        )
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        with _DB_LOCK:
            conn = _init_db()
            conn.execute("INSERT OR REPLACE INTO resources_cache (id, data, ts) VALUES (1, ?, ?)", (data, ts))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning("save_resources_cache: %s", e)


def load_resources_cache():
    try:
        with _DB_LOCK:
            conn = _init_db()
            cur = conn.execute("SELECT data, ts FROM resources_cache WHERE id = 1")
            row = cur.fetchone()
            conn.close()
            if row:
                return json.loads(row[0]), row[1]
    except Exception as e:
        logger.warning("load_resources_cache: %s", e)
    return None, None


# ── ui state ────────────────────────────────────────────────────



def save_ui_state(key: str, value: str):
    try:
        with _DB_LOCK:
            conn = _init_db()
            conn.execute("INSERT OR REPLACE INTO ui_state (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning("save_ui_state(%s): %s", key, e)


def load_ui_state(key: str) -> str | None:
    try:
        with _DB_LOCK:
            conn = _init_db()
            cur = conn.execute("SELECT value FROM ui_state WHERE key = ?", (key,))
            row = cur.fetchone()
            conn.close()
            return row[0] if row else None
    except Exception as e:
        logger.warning("load_ui_state(%s): %s", key, e)
        return None


def load_tree_notes() -> dict[str, str]:
    """Load all user tree notes, keyed by item key strings ("kind:name")."""
    try:
        with _DB_LOCK:
            conn = _init_db()
            cur = conn.execute("SELECT key, note FROM tree_notes")
            rows = cur.fetchall()
            conn.close()
            return {k: n for k, n in rows}
    except Exception as e:
        logger.warning("load_tree_notes: %s", e)
        return {}


def save_tree_note(key: str, note: str):
    """Store a tree item note; an empty note removes the entry."""
    try:
        with _DB_LOCK:
            conn = _init_db()
            if note.strip():
                conn.execute(
                    "INSERT OR REPLACE INTO tree_notes (key, note) VALUES (?, ?)",
                    (key, note.strip()),
                )
            else:
                conn.execute("DELETE FROM tree_notes WHERE key = ?", (key,))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning("save_tree_note(%s): %s", key, e)


# ── translations ────────────────────────────────────────────────



def seed_translations(lang: str, translations: dict[str, str], version: int = 0):
    try:
        with _DB_LOCK:
            conn = _init_db()
            if version:
                cur = conn.execute(
                    "SELECT value FROM ui_state WHERE key = 'i18n_version'"
                )
                row = cur.fetchone()
                stored = 0
                try:
                    stored = int(row[0]) if row else 0
                except (TypeError, ValueError):
                    stored = 0
                if stored != version:
                    conn.execute("DELETE FROM translations")
                    conn.execute(
                        "INSERT OR REPLACE INTO ui_state (key, value) VALUES ('i18n_version', ?)",
                        (str(version),),
                    )
            inserted = 0
            for msgid, msgstr in translations.items():
                cur = conn.execute(
                    "SELECT 1 FROM translations WHERE lang = ? AND msgid = ?",
                    (lang, msgid),
                )
                if cur.fetchone() is None:
                    conn.execute(
                        "INSERT INTO translations (lang, msgid, msgstr) VALUES (?, ?, ?)",
                        (lang, msgid, msgstr),
                    )
                    inserted += 1
            conn.commit()
            conn.close()
            if inserted:
                logger.info("Seeded %d translations for %s", inserted, lang)
    except Exception as e:
        logger.warning("seed_translations(%s): %s", lang, e)
