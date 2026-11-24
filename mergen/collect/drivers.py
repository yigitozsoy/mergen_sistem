"""Aygıt sürücüleri: Win32_PnPSignedDriver (sürüm, tarih, sağlayıcı, .inf, imza) + Win32_PnPEntity (sorun kodu,
servis) + kayıt defteri (servisin .sys yolu, .inf'in DriverStore klasörü). Win32_SystemDriver 7+ sn sürdüğü için
.sys yolu doğrudan Services\\<ad>\\ImagePath'ten okunur."""
import os
import winreg

from . import wmi
from .services import service_exe

# Aygıt Yöneticisi sorun kodları (CM_PROB_*) — en sık görülenler; diğerleri "Kod N" olarak gösterilir
PROBLEMS = {1: "prob_1", 3: "prob_3", 10: "prob_10", 12: "prob_12", 14: "prob_14", 18: "prob_18", 19: "prob_19",
            21: "prob_21", 22: "prob_22", 24: "prob_24", 28: "prob_28", 31: "prob_31", 32: "prob_32",
            37: "prob_37", 39: "prob_39", 41: "prob_41", 43: "prob_43", 45: "prob_45", 52: "prob_52"}
SYSROOT = os.environ.get("SystemRoot", r"C:\Windows")


def _reg(path, name=""):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def driver_store(inf):
    """oemNN.inf -> DriverStore\\FileRepository\\<paket> klasörü (yoksa None)."""
    if not inf:
        return None
    v = _reg(r"SYSTEM\DriverDatabase\DriverInfFiles" + "\\" + inf)
    if isinstance(v, list) and v:
        v = v[-1]
    if not v:
        return None
    p = os.path.join(SYSROOT, "System32", "DriverStore", "FileRepository", str(v))
    return p if os.path.isdir(p) else None


def collect():
    signed = {}
    for r in wmi.query("SELECT DeviceID,DeviceName,DeviceClass,DriverProviderName,DriverVersion,DriverDate,"
                       "InfName,IsSigned,Signer,Manufacturer FROM Win32_PnPSignedDriver"):
        if r.get("DeviceID"):
            signed[r["DeviceID"].upper()] = r
    rows = []
    sys_cache = {}
    for e in wmi.query("SELECT DeviceID,Name,PNPClass,Service,ConfigManagerErrorCode,Present,Manufacturer "
                       "FROM Win32_PnPEntity"):
        dev = e.get("DeviceID") or ""
        key = dev.upper()
        s = signed.get(key, {})
        svc = e.get("Service") or None
        sys_path = None
        if svc:
            if svc not in sys_cache:
                sys_cache[svc] = service_exe(_reg(r"SYSTEM\CurrentControlSet\Services" + "\\" + svc, "ImagePath"))
            sys_path = sys_cache[svc]
        inf = s.get("InfName")
        code = e.get("ConfigManagerErrorCode") or 0
        rows.append({
            "id": "dev:" + dev, "device": e.get("Name") or s.get("DeviceName") or dev,
            "class": e.get("PNPClass") or s.get("DeviceClass"),
            "provider": s.get("DriverProviderName"), "manufacturer": e.get("Manufacturer") or s.get("Manufacturer"),
            "version": s.get("DriverVersion"), "date": _date(s.get("DriverDate")),
            "inf": inf, "inf_path": os.path.join(SYSROOT, "INF", inf) if inf else None,
            "store": driver_store(inf) if inf and inf.lower().startswith("oem") else None,
            "service": svc, "sys": sys_path, "signed": s.get("IsSigned"), "signer": s.get("Signer"),
            "problem": code, "problem_key": PROBLEMS.get(code) if code else None, "device_id": dev,
            "present": e.get("Present") is not False,
        })
    return rows


def _date(v):
    d = wmi.cim_date(v)
    return d.date().isoformat() if d else None
