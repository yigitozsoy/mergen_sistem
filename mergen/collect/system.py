"""Sistem sekmesinin verisi (dxdiag gibi): bölüm bölüm toplar. Arayüzden bağımsız, arka plan iş parçacığında çalışır.

Her bölüm ayrı try/except içinde: biri başarısız olursa yalnızca o bölüm "okunamadı" notu taşır.
Biçim için bkz. fmt.py (satır / bölüm / değer türleri)."""
import datetime
import getpass
import os
import platform
import re
import socket
import subprocess
import time
import traceback

from . import battery as bat
from . import dxgi, edid, wmi
from . import winapi as W
from .fmt import B, DATE, DT, K, L, MHz, N, ON, YES, row
from ..config import log_error

SECTIONS = ["general", "cpu", "board", "memory", "gpu", "display", "storage", "network", "audio", "usb",
            "bluetooth", "battery"]

# Genel / boş üretici adı veren ODM'ler: model adından ya da sürücü izlerinden gerçek marka / üretici
BRANDS = [(r"^(ABRA|TULPAR|SEMRUK|HUMA|ALBA|MARKUS)\b", "Monster Notebook"),
          (r"^EXCALIBUR\b", "Casper"), (r"^(NITRO|PREDATOR)\b", "Acer"), (r"^(ROG|TUF)\b", "ASUS")]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _section(sid, fn, *args):
    try:
        rows, groups = fn(*args)
        return {"id": sid, "rows": rows, "groups": groups}
    except Exception as e:
        log_error(f"system.{sid}: {traceback.format_exc()}")
        return {"id": sid, "rows": [row("lbl_error", K("val_read_failed", e=type(e).__name__))], "groups": []}


# ---------------------------------------------------------------------- genel
def _odm(manufacturer, model, board_mfr):
    """(marka, gerçek üretici / ODM) tahmini."""
    brand = odm = None
    for pat, name in BRANDS:
        if model and re.search(pat, model, re.I):
            brand = name
            break
    svc = W.reg(W.HKLM, r"SYSTEM\CurrentControlSet\Services\CCDCHUService", "ImagePath")
    generic = (manufacturer or "").lower() in ("notebook", "clevo", "") or (board_mfr or "").lower() == "notebook"
    if svc or (generic and (manufacturer or "").lower() in ("notebook", "clevo")):
        odm = "Clevo"
    elif "tongfang" in f"{manufacturer} {board_mfr}".lower():
        odm = "TongFang"
    return brand, odm


