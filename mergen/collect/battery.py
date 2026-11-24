"""Pil: root\\WMI Battery* sınıfları (yönetici istemez); başarısızsa `powercfg /batteryreport /xml` yedeği.
Pilsiz bilgisayarda boş liste döner."""
import os
import re
import subprocess
import tempfile

from . import wmi

CHEMISTRY = {"LION": "Li-ion", "LIP": "Li-polymer", "LIPO": "Li-polymer", "PBAC": "Lead acid", "NICD": "NiCd",
             "NIMH": "NiMH", "NIZN": "NiZn", "RAM": "Alkaline"}


def _chem(v):
    if isinstance(v, int) and v:
        s = v.to_bytes(4, "little", signed=v < 0).decode("ascii", "ignore").strip("\x00 ").upper()
    else:
        s = str(v or "").strip().upper()
    return CHEMISTRY.get(s, s or None)


def _by_instance(rows):
    return {r.get("InstanceName"): r for r in rows}


def batteries():
    """[{name, manufacturer, serial, chemistry, design, full, health, cycles, remaining, voltage, charging, ac}]
    Kapasiteler mWh."""
    static = wmi.query("SELECT * FROM BatteryStaticData", "root\\wmi", quiet=True)
    if not static:
        if not wmi.query("SELECT DeviceID FROM Win32_Battery", quiet=True):
            return []
        return _powercfg()
    full = _by_instance(wmi.query("SELECT * FROM BatteryFullChargedCapacity", "root\\wmi", quiet=True))
    cycles = _by_instance(wmi.query("SELECT * FROM BatteryCycleCount", "root\\wmi", quiet=True))
    status = _by_instance(wmi.query("SELECT * FROM BatteryStatus", "root\\wmi", quiet=True))
    out = []
    for s in static:
        inst = s.get("InstanceName")
        d = {"name": wmi.clean(s.get("DeviceName")), "manufacturer": wmi.clean(s.get("ManufactureName")),
             "serial": wmi.clean(s.get("SerialNumber")), "chemistry": _chem(s.get("Chemistry")),
             "design": s.get("DesignedCapacity") or None}
        d["full"] = (full.get(inst) or {}).get("FullChargedCapacity") or None
        c = (cycles.get(inst) or {}).get("CycleCount")
        d["cycles"] = c if c else None          # 0 = üretici bildirmiyor
        st = status.get(inst) or {}
        d["remaining"] = st.get("RemainingCapacity")
        d["voltage"] = st.get("Voltage") or None
        d["charging"] = st.get("Charging")
        d["ac"] = st.get("PowerOnline")
        d["rate"] = st.get("ChargeRate") or -(st.get("DischargeRate") or 0) or None
        out.append(_health(d))
    return out


def _health(d):
    if d.get("design") and d.get("full"):
        d["health"] = round(min(100.0, d["full"] * 100 / d["design"]), 1)
    if d.get("full") and d.get("remaining") is not None:
        d["percent"] = round(min(100, d["remaining"] * 100 / d["full"]))
    return d


def _powercfg():
    """WMI pil sınıfları yoksa: powercfg pil raporu (XML) — birkaç saniye sürebilir."""
    path = os.path.join(tempfile.gettempdir(), f"mergen-battery-{os.getpid()}.xml")
    try:
        subprocess.run(["powercfg", "/batteryreport", "/xml", "/output", path], capture_output=True, timeout=30,
                       creationflags=0x08000000)
        xml = open(path, encoding="utf-8", errors="ignore").read()
    except (OSError, subprocess.SubprocessError):
        return []
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    out = []
    for block in re.findall(r"<Battery>(.*?)</Battery>", xml, re.S):
        def tag(name):
            m = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
            return m.group(1).strip() if m else None

        def num(name):
            try:
                return int(tag(name) or 0) or None
            except ValueError:
                return None
        out.append(_health({"name": tag("Id"), "manufacturer": tag("Manufacturer"), "serial": tag("SerialNumber"),
                            "chemistry": _chem(tag("Chemistry")), "design": num("DesignCapacity"),
                            "full": num("FullChargeCapacity"), "cycles": num("CycleCount")}))
    return out
