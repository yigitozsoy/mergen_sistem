"""Clevo tabanlı dizüstüler (Monster, Tulpar, Casper Excalibur, Schenker/XMG, System76 …) — Control Center 3.0'ın
kullandığı InsydeDCHU.dll → AcpiBridge1.sys yolu.

- DLL Clevo'nundur: mergen onu kopyalamaz/dağıtmaz; CCDCHUService servisinin DriverStore klasöründen yüklenir.
- Okuma: GetDCHU_Data_Buffer (12 = canlı fan/sıcaklık, 13 = yetenekler) ve ReadAppSettings.
- Yazma: SetDCHU_Data / WriteAppSettings bu modülde hiç bağlanmaz. Güç modu Control Center'ın yaptığı gibi
  OutLog olay günlüğüne "clevocc30^101^<mod>" yazılarak değiştirilir; Clevo'nun FnKey servisi mesajı alıp BIOS'a
  kendisi yazar (WMI cmd=121 SubCMD=25) ve yenileme hızı / fan tablosunu da ayarlar. Yönetici istemez; 2026-11-24'te
  kullanıcı onayıyla bu makinede doğrulandı (2 → 3 → 2). Klavye ve fan yazma her kod ayrı onaylanınca eklenecek.
- Komut kodları belgesizdir; açık kaynak projelerden derlendi (cc30-nova, OpenControl, ClevoFanControl) ve bu
  makinede doğrulandı (Abra A5 V17.2, InsydeDCHU 2026-03). Yönetici izni gerekmez.
- Bir GetDCHU_Data_Buffer çağrısı ~5–30 ms; arayüz bunu arka plan iş parçacığında, en sık 2 sn'de bir çağırır."""
import ctypes
import os
import threading

from .base import Vendor

SERVICE = "CCDCHUService"
DLL = "InsydeDCHU.dll"

# ReadAppSettings(sayfa, konum, uzunluk) — Control Center'ın kendi kayıtlı ayarları (BIOS/servis tarafı)
APP_POWER_MODE = (1, 1, 1)
APP_FAN_MODE = (4, 5, 1)
APP_FAN_OFFSET = (4, 7, 1)

POWER_EVENT_SOURCE = "PowerBIOSServer_Out"     # OutLog günlüğünün kaynağı (Clevo kurulumu kaydeder)
SETTABLE_POWER_MODES = (0, 1, 3, 2)             # Sessiz+ (4) her modelde yok: yalnızca okunur
POWER_MODES = {0: "quiet", 1: "power_saving", 2: "performance", 3: "entertainment", 4: "quiet_plus"}
FAN_MODES = {0: "auto", 1: "max", 5: "maxq", 6: "custom"}
FAN_NAMES = ["cpu", "gpu", "gpu2"]
# buffer 12: büyük-sonlu takometre [2..3] CPU, [4..5] GPU1, [6..7] GPU2; görev oranı [16] [19] [22]; sıcaklık [18] [21] [24]
_TACH = (2, 4, 6)
_DUTY = (16, 19, 22)
_TEMP = (18, 21, 24)
# DLL "256 bayt" arabelleğe 257 bayt yazıyor (bu makinede ölçüldü): daha küçük arabellek Python yığınını bozar → çökme.
BUF = 1024
CC_PROCESSES = ("controlcenter30.exe", "controlcenter3.exe", "controlcenter.exe")


def service_dir():
    """CCDCHUService'in exe klasörü (etkin DriverStore kopyası) ya da None."""
    from ..collect import winapi
    from ..collect.services import service_exe
    img = winapi.reg(winapi.HKLM, rf"SYSTEM\CurrentControlSet\Services\{SERVICE}", "ImagePath")
    if not img:
        return None
    exe = service_exe(img)
    return os.path.dirname(exe) if exe else None


def rpm(raw):
    """Takometre ham değeri → devir/dk (OpenControl: 60 / (5.565e-5 · raw) · 2)."""
    return round(2156250 / raw) if raw else 0


