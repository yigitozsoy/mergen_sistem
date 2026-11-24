"""Süreç listesi (Görev yöneticisi): ntproc (tek NtQuerySystemInformation çağrısı) + psutil (exe yolu, komut
satırı, kullanıcı; bir kez) + PDH'den süreç başına GPU. Bellek = özel çalışma kümesi (Görev Yöneticisi'ndeki gibi)."""
import ctypes
import os
import time
from ctypes import wintypes

import psutil

user32 = ctypes.windll.user32

# Görev Yöneticisi'nin "Windows işlemleri" grubuna koyduğu çekirdek süreçler
WINDOWS_NAMES = {
    "system", "system idle process", "registry", "memory compression", "secure system", "smss.exe", "csrss.exe",
    "wininit.exe", "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "winlogon.exe", "dwm.exe",
    "fontdrvhost.exe", "spoolsv.exe", "sihost.exe", "taskhostw.exe", "ctfmon.exe", "runtimebroker.exe",
    "searchindexer.exe", "wudfhost.exe", "dllhost.exe", "conhost.exe", "explorer.exe", "audiodg.exe",
    "lsm.exe", "wlanext.exe", "dashost.exe", "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe",
    "sgrmbroker.exe", "smartscreen.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "searchhost.exe", "textinputhost.exe", "widgets.exe", "lockapp.exe", "wmiprvse.exe", "unsecapp.exe",
    "vmmem", "vmmemws", "vmcompute.exe", "searchprotocolhost.exe", "searchfilterhost.exe", "useroobebroker.exe",
}
SYSROOT = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))

PRIORITY_CLASS = {"prio_idle": psutil.IDLE_PRIORITY_CLASS, "prio_below": psutil.BELOW_NORMAL_PRIORITY_CLASS,
                  "prio_normal": psutil.NORMAL_PRIORITY_CLASS, "prio_above": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
                  "prio_high": psutil.HIGH_PRIORITY_CLASS, "prio_realtime": psutil.REALTIME_PRIORITY_CLASS}


def window_pids():
    """Görünür, sahipsiz, başlıklı ve gizlenmemiş (cloaked değil) üst düzey pencereleri olan süreçler."""
    pids = set()
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    dwm = ctypes.windll.dwmapi

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):     # GW_OWNER
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        cloaked = wintypes.DWORD(0)
        if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pids.add(pid.value)
        return True
    try:
        user32.EnumWindows(proto(cb), 0)
    except Exception:
        pass
    return pids


def group_of(name, exe, pid, has_window):
    n = (name or "").lower()
    if pid in (0, 4) or n in WINDOWS_NAMES:
        return "windows"
    if has_window:
        return "apps"
    if exe and os.path.normcase(exe).startswith(SYSROOT + os.sep) and not has_window:
        return "windows"
    return "background"


BASE_PRIORITY = {4: "prio_idle", 6: "prio_below", 8: "prio_normal", 10: "prio_above", 13: "prio_high",
                 24: "prio_realtime"}


class ProcessSampler:
    """Sayılar ntproc.snapshot()'tan (tek çağrı); exe yolu / komut satırı / kullanıcı psutil'den, süreç başına
    bir kez ve tur başına en çok STATIC_BUDGET saniye (ilk açılışta liste hemen gelir, ayrıntılar dolar)."""
    STATIC_BUDGET = 0.25

    def __init__(self):
        self.ncpu = psutil.cpu_count() or 1
        self.static = {}        # (pid, create) -> dict
        self.prev = {}          # (pid, create) -> (zaman, cpu_s, io_bytes)
        self.own_pid = os.getpid()

    def _static(self, pid, key, name, deadline):
        s = self.static.get(key)
        if s is not None or time.perf_counter() > deadline:
            return s
        s = {"exe": None, "cmd": None, "user": None}
        if pid not in (0, 4):
            try:
                p = psutil.Process(pid)
                for attr, fn in (("exe", p.exe), ("user", p.username)):
                    try:
                        s[attr] = fn() or None
                    except (psutil.Error, OSError):
                        pass
                try:
                    s["cmd"] = " ".join(p.cmdline()) or None
                except (psutil.Error, OSError):
                    pass
            except (psutil.Error, OSError):
                pass
        else:
            s["user"] = "SYSTEM"
        if s["user"] and "\\" in s["user"]:
            s["user"] = s["user"].split("\\", 1)[1]
        self.static[key] = s
        return s

    def sample(self, gpu_per_pid=None):
        from . import ntproc
        gpu_per_pid = gpu_per_pid or {}
        now = time.time()
        deadline = time.perf_counter() + self.STATIC_BUDGET
        wins = window_pids()
        rows = []
        alive = set()
        for e in ntproc.snapshot():
            pid = e["pid"]
            key = (pid, round(e["create"], 3))
            alive.add(key)
            st = self._static(pid, key, e["name"], deadline) or {}
            io_b = e["io_read"] + e["io_write"]
            row = {"key": f"{pid}:{key[1]:.3f}", "pid": pid, "ppid": e["ppid"], "name": e["name"],
                   "exe": st.get("exe"), "cmd": st.get("cmd"), "user": st.get("user"),
                   "start": e["create"] or None, "cpu": 0.0, "mem": e["ws_private"], "commit": e["private"],
                   "disk": 0.0, "threads": e["threads"], "handles": e["handles"], "session": e["session"],
                   "priority": BASE_PRIORITY.get(e["base_priority"]), "gpu": 0.0, "gpu_engine": None}
            prev = self.prev.get(key)
            if prev:
                dt = now - prev[0]
                if dt > 0:
                    row["cpu"] = max(0.0, min(100.0, (e["cpu_s"] - prev[1]) * 100 / (dt * self.ncpu)))
                    row["disk"] = max(0.0, (io_b - prev[2]) / dt)
            self.prev[key] = (now, e["cpu_s"], io_b)
            if pid == 0:
                row["cpu"] = 0.0           # Boşta işlemi (Görev Yöneticisi gibi süreç listesinde gösterme)
            g = gpu_per_pid.get(pid)
            if g:
                row["gpu"], row["gpu_engine"] = min(100.0, g[0]), g[1]
                row["gpu_luid"] = g[2] if len(g) > 2 else None
            row["group"] = group_of(row["name"], row["exe"], pid, pid in wins)
            row["self"] = pid == self.own_pid
            rows.append(row)
        for k in list(self.prev):
            if k not in alive:
                self.static.pop(k, None)
                self.prev.pop(k, None)
        return [r for r in rows if r["pid"] != 0]