def general():
    cs = wmi.first("SELECT Name,Manufacturer,Model,SystemType,HypervisorPresent,PCSystemType FROM Win32_ComputerSystem")
    os_ = wmi.first("SELECT Caption,Version,BuildNumber,InstallDate,LastBootUpTime,OSArchitecture,SerialNumber "
                    "FROM Win32_OperatingSystem")
    prod = wmi.first("SELECT IdentifyingNumber,UUID FROM Win32_ComputerSystemProduct")
    board = wmi.first("SELECT Manufacturer FROM Win32_BaseBoard")
    nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    display_ver = W.reg(W.HKLM, nt, "DisplayVersion") or W.reg(W.HKLM, nt, "ReleaseId")
    build = W.reg(W.HKLM, nt, "CurrentBuild") or os_.get("BuildNumber")
    ubr = W.reg(W.HKLM, nt, "UBR")
    caption = (os_.get("Caption") or platform.platform()).replace("Microsoft ", "")
    lic = wmi.first("SELECT LicenseStatus FROM SoftwareLicensingProduct WHERE PartialProductKey IS NOT NULL "
                    "AND ApplicationID='55c92734-d682-4d71-983e-d6ec3f16059f'", quiet=True)
    act = {0: "val_unlicensed", 1: "val_activated", 2: "val_grace", 3: "val_grace", 4: "val_grace",
           5: "val_notification", 6: "val_grace"}.get(lic.get("LicenseStatus"))
    key = wmi.first("SELECT OA3xOriginalProductKey FROM SoftwareLicensingService", quiet=True).get(
        "OA3xOriginalProductKey")
    manufacturer, model = wmi.clean(cs.get("Manufacturer")), wmi.clean(cs.get("Model"))
    brand, odm = _odm(manufacturer, model, wmi.clean(board.get("Manufacturer")))
    boot = wmi.cim_date(os_.get("LastBootUpTime"))
    up = None
    try:
        import psutil
        up = int(time.time() - psutil.boot_time())
    except Exception:
        pass
    fw = W.firmware_type()
    tpm = W.tpm()
    rows = [
        row("lbl_computer_name", cs.get("Name") or socket.gethostname(), "r"),
        row("lbl_manufacturer", manufacturer),
        row("lbl_model", model),
    ]
    if brand:
        rows.append(row("lbl_brand", brand))
    if odm:
        rows.append(row("lbl_odm", odm))
    rows += [
        row("lbl_system_type", K({1: "val_desktop", 2: "val_laptop", 3: "val_workstation"}.get(
            cs.get("PCSystemType"), "val_unknown"))),
        row("lbl_serial", wmi.clean(prod.get("IdentifyingNumber")), True),
        row("lbl_uuid", wmi.clean(prod.get("UUID")), True),
        row("lbl_windows", f"{caption} {display_ver}".strip() if display_ver else caption),
        row("lbl_build", f"{build}.{ubr}" if build and ubr is not None else build),
        row("lbl_arch", os_.get("OSArchitecture")),
        row("lbl_install_date", DATE(wmi.cim_date(os_.get("InstallDate")))),
        row("lbl_last_boot", DT(boot)),
        row("lbl_uptime", K("val_uptime", d=up // 86400, h=up % 86400 // 3600, m=up % 3600 // 60) if up else None),
        row("lbl_user", getpass.getuser(), "r"),
        row("lbl_ui_language", W.ui_language()),
        row("lbl_locale", L([W.user_locale(), W.region()])),
        row("lbl_activation", K(act) if act else None),
        row("lbl_product_id", W.reg(W.HKLM, nt, "ProductId") or os_.get("SerialNumber"), True),
        row("lbl_product_key", key or None, True),
        row("lbl_firmware", {"uefi": "UEFI", "bios": K("val_legacy_bios")}.get(fw)),
        row("lbl_secure_boot", ON(W.secure_boot())),
        row("lbl_tpm", tpm if tpm else (K("val_none") if tpm is False else None)),
        row("lbl_hypervisor", YES(cs.get("HypervisorPresent"))),
    ]
    return rows, []


# ---------------------------------------------------------------------- işlemci
def cpu():
    procs = wmi.query("SELECT Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,"
                      "SocketDesignation,VirtualizationFirmwareEnabled,ProcessorId FROM Win32_Processor")
    cs = wmi.first("SELECT HypervisorPresent FROM Win32_ComputerSystem")
    reg = W.cpu_registry()
    caches = W.cpu_caches()
    feats = W.cpu_features()
    rows, groups = [], []
    for i, p in enumerate(procs or [{}]):
        r = [
            row("lbl_cpu_name", wmi.clean(p.get("Name")) or platform.processor()),
            row("lbl_vendor", {"GenuineIntel": "Intel", "AuthenticAMD": "AMD"}.get(p.get("Manufacturer"),
                                                                                    p.get("Manufacturer"))),
            row("lbl_cores", p.get("NumberOfCores")),
            row("lbl_threads", p.get("NumberOfLogicalProcessors") or os.cpu_count()),
            row("lbl_base_clock", MHz(p.get("MaxClockSpeed") or reg.get("mhz"))),
            row("lbl_socket", wmi.clean(p.get("SocketDesignation"))),
            row("lbl_cpu_id", reg.get("identifier")),
            row("lbl_microcode", reg.get("microcode")),
        ]
        if i == 0:
            for lv, kind, cnt, size in caches:
                label = {"data": "lbl_cache_l1d", "instruction": "lbl_cache_l1i"}.get(kind) if lv == 1 else f"lbl_cache_l{lv}"
                r.append(row(label, K("val_cache", n=cnt, size=B(size)) if cnt > 1 else B(size)))
            if cs.get("HypervisorPresent"):
                virt = K("val_virt_hyperv")
            else:
                v = p.get("VirtualizationFirmwareEnabled")
                virt = ON(v if v is not None else W.virt_firmware_enabled())
            r.append(row("lbl_virtualization", virt))
            r.append(row("lbl_instructions", L(feats)))
        if len(procs) > 1:
            groups.append({"title": K("val_cpu_n", n=i + 1), "rows": r})
        else:
            rows = r
    return rows, groups


# ---------------------------------------------------------------------- anakart
def _chipset():
    """LPC/ISA köprüsünden yonga seti: "Intel(R) LPC Controller (HM570) - 438B" -> ("Intel", "HM570", ad)."""
    devs = wmi.query("SELECT Name,Manufacturer,CompatibleID,DeviceID FROM Win32_PnPEntity WHERE DeviceID LIKE 'PCI%'",
                     quiet=True)
    for want in ("CC_0601", "CC_0C05"):         # ISA köprüsü, yoksa SMBus denetleyicisi
        for d in devs:
            if any(c.endswith(want) for c in (d.get("CompatibleID") or [])):
                name = d.get("Name") or ""
                ven = re.search(r"VEN_([0-9A-F]{4})", d.get("DeviceID") or "", re.I)
                vendor = dxgi.VENDORS.get(int(ven.group(1), 16)) if ven else None
                m = re.search(r"\(([A-Z]{1,3}\d{3,4}[A-Z]?)\)", name)
                if not m:
                    m = re.search(r"\b([ABHQWXZ]\d{3}[A-Z]?|[A-Z]{1,2}\d{3,4})\b(?= (Series|Chipset|LPC))", name)
                return vendor, (m.group(1) if m else None), name
    return None, None, None


def board():
    bb = wmi.first("SELECT Manufacturer,Product,Version,SerialNumber FROM Win32_BaseBoard")
    bios = wmi.first("SELECT Manufacturer,SMBIOSBIOSVersion,ReleaseDate,SerialNumber,SMBIOSMajorVersion,"
                     "SMBIOSMinorVersion FROM Win32_BIOS")
    enc = wmi.first("SELECT ChassisTypes,SerialNumber,SMBIOSAssetTag FROM Win32_SystemEnclosure")
    vendor, chip, chip_dev = _chipset()
    breg = r"HARDWARE\DESCRIPTION\System\BIOS"
    ec_major, ec_minor = W.reg(W.HKLM, breg, "ECFirmwareMajorRelease"), W.reg(W.HKLM, breg, "ECFirmwareMinorRelease")
    smb = (bios.get("SMBIOSMajorVersion"), bios.get("SMBIOSMinorVersion"))
    rows = [
        row("lbl_manufacturer", wmi.clean(bb.get("Manufacturer"))),
        row("lbl_model", wmi.clean(bb.get("Product"))),
        row("lbl_version", wmi.clean(bb.get("Version"))),
        row("lbl_serial", wmi.clean(bb.get("SerialNumber")), True),
        row("lbl_chipset", " ".join(x for x in (vendor, chip) if x) or None),
        row("lbl_chipset_device", chip_dev),
        row("lbl_bios_vendor", wmi.clean(bios.get("Manufacturer"))),
        row("lbl_bios_version", wmi.clean(bios.get("SMBIOSBIOSVersion"))),
        row("lbl_bios_date", DATE(wmi.cim_date(bios.get("ReleaseDate")))),
        row("lbl_bios_serial", wmi.clean(bios.get("SerialNumber")), True),
        row("lbl_smbios", f"{smb[0]}.{smb[1]}" if smb[0] else None),
        row("lbl_ec_version", f"{ec_major}.{ec_minor}" if ec_major not in (None, 255) else None),
        row("lbl_chassis_serial", wmi.clean(enc.get("SerialNumber")), True),
        row("lbl_asset_tag", wmi.clean(enc.get("SMBIOSAssetTag")) if "no asset" not in str(
            enc.get("SMBIOSAssetTag")).lower() else None, True),
    ]
    return rows, []


# ---------------------------------------------------------------------- bellek
MEM_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4",
             34: "DDR5", 35: "LPDDR5"}
FORM = {8: "DIMM", 12: "SO-DIMM", 13: "SRIMM", 9: "RIMM"}


def memory():
    mods = wmi.query("SELECT BankLabel,DeviceLocator,Capacity,Speed,ConfiguredClockSpeed,Manufacturer,PartNumber,"
                     "SerialNumber,SMBIOSMemoryType,FormFactor,ConfiguredVoltage FROM Win32_PhysicalMemory")
    arr = wmi.query("SELECT MemoryDevices,MaxCapacityEx,MaxCapacity FROM Win32_PhysicalMemoryArray")
    cs = wmi.first("SELECT TotalPhysicalMemory FROM Win32_ComputerSystem")
    avail = None
    try:
        import psutil
        avail = psutil.virtual_memory().available
    except Exception:
        pass
    installed = sum(_int(m.get("Capacity")) or 0 for m in mods)
    slots = sum(_int(a.get("MemoryDevices")) or 0 for a in arr)
    maxcap = sum((_int(a.get("MaxCapacityEx")) or _int(a.get("MaxCapacity")) or 0) for a in arr) * 1024
    chans = set()
    for m in mods:
        loc = f"{m.get('DeviceLocator') or ''} {m.get('BankLabel') or ''}"
        ch = re.search(r"channel\s*-?\s*([a-h])\b", loc, re.I) or re.search(r"\bchannel([a-h])", loc, re.I)
        ctl = re.search(r"controller\s*(\d+)", loc, re.I)
        if ch:
            chans.add(((ctl.group(1) if ctl else "0"), ch.group(1).upper()))
    channel = {1: "val_single_channel", 2: "val_dual_channel", 3: "val_triple_channel",
               4: "val_quad_channel"}.get(len(chans))
    types = {MEM_TYPES.get(m.get("SMBIOSMemoryType")) for m in mods} - {None}
    speeds = {m.get("ConfiguredClockSpeed") or m.get("Speed") for m in mods} - {None, 0}
    rows = [
        row("lbl_installed", B(installed)),
        row("lbl_usable", B(cs.get("TotalPhysicalMemory"))),
        row("lbl_available", B(avail)),
        row("lbl_mem_type", L(sorted(types))),
        row("lbl_mem_speed", L([f"{s} MT/s" for s in sorted(speeds)])),
        row("lbl_channels", K(channel) if channel else None),
        row("lbl_slots", K("val_slots", used=len(mods), total=slots) if slots else len(mods) or None),
        row("lbl_max_capacity", B(maxcap)),
    ]
    groups = []
    for m in mods:
        title = wmi.clean(m.get("DeviceLocator")) or wmi.clean(m.get("BankLabel")) or "—"
        volt = m.get("ConfiguredVoltage")
        groups.append({"title": title, "rows": [
            row("lbl_size", B(m.get("Capacity"))),
            row("lbl_mem_type", " ".join(x for x in (MEM_TYPES.get(m.get("SMBIOSMemoryType")),
                                                     FORM.get(m.get("FormFactor"))) if x) or None),
            row("lbl_speed", f"{m.get('Speed')} MT/s" if m.get("Speed") else None),
            row("lbl_configured_speed", f"{m.get('ConfiguredClockSpeed')} MT/s" if m.get("ConfiguredClockSpeed") else None),
            row("lbl_voltage", N(volt / 1000, "V", 2) if volt else None),
            row("lbl_manufacturer", wmi.clean(m.get("Manufacturer"))),
            row("lbl_part_number", wmi.clean(m.get("PartNumber"))),
            row("lbl_serial", wmi.clean(m.get("SerialNumber")), True),
            row("lbl_bank", wmi.clean(m.get("BankLabel"))),
        ]})
    for _ in range(max(0, slots - len(mods))):
        groups.append({"title": K("val_empty_slot"), "rows": []})
    return rows, groups


# ---------------------------------------------------------------------- ekran kartı
def gpu(adapters):
    vcs = wmi.query("SELECT Name,DriverVersion,DriverDate,PNPDeviceID,VideoModeDescription,CurrentRefreshRate,"
                    "InfSection,InstalledDisplayDrivers FROM Win32_VideoController")
    nv = dxgi.nvidia()
    groups = []
    for a in [x for x in adapters if not x.get("software")]:
        vc = next((v for v in vcs if f"VEN_{a['vendor_id']:04X}&DEV_{a['device_id']:04X}"
                   in (v.get("PNPDeviceID") or "").upper()), {})
        n = next((x for x in nv if x.get("device_id") == a["device_id"]), {}) if a["vendor_id"] == 0x10DE else {}
        fl = a.get("feature_level")
        rows = [
            row("lbl_vendor", a.get("vendor")),
            row("lbl_vram", B(a.get("dedicated"))),
            row("lbl_shared_mem", B(a.get("shared"))),
            row("lbl_driver_version", wmi.clean(vc.get("DriverVersion"))),
            row("lbl_driver_version_vendor", n.get("driver")),
            row("lbl_driver_date", DATE(wmi.cim_date(vc.get("DriverDate")))),
            row("lbl_wddm", a.get("wddm")),
            row("lbl_dx_feature", fl.replace("_", ".") if fl else (K("val_no_d3d12") if not a.get("d3d12") else None)),
            row("lbl_shader_model", a.get("shader_model")),
            row("lbl_dx12_ultimate", YES(a.get("dx12_ultimate")) if a.get("d3d12") else None),
            row("lbl_raytracing", (K("val_tier", v=a["raytracing"]) if a.get("raytracing") else K("val_no"))
                if a.get("d3d12") else None),
            row("lbl_mesh_shader", YES(a.get("mesh_shader"))),
            row("lbl_vrs", K("val_tier", v=a["vrs_tier"]) if a.get("vrs_tier") else None),
            row("lbl_pcie", n.get("pcie") and (f"{n['pcie']} (max {n['pcie_max'].replace('PCIe ', '')})"
                                               if n.get("pcie_max") and n["pcie_max"] != n["pcie"] else n["pcie"])),
            row("lbl_power_limit", f"{n['power_limit']} W" if n.get("power_limit") else None),
            row("lbl_vbios", n.get("vbios")),
            row("lbl_device_id", f"{a['vendor_id']:04X}:{a['device_id']:04X}"),
        ]
        groups.append({"title": a["name"], "rows": rows})
    if not groups:                       # DXGI yoksa (ör. çok eski sistem / uzak masaüstü) WMI'dan
        for v in vcs:
            groups.append({"title": wmi.clean(v.get("Name")) or "—", "rows": [
                row("lbl_driver_version", wmi.clean(v.get("DriverVersion"))),
                row("lbl_driver_date", DATE(wmi.cim_date(v.get("DriverDate"))))]})
    return [], groups


def display(adapters):
    names = {a["luid"]: a["name"] for a in adapters}
    groups = []
    for d in edid.displays(names):
        title = d.get("name") or (K("val_internal_display") if d.get("internal") else K("val_display"))
        res = f"{d['width']} × {d['height']}" if d.get("width") else None
        hdr = None
        if d.get("hdr_supported") is not None:
            hdr = K("val_hdr_on") if d.get("hdr_enabled") else (K("val_hdr_off") if d["hdr_supported"] else K("val_no"))
        groups.append({"title": title, "badge": K("val_primary") if d.get("primary") else None, "rows": [
            row("lbl_manufacturer", d.get("manufacturer")),
            row("lbl_model_code", d.get("model_code")),
            row("lbl_resolution", res),
            row("lbl_refresh", N(d["refresh"], "Hz", 0 if float(d["refresh"]).is_integer() else 2) if d.get("refresh") else None),
            row("lbl_scale", N(d["scale"], "%") if d.get("scale") else None),
            row("lbl_hdr", hdr),
            row("lbl_color_depth", K("val_bits", n=d["bits"]) if d.get("bits") else None),
            row("lbl_connection", K("val_internal") if d.get("connection") == "internal" else d.get("connection")),
            row("lbl_physical_size", L([d["size_cm"], N(d["diagonal"], "in", 1)]) if d.get("size_cm") else None),
            row("lbl_manufacture_year", d.get("year")),
            row("lbl_connected_gpu", d.get("gpu")),
            row("lbl_serial", d.get("serial"), True),
        ]})
    return [], groups


# ---------------------------------------------------------------------- depolama
BUS = {1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "IEEE 1394", 5: "SSA", 6: "Fibre Channel", 7: "USB", 8: "RAID",
       9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC", 15: "File-backed virtual", 16: "Storage Spaces",
       17: "NVMe", 18: "SCM", 19: "UFS"}
MEDIA = {3: "HDD", 4: "SSD", 5: "SCM"}
HEALTH = {0: "val_healthy", 1: "val_warning", 2: "val_unhealthy"}


def storage():
    pds = wmi.query("SELECT DeviceId,FriendlyName,Model,MediaType,BusType,Size,HealthStatus,SerialNumber,"
                    "FirmwareVersion,SpindleSpeed FROM MSFT_PhysicalDisk", "root\\Microsoft\\Windows\\Storage", quiet=True)
    drives = wmi.query("SELECT Index,Model,Size,SerialNumber,InterfaceType,FirmwareRevision,MediaType FROM Win32_DiskDrive")
    links = wmi.query("SELECT Antecedent,Dependent FROM Win32_LogicalDiskToPartition")
    lds = {d.get("DeviceID"): d for d in wmi.query(
        "SELECT DeviceID,FileSystem,VolumeName,Size,FreeSpace,DriveType FROM Win32_LogicalDisk")}
    letters = {}            # disk no -> [harf]
    for ln in links:
        m = re.search(r"Disk #(\d+)", ln.get("Antecedent") or "")
        l2 = re.search(r'DeviceID="([A-Z]:)"', ln.get("Dependent") or "")
        if m and l2:
            letters.setdefault(int(m.group(1)), []).append(l2.group(1))
    groups = []
    disks = pds or [{"DeviceId": str(d.get("Index")), "FriendlyName": d.get("Model"), "Size": d.get("Size"),
                     "SerialNumber": d.get("SerialNumber"), "FirmwareVersion": d.get("FirmwareRevision")} for d in drives]
    for d in sorted(disks, key=lambda x: _int(x.get("DeviceId")) or 0):
        num = _int(d.get("DeviceId"))
        media = MEDIA.get(d.get("MediaType"))
        bus = BUS.get(d.get("BusType"))
        kind = "NVMe SSD" if bus == "NVMe" else media
        serial = (d.get("SerialNumber") or "").strip().rstrip(".") or None
        groups.append({"title": wmi.clean(d.get("FriendlyName")) or wmi.clean(d.get("Model")) or "—",
                       "badge": K(HEALTH[d["HealthStatus"]]) if d.get("HealthStatus") in (1, 2) else None,
                       "rows": [
                           row("lbl_disk_number", num),
                           row("lbl_size", B(d.get("Size"))),
                           row("lbl_disk_type", kind),
                           row("lbl_bus", bus),
                           row("lbl_health", K(HEALTH[d["HealthStatus"]]) if d.get("HealthStatus") in HEALTH else None),
                           row("lbl_firmware_version", wmi.clean(d.get("FirmwareVersion"))),
                           row("lbl_rpm", f"{d['SpindleSpeed']} rpm" if _int(d.get("SpindleSpeed")) and
                               _int(d.get("SpindleSpeed")) < 0xFFFFFFFF else None),
                           row("lbl_volumes", L(sorted(letters.get(num, [])))),
                           row("lbl_smart", K("val_needs_helper")),
                           row("lbl_serial", serial, True),
                       ]})
    vols = []
    for letter, v in sorted(lds.items()):
        size, free = _int(v.get("Size")), _int(v.get("FreeSpace"))
        if not size:
            continue
        r = row("", K("val_volume", label=v.get("VolumeName") or "", fs=v.get("FileSystem") or "",
                      free=B(free), size=B(size)))
        r["l"] = letter                 # etiket çevrilmez: sürücü harfi
        vols.append(r)
    if vols:
        groups.append({"title": K("val_volumes"), "rows": vols})
    return [], groups


# ---------------------------------------------------------------------- ağ
def _wifi():
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, timeout=8,
                             creationflags=0x08000000).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    text = None
    for enc in ("utf-8", "cp857", "cp1252"):
        try:
            text = out.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    info = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        kl = k.lower()
        if kl == "ssid":
            info["ssid"] = v
        elif "802.11" in v and "radio" not in info:
            info["radio"] = v
        elif re.fullmatch(r"\d+(\.\d+)?\s*GHz", v):
            info["band"] = v
        elif re.fullmatch(r"\d{1,3}%", v):
            info["signal"] = v
        elif kl in ("channel", "kanal"):
            info["channel"] = v
    return info


