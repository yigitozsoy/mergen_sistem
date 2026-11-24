"""Sekme 2 — Programlar ve sürücüler: alt sekmeler (çip çubuğu) programlar, başlangıç, servisler, sürücüler,
dosya yolları, klasör boyutları.

Veri arka planda toplanır (WMI/kayıt defteri; arayüz donmaz), alt sekme ilk açıldığında. Sistemi değiştiren her
işlem (kaldırma, başlangıç aç/kapat, servis başlat/durdur) önce ne yapacağını söyleyip onay ister; başlangıç
aç/kapat silmeden yapılır ve geri alınabilir."""
import os
import subprocess
import threading
import winreg

from PyQt6.QtCore import QFileInfo, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFileIconProvider, QHBoxLayout, QLabel, QMenu,
                             QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import actions
from ..collect.fmt import human_bytes
from ..config import log_error, prefs
from ..i18n import is_tr, t
from ..widgets import Chip
from ..widgets.table import Col, DataTable
from .base import Page

SYSROOT = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows")) + os.sep
_icons = {}
_provider = None


def file_icon(path):
    global _provider
    if not path:
        return None
    ic = _icons.get(path)
    if ic is None:
        if _provider is None:
            _provider = QFileIconProvider()
        p = os.path.expandvars(str(path).strip('"'))
        ic = _provider.icon(QFileInfo(p)) if os.path.exists(p) else QIcon()
        _icons[path] = ic
    return ic


def fdate(iso):
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}" if is_tr() else iso[:10]


def fsize(v):
    return human_bytes(v, is_tr()) if v else ""


class _Bridge(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)


# ================================================================================================ taban
class SubTab(QWidget):
    key = ""
    name = ""                  # tablo tercih adı
    default_sort = None

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.loaded = False
        self.loading = False
        self._bridge = _Bridge()
        self._bridge.done.connect(self._on_done)
        self._bridge.failed.connect(self._on_failed)
        self._bridge.progress.connect(self._on_progress)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.bar = QHBoxLayout()
        self.bar.setSpacing(6)
        self.status = QLabel(t("loading"))
        self.status.setObjectName("Secondary")
        self.bar.addWidget(self.status, 1)
        self.build_bar(self.bar)
        self.btn_refresh = QPushButton(t("refresh"))
        self.btn_refresh.setObjectName("Pill")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load)
        self.bar.addWidget(self.btn_refresh)
        v.addLayout(self.bar)
        self.table = DataTable(self.name, self.columns(), muted=self.muted,
                               sort=self.default_sort)
        self.table.customContextMenuRequested.connect(self._context)
        self.table.activated_row.connect(self.activate)
        v.addWidget(self.table, 1)

    # alt sınıflar
    def build_bar(self, bar):
        pass

    def columns(self):
        return []

    def muted(self, r):
        return False

    def collect(self):
        return []

    def menu(self, m, r):
        pass

    def activate(self, r):
        pass

    def extra_filter(self, r):
        return True

    # ortak
    def ensure_loaded(self):
        if not self.loaded and not self.loading:
            self.load()

    def load(self):
        if self.loading:
            return
        self.loading = True
        self.btn_refresh.setEnabled(False)
        self.status.setText(t("loading"))

        def run():
            from ..collect import wmi
            try:
                with wmi.com_thread():
                    rows = self.collect()
                self._bridge.done.emit(rows)
            except Exception as e:
                log_error(f"programs/{self.key}: {e!r}")
                self._bridge.failed.emit(str(e))
        threading.Thread(target=run, name="mergen-" + self.key, daemon=True).start()

    def _on_done(self, rows):
        self.loading = False
        self.loaded = True
        self.btn_refresh.setEnabled(True)
        self.table.proxy.extra = self.extra_filter
        self.table.set_rows(rows)
        self.update_status()

    def _on_failed(self, msg):
        self.loading = False
        self.btn_refresh.setEnabled(True)
        self.status.setText(t("load_failed", msg=msg))

    def _on_progress(self, text):
        self.status.setText(text)

    def update_status(self):
        n, total = self.table.visible_count(), len(self.table.rows())
        self.status.setText(t("n_items", n=n) if n == total else t("n_of_items", n=n, total=total))

    def refilter(self):
        self.table.proxy.set_extra(self.extra_filter)
        self.update_status()

    def set_filter(self, text):
        self.table.set_filter(text)
        if self.loaded:
            self.update_status()

    def _context(self, pos):
        r = self.table.row_at(pos)
        if r is None:
            return
        m = QMenu(self)
        self.menu(m, r)
        if not m.isEmpty():
            m.addSeparator()
        m.addMenu(self.table.columns_menu(m))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def check(self, key, pref, default, slot=None):
        cb = QCheckBox(t(key))
        cb.setChecked(bool(prefs.get(pref, default)))

        def changed(on):
            prefs.set(pref, on)
            (slot or self.refilter)()
        cb.toggled.connect(changed)
        return cb

    @staticmethod
    def add(m, key, fn, enabled=True):
        a = m.addAction(t(key))
        a.setEnabled(bool(enabled))
        a.triggered.connect(lambda _c=False: fn())
        return a

    def copy_menu(self, m, items):
        cm = m.addMenu(t("copy"))
        for key, val in items:
            a = cm.addAction(t(key))
            a.setEnabled(bool(val))
            a.triggered.connect(lambda _c=False, v=val: actions.copy(v))


