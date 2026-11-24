"""mergen-helper istemcisi: yardımcıyı başlatır, adlandırılmış kanaldan satır satır JSON okur, kopunca yeniden dener.

Yükseltme yolları (CLAUDE.md bölüm 2):
- Zamanlanmış görev "mergen-helper" varsa: `schtasks /Run` (UAC sormaz). Görev kullanıcı onayıyla bir kez oluşturulur;
  yardımcı o sırada yalnızca yöneticinin yazabildiği %ProgramFiles%\\mergen-helper\\ klasörüne kopyalanır (kullanıcının
  yazabildiği bir exe'yi en yüksek ayrıcalıkla çalıştıran görev, UAC'ı atlatmaya açık kapı olurdu).
- Görev yoksa yardımcı yükseltilmeden başlar (sınırlı sensörler); kullanıcı "yönetici olarak aç" derse tek seferlik UAC.

Kanal: \\\\.\\pipe\\mergen-helper-<kullanıcı>. Okuma PeekNamedPipe ile yoklanır (eşzamanlı tanıtıcıda bekleyen bir
ReadFile, WriteFile'ı da kilitlerdi)."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from .config import BASE_DIR, log_error

USER = os.environ.get("USERNAME") or "user"
PIPE = r"\\.\pipe\mergen-helper-" + USER
TASK = "mergen-helper"
SECURE_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "mergen-helper")
SECURE_EXE = os.path.join(SECURE_DIR, "mergen-helper.exe")
NO_WINDOW = 0x08000000


def helper_path():
    """Paketle gelen ya da geliştirmede derlenmiş yardımcı (yoksa None)."""
    env = os.environ.get("MERGEN_HELPER")
    cands = [env] if env else []
    root = os.path.dirname(BASE_DIR) if os.path.basename(BASE_DIR) == "mergen" else BASE_DIR
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None
    if exe_dir:
        cands.append(os.path.join(exe_dir, "helper", "mergen-helper.exe"))
    cands += [os.path.join(root, "helper", "publish", "mergen-helper.exe"),
              os.path.join(root, "helper", "bin", "Release", "net10.0-windows", "win-x64", "mergen-helper.exe")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _run(args, timeout=10):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        log_error(f"{args[0]}: {e!r}")
        return None


def task_exists():
    r = _run(["schtasks", "/Query", "/TN", TASK])
    return bool(r) and r.returncode == 0


def pawnio_installed():
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO", 0,
                                winreg.KEY_READ | view):
                return True
        except OSError:
            continue
    return False


def _user_sid():
    try:
        import win32api
        import win32security
        tok = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(tok, win32security.TokenUser)[0])
    except Exception as e:
        log_error(f"sid: {e!r}")
        return None


def task_xml(exe, sid):
    """Tetikleyicisiz (yalnızca istekle çalışan), en yüksek ayrıcalıklı, etkileşimli görev. Güvenlik tanımlayıcısı
    kullanıcıya yalnızca okuma + çalıştırma verir (değiştiremez)."""
    from xml.sax.saxutils import escape
    sd = f"D:(A;;FA;;;BA)(A;;FA;;;SY)(A;;GRGX;;;{sid})" if sid else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>mergen</Author>
    <Description>mergen yardımcısı (sensör okuma). mergen tarafından istekle başlatılır.</Description>
    {f"<SecurityDescriptor>{sd}</SecurityDescriptor>" if sd else ""}
  </RegistrationInfo>
  <Triggers />
  <Principals>
    <Principal id="Author">
      {f"<UserId>{sid}</UserId>" if sid else ""}
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
    </Exec>
  </Actions>
</Task>
"""


def create_task(src):
    """Kullanıcı onayından SONRA çağrılır: yardımcıyı %ProgramFiles%'a kopyalar ve görevi kaydeder (tek UAC).
    Dönüş: actions.run_elevated sonucu."""
    from . import actions
    xml = os.path.join(tempfile.gettempdir(), "mergen-helper-task.xml")
    with open(xml, "w", encoding="utf-16") as f:
        f.write(task_xml(SECURE_EXE, _user_sid()))
    q = actions.ps_quote
    cmd = (f"$ErrorActionPreference='Stop'; New-Item -ItemType Directory -Force {q(SECURE_DIR)} | Out-Null; "
           f"Copy-Item -Force {q(src)} {q(SECURE_EXE)}; "
           f"schtasks.exe /Create /TN {TASK} /XML {q(xml)} /F | Out-Null; exit $LASTEXITCODE")
    return actions.powershell_elevated(cmd)


def delete_task():
    from . import actions
    q = actions.ps_quote
    cmd = (f"schtasks.exe /Delete /TN {TASK} /F | Out-Null; "
           f"Remove-Item -Force -Recurse -ErrorAction SilentlyContinue {q(SECURE_DIR)}")
    return actions.powershell_elevated(cmd)


