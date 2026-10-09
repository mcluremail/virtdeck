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

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent

# Bump when built-in translations change structurally; forces re-seed.
_I18N_VERSION = 36

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