# ================================================================================================ programlar
class ProgramsTab(SubTab):
    key = "programs"
    name = "programs"

    def build_bar(self, bar):
        self.cb_store = self.check("show_store", "programs_show_store", True)
        bar.addWidget(self.cb_store)

    def columns(self):
        return [
            Col("name", "col_name", lambda r: r["name"], width=300, stretch=True,
                icon=lambda r: file_icon(r.get("icon") if r.get("icon") and r["icon"].lower().endswith((".exe", ".ico"))
                                         else None)),
            Col("publisher", "col_publisher", lambda r: r.get("publisher"), width=180),
            Col("version", "col_version", lambda r: r.get("version"), width=120),
            Col("date", "col_installed", lambda r: fdate(r.get("date")), sort=lambda r: r.get("date") or "", width=95),
            Col("size", "col_size", lambda r: fsize(r.get("size")), sort=lambda r: r.get("size") or 0, right=True,
                width=85),
            Col("location", "col_location", lambda r: r.get("location"), width=300),
            Col("kind", "col_kind", lambda r: t("kind_" + r["kind"]), visible=False, width=90),
            Col("scope", "col_scope", lambda r: t("scope_" + r["scope"]), visible=False, width=110),
            Col("arch", "col_arch", lambda r: (r["arch"] + " bit") if r.get("arch") in ("32", "64") else
                (r.get("arch") or ""), visible=False, width=70),
            Col("uninstall", "col_uninstall", lambda r: r.get("uninstall"), visible=False, width=300),
            Col("regkey", "col_regkey", lambda r: r.get("regkey"), visible=False, width=300),
        ]

    def collect(self):
        from ..collect import programs
        return programs.collect()

    def extra_filter(self, r):
        return r["kind"] != "store" or self.cb_store.isChecked()

    def activate(self, r):
        actions.open_folder(r.get("location"), select=False)

    def menu(self, m, r):
        self.add(m, "open_folder", lambda: actions.open_folder(r.get("location"), select=False), r.get("location"))
        self.add(m, "uninstall", lambda: self.uninstall(r), r.get("uninstall") or r["kind"] == "store")
        if r.get("modify"):
            self.add(m, "modify", lambda: self._launch(r["modify"]))
        m.addSeparator()
        self.add(m, "show_in_registry", lambda: actions.show_in_regedit(r["regkey"]), r.get("regkey"))
        self.add(m, "search_online", lambda: actions.search_online(r["name"]))
        self.copy_menu(m, [("col_name", r["name"]), ("col_location", r.get("location")),
                           ("col_uninstall", r.get("uninstall")), ("col_regkey", r.get("regkey"))])

    def uninstall(self, r):
        if r["kind"] == "store":
            if r.get("system"):
                QMessageBox.information(self, "mergen", t("store_system"))
                return
            cmd = f"Remove-AppxPackage -Package {actions.ps_quote(r['package'])}"
            if not actions.confirm(self, t("uninstall"), t("uninstall_confirm", name=r["name"]), t("uninstall"),
                                   details=cmd):
                return
            ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              r"System32\WindowsPowerShell\v1.0\powershell.exe")
            self._watch(subprocess.Popen([ps, "-NoProfile", "-NonInteractive", "-Command", cmd],
                                         creationflags=subprocess.CREATE_NO_WINDOW))
            return
        cmd = r.get("uninstall")
        if not cmd or not actions.confirm(self, t("uninstall"), t("uninstall_confirm", name=r["name"]),
                                          t("uninstall"), details=cmd):
            return
        self._launch(cmd)

    def _launch(self, cmd):
        """Kaldırıcıyı kendi penceresiyle çalıştırır; yönetici isterse (hata 740) UAC ile yeniden dener."""
        cmd = os.path.expandvars(cmd)
        try:
            self._watch(subprocess.Popen(cmd))
            return
        except OSError as e:
            if getattr(e, "winerror", None) != 740:
                QMessageBox.warning(self, "mergen", str(e))
                return
        from ..collect.startup import command_exe
        exe = command_exe(cmd) or cmd
        rest = cmd[len(exe) + (2 if cmd.startswith('"') else 0):].strip()
        actions.report(self, *actions.shell_execute(exe, rest or None, verb="runas"))

    def _watch(self, proc):
        """Kaldırıcı kapanınca listeyi tazele."""
        def wait():
            try:
                proc.wait()
            finally:
                self._bridge.progress.emit(t("refreshing"))
                self._reload_later()
        threading.Thread(target=wait, daemon=True).start()

    def _reload_later(self):
        # iş parçacığından: done sinyali üzerinden yeniden yükleme (arayüz iş parçacığında çalışsın diye collect burada)
        from ..collect import programs, wmi
        try:
            with wmi.com_thread():
                rows = programs.collect()
            self._bridge.done.emit(rows)
        except Exception as e:
            self._bridge.failed.emit(str(e))


