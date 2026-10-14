import base64
import json
import logging
import os
import sqlite3
import sys
import threading
import unicodedata
import uuid

logger = logging.getLogger(__name__)

CONFIG_DB = "config.sqlite"
_OLD_DB = "tasks_cache.sqlite"
_OLD_ENC = "nodes.enc"
_OLD_SALT = "nodes.salt"
_OLD_JSON = "nodes.json"

_KEYRING_SERVICE = "virtdeck"
_KEYRING_SERVICE_LEGACY = "pvecenter"  # pre-3.0 name (PVECenter era)
_DB_LOCK = threading.RLock()

# Stage 5.1.2: True while conn_ids assigned at load exist only in memory.
# Resource cache writes are blocked in this state (see
# save_resources_cache) — the cache must never hold identifiers that the
# persistent config does not confirm yet.
_conn_ids_pending = False


def conn_ids_pending() -> bool:
    """True while assigned conn_ids are not anchored in the stored config."""
    return _conn_ids_pending


# ── name policy (stage 5.1) ────────────────────────────────────

def normalize_name(name: str) -> str:
    """Single name-normalization policy: NFC + strip outer whitespace."""
    return unicodedata.normalize("NFC", str(name)).strip()


def name_key(name: str) -> str:
    """Case-insensitive identity key used for uniqueness checks."""
    return normalize_name(name).casefold()


def _new_conn_id() -> str:
    """Stable connection identity, independent of the display name."""
    return uuid.uuid4().hex

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


def _save_token_if_changed(name: str, token_value: str):
    """Write the secret only when it actually changed (stage 5.1.1 §4:
    re-imports and repeated saves must not churn the keyring)."""
    kr = _get_keyring()
    if kr is None:
        logger.warning("keyring not available, token for %s not saved", name)
        return
    try:
        current = kr.get_password(_KEYRING_SERVICE, _keyring_key(name))
    except Exception:
        current = None
    if current == token_value:
        return
    _save_token(name, token_value)


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
    for field in ("name", "host", "user", "token_name", "token_value", "group"):
        val = cfg.get(field, "")
        if val and not _validate_field(val):
            raise ValueError(f"Invalid characters in {field}")


def mark_ambiguous(config_list: list[dict]) -> None:
    """Flag entries whose normalized names collide (stage 5.1.1 §3).

    Colliding entries are NOT merged, renamed or removed: they stay
    visible with their own tokens and are excluded from refresh, cache
    restore and token operations by the callers. The user resolves the
    conflict explicitly. The flags are recomputed from scratch: shrinking
    a group to one member clears its flag.
    """
    for cfg in config_list:
        if isinstance(cfg, dict):
            cfg.pop("_ambiguous", None)
    groups: dict[str, list[dict]] = {}
    for cfg in config_list:
        groups.setdefault(name_key(cfg.get("name", "")), []).append(cfg)
    for members in groups.values():
        if len(members) > 1:
            for cfg in members:
                cfg["_ambiguous"] = True


def ambiguous_name_keys(config_list: list[dict]) -> frozenset[str]:
    """Normalized name keys of entries flagged as ambiguous."""
    return frozenset(
        name_key(c.get("name", "")) for c in config_list if c.get("_ambiguous"))


def load_config() -> list[dict]:
    """Load nodes from sqlite, attach token_value from keyring.

    Stage 5.1.2: entries without conn_id get one assigned, and the changed
    rows are persisted in a single transaction BEFORE any refresh or cache
    can consume the ids (write-only-what-changed: subsequent loads without
    a save do not rewrite anything). On persistence failure the ids stay
    in memory, conn_ids_pending() turns True and resource cache writes are
    blocked until a successful save_config() anchors them. Entries whose
    names collide after normalization are flagged ``_ambiguous`` — they
    are not merged, renamed or removed.
    """
    global _conn_ids_pending
    for fn in (_OLD_DB,):
        _migrate_file(fn)
    _migrate_old_db()

    with _DB_LOCK:
        conn = _init_db()
        cur = conn.execute("SELECT name, data FROM nodes")
        rows = cur.fetchall()

        config = []
        changed = []  # (pk_name, json_with_conn_id)
        for pk_name, raw in rows:
            try:
                cfg = json.loads(raw)
            except Exception:
                logger.warning("load_config: skipping corrupt row %r", pk_name)
                continue
            disk_name = cfg.get("name", "")
            if not disk_name or not _validate_field(disk_name):
                logger.warning("load_config: skipping row %r with invalid name",
                               pk_name)
                continue
            # The stored name stays the display truth; normalization is
            # applied on write and for comparisons (name_key).
            if not cfg.get("conn_id"):
                cfg["conn_id"] = _new_conn_id()
                clean = {k: v for k, v in cfg.items()
                         if k != "token_value" and not k.startswith("_")}
                changed.append((pk_name, json.dumps(clean, ensure_ascii=False)))
            token = _load_token(disk_name)
            cfg["token_value"] = token or ""
            config.append(cfg)

        if changed:
            try:
                for pk_name, new_json in changed:
                    conn.execute(
                        "INSERT OR REPLACE INTO nodes (name, data) VALUES (?, ?)",
                        (pk_name, new_json))
                conn.commit()
                _conn_ids_pending = False
            except Exception as e:
                conn.rollback()
                _conn_ids_pending = True
                logger.warning(
                    "load_config: conn_id migration not persisted (%s); "
                    "resource cache writes stay blocked until the config "
                    "is saved successfully", e)
        conn.close()

    mark_ambiguous(config)
    return config


