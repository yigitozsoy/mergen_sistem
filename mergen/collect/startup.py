"""Başlangıçta çalışanlar: Run anahtarları, Başlangıç klasörleri, oturum açılışında / önyüklemede çalışan
zamanlanmış görevler, otomatik başlayan (Windows dışı) servisler.

Aç/kapat, Görev Yöneticisi'nin kullandığı StartupApproved anahtarıyla yapılır (girdi silinmez):
12 baytlık değer, ilk bayt çift (02/06) = etkin, tek (03/07) = devre dışı; devre dışıysa 4-12. baytlar FILETIME."""
import datetime
import os
import shlex
import struct
import time
import winreg

from ..config import log_error

APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_SOURCES = [
    # (kaynak kimliği, kovan, görünüm, anahtar, StartupApproved alt anahtarı)
    ("run_user", winreg.HKEY_CURRENT_USER, 0, RUN, "Run"),
    ("run_machine", winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, RUN, "Run"),
    ("run_machine32", winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, RUN, "Run32"),
]
HIVE_NAME = {winreg.HKEY_CURRENT_USER: "HKEY_CURRENT_USER", winreg.HKEY_LOCAL_MACHINE: "HKEY_LOCAL_MACHINE"}


def startup_folders():
    return [("folder_user", winreg.HKEY_CURRENT_USER,
             os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")),
            ("folder_common", winreg.HKEY_LOCAL_MACHINE,
             os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                          r"Microsoft\Windows\Start Menu\Programs\StartUp"))]


def command_exe(cmd):
    """Komut satırından çalıştırılabilir dosya yolu."""
    s = os.path.expandvars(str(cmd or "").strip())
    if not s:
        return None
    if s.startswith('"'):
        end = s.find('"', 1)
        return s[1:end] if end > 0 else s.strip('"')
    low = s.lower()
    for ext in (".exe", ".bat", ".cmd", ".com", ".lnk", ".vbs", ".ps1"):
        i = low.find(ext)
        if i > 0:
            return s[:i + len(ext)]
    try:
        return shlex.split(s, posix=False)[0]
    except ValueError:
        return s.split(" ")[0]


def _approved(hive, sub, name):
    """True = etkin, False = devre dışı, None = kayıt yok (etkin sayılır)."""
    try:
        with winreg.OpenKey(hive, APPROVED + "\\" + sub) as k:
            val, _t = winreg.QueryValueEx(k, name)
    except OSError:
        return None
    if isinstance(val, (bytes, bytearray)) and val:
        return val[0] % 2 == 0
    return None


def _approved_time(hive, sub, name):
    try:
        with winreg.OpenKey(hive, APPROVED + "\\" + sub) as k:
            val, _t = winreg.QueryValueEx(k, name)
        if isinstance(val, (bytes, bytearray)) and len(val) >= 12 and val[0] % 2:
            ft = struct.unpack("<Q", bytes(val[4:12]))[0]
            if ft:
                return (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)).isoformat(" ", "seconds")
    except (OSError, OverflowError, struct.error):
        pass
    return None


def approved_value(enable):
    """StartupApproved için yazılacak 12 bayt (Görev Yöneticisi biçimi)."""
    if enable:
        return bytes([2]) + bytes(11)
    ft = int((time.time() + 11644473600) * 1e7)
    return bytes([3, 0, 0, 0]) + struct.pack("<Q", ft)


def _run_entries():
    rows = []
    for src, hive, view, key, sub in RUN_SOURCES:
        try:
            k = winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with k:
            i = 0
            while True:
                try:
                    name, val, _t = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if not name:
                    continue
                ok = _approved(hive, sub, name)
                regpath = HIVE_NAME[hive] + "\\" + ("SOFTWARE\\WOW6432Node" + key[8:] if sub == "Run32" else key)
                rows.append({"id": f"{src}:{name}", "name": name, "source": src, "command": str(val),
                             "exe": command_exe(val), "enabled": ok is not False,
                             "disabled_at": _approved_time(hive, sub, name),
                             "toggle": {"hive": "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM",
                                        "sub": sub, "name": name},
                             "location": regpath, "admin": hive == winreg.HKEY_LOCAL_MACHINE})
    return rows