# ================================================================================================ başlangıç
class StartupTab(SubTab):
    key = "startup"
    name = "startup"

    def columns(self):
        return [
            Col("name", "col_name", lambda r: r["name"], width=260, stretch=True, icon=lambda r: file_icon(r.get("exe"))),
            Col("status", "col_status", lambda r: t("enabled") if r["enabled"] else t("disabled"),
                badge=lambda r: not r["enabled"],
                width=110),
            Col("source", "col_source", lambda r: t("src_" + r["source"]), width=200),
            Col("exe", "col_exe", lambda r: r.get("exe"), width=320),
            Col("command", "col_cmd", lambda r: r.get("command"), visible=False, width=360),
            Col("location", "col_location", lambda r: r.get("location"), visible=False, width=300),
            Col("disabled_at", "col_disabled_at", lambda r: r.get("disabled_at") or "", visible=False, width=150),
        ]

    def muted(self, r):
        return not r["enabled"]

    def collect(self):
        from ..collect import services, startup
        try:
            svcs = services.collect()
        except Exception as e:
            log_error(f"startup services: {e!r}")
            svcs = None
        return startup.collect(svcs)

    def activate(self, r):
        actions.open_folder(r.get("exe"))

    def menu(self, m, r):
        can = r.get("toggle") is not None
        a = self.add(m, "disable" if r["enabled"] else "enable", lambda: self.toggle(r), can)
        if not can:
            a.setToolTip(t("startup_service_hint"))
            a.setText(t("startup_service_hint"))
        m.addSeparator()
        self.add(m, "open_location", lambda: actions.open_folder(r.get("exe")), r.get("exe"))
        if r["source"].startswith("run_"):
            self.add(m, "show_in_registry", lambda: actions.show_in_regedit(r["location"]))
        elif r["source"].startswith("folder_"):
            self.add(m, "open_startup_folder", lambda: actions.open_folder(r["location"]))
        elif r["source"].startswith("task_"):
            self.add(m, "open_task_scheduler", lambda: actions.shell_execute("taskschd.msc"))
        self.add(m, "search_online", lambda: actions.search_online(r["name"]))
        self.copy_menu(m, [("col_name", r["name"]), ("col_exe", r.get("exe")), ("col_cmd", r.get("command"))])

    def toggle(self, r):
        from ..collect import startup
        enable = not r["enabled"]
        tg = r["toggle"]
        verb = t("enable") if enable else t("disable")
        if "task" in tg:
            what = f'schtasks /Change /TN "{tg["task"]}" /{"ENABLE" if enable else "DISABLE"}'
        else:
            what = f'{tg["hive"]}\\{startup.APPROVED}\\{tg["sub"]} : "{tg["name"]}" = ' + \
                   startup.approved_value(enable).hex(" ")
        text = t("startup_enable_confirm" if enable else "startup_disable_confirm", name=r["name"]) + \
            ("\n\n" + t("needs_admin") if r.get("admin") else "")
        if not actions.confirm(self, verb, text, verb, destructive=not enable, details=what):
            return
        ok = False
        if "task" in tg:
            ok = actions.report(self, *actions.run_elevated(
                "schtasks.exe", f'/Change /TN "{tg["task"]}" /{"ENABLE" if enable else "DISABLE"}'))
        elif tg["hive"] == "HKCU":
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, startup.APPROVED + "\\" + tg["sub"]) as k:
                    winreg.SetValueEx(k, tg["name"], 0, winreg.REG_BINARY, startup.approved_value(enable))
                ok = True
            except OSError as e:
                QMessageBox.warning(self, "mergen", str(e))
        else:
            data = startup.approved_value(enable).hex()
            ok = actions.report(self, *actions.run_elevated(
                "reg.exe", f'add "HKLM\\{startup.APPROVED}\\{tg["sub"]}" /v "{tg["name"]}" /t REG_BINARY '
                           f'/d {data} /f'))
        if ok:
            self.load()