WIFI_GEN = {"802.11be": "Wi-Fi 7", "802.11ax": "Wi-Fi 6/6E", "802.11ac": "Wi-Fi 5", "802.11n": "Wi-Fi 4"}
NET_STATUS = {0: "val_disconnected", 1: "val_connecting", 2: "val_connected", 7: "val_media_disconnected"}


def network():
    try:
        import psutil
        addrs = psutil.net_if_addrs()
    except Exception:
        addrs = {}
    ads = wmi.query("SELECT DeviceID,Name,NetConnectionID,MACAddress,Speed,NetConnectionStatus,PNPDeviceID,Manufacturer "
                    "FROM Win32_NetworkAdapter WHERE PhysicalAdapter=True")
    cfgs = {c.get("Index"): c for c in wmi.query(
        "SELECT Index,DefaultIPGateway,DNSServerSearchOrder,DHCPEnabled FROM Win32_NetworkAdapterConfiguration")}
    wifi = None
    groups = []
    for a in sorted(ads, key=lambda x: x.get("NetConnectionStatus") != 2):
        pnp = (a.get("PNPDeviceID") or "").upper()
        if pnp.startswith(("ROOT\\", "BTH\\", "SWD\\")):
            continue
        conn_id = a.get("NetConnectionID")
        ipv4, ipv6 = [], []
        for ad in addrs.get(conn_id, []):
            fam = getattr(ad.family, "name", str(ad.family))
            if fam == "AF_INET":
                ipv4.append(ad.address)
            elif fam == "AF_INET6":
                ipv6.append(ad.address.split("%")[0])
        cfg = cfgs.get(_int(a.get("DeviceID"))) or {}
        connected = a.get("NetConnectionStatus") == 2
        speed = _int(a.get("Speed"))
        name = wmi.clean(a.get("Name")) or "—"
        is_wifi = bool(re.search(r"wi-?fi|wireless|wlan|802\.11", name, re.I))
        rows = [
            row("lbl_connection_name", conn_id),
            row("lbl_status", K(NET_STATUS.get(a.get("NetConnectionStatus"), "val_unknown"))),
            row("lbl_link_speed", (f"{speed / 1e9:g} Gbps" if speed >= 1e9 else f"{speed / 1e6:g} Mbps")
                if connected and speed and speed < 2 ** 62 else None),
            row("lbl_mac", a.get("MACAddress"), True),
            row("lbl_ipv4", L(ipv4) if connected else None, True),
            row("lbl_ipv6", L(ipv6) if connected else None, True),
            row("lbl_gateway", L(cfg.get("DefaultIPGateway") or []) if connected else None, True),
            row("lbl_dns", L(cfg.get("DNSServerSearchOrder") or []) if connected else None),
            row("lbl_dhcp", ON(cfg.get("DHCPEnabled")) if connected else None),
        ]
        if is_wifi and connected:
            if wifi is None:
                wifi = _wifi()
            radio = wifi.get("radio")
            gen = WIFI_GEN.get(radio) if radio else None
            rows += [row("lbl_wifi_standard", f"{gen} ({radio})" if gen else radio),
                     row("lbl_wifi_band", wifi.get("band")), row("lbl_wifi_channel", wifi.get("channel")),
                     row("lbl_wifi_signal", wifi.get("signal")), row("lbl_ssid", wifi.get("ssid"), True)]
        groups.append({"title": name, "badge": K("val_connected") if connected else None, "rows": rows})
    return [row("lbl_hostname", socket.gethostname(), "r")], groups


