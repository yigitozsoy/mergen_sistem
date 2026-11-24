"""Ekranlar: QueryDisplayConfig (çözünürlük, yenileme, bağlantı, HDR, bağlı GPU) + WmiMonitorID / EDID
(üretici, model, seri, üretim yılı) + fiziksel boyut + ölçek (GetDpiForMonitor)."""
import ctypes
import math
from ctypes import wintypes

from . import wmi
from .dxgi import LUID

user32 = ctypes.windll.user32


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class PATH_SOURCE(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class PATH_TARGET(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_int32), ("rotation", ctypes.c_uint32), ("scaling", ctypes.c_uint32),
                ("refreshRate", RATIONAL), ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", wintypes.BOOL),
                ("statusFlags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE), ("targetInfo", PATH_TARGET), ("flags", ctypes.c_uint32)]


class SOURCE_MODE(ctypes.Structure):
    _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32), ("pixelFormat", ctypes.c_uint32),
                ("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MODE_U(ctypes.Union):
    _fields_ = [("source", SOURCE_MODE), ("raw", ctypes.c_ubyte * 48)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", LUID), ("u", _MODE_U)]


class HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", LUID), ("id", ctypes.c_uint32)]


class SOURCE_NAME(ctypes.Structure):
    _fields_ = [("header", HEADER), ("viewGdiDeviceName", wintypes.WCHAR * 32)]


class TARGET_NAME(ctypes.Structure):
    _fields_ = [("header", HEADER), ("flags", ctypes.c_uint32), ("outputTechnology", ctypes.c_int32),
                ("edidManufactureId", ctypes.c_uint16), ("edidProductCodeId", ctypes.c_uint16),
                ("connectorInstance", ctypes.c_uint32), ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
                ("monitorDevicePath", wintypes.WCHAR * 128)]


class ADV_COLOR(ctypes.Structure):
    _fields_ = [("header", HEADER), ("value", ctypes.c_uint32), ("colorEncoding", ctypes.c_uint32),
                ("bitsPerColorChannel", ctypes.c_uint32)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


CONNECTION = {0: "VGA", 4: "DVI", 5: "HDMI", 6: "LVDS", 9: "SDI", 10: "DisplayPort", 11: "eDP",
              12: "UDI", 13: "UDI", 15: "Miracast", 16: "USB", 17: "virtual", -2147483648: "internal"}

# EDID üretici kodu (PNP ID) -> ad
PNP = {"GSM": "LG", "LGD": "LG Display", "SAM": "Samsung", "SDC": "Samsung Display", "BOE": "BOE",
       "AUO": "AU Optronics", "SHP": "Sharp", "CMN": "Innolux", "CSO": "CSOT", "TMX": "Tianma", "IVO": "InfoVision",
       "DEL": "Dell", "ACR": "Acer", "AUS": "ASUS", "HWP": "HP", "HPN": "HP", "LEN": "Lenovo", "BNQ": "BenQ",
       "AOC": "AOC", "PHL": "Philips", "MSI": "MSI", "GBT": "Gigabyte", "VSC": "ViewSonic", "IVM": "iiyama",
       "SNY": "Sony", "APP": "Apple", "NEC": "NEC", "ENC": "EIZO", "HSD": "HannStar", "MEI": "Panasonic",
       "XMI": "Xiaomi", "HKC": "HKC", "KTC": "KTC", "AMR": "Arzopa", "PRI": "Prima", "MSF": "Microsoft",
       "RTK": "Realtek", "VSN": "Virtual", "CHI": "Chimei"}


def _wstr(arr):
    try:
        return "".join(chr(c) for c in arr if c).strip() or None
    except (TypeError, ValueError):
        return None


def _key_from_path(path):
    """\\\\?\\DISPLAY#GSM5C19#4&24ea6b94&0&UID4145#{guid} -> DISPLAY\\GSM5C19\\4&24EA6B94&0&UID4145"""
    p = path.replace("\\\\?\\", "").split("#")
    return "\\".join(p[:3]).upper() if len(p) >= 3 else path.upper()


def _key_from_instance(inst):
    s = (inst or "").upper()
    return s[:-2] if s.endswith("_0") else s


def _dpi_scales():
    """GDI adı (\\\\.\\DISPLAY1) -> ölçek yüzdesi. Geçici olarak monitör başına DPI farkındalığıyla ölçülür."""
    out = {}
    try:
        shcore = ctypes.windll.shcore
    except OSError:
        return out
    prev = None
    try:
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        prev = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
    except Exception:
        pass
    try:
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                   wintypes.LPARAM)

        def cb(hmon, _hdc, _rc, _lp):
            mi = MONITORINFOEXW()
            mi.cbSize = ctypes.sizeof(mi)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                x, y = wintypes.UINT(), wintypes.UINT()
                if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(x), ctypes.byref(y)) == 0 and x.value:
                    out[mi.szDevice] = round(x.value * 100 / 96)
            return True
        user32.EnumDisplayMonitors(None, None, proto(cb), 0)
    except Exception:
        pass
    finally:
        if prev:
            try:
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(prev))
            except Exception:
                pass
    return out


def displays(gpu_names=None):
    """[{name, manufacturer, model_code, serial, year, connection, width, height, refresh, hdr_supported,
    hdr_enabled, bits, scale, size_cm, diagonal, gpu, primary}]. gpu_names: {luid: ad}."""
    gpu_names = gpu_names or {}
    np_, nm = ctypes.c_uint32(), ctypes.c_uint32()
    if user32.GetDisplayConfigBufferSizes(2, ctypes.byref(np_), ctypes.byref(nm)) != 0:
        return []
    paths = (PATH_INFO * np_.value)()
    modes = (MODE_INFO * nm.value)()
    if user32.QueryDisplayConfig(2, ctypes.byref(np_), paths, ctypes.byref(nm), modes, None) != 0:
        return []

    edid = {}
    for r in wmi.query("SELECT InstanceName,ManufacturerName,ProductCodeID,SerialNumberID,UserFriendlyName,"
                       "YearOfManufacture,WeekOfManufacture FROM WmiMonitorID", "root\\wmi", quiet=True):
        edid[_key_from_instance(r.get("InstanceName"))] = r
    size = {}
    for r in wmi.query("SELECT InstanceName,MaxHorizontalImageSize,MaxVerticalImageSize "
                       "FROM WmiMonitorBasicDisplayParams", "root\\wmi", quiet=True):
        size[_key_from_instance(r.get("InstanceName"))] = (r.get("MaxHorizontalImageSize"), r.get("MaxVerticalImageSize"))
    scales = _dpi_scales()

    out = []
    for i in range(np_.value):
        p = paths[i]
        t = p.targetInfo
        d = {}
        sn = SOURCE_NAME()
        sn.header.type, sn.header.size = 1, ctypes.sizeof(sn)
        sn.header.adapterId, sn.header.id = p.sourceInfo.adapterId, p.sourceInfo.id
        gdi = sn.viewGdiDeviceName if user32.DisplayConfigGetDeviceInfo(ctypes.byref(sn)) == 0 else None
        tn = TARGET_NAME()
        tn.header.type, tn.header.size = 2, ctypes.sizeof(tn)
        tn.header.adapterId, tn.header.id = t.adapterId, t.id
        devpath = None
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(tn)) == 0:
            d["name"] = tn.monitorFriendlyDeviceName or None
            devpath = tn.monitorDevicePath
        tech = t.outputTechnology
        d["connection"] = CONNECTION.get(tech)
        d["internal"] = tech in (6, 11, 13, -2147483648)
        if p.sourceInfo.modeInfoIdx < nm.value and modes[p.sourceInfo.modeInfoIdx].infoType == 1:
            sm = modes[p.sourceInfo.modeInfoIdx].u.source
            d["width"], d["height"] = sm.width, sm.height
            d["primary"] = sm.x == 0 and sm.y == 0
        rr = t.refreshRate
        if rr.Denominator:
            d["refresh"] = round(rr.Numerator / rr.Denominator, 2)
        ac = ADV_COLOR()
        ac.header.type, ac.header.size = 9, ctypes.sizeof(ac)
        ac.header.adapterId, ac.header.id = t.adapterId, t.id
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(ac)) == 0:
            d["hdr_supported"] = bool(ac.value & 1)
            d["hdr_enabled"] = bool(ac.value & 2)
            d["bits"] = ac.bitsPerColorChannel or None
        luid = (t.adapterId.HighPart << 32) | t.adapterId.LowPart
        d["gpu"] = gpu_names.get(luid)
        d["scale"] = scales.get(gdi) if gdi else None
        if devpath:
            key = _key_from_path(devpath)
            e = edid.get(key)
            if e:
                code = _wstr(e.get("ManufacturerName") or [])
                d["manufacturer"] = PNP.get(code, code)
                d["model_code"] = (code or "") + (_wstr(e.get("ProductCodeID") or []) or "")
                d["name"] = d.get("name") or _wstr(e.get("UserFriendlyName") or [])
                serial = _wstr(e.get("SerialNumberID") or [])
                d["serial"] = serial if serial and serial.strip("0") else None
                d["year"] = e.get("YearOfManufacture") or None
            sz = size.get(key)
            if sz and sz[0] and sz[1]:
                d["size_cm"] = f"{sz[0]} × {sz[1]} cm"
                d["diagonal"] = round(math.hypot(sz[0], sz[1]) / 2.54, 1)
        out.append(d)
    out.sort(key=lambda x: (not x.get("primary"), not x.get("internal")))
    return out