# ================================================================================================ servisler
class ServicesTab(SubTab):
    key = "services"
    name = "services"

    def build_bar(self, bar):
        self.cb_third = self.check("third_party_only", "services_third_party", False)
        bar.addWidget(self.cb_third)
        b = QPushButton(t("open_services_msc"))
        b.setObjectName("Pill")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda: actions.shell_execute("services.msc"))
        bar.addWidget(b)

    def columns(self):
        return [
            Col("display", "col_name", lambda r: r["display"], width=280, stretch=True),
            Col("name", "col_service_name", lambda r: r["name"], width=160),
            Col("state", "col_status", lambda r: t("svc_" + r["state"]) if r.get("state") else "",
                badge=False, width=110),
            Col("start", "col_start_type", lambda r: t("start_" + r["start"]) if r.get("start") else "", width=150),
            Col("account", "col_account", lambda r: r.get("account"), visible=False, width=180),
            Col("pid", "col_pid", lambda r: r.get("pid") or "", sort=lambda r: r.get("pid") or 0, right=True,
                visible=False, width=70),
            Col("exe", "col_exe", lambda r: r.get("exe"), width=320),
            Col("description", "col_description", lambda r: r.get("description"), visible=False, width=400),
            Col("path", "col_cmd", lambda r: r.get("path"), visible=False, width=400),
        ]

    def muted(self, r):
        return r.get("start") == "disabled"

    def collect(self):
        from ..collect import services
        return services.collect()

    def extra_filter(self, r):
        if not self.cb_third.isChecked():
            return True
        exe = r.get("exe")
        return bool(exe) and not os.path.normcase(exe).startswith(SYSROOT)

    def activate(self, r):
        actions.open_folder(r.get("exe"))

    def menu(self, m, r):
        running = r.get("state") == "running"
        self.add(m, "svc_start", lambda: self.control(r, "start"), not running and r.get("start") != "disabled")
        self.add(m, "svc_stop", lambda: self.control(r, "stop"), running)
        self.add(m, "svc_restart", lambda: self.control(r, "restart"), running)
        m.addSeparator()
        self.add(m, "open_location", lambda: actions.open_folder(r.get("exe")), r.get("exe"))
        self.add(m, "show_in_registry", lambda: actions.show_in_regedit(
            "HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services\\" + r["name"]))
        self.add(m, "search_online", lambda: actions.search_online(f'{r["name"]} {r["display"]}'))
        self.copy_menu(m, [("col_name", r["display"]), ("col_service_name", r["name"]), ("col_exe", r.get("exe"))])

    def control(self, r, op):
        cmd = {"start": "Start-Service", "stop": "Stop-Service -Force", "restart": "Restart-Service -Force"}[op]
        cmd = f"{cmd} -Name {actions.ps_quote(r['name'])}"
        text = t("svc_confirm_" + op, name=r["display"]) + "\n\n" + t("needs_admin")
        if op != "start":
            text += "\n" + t("svc_stop_warn")
        if not actions.confirm(self, t("svc_" + op), text, t("svc_" + op), destructive=op != "start", details=cmd):
            return
        if actions.report(self, *actions.powershell_elevated(cmd)):
            self.load()