# ---------------------------------------------------------------------- ses / usb / bluetooth
def audio():
    groups = []
    for d in wmi.query("SELECT Name,Manufacturer,Status,DeviceID FROM Win32_SoundDevice"):
        groups.append({"title": wmi.clean(d.get("Name")) or "—", "rows": [
            row("lbl_manufacturer", wmi.clean(d.get("Manufacturer"))),
            row("lbl_status", K("val_ok") if d.get("Status") == "OK" else d.get("Status"))]})
    return [], groups


USB_VENDORS = {0x046D: "Logitech", 0x03F0: "HP / HyperX", 0x04F2: "Chicony", 0x8087: "Intel", 0x05E3: "Genesys Logic",
               0x0BDA: "Realtek", 0x1532: "Razer", 0x1B1C: "Corsair", 0x045E: "Microsoft", 0x05AC: "Apple",
               0x0781: "SanDisk", 0x0951: "Kingston", 0x04E8: "Samsung", 0x2109: "VIA Labs", 0x1038: "SteelSeries",
               0x3434: "Keychron", 0x258A: "Sinowealth", 0x0B05: "ASUS", 0x1462: "MSI", 0x13D3: "IMC Networks",
               0x0489: "Foxconn", 0x0CF3: "Qualcomm Atheros", 0x174F: "Syntek", 0x1BCF: "Sunplus", 0x30C9: "Luxvisions"}
