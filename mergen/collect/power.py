"""Windows güç planı, güç modu (kaydırıcı / overlay), güç kaynağı ve ekran parlaklığı.

Okuma yönetici istemez. Yazma işlevleri (set_*) yalnızca kullanıcı onayından sonra arayüzden çağrılır; plan ve güç modu
kullanıcı başına ayardır, yönetici istemez."""
import ctypes
import uuid
from ctypes import wintypes

from . import wmi

_pp = ctypes.WinDLL("powrprof")
_k32 = ctypes.WinDLL("kernel32")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, s):
        g = cls()
        ctypes.memmove(ctypes.byref(g), uuid.UUID(s).bytes_le, 16)
        return g

    def __str__(self):
        return str(uuid.UUID(bytes_le=bytes(self)))


# Ayarlar › Sistem › Güç: "Güç modu" (overlay). Pilde "daha iyi pil" ayrı bir GUID.
OVERLAYS = [
    ("961cc777-2547-4f9d-8174-7d86181b8a7a", "efficiency"),
    ("3af9b8d9-7c97-431d-ad78-34a8bfea439f", "better_battery"),
    ("00000000-0000-0000-0000-000000000000", "balanced"),
    ("ded574b5-45a0-4f42-8737-46345c09c238", "performance"),
]
OVERLAY_KEY = dict(OVERLAYS)
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"     # güç modu (overlay) yalnızca Dengeli planda seçilebilir
ACCESS_SCHEME = 16


def _friendly(guid):
    size = wintypes.DWORD(0)
    if _pp.PowerReadFriendlyName(None, ctypes.byref(guid), None, None, None, ctypes.byref(size)) != 0 or not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if _pp.PowerReadFriendlyName(None, ctypes.byref(guid), None, None, buf, ctypes.byref(size)) != 0:
        return None
    return ctypes.wstring_at(buf)


def plans():
    """[(guid, ad)] — powercfg /list ile aynı."""
    out = []
    i = 0
    while i < 64:
        g = GUID()
        size = wintypes.DWORD(ctypes.sizeof(g))
        if _pp.PowerEnumerate(None, None, None, ACCESS_SCHEME, i, ctypes.byref(g), ctypes.byref(size)) != 0:
            break
        out.append((str(g), _friendly(g) or str(g)))
        i += 1
    return out


def active_plan():
    p = ctypes.POINTER(GUID)()
    if _pp.PowerGetActiveScheme(None, ctypes.byref(p)) != 0 or not p:
        return None
    try:
        return str(p.contents)
    finally:
        _k32.LocalFree(p)


def overlay():
    """Etkin güç modu GUID'i (Windows 10 1709+). Yoksa None."""
    fn = getattr(_pp, "PowerGetEffectiveOverlayScheme", None)
    if fn is None:
        return None
    g = GUID()
    if fn(ctypes.byref(g)) != 0:
        return None
    return str(g)


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD)]


def power_status():
    """{"ac": True/False/None, "battery": % | None, "saver": bool}"""
    s = SYSTEM_POWER_STATUS()
    if not _k32.GetSystemPowerStatus(ctypes.byref(s)):
        return {"ac": None, "battery": None, "saver": False}
    return {"ac": {0: False, 1: True}.get(s.ACLineStatus),
            "battery": None if s.BatteryFlag & 128 or s.BatteryLifePercent == 255 else s.BatteryLifePercent,
            "saver": bool(s.SystemStatusFlag & 1)}


def brightness():
    """Dahili ekran parlaklığı (%) — WmiMonitorBrightness; harici ekranlarda yok → None. COM iş parçacığında çağır."""
    r = wmi.first("SELECT CurrentBrightness, Active FROM WmiMonitorBrightness", "root\\wmi", quiet=True)
    if not r or r.get("CurrentBrightness") is None:
        return None
    return int(r["CurrentBrightness"])


def collect():
    """Arka plan iş parçacığında (WMI)."""
    with wmi.com_thread():
        return {"plans": plans(), "active": active_plan(), "overlay": overlay(), "status": power_status(),
                "brightness": brightness()}


# ---- yazma (yalnızca kullanıcı onayından sonra)
def set_plan(guid):
    return _pp.PowerSetActiveScheme(None, ctypes.byref(GUID.of(guid))) == 0


def set_overlay(guid):
    fn = getattr(_pp, "PowerSetActiveOverlayScheme", None)
    return fn is not None and fn(ctypes.byref(GUID.of(guid))) == 0


def set_brightness(pct):
    """WmiSetBrightness; COM iş parçacığında çağır."""
    import win32com.client
    with wmi.com_thread():
        svc = win32com.client.GetObject("winmgmts:\\\\.\\root\\wmi")
        ok = False
        for m in svc.ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods"):
            m.WmiSetBrightness(0, max(0, min(100, int(pct))))
            ok = True
        return ok
