"""Performans sayaçları (PDH, pywin32 win32pdh) — Görev Yöneticisi'nin kullandığı sayaçlar.

Yalnızca örnekleyici iş parçacığında kullan (ilk toplama yavaş olabilir). İngilizce sayaç adları
(AddEnglishCounter) her dildeki Windows'ta çalışır. Oran sayaçları iki toplamadan sonra değer verir."""
import re

from ..config import log_error

FMT = 0x00000200 | 0x00008000           # PDH_FMT_DOUBLE | PDH_FMT_NOCAP100

GPU_RE = re.compile(r"pid_(\d+)_luid_0x([0-9a-f]+)_0x([0-9a-f]+)_phys_(\d+)_eng_(\d+)_engtype_(.*)$", re.I)
LUID_RE = re.compile(r"luid_0x([0-9a-f]+)_0x([0-9a-f]+)", re.I)


class Counters:
    def __init__(self):
        import win32pdh
        self._pdh = win32pdh
        self.query = win32pdh.OpenQuery()
        self.handles = {}

    def add(self, name, path):
        try:
            self.handles[name] = self._pdh.AddEnglishCounter(self.query, path)
            return True
        except Exception as e:                  # sayaç bu sistemde yok (ör. eski Windows'ta GPU sayaçları)
            log_error(f"PDH {path}: {e!r}")
            return False

    def collect(self):
        try:
            self._pdh.CollectQueryData(self.query)
        except Exception:
            pass

    def value(self, name):
        h = self.handles.get(name)
        if h is None:
            return None
        try:
            return self._pdh.GetFormattedCounterValue(h, FMT)[1]
        except Exception:
            return None

    def array(self, name):
        """Joker (*) sayaç -> {örnek adı: değer}; okunamazsa {}."""
        h = self.handles.get(name)
        if h is None:
            return {}
        try:
            return self._pdh.GetFormattedCounterArray(h, FMT)
        except Exception:
            return {}

    def close(self):
        try:
            self._pdh.CloseQuery(self.query)
        except Exception:
            pass


def luid_of(instance):
    m = LUID_RE.search(instance or "")
    return (int(m.group(1), 16) << 32) | int(m.group(2), 16) if m else None


def gpu_engines(arr):
    """GPU Engine dizisi -> (adapters, per_pid)
    adapters: {luid: {"util": %, "types": {"3D": %, "Copy": %, …}}}  (motor başına toplam; tür = en meşgul motor)
    per_pid:  {pid: (%, "3D", luid)}  (sürecin en meşgul motoru — Görev Yöneticisi'nin GPU sütunu gibi)"""
    engines = {}            # (luid, eng) -> [type, toplam]
    per_pid = {}
    for inst, val in arr.items():
        m = GPU_RE.match(inst)
        if not m:
            continue
        pid = int(m.group(1))
        luid = (int(m.group(2), 16) << 32) | int(m.group(3), 16)
        eng = int(m.group(5))
        typ = m.group(6).strip() or "?"
        e = engines.setdefault((luid, eng), [typ, 0.0])
        e[1] += val
        cur = per_pid.get(pid)
        if cur is None or val > cur[0]:
            per_pid[pid] = (val, typ, luid)
    adapters = {}
    for (luid, _eng), (typ, total) in engines.items():
        a = adapters.setdefault(luid, {"util": 0.0, "types": {}})
        total = min(100.0, total)
        a["types"][typ] = max(a["types"].get(typ, 0.0), total)
        a["util"] = max(a["util"], total)
    return adapters, per_pid