GENERIC = re.compile(r"^(USB (Input|Composite|Mass Storage) Device|HID-compliant.*|Camera DFU Device|USB Device|"
                     r"USB Serial Device.*|Unknown USB Device.*)$", re.I)


def usb():
    devs = wmi.query("SELECT Name,DeviceID,PNPClass,Status FROM Win32_PnPEntity WHERE DeviceID LIKE 'USB%'")
    by = {}
    for d in devs:
        m = re.match(r"USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", d.get("DeviceID") or "", re.I)
        if not m:
            continue
        key = (m.group(1).upper(), m.group(2).upper())
        e = by.setdefault(key, {"names": [], "classes": set(), "hub": False})
        name = wmi.clean(d.get("Name")) or ""
        if "hub" in name.lower():
            e["hub"] = True
        e["names"].append(name)
        e["classes"].add(d.get("PNPClass"))
    groups = []
    for (vid, pid), e in sorted(by.items()):
        if e["hub"]:
            continue
        good = [n for n in e["names"] if n and not GENERIC.match(n)]
        vendor = USB_VENDORS.get(int(vid, 16))
        name = good[0] if good else " ".join(x for x in (vendor, e["names"][0] or "USB") if x)
        cls = sorted(c for c in e["classes"] if c and c not in ("USB", "USBDevice"))
        groups.append({"title": name, "rows": [
            row("lbl_manufacturer", vendor),
            row("lbl_device_class", L(cls)),
            row("lbl_device_id", f"{vid}:{pid}")]})
    return [], groups