def save_config(config_list: list[dict]):
    """Save nodes to sqlite, token_value to keyring.

    Stage 5.1: names are normalized (NFC + strip) and must be unique up to
    that normalization. Stage 5.1.3 (owner review): enforcement is central
    here — the only tolerated conflicts are the ones already stored in the
    database, and a stored conflict group can only SHRINK. Saving more
    members under a conflicting normalized name than are currently stored
    raises ValueError, so no caller can widen the allowance (the removed
    ``known_ambiguous`` parameter allowed exactly that: import computed its
    allowance from the very list being saved). A conflict group loaded from
    a legacy database can be kept as-is, shrunk or dropped, never grown.
    Validation happens before the database is touched, so a raise leaves
    the stored config and the keyring untouched. conn_id is assigned to
    entries missing one, so every saved row is anchored; a successful save
    also clears the conn_ids_pending state.
    """
    global _conn_ids_pending
    prepared = []  # (name, json, token_value)
    new_counts: dict[str, int] = {}
    first_name: dict[str, str] = {}
    for cfg in config_list:
        if not isinstance(cfg, dict):
            continue
        name = normalize_name(cfg.get("name", ""))
        if not name:
            continue
        cfg["name"] = name
        _sanitize_cfg(cfg)
        key = name_key(name)
        new_counts[key] = new_counts.get(key, 0) + 1
        first_name.setdefault(key, name)
        if not cfg.get("conn_id"):
            cfg["conn_id"] = _new_conn_id()
        store = {k: v for k, v in cfg.items()
                 if k != "token_value" and not k.startswith("_")}
        prepared.append((name, json.dumps(store, ensure_ascii=False),
                         cfg.get("token_value")))

    with _DB_LOCK:
        conn = _init_db()
        stored_counts: dict[str, int] = {}
        for (row_name,) in conn.execute("SELECT name FROM nodes").fetchall():
            k = name_key(row_name)
            stored_counts[k] = stored_counts.get(k, 0) + 1
        # Shrink-only rule: a group that conflicts under normalization must
        # already exist in the stored config with at least as many members.
        for key, count in new_counts.items():
            stored = stored_counts.get(key, 0)
            if count > 1 and stored < count:
                raise ValueError(
                    f'Duplicate connection name: "{first_name[key]}" '
                    f"({count} connections share the normalized name, "
                    f"{stored} stored) — a conflict group may only shrink")
        conn.execute("DELETE FROM nodes")
        for name, data_json, _token in prepared:
            conn.execute("INSERT OR REPLACE INTO nodes (name, data) VALUES (?, ?)",
                         (name, data_json))
        conn.commit()
        conn.close()
    for name, _data_json, token_value in prepared:
        if token_value:
            _save_token_if_changed(name, token_value)
    # every saved row carries a conn_id — the ids are anchored now
    _conn_ids_pending = False


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
    """Normalize and filter imported entries.

    Returns ``(entries, skipped)`` where skipped is a list of
    ``(name, reason)`` pairs. Each entry is normalized (NFC + strip on the
    name), must carry name/host/user and must pass _sanitize_cfg; a bad
    entry is skipped with a reason instead of aborting the whole import.
    ``conn_id`` never survives validation: a file-borne id is not proof of
    identity (stage 5.1.1 §4).
    """
    entries, skipped = [], []
    for cfg in imported:
        if not isinstance(cfg, dict):
            skipped.append(("", "not an object"))
            continue
        name = normalize_name(cfg.get("name", ""))
        host = str(cfg.get("host", "")).strip()
        user = cfg.get("user", "")
        if not name or not host or not user:
            skipped.append((name or host or "?", "missing name/host/user"))
            continue
        try:
            _sanitize_cfg(cfg)
        except ValueError as e:
            skipped.append((name, str(e)))
            continue
        clean = {k: v for k, v in cfg.items() if k in _ALLOWED_IMPORT_FIELDS}
        clean["name"] = name
        entries.append(clean)
    return entries, skipped


