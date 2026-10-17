"""
i18n — Lightweight translation module.

All UI strings are written in English and wrapped in tr():
    self.setWindowTitle(tr("Add Server"))

Translations are stored in external JSON files (ru.json, ar.json, ...).
On set_language(), the JSON for the requested language is loaded lazily
and seeded into the SQLite translations table (via config.seed_translations).
Only the active language is held in memory — not all five.
"""

import json
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QLocale

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent

# Bump when built-in translations change structurally; forces re-seed.
_I18N_VERSION = 52

_current_lang = "en"
_current_dict: dict[str, str] = {}
_lock = threading.Lock()

_SUPPORTED_LANGUAGES = {
    "en": "English",
    "ru": "Русский",
    "ar": "العربية",
    "zh": "中文",
    "fr": "Français",
    "es": "Español",
}

# Languages that ship with a JSON file in this directory.
_JSON_LANGS = {"ru", "ar", "zh", "fr", "es"}

# U31: retranslatable module-level containers (tr_list/tr_dict builders).
# set_language() re-runs every builder so labels baked at import time do
# not keep the previous language (mixed-language UI without a restart).
_RETARGETS: list = []


def tr_list(builder):
    """A list built with tr() that re-translates on language change."""
    lst = builder()

    def _retranslate():
        lst[:] = builder()

    _RETARGETS.append(_retranslate)
    return lst


def tr_dict(builder):
    """A dict built with tr() that re-translates on language change."""
    d = builder()

    def _retranslate():
        d.clear()
        d.update(builder())

    _RETARGETS.append(_retranslate)
    return d


def _load_json(lang: str) -> dict[str, str]:
    """Load translations for *lang* from the sibling JSON file."""
    path = _DATA_DIR / f"{lang}.json"
    if not path.is_file():
        logger.warning("i18n JSON not found: %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.error("i18n JSON root is not an object: %s", path)
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except Exception as e:
        logger.error("Failed to load i18n JSON %s: %s", path, e)
        return {}


def set_language(lang: str):
    """Set current language (e.g. 'en', 'ru').
    Loads the JSON for that language (if shipped) and seeds built-in
    translations into the DB on first use for non-English languages.
    """
    global _current_lang, _current_dict
    with _lock:
        _current_lang = lang
        if lang in _JSON_LANGS:
            _current_dict = _load_json(lang)
            from ...config import seed_translations
            seed_translations(lang, _current_dict, version=_I18N_VERSION)
        else:
            _current_dict = {}
    # U31: module-level label tables are rebuilt with the new dictionary
    for retranslate in list(_RETARGETS):
        try:
            retranslate()
        except Exception:
            logger.exception("retranslate failed for %r", retranslate)
    logger.info("Language set to %s", lang)


def get_language() -> str:
    return _current_lang


def supported_languages() -> dict[str, str]:
    """Return dict of language code -> native name."""
    return dict(_SUPPORTED_LANGUAGES)


def tr(text: str) -> str:
    """Translate a string to the current language.
    Falls back to the original English text if no translation exists.
    """
    if _current_lang == "en":
        return text
    return _current_dict.get(text, text)


# U30: CLDR plural categories for the shipped languages. ru needs all
# three Slavic forms; ar the six Arabic ones; en/fr/es two; zh one.
def _plural_category(n: int) -> str:
    n = int(n)
    lang = _current_lang
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if lang == "ar":
        if n == 0:
            return "zero"
        if n == 1:
            return "one"
        if n == 2:
            return "two"
        if 3 <= n % 100 <= 10:
            return "few"
        if 11 <= n % 100 <= 99:
            return "many"
        return "other"
    if lang == "fr":
        return "one" if n <= 1 else "many"
    if lang in ("es",):
        return "one" if n == 1 else "many"
    # en, zh (and any future language without special rules)
    return "one" if n == 1 else "other"


def trn(one: str, other: str, n: int) -> str:
    """Plural-aware tr() (U30): "1 узел / 2 узла / 5 узлов".

    Dictionary convention: "<one>|one", "<one>|few", "<one>|many", ...
    hold the inflected forms; the fallback chain is category form ->
    "<one>|other" -> the plain "<one>" key -> the English argument.

    Usage: f"{n} {trn('node', 'nodes', n)}".
    """
    if _current_lang == "en":
        return one if n == 1 else other
    cat = _plural_category(n)
    d = _current_dict
    for key in (f"{one}|{cat}", f"{one}|other"):
        if key in d:
            return d[key]
    return one if n == 1 else other


def current_locale():
    """QLocale for the current interface language (Д12/GAP-9)."""
    return QLocale(_current_lang)


def format_datetime(dt) -> str:
    """Д12: dates follow the interface locale, not a hard-coded format."""
    return current_locale().toString(dt, QLocale.FormatType.ShortFormat)


def format_date(dt) -> str:
    """Д12: date-only variant (token expiry etc.)."""
    return current_locale().toString(dt.date() if hasattr(dt, "date") else dt,
                                     QLocale.FormatType.ShortFormat)


def format_time(dt) -> str:
    """Д12: time-only variant (fleet "today" branch)."""
    return current_locale().toString(
        dt.time() if hasattr(dt, "time") else dt,
        QLocale.FormatType.ShortFormat)
