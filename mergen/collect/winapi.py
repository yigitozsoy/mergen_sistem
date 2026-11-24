"""Küçük Win32 yardımcıları (ctypes + winreg): yönetici gerektirmez, hata olursa None döner."""
import ctypes
import winreg
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32


def reg(root, path, name, default=None, wow64=False):
    """Kayıt defteri değeri; yoksa default. root: winreg.HKEY_LOCAL_MACHINE …"""
    flags = winreg.KEY_READ | (winreg.KEY_WOW64_32KEY if wow64 else winreg.KEY_WOW64_64KEY)
    try:
        with winreg.OpenKey(root, path, 0, flags) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


HKLM = winreg.HKEY_LOCAL_MACHINE
HKCU = winreg.HKEY_CURRENT_USER


# ---------------------------------------------------------------------- işletim sistemi
def firmware_type():
    """"uefi" / "bios" / None (GetFirmwareType)."""
    ft = ctypes.c_int(0)
    try:
        if kernel32.GetFirmwareType(ctypes.byref(ft)):
            return {1: "bios", 2: "uefi"}.get(ft.value)
    except Exception:
        pass
    return None


def secure_boot():
    v = reg(HKLM, r"SYSTEM\CurrentControlSet\Control\SecureBoot\State", "UEFISecureBootEnabled")
    return None if v is None else bool(v)


class TPM_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("structVersion", wintypes.UINT), ("tpmVersion", wintypes.UINT),
                ("tpmInterfaceType", wintypes.UINT), ("tpmImpRevision", wintypes.UINT)]


def tpm():
    """TPM sürümü ("2.0" / "1.2"), yoksa False, okunamazsa None. TBS API yönetici istemez."""
    try:
        tbs = ctypes.windll.tbs
    except OSError:
        return None
    info = TPM_DEVICE_INFO()
    info.structVersion = 1
    try:
        r = tbs.Tbsi_GetDeviceInfo(ctypes.sizeof(info), ctypes.byref(info)) & 0xFFFFFFFF
    except Exception:
        return None
    if r == 0:
        return {1: "1.2", 2: "2.0"}.get(info.tpmVersion, str(info.tpmVersion))
    if r == 0x8028400F:            # TBS_E_TPM_NOT_FOUND
        return False
    return None


def ui_language():
    buf = ctypes.create_unicode_buffer(85)
    try:
        lcid = kernel32.GetUserDefaultUILanguage()
        if lcid and kernel32.LCIDToLocaleName(lcid, buf, 85, 0):
            return buf.value
    except Exception:
        pass
    return None


def user_locale():
    buf = ctypes.create_unicode_buffer(85)
    try:
        if kernel32.GetUserDefaultLocaleName(buf, 85):
            return buf.value
    except Exception:
        pass
    return None


def region():
    """Ülke/bölge kodu (ör. "TR")."""
    try:
        geo = kernel32.GetUserGeoID(16)        # GEOCLASS_NATION
        buf = ctypes.create_unicode_buffer(16)
        if kernel32.GetGeoInfoW(geo, 4, buf, 16, 0):   # GEO_ISO2
            return buf.value
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------- işlemci
PF = {   # IsProcessorFeaturePresent sabitleri (eski Windows bazılarını tanımaz -> False)
    "MMX": 3, "SSE": 6, "SSE2": 10, "SSE3": 13, "SSSE3": 36, "SSE4.1": 37, "SSE4.2": 38,
    "AVX": 39, "AVX2": 40, "AVX-512F": 41, "NX": 12, "RDRAND": 28,
}


def cpu_features():
    out = []
    for name, code in PF.items():
        try:
            if kernel32.IsProcessorFeaturePresent(code):
                out.append(name)
        except Exception:
            pass
    return out


def virt_firmware_enabled():
    try:
        return bool(kernel32.IsProcessorFeaturePresent(21))   # PF_VIRT_FIRMWARE_ENABLED
    except Exception:
        return None


class CACHE_DESCRIPTOR(ctypes.Structure):
    _fields_ = [("Level", ctypes.c_ubyte), ("Associativity", ctypes.c_ubyte), ("LineSize", wintypes.WORD),
                ("Size", wintypes.DWORD), ("Type", wintypes.DWORD)]


class _SLPI_U(ctypes.Union):
    _fields_ = [("Flags", ctypes.c_ubyte), ("NodeNumber", wintypes.DWORD), ("Cache", CACHE_DESCRIPTOR),
                ("Reserved", ctypes.c_ulonglong * 2)]


class SLPI(ctypes.Structure):
    _fields_ = [("ProcessorMask", ctypes.c_size_t), ("Relationship", wintypes.DWORD), ("u", _SLPI_U)]


def cpu_caches():
    """[(düzey, tür, adet, tek boyut bayt)] — tür: "data" / "instruction" / "unified"."""
    n = wintypes.DWORD(0)
    kernel32.GetLogicalProcessorInformation(None, ctypes.byref(n))
    if not n.value:
        return []
    count = n.value // ctypes.sizeof(SLPI)
    arr = (SLPI * count)()
    if not kernel32.GetLogicalProcessorInformation(arr, ctypes.byref(n)):
        return []
    agg = {}
    for item in arr:
        if item.Relationship != 2:          # RelationCache
            continue
        c = item.u.Cache
        kind = {0: "unified", 1: "instruction", 2: "data"}.get(c.Type)
        if kind is None:
            continue
        key = (c.Level, kind, c.Size)
        agg[key] = agg.get(key, 0) + 1
    return sorted(((lv, kind, cnt, size) for (lv, kind, size), cnt in agg.items()),
                  key=lambda x: (x[0], x[1] != "data"))


def cpu_registry():
    base = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    rev = reg(HKLM, base, "Update Revision")
    micro = None
    if isinstance(rev, (bytes, bytearray)) and len(rev) >= 4:
        # 8 bayt: eski biçim, revizyon üst dword'de; 4 bayt: doğrudan revizyon
        v = (int.from_bytes(rev[4:8], "little") if len(rev) >= 8 else 0) or int.from_bytes(rev[0:4], "little")
        micro = f"0x{v:X}" if v else None
    return {"identifier": reg(HKLM, base, "Identifier"), "mhz": reg(HKLM, base, "~MHz"), "microcode": micro}