# ================================================================================================ sürücüler
class DriversTab(SubTab):
    key = "drivers"
    name = "drivers"
    default_sort = ["problem", 1]

    def build_bar(self, bar):
        self.cb_problems = self.check("problems_only", "drivers_problems_only", False)
        bar.addWidget(self.cb_problems)
        b = QPushButton(t("open_devmgmt"))
        b.setObjectName("Pill")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda: actions.shell_execute("devmgmt.msc"))
        bar.addWidget(b)

    def columns(self):
        def problem(r):
            if not r.get("problem"):
                return ""
            return t(r["problem_key"]) if r.get("problem_key") else t("prob_code", code=r["problem"])
        return [
            Col("device", "col_device", lambda r: r["device"], width=300, stretch=True),
            Col("problem", "col_problem", problem, sort=lambda r: r.get("problem") or 0, badge=True, width=170,
                tip=lambda r: t("prob_code", code=r["problem"]) if r.get("problem") else None),
            Col("class", "col_class", lambda r: r.get("class"), width=120),
            Col("provider", "col_provider", lambda r: r.get("provider"), width=150),
            Col("version", "col_version", lambda r: r.get("version"), width=130),
            Col("date", "col_date", lambda r: fdate(r.get("date")), sort=lambda r: r.get("date") or "", width=95),
            Col("inf", "col_inf", lambda r: r.get("inf"), width=120),
            Col("sys", "col_sys", lambda r: r.get("sys"), width=300),
            Col("store", "col_store", lambda r: r.get("store"), visible=False, width=300),
            Col("signer", "col_signer", lambda r: r.get("signer"), visible=False, width=180),
            Col("signed", "col_signed", lambda r: "" if r.get("signed") is None else t("yes" if r["signed"] else "no"),
                visible=False, width=70),
            Col("manufacturer", "col_manufacturer", lambda r: r.get("manufacturer"), visible=False, width=160),
            Col("service", "col_service_name", lambda r: r.get("service"), visible=False, width=120),
            Col("device_id", "col_device_id", lambda r: r.get("device_id"), visible=False, width=320),
        ]

    def collect(self):
        from ..collect import drivers
        return drivers.collect()

    def extra_filter(self, r):
        return not self.cb_problems.isChecked() or bool(r.get("problem"))

    def update_status(self):
        super().update_status()
        bad = sum(1 for r in self.table.rows() if r.get("problem"))
        if bad:
            self.status.setText(self.status.text() + " · " + t("n_problems", n=bad))

    def activate(self, r):
        actions.open_folder(r.get("sys") or r.get("store") or r.get("inf_path"))

    def menu(self, m, r):
        self.add(m, "open_sys", lambda: actions.open_folder(r.get("sys")), r.get("sys"))
        self.add(m, "open_inf", lambda: actions.open_folder(r.get("inf_path")), r.get("inf_path"))
        self.add(m, "open_store", lambda: actions.open_folder(r.get("store"), select=False), r.get("store"))
        m.addSeparator()
        if r.get("service"):
            self.add(m, "show_in_registry", lambda: actions.show_in_regedit(
                "HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services\\" + r["service"]))
        self.add(m, "search_online", lambda: actions.search_online(
            f'{r["device"]} {r.get("problem_key") and t(r["problem_key"]) or ""} driver'.strip()))
        self.copy_menu(m, [("col_device", r["device"]), ("col_device_id", r.get("device_id")),
                           ("col_sys", r.get("sys")), ("col_version", r.get("version"))])


