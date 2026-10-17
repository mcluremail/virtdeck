"""CI gate: every key that can reach tr() must exist in every shipped
locale dictionary (audit U26).

Extraction rules live in tools/i18n_hygiene.py (U32/U33) so the gate and
the prune report can never disagree: tr("literal"), tr("a" + joined
prefix), add_section(form, "title"), plus an explicit allow-list for
keys that reach tr() through runtime variables.
"""
import json
import sys
from pathlib import Path

_UI_DIR = Path(__file__).resolve().parents[2] / "virtdeck" / "ui"
_JSON_LANGS = ("ru", "ar", "zh", "fr", "es")

# U32/U33: the extraction rules live in one place — the hygiene tool —
# so the CI gate and the prune report can never disagree.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from i18n_hygiene import _extract_tr_keys  # noqa: E402


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