def _folder_entries():
    rows = []
    for src, hive, folder in startup_folders():
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for f in names:
            p = os.path.join(folder, f)
            if f.lower() == "desktop.ini" or not os.path.isfile(p):
                continue
            target = p
            if f.lower().endswith(".lnk"):
                target = _lnk_target(p) or p
            ok = _approved(hive, "StartupFolder", f)
            rows.append({"id": f"{src}:{f}", "name": os.path.splitext(f)[0], "source": src, "command": target,
                         "exe": target, "enabled": ok is not False,
                         "disabled_at": _approved_time(hive, "StartupFolder", f),
                         "toggle": {"hive": "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM",
                                    "sub": "StartupFolder", "name": f},
                         "location": p, "admin": hive == winreg.HKEY_LOCAL_MACHINE})
    return rows


def _lnk_target(path):
    try:
        import pythoncom
        from win32com.shell import shell
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                          shell.IID_IShellLink)
        link.QueryInterface(pythoncom.IID_IPersistFile).Load(path)
        target = link.GetPath(shell.SLGP_RAWPATH)[0]
        args = link.GetArguments()
        return os.path.expandvars(target) + (" " + args if args else "") if target else None
    except Exception:
        return None


def _task_entries():
    """Oturum açılışında (tetikleyici 9) ya da önyüklemede (8) çalışan zamanlanmış görevler."""
    rows = []
    try:
        import win32com.client
        svc = win32com.client.Dispatch("Schedule.Service")
        svc.Connect()
    except Exception as e:
        log_error(f"startup tasks: {e!r}")
        return rows

    def walk(folder):
        try:
            tasks = folder.GetTasks(1)        # gizli görevler dahil
        except Exception:
            tasks = []
        for task in tasks:
            try:
                d = task.Definition
                kinds = [tr.Type for tr in d.Triggers]
                if 8 not in kinds and 9 not in kinds:
                    continue
                path = task.Path
                if path.lower().startswith("\\microsoft\\"):
                    continue                  # Windows'un kendi görevleri (Görev Yöneticisi de göstermez)
                cmd = None
                for a in d.Actions:
                    if a.Type == 0:           # TASK_ACTION_EXEC
                        cmd = (a.Path or "") + (" " + a.Arguments if a.Arguments else "")
                        break
                rows.append({"id": "task:" + path, "name": task.Name, "source": "task_boot" if 8 in kinds and 9 not in kinds
                             else "task_logon", "command": cmd, "exe": command_exe(cmd),
                             "enabled": bool(task.Enabled), "disabled_at": None, "toggle": {"task": path},
                             "location": path, "admin": True,
                             "author": d.RegistrationInfo.Author or None})
            except Exception:
                continue
        try:
            for sub in folder.GetFolders(0):
                walk(sub)
        except Exception:
            pass
    walk(svc.GetFolder("\\"))
    return rows


def _service_entries(services):
    sysroot = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    rows = []
    for s in services or []:
        if s.get("start") not in ("auto", "auto_delayed"):
            continue
        exe = s.get("exe")
        if not exe or os.path.normcase(exe).startswith(sysroot + os.sep):
            continue
        rows.append({"id": "svc:" + s["name"], "name": s.get("display") or s["name"], "source": "service",
                     "command": s.get("path"), "exe": exe, "enabled": True, "disabled_at": None, "toggle": None,
                     "location": s["name"], "admin": True})
    return rows


def collect(services=None):
    """services: services.collect() çıktısı (verilmezse servisler başlangıç listesine eklenmez)."""
    rows = []
    for fn in (_run_entries, _folder_entries, _task_entries):
        try:
            rows += fn()
        except Exception as e:
            log_error(f"startup {fn.__name__}: {e!r}")
    rows += _service_entries(services)
    for r in rows:
        r["publisher"] = None
    return rows
