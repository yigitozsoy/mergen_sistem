"""Yollar ve mergen tercihleri (%LOCALAPPDATA%\\mergen\\preferences.json)."""
import json
import os
import sys
import threading

LOCAL = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
# MERGEN_DATA_DIR: testler veriyi geçici klasöre yönlendirir
DATA_DIR = os.environ.get("MERGEN_DATA_DIR") or os.path.join(LOCAL, "mergen")
PREFS_FILE = os.path.join(DATA_DIR, "preferences.json")
ERROR_LOG = os.path.join(DATA_DIR, "error.log")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "mergen")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def asset(*parts):
    return os.path.join(BASE_DIR, "assets", *parts)


DEFAULTS = {
    # tamga ortak anahtarları (tamga_sync.SHARED)
    "language": "tr",
    "theme": "amoled",
    "dark_variant": "amoled",
    "light_variant": "white",
    "accent": "gray",
    # mergen
    "window_geometry": None,
    "window_maximized": False,
    "last_page": "system",
}


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path, data, indent=1):
    """Yarım dosya kalmasın: geçici dosyaya yazıp yerine koyar."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".mergen.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


class Prefs:
    def __init__(self, path=PREFS_FILE):
        self.path = path
        self.data = dict(DEFAULTS)
        self._lock = threading.Lock()
        self.data.update(read_json(path) or {})

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        return DEFAULTS.get(key, default)

    def set(self, key, value):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        self.save()

    def update(self, values):
        self.data.update(values)
        self.save()

    def save(self):
        with self._lock:
            try:
                write_json(self.path, self.data)
            except OSError:
                pass


prefs = Prefs()


def log_error(text):
    """error.log'a tarihli satır ekler; asla hata fırlatmaz."""
    import datetime
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {text.rstrip()}\n")
    except OSError:
        pass