class HelperClient(QObject):
    """state: missing | starting | connected | disconnected | elevating"""
    info = pyqtSignal(dict)
    sensors = pyqtSignal(dict)
    state = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._want = False
        self._out = []
        self._lock = threading.Lock()
        self._thread = None
        self._stop = False
        self.groups = None
        self.interval = 1000
        self.last_info = None
        self.current_state = "disconnected"
        self._launched_at = 0.0

    # ---- arayüz iş parçacığından
    def want(self, on, groups=None, interval=1000):
        self.groups = groups
        self.interval = interval
        with self._lock:
            self._want = on
            self._out.append({"cmd": "subscribe", "interval": interval, "groups": groups} if on
                             else {"cmd": "unsubscribe"})
        if on and (self._thread is None or not self._thread.is_alive()):
            self._stop = False
            self._thread = threading.Thread(target=self._loop, name="mergen-helper-client", daemon=True)
            self._thread.start()

    def resubscribe(self, groups=None, interval=None):
        self.want(self._want, groups if groups is not None else self.groups, interval or self.interval)

    def stop(self):
        self._stop = True
        with self._lock:
            self._want = False
        if self._thread is not None:
            self._thread.join(timeout=3)

    def elevate(self):
        """Çalışan (yükseltilmemiş) yardımcıyı kapatıp yönetici olarak yeniden başlatır. Dönüş: (ok, kod)."""
        from . import actions
        exe = helper_path()
        if not exe:
            return False, "missing"
        self._set_state("elevating")
        with self._lock:
            self._out.append({"cmd": "quit"})
        time.sleep(0.6)
        res = actions.shell_execute(exe, None, verb="runas", show=0)
        self._launched_at = time.time()
        return res

    # ---- iş parçacığı
    def _set_state(self, s):
        if s != self.current_state:
            self.current_state = s
            self.state.emit(s)

    def _launch(self):
        """Görev varsa onu, yoksa yükseltilmemiş yardımcıyı başlatır."""
        if time.time() - self._launched_at < 8:          # az önce başlatıldı: kanalın açılmasını bekle
            return True
        self._launched_at = time.time()
        if task_exists():
            r = _run(["schtasks", "/Run", "/TN", TASK])
            if r and r.returncode == 0:
                return True
            log_error(f"schtasks /Run: {r.stdout if r else ''} {r.stderr if r else ''}")
        exe = helper_path()
        if not exe:
            self._set_state("missing")
            return False
        try:
            subprocess.Popen([exe], creationflags=NO_WINDOW | 0x00000008, close_fds=True)   # DETACHED_PROCESS
            return True
        except OSError as e:
            log_error(f"helper start: {e!r}")
            return False

    def _connect(self):
        import pywintypes
        import win32file
        import win32pipe
        try:
            h = win32file.CreateFile(PIPE, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None,
                                     win32file.OPEN_EXISTING, 0, None)
            win32pipe.SetNamedPipeHandleState(h, win32pipe.PIPE_READMODE_BYTE, None, None)
            return h
        except pywintypes.error:
            return None

    def _loop(self):
        import pywintypes
        import win32file
        import win32pipe
        while not self._stop:
            with self._lock:
                want = self._want
            if not want:
                return
            h = self._connect()
            if h is None:
                if self.current_state != "missing":
                    self._set_state("starting")
                if not self._launch():
                    time.sleep(2)
                    continue
                for _ in range(40):
                    if self._stop:
                        return
                    time.sleep(0.25)
                    h = self._connect()
                    if h is not None:
                        break
                if h is None:
                    continue
            self._set_state("connected")
            with self._lock:
                self._out[:0] = [{"cmd": "info"}, {"cmd": "subscribe", "interval": self.interval,
                                                   "groups": self.groups}]
            buf = b""
            try:
                while not self._stop:
                    with self._lock:
                        out, self._out = self._out, []
                        want = self._want
                    if not want:
                        out.append({"cmd": "bye"})
                    for m in out:
                        win32file.WriteFile(h, (json.dumps(m) + "\n").encode("utf-8"))
                        if m["cmd"] in ("quit", "bye"):
                            raise EOFError
                    _, avail, _ = win32pipe.PeekNamedPipe(h, 0)
                    if not avail:
                        time.sleep(0.05)
                        continue
                    _, data = win32file.ReadFile(h, avail)
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            msg = json.loads(line)
                        except ValueError:
                            continue
                        if msg.get("type") == "info":
                            self.last_info = msg
                            self.info.emit(msg)
                        elif msg.get("type") == "sensors":
                            self.sensors.emit(msg)
            except (pywintypes.error, EOFError):
                pass
            finally:
                try:
                    win32file.CloseHandle(h)
                except Exception:
                    pass
            self._set_state("disconnected")
            time.sleep(0.5)


_client = None


def client():
    global _client
    if _client is None:
        _client = HelperClient()
    return _client
