"""Windows servisleri (Win32_Service) — salt okunur. Başlat/durdur sayfadan, onay + yönetici izniyle."""
import os

from . import wmi
from .startup import command_exe

START = {"Auto": "auto", "Manual": "manual", "Disabled": "disabled", "Boot": "boot", "System": "system"}
STATE = {"Running": "running", "Stopped": "stopped", "Paused": "paused", "Start Pending": "starting",
         "Stop Pending": "stopping", "Continue Pending": "starting", "Pause Pending": "stopping"}


def service_exe(path):
    """ImagePath / PathName -> çalıştırılabilir dosya (\\SystemRoot\\, \\??\\ ve system32\\ önekleri çözülür)."""
    if not path:
        return None
    s = str(path).strip()
    root = os.environ.get("SystemRoot", r"C:\Windows")
    if s.startswith("\\??\\"):
        s = s[4:]
    if s.lower().startswith("\\systemroot\\"):
        s = root + s[11:]
    elif s.lower().startswith("system32\\"):
        s = os.path.join(root, s)
    exe = command_exe(s)
    return os.path.normpath(exe) if exe else None


def collect():
    rows = []
    for r in wmi.query("SELECT Name,DisplayName,State,StartMode,PathName,Description,ProcessId,StartName,"
                       "DelayedAutoStart FROM Win32_Service"):
        start = START.get(r.get("StartMode"), (r.get("StartMode") or "").lower() or None)
        if start == "auto" and r.get("DelayedAutoStart"):
            start = "auto_delayed"
        rows.append({"name": r.get("Name"), "display": r.get("DisplayName") or r.get("Name"),
                     "state": STATE.get(r.get("State"), (r.get("State") or "").lower() or None),
                     "start": start, "path": r.get("PathName"), "exe": service_exe(r.get("PathName")),
                     "description": r.get("Description"), "pid": r.get("ProcessId") or None,
                     "account": r.get("StartName"), "id": "svc:" + str(r.get("Name"))})
    return rows
