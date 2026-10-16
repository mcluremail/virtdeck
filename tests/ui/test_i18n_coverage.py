"""CI gate: every tr() literal used in virtdeck/ui must exist in every
shipped locale dictionary (audit U26).

Extraction is AST-based: Call(func=Name('tr'), args=[Const(str)]).
Dynamic tr(variable) calls cannot be extracted — they degrade to the
English fallback by design and are out of scope here.

Keys are collected from the AST (not regex) so multi-line implicit
string concatenation inside tr(...) is handled correctly.
"""
import ast
import json
from pathlib import Path

_UI_DIR = Path(__file__).resolve().parents[2] / "virtdeck" / "ui"
_JSON_LANGS = ("ru", "ar", "zh", "fr", "es")


def _extract_tr_keys() -> set[str]:
    keys: set[str] = set()
    for path in sorted(_UI_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
    return keys


def test_tr_keys_present_in_every_locale():
    keys = _extract_tr_keys()
    assert keys, "AST extraction found no tr() keys — extractor is broken"
    for lang in _JSON_LANGS:
        data = json.loads((_UI_DIR / "i18n" / f"{lang}.json").read_text(
            encoding="utf-8"))
        missing = sorted(k for k in keys if k not in data)
        assert not missing, f"{lang}: untranslated tr() keys: {missing!r}"


def test_dictionaries_load_and_are_flat_strings():
    for lang in _JSON_LANGS:
        data = json.loads((_UI_DIR / "i18n" / f"{lang}.json").read_text(
            encoding="utf-8"))
        assert data, f"{lang}: dictionary is empty"
        bad = [k for k, v in data.items()
               if not isinstance(k, str) or not isinstance(v, str)]
        assert not bad, f"{lang}: non-string entries: {bad[:5]!r}"