# ================================================================================================ yollar
class PathsTab(SubTab):
    key = "paths"
    name = "paths"
    default_sort = ["kind", 0]

    def build_bar(self, bar):
        self.kind = QComboBox()
        for k in ("all", "env", "path", "known"):
            self.kind.addItem(t("pk_" + k), k)
        i = self.kind.findData(prefs.get("paths_kind", "all"))
        self.kind.setCurrentIndex(max(0, i))
        self.kind.currentIndexChanged.connect(lambda _i: (prefs.set("paths_kind", self.kind.currentData()),
                                                          self.refilter()))
        bar.addWidget(self.kind)
        b = QPushButton(t("edit_env"))
        b.setObjectName("Pill")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda: actions.shell_execute("rundll32.exe", "sysdm.cpl,EditEnvironmentVariables"))
        bar.addWidget(b)

    def columns(self):
        def state(r):
            if r["kind"] == "env":
                return ""
            if not r.get("exists"):
                return t("missing")
            return t("duplicate") if r.get("duplicate") else ""
        return [
            Col("name", "col_name", lambda r: t(r["name"]) if r["kind"] == "known" else r["name"], width=260,
                stretch=False),
            Col("value", "col_value", lambda r: r.get("value"), width=460, stretch=True),
            Col("state", "col_status", state, badge=True, width=110),
            Col("kind", "col_kind", lambda r: t("pk_" + r["kind"]),
                sort=lambda r: ({"path": 0, "env": 1, "known": 2}[r["kind"]], r.get("order") or 0,
                                r["name"].casefold()), width=130),
            Col("scope", "col_scope", lambda r: t("scope_" + r["scope"]) if r.get("scope") else "", width=110),
        ]

    def muted(self, r):
        return r["kind"] != "env" and not r.get("exists")

    def collect(self):
        from ..collect import paths
        return paths.collect()

    def extra_filter(self, r):
        k = self.kind.currentData()
        return k == "all" or r["kind"] == k

    def activate(self, r):
        actions.open_folder(r.get("value"), select=False)

    def menu(self, m, r):
        self.add(m, "open_folder", lambda: actions.open_folder(r.get("value"), select=False),
                 r["kind"] != "env" and r.get("exists") or (r["kind"] == "env" and os.path.isdir(r.get("value") or "")))
        self.add(m, "scan_sizes_here", lambda: self.page.scan_folder(r["value"]),
                 r.get("value") and os.path.isdir(r["value"]))
        self.copy_menu(m, [("col_name", r["name"]), ("col_value", r.get("value"))])