def bluetooth():
    devs = wmi.query("SELECT Name,DeviceID,Status FROM Win32_PnPEntity WHERE PNPClass='Bluetooth'")
    radios, paired = [], []
    for d in devs:
        did = (d.get("DeviceID") or "").upper()
        name = wmi.clean(d.get("Name"))
        if not name:
            continue
        if did.startswith(("USB\\", "PCI\\")):
            radios.append(name)
        elif did.startswith(("BTHENUM\\DEV_", "BTHLE\\DEV_")) and name not in paired:
            paired.append(name)
    if not radios and not paired:
        return [row("lbl_bluetooth_radio", K("val_none"))], []
    return [row("lbl_bluetooth_radio", L(radios)), row("lbl_paired", L(sorted(paired)), "r")], []


def battery():
    groups = []
    for b in bat.batteries():
        rows = [
            row("lbl_manufacturer", b.get("manufacturer")),
            row("lbl_chemistry", b.get("chemistry")),
            row("lbl_design_capacity", N(b["design"], "mWh") if b.get("design") else None),
            row("lbl_full_capacity", N(b["full"], "mWh") if b.get("full") else None),
            row("lbl_battery_health", N(b["health"], "%", 1) if b.get("health") else None),
            row("lbl_cycles", b.get("cycles") or K("val_not_reported")),
            row("lbl_charge", N(b["percent"], "%") if b.get("percent") is not None else None),
            row("lbl_power_state", (K("val_charging") if b.get("charging") else K("val_plugged"))
                if b.get("ac") else (K("val_on_battery") if b.get("ac") is False else None)),
            row("lbl_voltage", N(b["voltage"] / 1000, "V", 2) if b.get("voltage") else None),
            row("lbl_serial", b.get("serial"), True),
        ]
        groups.append({"title": b.get("name") or K("val_battery"), "rows": rows})
    if not groups:
        return [row("lbl_battery", K("val_no_battery"))], []
    return [], groups


# ---------------------------------------------------------------------- hepsi
def collect(progress=None):
    """Tüm bölümleri toplar. progress(bölüm_sözlüğü) her bölüm bitince çağrılır (arayüz parça parça doldurur)."""
    out = []
    t0 = time.time()
    with wmi.com_thread():
        try:
            adapters = dxgi.adapters()
        except Exception as e:
            log_error(f"dxgi: {e!r}")
            adapters = []
        fns = {"general": (general,), "cpu": (cpu,), "board": (board,), "memory": (memory,),
               "gpu": (gpu, adapters), "display": (display, adapters), "storage": (storage,),
               "network": (network,), "audio": (audio,), "usb": (usb,), "bluetooth": (bluetooth,),
               "battery": (battery,)}
        for sid in SECTIONS:
            fn, *args = fns[sid]
            s = _section(sid, fn, *args)
            out.append(s)
            if progress:
                progress(s)
    return {"sections": out, "collected": datetime.datetime.now().replace(microsecond=0).isoformat(),
            "seconds": round(time.time() - t0, 2)}
