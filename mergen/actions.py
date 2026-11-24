"""Sayfaların paylaştığı küçük işlemler: klasör aç, kayıt defterinde göster, çevrimiçi ara, onay kutusu ve
tek seferlik yönetici izniyle (UAC) komut çalıştırma.

Not: 5. aşamada yükseltilmiş mergen-helper gelince yönetici isteyen yazmalar oradan geçecek; o zamana kadar her
işlem kendi UAC penceresini açar (yalnızca bilinen komutlar: sc/PowerShell servis komutları, reg add, schtasks)."""
import ctypes
import os
import subprocess
from ctypes import wintypes
from urllib.parse import quote

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QMessageBox

from .config import log_error
from .i18n import t

SEE_MASK_NOCLOSEPROCESS = 0x40
SEE_MASK_NOASYNC = 0x100
ERROR_CANCELLED = 1223


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def shell_execute(file, params=None, verb="open", show=1, wait=False, timeout_ms=120000):
    """ShellExecuteEx. Dönüş: (başarılı mı, çıkış kodu ya da None). Kullanıcı UAC'ı reddederse (False, "cancelled")."""
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = verb
    info.lpFile = file
    info.lpParameters = params
    info.nShow = show
    k32 = ctypes.windll.kernel32
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.GetLastError()
        return False, "cancelled" if err == ERROR_CANCELLED else err
    code = None
    if info.hProcess:
        if wait:
            k32.WaitForSingleObject(info.hProcess, timeout_ms)
            c = wintypes.DWORD()
            if k32.GetExitCodeProcess(info.hProcess, ctypes.byref(c)):
                code = c.value
        k32.CloseHandle(info.hProcess)
    return True, code


def run_elevated(exe, params, wait=True):
    """Gizli pencerede, yönetici izniyle (UAC sorulur). Dönüş: (başarılı mı, çıkış kodu / hata)."""
    return shell_execute(exe, params, verb="runas", show=0, wait=wait)


def powershell_elevated(command):
    ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\WindowsPowerShell\v1.0\powershell.exe")
    return run_elevated(ps, f'-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "{command}"')


def ps_quote(s):
    """PowerShell tek tırnaklı dize."""
    return "'" + str(s).replace("'", "''") + "'"


def open_folder(path, select=True):
    """Dosyaysa (ya da select) Gezgin'de seçili gösterir, klasörse açar."""
    if not path:
        return False
    p = os.path.normpath(os.path.expandvars(str(path).strip().strip('"')))
    if os.path.isfile(p) and select:
        subprocess.Popen(["explorer.exe", "/select,", p])
        return True
    if os.path.isdir(p):
        subprocess.Popen(["explorer.exe", p])
        return True
    parent = os.path.dirname(p)
    if parent and os.path.isdir(parent):
        subprocess.Popen(["explorer.exe", parent])
        return True
    return False


def show_in_regedit(path):
    """Kayıt Defteri Düzenleyicisi'ni verilen anahtarda açar (regedit'in kendi LastKey ayarı + /m yeni pencere).
    regedit yönetici ister; UAC'ı Windows sorar."""
    import winreg
    path = str(path)
    for short, long_ in (("HKLM\\", "HKEY_LOCAL_MACHINE\\"), ("HKCU\\", "HKEY_CURRENT_USER\\")):
        if path.upper().startswith(short):
            path = long_ + path[len(short):]
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit") as k:
            try:        # kök adı Windows diline göre değişir ("Bilgisayar" / "Computer"): var olandan al
                root = str(winreg.QueryValueEx(k, "LastKey")[0]).split("\\", 1)[0] or "Computer"
            except OSError:
                root = "Computer"
            if root.upper().startswith("HKEY_"):
                root = "Computer"
            winreg.SetValueEx(k, "LastKey", 0, winreg.REG_SZ, root + "\\" + path)
        return shell_execute("regedit.exe", "/m")[0]
    except OSError as e:
        log_error(f"regedit: {e!r}")
        return False


def search_online(text):
    QDesktopServices.openUrl(QUrl("https://www.bing.com/search?q=" + quote(str(text))))


def copy(text):
    QGuiApplication.clipboard().setText(str(text or ""))


def confirm(parent, title, text, ok_text, destructive=True, details=None):
    box = QMessageBox(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question, title, text,
                      parent=parent)
    if details:
        box.setDetailedText(details)
    ok = box.addButton(ok_text, QMessageBox.ButtonRole.DestructiveRole if destructive
                       else QMessageBox.ButtonRole.AcceptRole)
    box.addButton(t("cancel"), QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is ok


def report(parent, ok, code=None):
    """run_elevated sonucunu kullanıcıya bildirir (başarıda sessiz)."""
    if ok and not code:
        return True
    if code == "cancelled":
        QMessageBox.information(parent, "mergen", t("uac_cancelled"))
    else:
        QMessageBox.warning(parent, "mergen", t("action_failed", code=code))
    return False
