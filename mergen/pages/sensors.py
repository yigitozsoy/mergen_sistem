"""Sekme 3 — Sensörler (HWiNFO gibi): donanım başına sıcaklık, fan, voltaj, güç, saat, yük… her değerde anlık /
en düşük / en yüksek / ortalama. Veri mergen-helper'dan (LibreHardwareMonitorLib) gelir; yönetici izni ve PawnIO
yoksa yalnızca okunabilenler gösterilir ve nedeni üstte açıklanır."""
import os

from PyQt6.QtCore import QSortFilterProxyModel, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                             QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton, QSpinBox,
                             QSystemTrayIcon, QTreeView, QVBoxLayout)

from .. import actions, helper_client
from ..config import prefs
from ..i18n import is_tr, t
from ..sensor_service import GROUPS, LOG_DIR, UNITS, groups, service
from ..theme import theme
from .base import Page

PAWNIO_URL = "https://pawnio.eu/"
TYPE_ORDER = ["Temperature", "Fan", "Control", "Voltage", "Current", "Power", "Clock", "Frequency", "Load", "Level",
              "Factor", "Data", "SmallData", "Throughput", "Energy", "TimeSpan", "Timing", "Noise", "Humidity"]
HW_ORDER = ["Cpu", "GpuNvidia", "GpuAmd", "GpuIntel", "Motherboard", "SuperIO", "EmbeddedController", "Memory",
            "Storage", "Battery", "Network", "Cooler", "Psu"]
IdRole = Qt.ItemDataRole.UserRole + 1
SortRole = Qt.ItemDataRole.UserRole + 2


def fmt(v, typ):
    if v is None:
        return "—"
    if typ == "Throughput":
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        i = 0
        while v >= 1024 and i < 3:
            v /= 1024
            i += 1
        s = f"{v:.1f} {units[i]}"
    else:
        d = {"Fan": 0, "Clock": 0, "Frequency": 0, "Load": 1, "Control": 1, "Level": 1, "Temperature": 1,
             "Voltage": 3, "Current": 2, "Power": 1, "Data": 1, "SmallData": 0, "Energy": 0, "Factor": 2}.get(typ, 1)
        s = f"{v:.{d}f}"
        unit = UNITS.get(typ, "")
        if unit == "%":
            return ("%" + s.replace(".", ",")) if is_tr() else (s + "%")
        s = f"{s} {unit}".strip()
    return s.replace(".", ",") if is_tr() else s


class SensorProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setRecursiveFilteringEnabled(True)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(0)
        self.text = ""

    def set_text(self, text):
        self.text = (text or "").strip().casefold()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        if not self.text:
            return True
        idx = self.sourceModel().index(row, 0, parent)
        # üst öğe (donanım) eşleşirse tüm sensörleri görünsün
        p = parent
        while p.isValid():
            if self.text in (p.data() or "").casefold():
                return True
            p = p.parent()
        return self.text in (idx.data() or "").casefold()


class AlertDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(t("sensor_alerts"))
        v = QVBoxLayout(self)
        self.on = QCheckBox(t("alert_enable"))
        self.on.setChecked(bool(prefs.get("sensors_alert", False)))
        v.addWidget(self.on)
        form = QFormLayout()
        self.temp = QSpinBox()
        self.temp.setRange(50, 110)
        self.temp.setSuffix(" °C")
        self.temp.setValue(int(prefs.get("sensors_alert_temp", 95)))
        self.secs = QSpinBox()
        self.secs.setRange(1, 600)
        self.secs.setSuffix(" " + t("per_s"))
        self.secs.setValue(int(prefs.get("sensors_alert_secs", 30)))
        form.addRow(t("alert_temp"), self.temp)
        form.addRow(t("alert_secs"), self.secs)
        v.addLayout(form)
        hint = QLabel(t("alert_hint"))
        hint.setObjectName("Secondary")
        hint.setWordWrap(True)
        v.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def save(self):
        prefs.set("sensors_alert", self.on.isChecked())
        prefs.set("sensors_alert_temp", self.temp.value())
        prefs.set("sensors_alert_secs", self.secs.value())