def parse_live(b, fans=2):
    out = []
    for i in range(max(1, min(fans, 3))):
        t = _TACH[i]
        raw = (b[t] << 8) | b[t + 1]
        out.append({"name": FAN_NAMES[i], "rpm": rpm(raw), "duty": round(b[_DUTY[i]] * 100 / 255),
                    "temp": b[_TEMP[i]] or None})
    return out


def control_center_running():
    """Control Center 3.0 açık mı (ikisi aynı anda fanı yönetirse birbirini ezer)."""
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if (p.info["name"] or "").lower() in CC_PROCESSES:
                return True
    except Exception:
        pass
    return False


class Clevo(Vendor):
    name = "Clevo"

    def __init__(self):
        self._dll = None
        self._lock = threading.Lock()
        self._caps = None

    def detect(self):
        d = service_dir()
        return bool(d and os.path.isfile(os.path.join(d, DLL)))

    # ---- DLL (yalnızca okuma işlevleri bağlanır)
    def _lib(self):
        if self._dll is None:
            d = service_dir()
            path = os.path.join(d, DLL) if d else None
            if not path or not os.path.isfile(path):
                raise OSError("InsydeDCHU.dll bulunamadı")
            with os.add_dll_directory(d):
                dll = ctypes.WinDLL(path)
            dll.GetDCHU_Data_Buffer.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte)]
            dll.GetDCHU_Data_Buffer.restype = ctypes.c_int
            dll.ReadAppSettings.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte)]
            dll.ReadAppSettings.restype = ctypes.c_int
            self._dll = dll
            self.dll_path = path
        return self._dll

    def _buffer(self, cmd):
        b = (ctypes.c_ubyte * BUF)()
        with self._lock:
            self._lib().GetDCHU_Data_Buffer(cmd, b)
        return bytes(b[:256])

    def _app(self, page, off, ln):
        b = (ctypes.c_ubyte * BUF)()
        with self._lock:
            self._lib().ReadAppSettings(page, off, ln, b)
        return bytes(b[:ln])

    # ---- arayüz
    def capabilities(self):
        if self._caps is None:
            b = self._buffer(13)
            fans = b[12] if 1 <= b[12] <= 3 else 2
            self._caps = {"fans": fans, "keyboard_type": b[15], "power_modes": list(POWER_MODES),
                          "fan_modes": list(FAN_MODES),
                          "settable_power_modes": list(SETTABLE_POWER_MODES), "write": ["power_mode"]}
        return self._caps

    def read(self):
        caps = self.capabilities()
        live = self._buffer(12)
        pm = self._app(*APP_POWER_MODE)[0]
        fm = self._app(*APP_FAN_MODE)[0]
        off = self._app(*APP_FAN_OFFSET)[0]
        return {"fans": parse_live(live, caps["fans"]), "power_mode": pm, "power_mode_key": POWER_MODES.get(pm),
                "fan_mode": fm, "fan_mode_key": FAN_MODES.get(fm), "fan_offset": off,
                "control_center": control_center_running()}

    # Fan ve klavye yazma henüz yok: her SetDCHU_Data kodu kullanıcı onayıyla tek tek eklenecek.
    def set_fan(self, *args, **kw):
        raise NotImplementedError("Clevo fan yazma henüz etkin değil")

    def set_power_mode(self, mode):
        """Güç modunu değiştirir (yalnızca kullanıcı onayından sonra çağrılır). Uygulanması ~1 sn sürer."""
        mode = int(mode)
        if mode not in SETTABLE_POWER_MODES:
            raise ValueError(f"geçersiz güç modu {mode}")
        import win32evtlog
        h = win32evtlog.RegisterEventSource(None, POWER_EVENT_SOURCE)
        try:
            win32evtlog.ReportEvent(h, win32evtlog.EVENTLOG_INFORMATION_TYPE, 0, 0, None, [f"clevocc30^101^{mode}"], None)
        finally:
            win32evtlog.DeregisterEventSource(h)

    def set_keyboard(self, *args, **kw):
        raise NotImplementedError("Clevo klavye yazma henüz etkin değil")


vendor = Clevo()