# ================================================================================================ boyutlar
class SizesTab(SubTab):
    key = "sizes"
    name = "sizes"
    default_sort = ["size", 1]

    def __init__(self, page):
        self.root = prefs.get("sizes_root") or os.path.expanduser("~")
        self._cancel = False
        super().__init__(page)
        self.btn_refresh.setText(t("scan"))

    def build_bar(self, bar):
        self.btn_up = QPushButton(t("parent_folder"))
        self.btn_up.setObjectName("Pill")
        self.btn_up.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_up.clicked.connect(self.up)
        bar.addWidget(self.btn_up)
        b = QPushButton(t("choose_folder"))
        b.setObjectName("Pill")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(self.choose)
        bar.addWidget(b)
        self.btn_stop = QPushButton(t("stop"))
        self.btn_stop.setObjectName("Pill")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.hide()
        bar.addWidget(self.btn_stop)

    def columns(self):
        return [
            Col("name", "col_name", lambda r: r["name"] or t("loose_files"), width=300, stretch=True,
                icon=lambda r: file_icon(r["path"]) if r["name"] else None),
            Col("size", "col_size", lambda r: fsize(r["size"]) or "0 B", sort=lambda r: r["size"], right=True,
                width=100),
            Col("share", "col_share", lambda r: self._share(r), sort=lambda r: r["size"], right=True, width=80),
            Col("files", "col_files", lambda r: f"{r['files']:,}".replace(",", ".") if r.get("files") is not None
                else "", sort=lambda r: r.get("files") or 0, right=True, width=100),
            Col("path", "col_path", lambda r: r["path"], visible=False, width=360),
        ]

    def _share(self, r):
        total = sum(x["size"] for x in self.table.rows()) or 1
        v = r["size"] * 100 / total
        return (f"%{v:.0f}" if is_tr() else f"{v:.0f}%")

    def ensure_loaded(self):
        if not self.loaded and not self.loading:
            self.status.setText(t("sizes_hint", root=self.root))

    def collect(self):
        from ..collect import paths
        self._cancel = False
        return paths.folder_sizes(self.root, cancelled=lambda: self._cancel,
                                  progress=lambda p: self._bridge.progress.emit(t("scanning", path=p)))

    def load(self):
        self.btn_stop.show()
        super().load()

    def _on_done(self, rows):
        self.btn_stop.hide()
        super()._on_done(rows)

    def _on_failed(self, msg):
        self.btn_stop.hide()
        super()._on_failed(msg)

    def update_status(self):
        total = sum(x["size"] for x in self.table.rows())
        self.status.setText(t("sizes_status", root=self.root, size=fsize(total) or "0 B") +
                            (" · " + t("stopped") if self._cancel else ""))

    def stop(self):
        self._cancel = True

    def set_root(self, path):
        self.root = os.path.normpath(path)
        prefs.set("sizes_root", self.root)
        self.load()

    def up(self):
        parent = os.path.dirname(self.root.rstrip("\\/"))
        if parent and parent != self.root:
            self.set_root(parent)

    def choose(self):
        d = QFileDialog.getExistingDirectory(self, t("choose_folder"), self.root)
        if d:
            self.set_root(d)

    def activate(self, r):
        if r["name"]:
            self.set_root(r["path"])

    def menu(self, m, r):
        self.add(m, "scan_sizes_here", lambda: self.set_root(r["path"]), r["name"])
        self.add(m, "open_folder", lambda: actions.open_folder(r["path"], select=False))
        self.copy_menu(m, [("col_path", r["path"])])


# ================================================================================================ sayfa
class ProgramsPage(Page):
    key = "programs"
    icon = "apps"
    TABS = [ProgramsTab, StartupTab, ServicesTab, DriversTab, PathsTab, SizesTab]

    def build(self):
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips = {}
        self.stack = QStackedWidget()
        self.tabs = {}
        for cls in self.TABS:
            c = Chip(t("sub_" + cls.key))
            c.clicked.connect(lambda _c=False, k=cls.key: self.show_tab(k))
            chips.addWidget(c)
            self.chips[cls.key] = c
        chips.addStretch(1)
        self.root.addLayout(chips)
        self.root.addSpacing(8)
        self.root.addWidget(self.stack, 1)
        self.current = None
        self.show_tab(prefs.get("programs_tab") or "programs")

    def tab(self, key):
        w = self.tabs.get(key)
        if w is None:
            cls = next(c for c in self.TABS if c.key == key)
            w = cls(self)
            w.set_filter(self.filter_text)
            self.tabs[key] = w
            self.stack.addWidget(w)
        return w

    def show_tab(self, key):
        if key not in self.chips:
            key = "programs"
        self.current = key
        prefs.set("programs_tab", key)
        for k, c in self.chips.items():
            c.setChecked(k == key)
        w = self.tab(key)
        self.stack.setCurrentWidget(w)
        if self.isVisible():
            w.ensure_loaded()

    def on_shown(self):
        self.tab(self.current).ensure_loaded()

    def set_filter(self, text):
        super().set_filter(text)
        for w in self.tabs.values():
            w.set_filter(text)

    def scan_folder(self, path):
        self.show_tab("sizes")
        self.tab("sizes").set_root(path)