class SensorsPage(Page):
    key = "sensors"
    icon = "thermostat"

    def build(self):
        self.svc = service()
        self.client = self.svc.c
        self.items = {}            # sensör kimliği -> [ad, değer, min, maks, ort] öğeleri
        self.structure = None

        # ---- durum kartı (yönetici / PawnIO / yardımcı yok)
        self.banner = QFrame()
        self.banner.setObjectName("Card")
        bl = QVBoxLayout(self.banner)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(6)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_text.setTextFormat(Qt.TextFormat.PlainText)
        bl.addWidget(self.banner_text)
        bb = QHBoxLayout()
        bb.setSpacing(6)
        self.btn_elevate = self._pill("elevate_once", self.elevate)
        self.btn_task = self._pill("create_task", self.create_task)
        self.btn_pawnio = self._pill("open_pawnio", lambda: QDesktopServices.openUrl(QUrl(PAWNIO_URL)))
        for b in (self.btn_elevate, self.btn_task, self.btn_pawnio):
            bb.addWidget(b)
        bb.addStretch(1)
        bl.addLayout(bb)
        self.root.addWidget(self.banner)
        self.root.addSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.status = QLabel(t("loading"))
        self.status.setObjectName("Secondary")
        bar.addWidget(self.status, 1)
        bar.addWidget(self._pill("reset_stats", self.reset))
        self.btn_view = self._pill("view", self.show_menu)
        bar.addWidget(self.btn_view)
        self.root.addLayout(bar)
        self.root.addSpacing(6)

        self.model = QStandardItemModel(0, 5)
        self.model.setHorizontalHeaderLabels([t("col_sensor"), t("col_current"), t("col_min"), t("col_max"),
                                              t("col_avg")])
        self.proxy = SensorProxy()
        self.proxy.setSourceModel(self.model)
        v = QTreeView()
        v.setObjectName("DataView")
        v.setModel(self.proxy)
        v.setUniformRowHeights(True)
        v.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        v.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.setAllColumnsShowFocus(True)
        v.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        v.customContextMenuRequested.connect(self.context_menu)
        h = v.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            v.setColumnWidth(i, 110)
            self.model.horizontalHeaderItem(i).setTextAlignment(Qt.AlignmentFlag.AlignRight |
                                                                Qt.AlignmentFlag.AlignVCenter)
        self.view = v
        self.root.addWidget(v, 1)

        self.svc.updated.connect(self._on_update)
        self.client.state.connect(lambda _s: self._update_banner())
        self.client.info.connect(lambda _i: self._update_banner())
        theme.bind(self, lambda _w: None)
        self._update_banner()

    def _pill(self, key, slot):
        b = QPushButton(t(key))
        b.setObjectName("Pill")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    # ---- görünürlük
    def on_shown(self):
        self.svc.set_visible(True)
        self._update_banner()

    def on_hidden(self):
        self.svc.set_visible(False)

    # ---- durum kartı
    def _update_banner(self):
        st = self.client.current_state
        info = self.client.last_info or {}
        has_task = getattr(self, "_task_cache", None)
        if has_task is None:
            has_task = self._task_cache = helper_client.task_exists()
        lines = []
        show_elevate = show_task = False
        if st == "missing" or not helper_client.helper_path() and not has_task:
            lines.append(t("helper_missing"))
        elif st in ("starting", "elevating"):
            lines.append(t("helper_starting"))
        elif info and not info.get("admin"):
            lines.append(t("helper_limited"))
            show_elevate = True
            show_task = not has_task
        elif info and info.get("admin"):
            lines.append(t("helper_admin_task") if has_task else t("helper_admin"))
        pawn = info.get("pawnio_installed") if info else helper_client.pawnio_installed()
        if not pawn:
            lines.append(t("pawnio_missing"))
        self.banner_text.setText("\n\n".join(lines))
        self.banner.setVisible(bool(lines))
        self.btn_elevate.setVisible(show_elevate)
        self.btn_task.setVisible(show_task)
        self.btn_pawnio.setVisible(not pawn)

    def elevate(self):
        ok, code = self.client.elevate()
        actions.report(self, ok, code)

    def create_task(self):
        src = helper_client.helper_path()
        if not src:
            return
        if not actions.confirm(self, t("create_task"), t("create_task_confirm", dir=helper_client.SECURE_DIR),
                               t("create_task"), destructive=False,
                               details=helper_client.task_xml(helper_client.SECURE_EXE, None)):
            return
        ok, code = helper_client.create_task(src)
        if actions.report(self, ok, code):
            self._task_cache = None
            with self.client._lock:
                self.client._out.append({"cmd": "quit"})       # yükseltilmemiş kopya kapanır, görevle yenisi açılır
            self.client._launched_at = 0
        self._update_banner()

    def delete_task(self):
        if not actions.confirm(self, t("delete_task"), t("delete_task_confirm"), t("delete_task")):
            return
        ok, code = helper_client.delete_task()
        actions.report(self, ok, code)
        self._task_cache = None
        self._update_banner()

    # ---- veri
    def _on_update(self, msg):
        if not self.isVisible():
            return
        hide_empty = bool(prefs.get("sensors_hide_empty", True))
        hw = msg.get("hardware", [])
        stats = self.svc.stats            # hiç değer almamış sensörler gizlenir (anlık boşluk ağacı yeniden kurdurmaz)
        sig = (hide_empty, tuple((h["id"], tuple(s["id"] for s in h["sensors"]
                                                  if (not hide_empty or s["id"] in stats)
                                                  and not self._unreliable(h, s))) for h in hw))
        if sig != self.structure:
            self._rebuild(hw, hide_empty)
            self.structure = sig
        n = 0
        for h in hw:
            for s in h["sensors"]:
                row = self.items.get(s["id"])
                if row is None:
                    continue
                n += 1
                mn, mx, avg = self.svc.stat(s["id"])
                for item, val in zip(row[1:], (s.get("value"), mn, mx, avg)):
                    txt = fmt(val, s["type"])
                    if item.text() != txt:
                        item.setText(txt)
        admin = (self.client.last_info or {}).get("admin")
        self.status.setText(t("sensors_status", n=n, hw=len(hw)) + (" · " + t("limited") if admin is False else ""))

    def _unreliable(self, h, s):
        """PawnIO yokken LHM işlemci gücü / voltajı için 0 döndürür: yanıltıcı, gösterme."""
        info = self.client.last_info or {}
        return (h["type"] == "Cpu" and s["type"] in ("Power", "Voltage", "Current")
                and not info.get("pawnio_installed"))

    def _rebuild(self, hw, hide_empty):
        expanded = {self.proxy.mapToSource(self.proxy.index(i, 0)).data(IdRole)
                    for i in range(self.proxy.rowCount()) if self.view.isExpanded(self.proxy.index(i, 0))}
        first = not self.items
        scroll = self.view.verticalScrollBar().value()
        self.model.removeRows(0, self.model.rowCount())
        self.items = {}
        nodes = {}
        order = sorted(hw, key=lambda h: (HW_ORDER.index(h["type"]) if h["type"] in HW_ORDER else 99))
        for h in order:
            sensors = [s for s in h["sensors"] if (not hide_empty or s["id"] in self.svc.stats)
                       and not self._unreliable(h, s)]
            if not sensors and not any(x.get("parent") == h["id"] for x in hw):
                continue
            it = QStandardItem(h["name"])
            it.setData(h["id"], IdRole)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            row = [it] + [QStandardItem("") for _ in range(4)]
            parent = nodes.get(h.get("parent"))
            (parent or self.model.invisibleRootItem()).appendRow(row)
            nodes[h["id"]] = it
            by_type = {}
            for s in sensors:
                by_type.setdefault(s["type"], []).append(s)
            for typ in sorted(by_type, key=lambda x: TYPE_ORDER.index(x) if x in TYPE_ORDER else 99):
                g = QStandardItem(t("st_" + typ) if t("st_" + typ) != "st_" + typ else typ)
                g.setData(h["id"] + "/" + typ, IdRole)
                it.appendRow([g] + [QStandardItem("") for _ in range(4)])
                for s in sorted(by_type[typ], key=lambda x: x.get("index", 0)):
                    cells = [QStandardItem(s["name"])] + [QStandardItem("") for _ in range(4)]
                    cells[0].setData(s["id"], IdRole)
                    for c in cells[1:]:
                        c.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    g.appendRow(cells)
                    self.items[s["id"]] = cells
        # açık dalları koru (ilk kurulumda her şey açık)
        def walk(pidx):
            for i in range(self.proxy.rowCount(pidx)):
                idx = self.proxy.index(i, 0, pidx)
                sid = self.proxy.mapToSource(idx).data(IdRole)
                if first or sid in expanded or "/" in str(sid):
                    self.view.expand(idx)
                walk(idx)
        if first:
            self.view.expandAll()
        else:
            walk(self.proxy.index(-1, -1))
            self.view.verticalScrollBar().setValue(scroll)

    def reset(self):
        self.svc.reset()

    # ---- menüler
    def set_filter(self, text):
        super().set_filter(text)
        self.proxy.set_text(text)
        self.view.expandAll()             # süzgeç değişince gizlenip geri gelen dallar kapalı kalmasın

    def show_menu(self):
        m = QMenu(self)
        gm = m.addMenu(t("sensor_groups"))
        cur = groups()
        for g in GROUPS:
            a = gm.addAction(t("sg_" + g))
            a.setCheckable(True)
            a.setChecked(g in cur)
            a.toggled.connect(lambda on, g=g: self._toggle_group(g, on))
        a = m.addAction(t("hide_empty"))
        a.setCheckable(True)
        a.setChecked(bool(prefs.get("sensors_hide_empty", True)))
        a.toggled.connect(lambda on: (prefs.set("sensors_hide_empty", on), self._force_rebuild()))
        m.addSeparator()
        m.addAction(t("sensor_alerts") + "…").triggered.connect(self.alerts_dialog)
        a = m.addAction(t("csv_log"))
        a.setCheckable(True)
        a.setChecked(bool(prefs.get("sensors_csv", False)))
        a.toggled.connect(lambda on: (prefs.set("sensors_csv", on), self.svc.apply()))
        m.addAction(t("open_log_folder")).triggered.connect(
            lambda: (os.makedirs(LOG_DIR, exist_ok=True), actions.open_folder(LOG_DIR, select=False)))
        m.addSeparator()
        m.addAction(t("expand_all")).triggered.connect(self.view.expandAll)
        m.addAction(t("collapse_all")).triggered.connect(self.view.collapseAll)
        if helper_client.task_exists():
            m.addSeparator()
            m.addAction(t("delete_task")).triggered.connect(self.delete_task)
        b = self.btn_view
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))

    def _toggle_group(self, g, on):
        cur = groups()
        cur = [x for x in GROUPS if (x in cur and x != g) or (x == g and on)]
        prefs.set("sensors_groups", cur)
        self.svc.c.resubscribe(groups=cur)
        self._force_rebuild()

    def _force_rebuild(self):
        self.structure = None
        if self.svc.last:
            self._on_update(self.svc.last)

    def alerts_dialog(self):
        d = AlertDialog(self)
        if d.exec() == QDialog.DialogCode.Accepted:
            d.save()
            self.svc.apply()
            if prefs.get("sensors_alert") and not QSystemTrayIcon.isSystemTrayAvailable():
                QMessageBox.information(self, "mergen", t("tray_unavailable"))

    def context_menu(self, pos):
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        src = self.proxy.mapToSource(idx.siblingAtColumn(0))
        name = src.data()
        value = self.proxy.mapToSource(idx.siblingAtColumn(1)).data()
        m = QMenu(self)
        m.addAction(t("copy")).triggered.connect(lambda: actions.copy(f"{name}\t{value}" if value else name))
        m.addAction(t("expand_all")).triggered.connect(self.view.expandAll)
        m.addAction(t("collapse_all")).triggered.connect(self.view.collapseAll)
        m.exec(self.view.viewport().mapToGlobal(pos))
