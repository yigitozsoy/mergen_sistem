"""Arayüz metinleri: mergen/locales/<dil>.json (Türkçe varsayılan, eksik anahtar Türkçeye düşer)."""
import json
import os

from .config import BASE_DIR, prefs

LANGS = ("tr", "en")
_cache = {}


def _load(lang):
    if lang not in _cache:
        try:
            with open(os.path.join(BASE_DIR, "locales", lang + ".json"), "r", encoding="utf-8") as f:
                _cache[lang] = json.load(f)
        except (OSError, ValueError):
            _cache[lang] = {}
    return _cache[lang]


def lang():
    v = prefs.get("language", "tr")
    return v if v in LANGS else "tr"


def is_tr():
    return lang() == "tr"


def t(key, **kw):
    s = _load(lang()).get(key)
    if s is None:
        s = _load("tr").get(key, key)
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return s
    return s
