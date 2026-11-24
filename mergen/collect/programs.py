"""Kurulu programlar: kayıt defteri Uninstall anahtarları (HKLM 64/32 bit, HKCU) + Microsoft Store paketleri.

Store paketleri PowerShell (Get-AppxPackage, ~3 sn) yerine kullanıcının AppModel Repository anahtarından okunur;
"ms-resource:" adları SHLoadIndirectString ile çözülür. Hiçbir şey yazılmaz."""
import ctypes
import datetime
import os
import re
import winreg

UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
REPO = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
SOURCES = [
    ("HKLM", winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, "64"),
    ("HKLM", winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, "32"),
    ("HKCU", winreg.HKEY_CURRENT_USER, 0, ""),
]
SYSROOT = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows")) + os.sep
ROOT_NAMES = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER"}


def _values(key):
    out = {}
    i = 0
    while True:
        try:
            name, val, _typ = winreg.EnumValue(key, i)
        except OSError:
            break
        out[name] = val
        i += 1
    return out


def _filetime(ft):
    try:
        return datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
    except (OverflowError, ValueError):
        return None


def _install_date(v, fallback):
    s = str(v or "").strip()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        try:
            return datetime.date(*map(int, m.groups())).isoformat()
        except ValueError:
            pass
    return fallback.date().isoformat() if fallback else None


def _icon_path(v):
    """DisplayIcon: '"C:\\x\\a.exe",0' -> C:\\x\\a.exe"""
    s = str(v or "").strip().strip('"')
    s = re.sub(r",\s*-?\d+$", "", s).strip('"')
    return os.path.expandvars(s) if s else None


def registry_programs():
    rows = []
    seen = set()
    for hive_name, hive, view, bits in SOURCES:
        try:
            root = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            n = winreg.QueryInfoKey(root)[0]
            for i in range(n):
                try:
                    sub = winreg.EnumKey(root, i)
                    k = winreg.OpenKey(root, sub)
                except OSError:
                    continue
                with k:
                    v = _values(k)
                    modified = _filetime(winreg.QueryInfoKey(k)[2])
                name = str(v.get("DisplayName") or "").strip()
                if not name or v.get("SystemComponent") == 1 or v.get("ParentKeyName") \
                        or str(v.get("ReleaseType") or "") in ("Update", "Hotfix", "Security Update"):
                    continue
                ident = (name.casefold(), str(v.get("DisplayVersion") or ""))
                if ident in seen:           # aynı program hem 64 hem 32 bit görünümde
                    continue
                seen.add(ident)
                loc = os.path.expandvars(str(v.get("InstallLocation") or "").strip().strip('"')) or None
                derived = False
                if not loc:
                    icon = _icon_path(v.get("DisplayIcon"))
                    if icon and icon.lower().endswith(".exe") and os.path.isfile(icon):
                        loc, derived = os.path.dirname(icon), True
                size = v.get("EstimatedSize")
                path = f"{ROOT_NAMES[hive_name]}\\{'SOFTWARE' if hive_name == 'HKLM' else 'Software'}" + (
                    "\\WOW6432Node" if bits == "32" else "") + UNINSTALL[8:] + "\\" + sub
                rows.append({
                    "name": name, "publisher": str(v.get("Publisher") or "").strip() or None,
                    "version": str(v.get("DisplayVersion") or "").strip() or None,
                    "date": _install_date(v.get("InstallDate"), modified),
                    "size": int(size) * 1024 if isinstance(size, int) and size > 0 else None,
                    "location": loc, "location_derived": derived,
                    "uninstall": str(v.get("UninstallString") or "").strip() or None,
                    "quiet_uninstall": str(v.get("QuietUninstallString") or "").strip() or None,
                    "modify": str(v.get("ModifyPath") or "").strip() or None,
                    "icon": _icon_path(v.get("DisplayIcon")),
                    "scope": "user" if hive_name == "HKCU" else "machine",
                    "arch": bits or None, "regkey": path, "kind": "win32", "id": "reg:" + path,
                })
    return rows


def _indirect(s):
    buf = ctypes.create_unicode_buffer(1024)
    try:
        if ctypes.windll.shlwapi.SHLoadIndirectString(s, buf, len(buf), None) == 0:
            return buf.value
    except Exception:
        pass
    return None


def _resolve_name(display, full, pkg_name):
    if not display.startswith("ms-resource:"):
        return display
    res = display[len("ms-resource:"):]
    cands = []
    if res.startswith("//"):
        cands.append(f"@{{{full}?{display}}}")
    else:
        res = res.lstrip("/")
        if "/" not in res:
            cands.append(f"@{{{full}?ms-resource://{pkg_name}/Resources/{res}}}")
        cands.append(f"@{{{full}?ms-resource://{pkg_name}/{res}}}")
    for c in cands:
        v = _indirect(c)
        if v and not v.startswith(("ms-resource", "@{")):
            return v
    return None


def store_packages():
    """Kullanıcının Store paketleri (çatı/framework ve kaynak paketleri hariç; her paketin en yeni sürümü)."""
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REPO)
    except OSError:
        return []
    best = {}
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                full = winreg.EnumKey(root, i)
                k = winreg.OpenKey(root, full)
            except OSError:
                continue
            with k:
                v = _values(k)
                modified = _filetime(winreg.QueryInfoKey(k)[2])
            if v.get("Framework") == 1 or "_neutral_~_" in full and ".resource" in full.lower():
                continue
            parts = full.split("_")
            if len(parts) < 5:
                continue
            pkg_name, version, arch, publisher_id = parts[0], parts[1], parts[2], parts[-1]
            if "~" in parts[3] and arch == "neutral" and ".resource" in full.lower():
                continue
            prev = best.get(pkg_name)
            vt = tuple(int(x) if x.isdigit() else 0 for x in version.split("."))
            if prev is not None and prev[0] >= vt:
                continue
            best[pkg_name] = (vt, full, v, modified, version, arch, publisher_id)
    rows = []
    for pkg_name, (_vt, full, v, modified, version, arch, publisher_id) in best.items():
        loc = v.get("PackageRootFolder")
        if loc and os.path.normcase(str(loc)).startswith(SYSROOT):
            continue                     # C:\Windows\SystemApps: Windows bileşeni, kaldırılamaz
        display = str(v.get("DisplayName") or "")
        name = _resolve_name(display, full, pkg_name) or pkg_name
        rows.append({
            "name": name, "publisher": pkg_name.split(".")[0] if "." in pkg_name else None,
            "version": version, "date": modified.date().isoformat() if modified else None, "size": None,
            "location": str(loc) if loc else None, "location_derived": False,
            "uninstall": None, "quiet_uninstall": None, "modify": None, "icon": None,
            "scope": "user", "arch": arch if arch != "neutral" else None,
            "regkey": "HKEY_CURRENT_USER\\" + REPO + "\\" + full, "kind": "store", "package": full,
            "family": f"{pkg_name}_{publisher_id}", "system": pkg_name.startswith(("Microsoft.Windows.", "windows.",
                                                                                   "MicrosoftWindows.")),
            "id": "appx:" + full,
        })
    return rows


def collect():
    return registry_programs() + store_packages()