def _import_key(cfg: dict) -> tuple:
    """Identity key for import matching (stage 5.1.1 §4).

    ``type`` must participate: a PBS entry at the same address as a PVE
    entry is a different connection. ``host`` compares case-insensitively
    (DNS names); ``port``/``proxy`` are attributes, not identity.
    """
    return (str(cfg.get("type", "pve")),
            str(cfg.get("host", "")).strip().casefold(),
            str(cfg.get("user", "")))


def import_config(src_path: str, merge: bool = True,
                  report: list[str] | None = None) -> list[dict] | None:
    """Import encrypted bundle.

    Returns the resulting config list (None on hard failure). When
    ``report`` is a list, it is filled with human-readable lines
    describing updated/added/skipped connections for the UI.

    Modes (stage 5.1.1 §4):
    - ``merge=True`` — merge: existing entries are matched by
      (type, host, user); the LOCAL name and conn_id are kept and only
      credential/option fields are imported; new entries get fresh local
      conn_ids — a file-borne conn_id is never accepted, so a foreign
      bundle cannot attach local cache rows.
    - ``merge=False`` — full replace: the bundle becomes the whole config
      and every entry gets a FRESH local conn_id. There is no reliable way
      to tell a same-installation backup from a transfer, so no cache is
      attached to restored entries — data is re-fetched from the server
      instead of risking resources of a foreign infrastructure.
    """
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

    def _rep(msg: str):
        if report is not None:
            report.append(msg)

    imported, skipped = _validate_imported(imported)
    for name, reason in skipped:
        _rep(tr("Skipped {name}: {reason}").format(name=name, reason=reason))
    if not imported:
        QMessageBox.warning(None, tr("Error"),
                             tr("No valid server entries found in the bundle."))
        return None

    if not merge:
        for cfg in imported:
            cfg["conn_id"] = _new_conn_id()
        mark_ambiguous(imported)
        save_config(imported)
        return imported

    current = load_config()
    by_key: dict[tuple, list[dict]] = {}
    for c in current:
        by_key.setdefault(_import_key(c), []).append(c)
    merged = list(current)
    taken_names = {name_key(c.get("name", "")) for c in merged}
    matched_keys: set[tuple] = set()
    for imp in imported:
        key = _import_key(imp)
        matches = by_key.get(key, [])
        if key in matched_keys:
            _rep(tr("Skipped {name}: an earlier entry already matched "
                    "this connection").format(name=imp["name"]))
            continue
        if len(matches) > 1:
            _rep(tr("Skipped {name}: {count} local connections match — "
                    "resolve manually").format(name=imp["name"],
                                               count=len(matches)))
            continue
        if matches:
            existing = matches[0]
            if existing.get("_ambiguous"):
                _rep(tr("Skipped {name}: the local connection has an "
                        "unresolved name conflict").format(name=imp["name"]))
                continue
            # keep local identity, import attributes
            for k, v in imp.items():
                if k in _ALLOWED_IMPORT_FIELDS and k != "name":
                    existing[k] = v
            matched_keys.add(key)
            _rep(tr("Updated {name}").format(name=existing.get("name", "?")))
        else:
            nk = name_key(imp["name"])
            if nk in taken_names:
                _rep(tr("Skipped {name}: a connection with this name "
                        "already exists").format(name=imp["name"]))
                continue
            imp["conn_id"] = _new_conn_id()
            merged.append(imp)
            taken_names.add(nk)
            matched_keys.add(key)
            _rep(tr("Added {name}").format(name=imp["name"]))
    mark_ambiguous(merged)
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
    if _conn_ids_pending:
        # Stage 5.1.2 §2.1: the cache must never contain conn_ids that the
        # persistent config does not confirm — e.g. ids assigned at load
        # whose migration write failed and that would vanish on restart.
        logger.warning(
            "save_resources_cache skipped: conn_id migration is not "
            "anchored in the stored config yet")
        return
    try:
        # Error stubs of the current session (status="error") are not cached:
        # the cache holds "last successful data", and load-time stubs
        # create duplicates in the tree (the real host node arrives with
        # a short name while the stub is created with the config's FQDN).
        # Stage 5.1.2 §2.1: rows without conn_id are not cached either —
        # a row that cannot be attributed to a connection could never be
        # restored and must not occupy the cache.
        def _attributed(o):
            if isinstance(o, dict):
                return o.get("status") != "error" and o.get("conn_id")
            return (getattr(o, "status_value", "") != "error"
                    and getattr(o, "conn_id", ""))
        nodes = [
            dict(o) if not isinstance(o, dict) else o
            for o in nodes
            if _attributed(o)
        ]
        vms = [
            dict(o) if not isinstance(o, dict) else o
            for o in vms
            if _attributed(o)
        ]
        storages = [
            dict(o) if not isinstance(o, dict) else o
            for o in storages
            if _attributed(o)
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
