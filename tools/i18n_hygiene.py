#!/usr/bin/env python3
"""i18n dictionary hygiene (audit U32/U33).

Modes:
  report (default) — print counts of:
      - missing keys: code tr() literals absent from a locale JSON
        (the CI gate in tests/ui/test_i18n_coverage.py enforces this);
      - stale keys: JSON entries no tr() call references (candidates
        for removal — review the list before pruning);
      - duplicate values: different keys translated identically inside
        one locale (suspicious copy-paste or a legitimately identical
        phrase — the tool only reports, never merges).
  prune — remove stale keys from every locale JSON (after review).

Extraction is AST-based (Call(func=Name('tr'), args=[Const(str)])),
same as the coverage test. Dynamic tr(variable) keys are out of scope.

Usage:
    .venv/bin/python tools/i18n_hygiene.py            # report
    .venv/bin/python tools/i18n_hygiene.py prune      # drop stale keys
"""
import ast
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
# U32: tr() is consumed outside the UI package too (config.py password
# dialogs) — scan the whole application source.
_PKG_DIR = _ROOT / "virtdeck"
_UI_DIR = _ROOT / "virtdeck" / "ui"
_JSON_LANGS = ("ru", "ar", "zh", "fr", "es")

# Dynamic tr() sources the AST extractor cannot see (U32): keys reaching
# tr() through a variable — status names, confirm messages, storage type
# field labels, metric labels, the name-conflict dialog prefix (joined
# at runtime) — plus the trn() plural-form convention "<base>|<category>".
_DYNAMIC_KEYS = frozenset((
    # utils._STATUS_KEYS
    "running", "stopped", "paused", "error", "offline", "online",
    "unknown", "mounted",
    # vm_actions._CONFIRM_MESSAGES values
    "Force stop VM {vmid}? Unsaved data will be lost.",
    "Force reset VM {vmid}?",
    "Send ACPI shutdown to VM {vmid}?",
    # storage_config_dialog._TYPE_FIELDS labels
    "Path", "Server", "Export", "Share", "Username", "Password",
    "Pool", "VG name", "Thin pool", "Monitors", "Datastore", "Fingerprint",
    # vm_metrics_widget._METRIC_KEYS labels
    "CPU", "RAM", "Network", "Disk",
    # form_pattern.add_section titles (translated via tr(title) inside)
    "Selection", "Backup", "Schedule", "Retention and notes",
    "VM info", "Migration target",
    # fleet_health._SECTIONS titles (translated via tr(title) in the scan)
    "Backup compliance", "Version drift", "Storage runway",
    "Snapshot sprawl",
    # mainwindow conflict dialog: tr(prefix + "\n".join(labels)) — the
    # prefix is now extracted programmatically from the BinOp.
))
_PLURAL_RE = re.compile(r"^[^\s|]+\|(one|two|few|many|other|zero)$")


def _extract_tr_keys() -> set[str]:
    """Every string that can reach tr() in virtdeck/ui (AST-based).

    Covered: tr("literal"), tr("a" + joined parts — Constant leaves of a
    BinOp), add_section(form, "title") (the form primitive translates the
    title itself), plus the hand-maintained _DYNAMIC_KEYS for keys that
    reach tr() through runtime variables.
    """
    keys: set[str] = set()
    for path in sorted(_PKG_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "tr":
                keys.update(_constant_leaves(node.args[0]))
            elif (isinstance(node.func, ast.Name) and node.func.id == "add_section"
                    and len(node.args) >= 2):
                keys.update(_constant_leaves(node.args[1]))
    return keys | set(_DYNAMIC_KEYS)


def _constant_leaves(node: ast.AST) -> set[str]:
    """The static string prefix of an expression.

    tr("literal") -> the literal. tr("a" "\n" "b" + runtime_expr) -> "ab"
    (the leading all-constant run of the Add chain — the runtime key
    starts with it, so it is the translatable prefix). A dynamic first
    element yields nothing.
    """
    def flatten(n):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            return flatten(n.left) + flatten(n.right)
        return [n]

    prefix = []
    for item in flatten(node):
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            prefix.append(item.value)
        else:
            break
    return {"".join(prefix)} if prefix else set()


def _load_dicts() -> dict[str, dict[str, str]]:
    out = {}
    for lang in _JSON_LANGS:
        out[lang] = json.loads((_UI_DIR / "i18n" / f"{lang}.json").read_text(
            encoding="utf-8"))
    return out


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "report"
    if mode not in ("report", "prune"):
        print(__doc__)
        return 2

    code_keys = _extract_tr_keys()
    dicts = _load_dicts()
    exit_code = 0

    # ── missing: code ⊆ dictionary (CI gate parity) ──
    for lang, data in dicts.items():
        missing = sorted(k for k in code_keys if k not in data)
        if missing:
            print(f"[missing] {lang}: {len(missing)}")
            for k in missing[:20]:
                print(f"    {k!r}")
            exit_code = 1

    # ── stale: dictionary ⊄ code (candidates for pruning) ──
    keep = _DYNAMIC_KEYS
    stale_by_lang: dict[str, set[str]] = {}
    for lang, data in dicts.items():
        stale = sorted(k for k in data if k not in code_keys
                       and k not in keep and not _PLURAL_RE.match(k))
        stale_by_lang[lang] = set(stale)

    # Keys that are stale in EVERY locale are true orphans; keys stale in
    # one locale only signal drift between locales — report both.
    common_stale = set.intersection(*stale_by_lang.values()) \
        if stale_by_lang else set()
    if common_stale:
        print(f"[stale] {len(common_stale)} keys unused by any tr() literal:")
        for k in sorted(common_stale):
            print(f"    {k!r}")
    for lang, stale in stale_by_lang.items():
        drift = sorted(stale - common_stale)
        if drift:
            print(f"[drift] {lang}: {len(drift)} keys absent from other "
                  f"locales' stale set (locale drift):")
            for k in drift[:20]:
                print(f"    {k!r}")

    # ── duplicate values inside one locale (U33) ──
    for lang, data in dicts.items():
        seen: dict[str, list[str]] = {}
        for k, v in data.items():
            seen.setdefault(v, []).append(k)
        dups = {v: ks for v, ks in seen.items() if len(ks) > 1}
        if dups:
            print(f"[dup-values] {lang}: {len(dups)} shared translations")
            for v, ks in sorted(dups.items())[:10]:
                print(f"    {ks!r} -> {v!r}")

    if mode == "prune":
        if not common_stale:
            print("prune: nothing to remove")
            return exit_code
        for lang, data in dicts.items():
            pruned = {k: v for k, v in data.items() if k not in common_stale}
            path = _UI_DIR / "i18n" / f"{lang}.json"
            ordered = dict(sorted(pruned.items()))
            path.write_text(
                json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            print(f"prune {lang}: {len(data) - len(pruned)} removed, "
                  f"{len(pruned)} kept")
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
