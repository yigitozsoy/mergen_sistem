"""Sekme 5 — Görev yöneticisi: süreç listesi (gruplar + isteğe bağlı üst süreç ağacı), sağ tık işlemleri.

Model/görünüm (QAbstractItemModel + QSortFilterProxyModel): 300+ süreçte saniyede bir güncelleme akıcı kalsın diye
yapı değişmediyse yalnızca dataChanged; değiştiyse layoutChanged + kalıcı dizinler anahtarla (pid:başlama) eşlenir,
böylece seçim ve açık dallar korunur. Sistemi değiştiren her işlem (sonlandırma, öncelik, benzeşim) onay ister."""
import ctypes
import datetime
import os
import subprocess
from ctypes import wintypes
from urllib.parse import quote

import psutil
from PyQt6.QtCore import (QAbstractItemModel, QFileInfo, QModelIndex, QSortFilterProxyModel, Qt, QUrl)
from PyQt6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileIconProvider, QGridLayout,
                             QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton,
                             QStyledItemDelegate, QTreeView, QVBoxLayout)

from ..collect.procs import PRIORITY_CLASS
from ..config import log_error, prefs
from ..i18n import is_tr, t
from ..monitor import monitor
from ..theme import qcolor, theme
from .base import Page

GROUPS = ["apps", "background", "windows"]
SortRole = Qt.ItemDataRole.UserRole + 1
KeyRole = Qt.ItemDataRole.UserRole + 2


def _num(x, d=1):
    s = f"{x:.{d}f}"
    return s.replace(".", ",") if is_tr() else s


def _pct(v):
    return ("%" + _num(v)) if is_tr() else (_num(v) + "%")


def _pct0(v):
    return f"%{v:.0f}" if is_tr() else f"{v:.0f}%"


def _rate(v):
    """Bayt/sn -> "0,1 MB/sn" (Görev Yöneticisi gibi hep MB)."""
    return f"{_num(v / 1048576)} {t('mb_s')}"


def _mb(v):
    return f"{_num(v / 1048576)} MB"


# (kimlik, başlık anahtarı, metin, sıralama değeri, sağa yaslı, varsayılan görünür, genişlik)
COLUMNS = [
    ("name", "col_name", lambda r: r["name"], lambda r: (r["name"] or "").casefold(), False, True, 280),
    ("pid", "col_pid", lambda r: str(r["pid"]), lambda r: r["pid"], True, True, 70),
    ("cpu", "col_cpu", lambda r: _pct(r["cpu"]), lambda r: r["cpu"], True, True, 80),
    ("mem", "col_mem", lambda r: _mb(r["mem"]) if r.get("mem") is not None else "—",
     lambda r: r.get("mem") or 0, True, True, 100),
    ("disk", "col_disk", lambda r: _rate(r["disk"]), lambda r: r["disk"], True, True, 95),
    ("gpu", "col_gpu", lambda r: _pct(r["gpu"]), lambda r: r["gpu"], True, True, 75),
    ("gpu_engine", "col_gpu_engine", lambda r: r.get("gpu_engine_text") or "", lambda r: r.get("gpu_engine_text") or "",
     False, False, 110),
    ("user", "col_user", lambda r: r.get("user") or "", lambda r: (r.get("user") or "").casefold(), False, False, 110),
    ("priority", "col_priority", lambda r: t(r["priority"]) if r.get("priority") else "",
     lambda r: list(PRIORITY_CLASS).index(r["priority"]) if r.get("priority") in PRIORITY_CLASS else -1, False, False, 100),
    ("threads", "col_threads", lambda r: str(r.get("threads") or ""), lambda r: r.get("threads") or 0, True, False, 80),
    ("handles", "col_handles", lambda r: str(r.get("handles") or ""), lambda r: r.get("handles") or 0, True, False, 80),
    ("commit", "col_commit", lambda r: _mb(r["commit"]) if r.get("commit") is not None else "",
     lambda r: r.get("commit") or 0, True, False, 100),
    ("start", "col_start", lambda r: datetime.datetime.fromtimestamp(r["start"]).strftime(
        "%d.%m.%Y %H:%M:%S" if is_tr() else "%Y-%m-%d %H:%M:%S") if r.get("start") else "",
     lambda r: r.get("start") or 0, False, False, 140),
    ("exe", "col_exe", lambda r: r.get("exe") or "", lambda r: (r.get("exe") or "").casefold(), False, False, 320),
    ("cmd", "col_cmd", lambda r: r.get("cmd") or "", lambda r: (r.get("cmd") or "").casefold(), False, False, 400),
]
COL_IDS = [c[0] for c in COLUMNS]
HEAT = {"cpu": lambda v, tot: v / 100, "mem": lambda v, tot: v / max(1, tot * 0.15),
        "disk": lambda v, tot: v / (20 * 1048576), "gpu": lambda v, tot: v / 100}


class Node:
    __slots__ = ("key", "parent", "children", "row", "group")

    def __init__(self, key, parent=None, row=None, group=None):
        self.key = key
        self.parent = parent
        self.children = []
        self.row = row
        self.group = group


class ProcModel(QAbstractItemModel):
    def __init__(self):
        super().__init__()
        self.root = Node("root")
        self.nodes = {}
        self.grouped = bool(prefs.get("proc_groups", True))
        self.tree = bool(prefs.get("proc_tree", True))
        self.rows = []
        self.totals = {}
        self.mem_total = psutil.virtual_memory().total
        self.heat = True
        self._icons = {}
        self._icon_provider = QFileIconProvider()
        self._structure = None

    # ------------------------------------------------------------------ yapı
    def _build(self, rows):
        """(kök, düğümler, yapı imzası) üretir."""
        root = Node("root")
        nodes = {}
        by_pid = {r["pid"]: r for r in rows}
        groups = {}
        if self.grouped:
            for g in GROUPS:
                groups[g] = Node("group:" + g, root, group=g)
                nodes[groups[g].key] = groups[g]

        def top_of(r):
            """Ağaç kipinde: zincirin en üstteki (listede var olan) atası."""
            seen = set()
            cur = r
            while True:
                p = by_pid.get(cur["ppid"])
                if (p is None or p["pid"] == cur["pid"] or p["pid"] in seen or (p.get("start") or 0) > (cur.get("start") or 0)
                        or p["pid"] in (0, 4)):
                    return cur
                seen.add(cur["pid"])
                cur = p

        for r in rows:
            nodes[r["key"]] = Node(r["key"], row=r)
        sig = []
        for r in rows:
            n = nodes[r["key"]]
            parent = None
            if self.tree:
                p = by_pid.get(r["ppid"])
                if (p is not None and p["pid"] != r["pid"] and p["pid"] not in (0, 4)
                        and (p.get("start") or 0) <= (r.get("start") or 0)):
                    parent = nodes[p["key"]]
                    # Ağaçta grup, kökteki atanın grubu olur; ama "Windows" kökü altına uygulamaları gömme
                    if self.grouped and groups and top_of(r)["group"] != r["group"] and r["group"] == "apps":
                        parent = None
            if parent is None:
                parent = groups.get(top_of(r)["group"] if self.tree else r["group"], root) if self.grouped else root
                if self.tree and self.grouped and r["group"] == "apps":
                    parent = groups["apps"]
            n.parent = parent
            parent.children.append(n)
            sig.append((r["key"], parent.key))
        if self.grouped:
            for g in GROUPS:
                root.children.append(groups[g])
        return root, nodes, frozenset(sig)

    def set_rows(self, rows, totals=None):
        self.rows = rows
        if totals is not None:
            self.totals = totals
        root, nodes, sig = self._build(rows)
        if sig == self._structure and self.nodes:
            for key, n in nodes.items():         # yapı aynı: yalnızca değerleri güncelle
                old = self.nodes.get(key)
                if old is not None and n.row is not None:
                    old.row = n.row
            self._emit_all_changed(self.root)
        else:
            self.layoutAboutToBeChanged.emit()
            old_persistent = self.persistentIndexList()
            keys = [(self._node(i).key, i.column()) for i in old_persistent]
            self.root, self.nodes, self._structure = root, nodes, sig
            new = []
            for key, col in keys:
                n = self.nodes.get(key)
                new.append(self.createIndex(n.parent.children.index(n), col, n) if n is not None else QModelIndex())
            self.changePersistentIndexList(old_persistent, new)
            self.layoutChanged.emit()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)

    def _emit_all_changed(self, node):
        if node.children:
            first = self.createIndex(0, 0, node.children[0])
            last = self.createIndex(len(node.children) - 1, len(COLUMNS) - 1, node.children[-1])
            self.dataChanged.emit(first, last)
            for c in node.children:
                if c.children:
                    self._emit_all_changed(c)

    def relayout(self):
        """Gruplama / ağaç ayarı değişti: yapıyı baştan kur."""
        self.beginResetModel()
        self.root, self.nodes, self._structure = self._build(self.rows)
        self.endResetModel()

    # ------------------------------------------------------------------ Qt arayüzü
    def _node(self, index):
        return index.internalPointer() if index.isValid() else self.root

    def index(self, row, column, parent=QModelIndex()):
        p = self._node(parent)
        if 0 <= row < len(p.children):
            return self.createIndex(row, column, p.children[row])
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        n = index.internalPointer()
        p = n.parent
        if p is None or p is self.root:
            return QModelIndex()
        return self.createIndex(p.parent.children.index(p), 0, p)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid() and parent.column() > 0:
            return 0
        return len(self._node(parent).children)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        cid, key = COLUMNS[section][0], COLUMNS[section][1]
        if role == Qt.ItemDataRole.DisplayRole:
            tot = self.totals.get(cid)
            return f"{tot}\n{t(key)}" if tot else ("\n" + t(key) if cid in HEAT else t(key))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return (Qt.AlignmentFlag.AlignRight if COLUMNS[section][4] else Qt.AlignmentFlag.AlignLeft) \
                | Qt.AlignmentFlag.AlignVCenter
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        n = index.internalPointer()
        col = COLUMNS[index.column()]
        if n.row is None:                      # grup başlığı
            if role == Qt.ItemDataRole.DisplayRole and index.column() == 0:
                return f"{t('grp_' + n.group)} ({len(n.children)})"
            if role == SortRole:
                return GROUPS.index(n.group)
            if role == Qt.ItemDataRole.FontRole and index.column() == 0:
                f = QGuiApplication.font()
                f.setBold(True)
                return f
            if role == KeyRole:
                return n.key
            return None
        r = n.row
        if role == Qt.ItemDataRole.DisplayRole:
            return col[2](r)
        if role == SortRole:
            return col[3](r)
        if role == KeyRole:
            return n.key
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return (Qt.AlignmentFlag.AlignRight if col[4] else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            return self._icon(r.get("exe"))
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 0:
            return r.get("exe") or r["name"]
        if role == Qt.ItemDataRole.BackgroundRole and self.heat and col[0] in HEAT:
            v = r.get(col[0]) or 0
            level = max(0.0, min(1.0, HEAT[col[0]](v, self.mem_total)))
            if level >= 0.02:
                c = QColor(qcolor("accent"))
                c.setAlphaF(0.08 + 0.32 * level)
                return c
        return None

    def _icon(self, exe):
        if not exe:
            return None
        ic = self._icons.get(exe)
        if ic is None:
            try:
                ic = self._icon_provider.icon(QFileInfo(exe))
            except Exception:
                ic = QIcon()
            self._icons[exe] = ic
        return ic

    def row_for(self, index):
        n = self._node(index)
        return n.row if n is not self.root else None


class ProcProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setRecursiveFilteringEnabled(True)
        self.setSortRole(SortRole)
        self.setDynamicSortFilter(True)
        self.text = ""

    def set_text(self, text):
        self.text = (text or "").strip().casefold()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        if not self.text:
            return True
        src = self.sourceModel()
        idx = src.index(row, 0, parent)
        r = src.row_for(idx)
        if r is None:
            return False           # grup başlığı kendi başına eşleşmez (alt süreç eşleşirse görünür)
        hay = " ".join(str(x) for x in (r["name"], r["pid"], r.get("exe") or "", r.get("cmd") or "",
                                        r.get("user") or "")).casefold()
        return self.text in hay

    def lessThan(self, left, right):
        src = self.sourceModel()
        ln, rn = src._node(left), src._node(right)
        if ln.row is None and rn.row is None:      # gruplar sıralamadan bağımsız hep aynı sırada
            a, b = GROUPS.index(ln.group), GROUPS.index(rn.group)
            return a > b if self.sortOrder() == Qt.SortOrder.DescendingOrder else a < b
        a, b = left.data(SortRole), right.data(SortRole)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class HeatDelegate(QStyledItemDelegate):
    """Stil sayfası ::item kuralları BackgroundRole'ü ezdiği için yoğunluk rengini önce kendimiz boyarız."""

    def paint(self, painter, option, index):
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(bg, QColor):
            painter.fillRect(option.rect, bg)
        super().paint(painter, option, index)


class AffinityDialog(QDialog):
    def __init__(self, parent, name, current):
        super().__init__(parent)
        self.setWindowTitle(t("affinity_title", name=name))
        v = QVBoxLayout(self)
        v.addWidget(QLabel(t("affinity_text")))
        grid = QGridLayout()
        self.boxes = []
        n = psutil.cpu_count() or 1
        self.all = QCheckBox(t("affinity_all"))
        self.all.setChecked(len(current) == n)
        self.all.toggled.connect(lambda on: [b.setChecked(on) for b in self.boxes])
        v.addWidget(self.all)
        for i in range(n):
            b = QCheckBox(f"CPU {i}")
            b.setChecked(i in current)
            self.boxes.append(b)
            grid.addWidget(b, i // 4, i % 4)
        v.addLayout(grid)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def selected(self):
        return [i for i, b in enumerate(self.boxes) if b.isChecked()]


class ProcessesPage(Page):
    key = "processes"
    icon = "view_list"

    def build(self):
        self.model = ProcModel()
        self.proxy = ProcProxy()
        self.proxy.setSourceModel(self.model)
        self._first = True

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.status = QLabel(t("loading"))
        self.status.setObjectName("Secondary")
        bar.addWidget(self.status, 1)
        self.btn_view = QPushButton(t("view"))
        self.btn_view.setObjectName("Pill")
        self.btn_view.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view.clicked.connect(self.show_view_menu)
        bar.addWidget(self.btn_view)
        self.btn_end = QPushButton(t("end_task"))
        self.btn_end.setObjectName("Pill")
        self.btn_end.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_end.setEnabled(False)
        self.btn_end.clicked.connect(lambda: self.end_task(tree=False))
        bar.addWidget(self.btn_end)
        self.root.addLayout(bar)
        self.root.addSpacing(6)

        v = QTreeView()
        v.setObjectName("DataView")
        v.setModel(self.proxy)
        v.setUniformRowHeights(True)
        v.setSortingEnabled(True)
        v.setAlternatingRowColors(False)
        v.setAllColumnsShowFocus(True)
        v.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        v.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        v.customContextMenuRequested.connect(self.context_menu)
        v.setExpandsOnDoubleClick(True)
        h = v.header()
        h.setStretchLastSection(False)
        h.setSectionsMovable(True)
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        h.setMinimumHeight(44)
        h.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        h.customContextMenuRequested.connect(self.header_menu)
        for i, c in enumerate(COLUMNS):
            v.setColumnWidth(i, c[6])
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setMinimumSectionSize(48)
        self._delegate = HeatDelegate(v)
        v.setItemDelegate(self._delegate)
        visible = prefs.get("proc_columns") or [c[0] for c in COLUMNS if c[5]]
        for i, c in enumerate(COLUMNS):
            v.setColumnHidden(i, c[0] not in visible and c[0] != "name")
        col, order = prefs.get("proc_sort") or ["cpu", 1]
        if col in COL_IDS:
            v.sortByColumn(COL_IDS.index(col), Qt.SortOrder(order))
        h.sortIndicatorChanged.connect(lambda i, o: prefs.set("proc_sort", [COL_IDS[i], o.value]))
        v.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())
        self.view = v
        self.root.addWidget(v, 1)
        theme.bind(v, lambda w: w.viewport().update())

        self._mon = monitor()
        self._mon.procs.connect(self._on_procs)
        self._mon.sample.connect(self._on_sample)
        self._sample = None

    # ------------------------------------------------------------------ veri
    def on_shown(self):
        self._mon.want("procs", True)

    def on_hidden(self):
        self._mon.want("procs", False)

    def _on_sample(self, s):
        self._sample = s

    def _on_procs(self, rows):
        if not self.isVisible():
            return
        s = self._sample or {}
        gidx = {g["luid"]: g["index"] for g in s.get("gpus", [])}
        for r in rows:
            if r.get("gpu_engine"):
                r["gpu_engine_text"] = f"GPU {gidx.get(r.get('gpu_luid'), 0)} - {r['gpu_engine']}" \
                    if r.get("gpu_luid") in gidx else r["gpu_engine"]
        totals = {}
        if s:
            totals["cpu"] = _pct0(s["cpu"]["util"])
            totals["mem"] = _pct0(s["mem"]["util"])
            disks = s.get("disks") or []
            if disks:
                totals["disk"] = _pct0(max(d["active"] for d in disks))
            gpus = s.get("gpus") or []
            if gpus:
                totals["gpu"] = _pct0(max(g["util"] for g in gpus))
        self.model.set_rows(rows, totals)
        if self._first:
            self._first = False
            self.view.expand(self.proxy.index(0, 0))       # "Uygulamalar" açık başlasın
        n = len(rows)
        cpu = s.get("cpu", {}).get("util") if s else None
        mem = s.get("mem", {}).get("util") if s else None
        self.status.setText(t("proc_status", n=n, cpu=_pct(cpu or 0), mem=_pct(mem or 0)))
        self._update_buttons()

    # ------------------------------------------------------------------ arama / görünüm
    def set_filter(self, text):
        super().set_filter(text)
        self.proxy.set_text(text)
        if text.strip():
            self.view.expandAll()
        elif self.model.grouped:
            self.view.expand(self.proxy.index(0, 0))

    def show_view_menu(self):
        m = QMenu(self)
        a = m.addAction(t("view_groups"))
        a.setCheckable(True)
        a.setChecked(self.model.grouped)
        a.toggled.connect(lambda on: self._set_view("proc_groups", on))
        a = m.addAction(t("view_tree"))
        a.setCheckable(True)
        a.setChecked(self.model.tree)
        a.toggled.connect(lambda on: self._set_view("proc_tree", on))
        a = m.addAction(t("view_heat"))
        a.setCheckable(True)
        a.setChecked(self.model.heat)
        a.toggled.connect(self._set_heat)
        m.addSeparator()
        m.addMenu(self._columns_menu(m))
        m.addSeparator()
        m.addAction(t("expand_all")).triggered.connect(self.view.expandAll)
        m.addAction(t("collapse_all")).triggered.connect(self.view.collapseAll)
        b = self.btn_view
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))

    def _set_view(self, key, on):
        prefs.set(key, on)
        self.model.grouped = bool(prefs.get("proc_groups", True))
        self.model.tree = bool(prefs.get("proc_tree", True))
        self.model.relayout()
        if self.model.grouped:
            self.view.expand(self.proxy.index(0, 0))

    def _set_heat(self, on):
        self.model.heat = on
        self.view.viewport().update()

    def _columns_menu(self, parent):
        cm = QMenu(t("columns"), parent)
        for i, c in enumerate(COLUMNS):
            if c[0] == "name":
                continue
            a = cm.addAction(t(c[1]).replace("\n", " "))
            a.setCheckable(True)
            a.setChecked(not self.view.isColumnHidden(i))
            a.toggled.connect(lambda on, i=i: self._toggle_column(i, on))
        return cm

    def header_menu(self, pos):
        self._columns_menu(self).exec(self.view.header().mapToGlobal(pos))

    def _toggle_column(self, i, on):
        self.view.setColumnHidden(i, not on)
        prefs.set("proc_columns", [c[0] for j, c in enumerate(COLUMNS) if not self.view.isColumnHidden(j)])

    # ------------------------------------------------------------------ seçim / işlemler
    def selected_row(self):
        idxs = self.view.selectionModel().selectedRows()
        if not idxs:
            return None
        return self.model.row_for(self.proxy.mapToSource(idxs[0]))

    def _update_buttons(self):
        self.btn_end.setEnabled(self.selected_row() is not None)

    def _process(self, r):
        """Seçilen satırın süreci hâlâ aynı süreç mi (PID yeniden kullanılmış olabilir)?"""
        try:
            p = psutil.Process(r["pid"])
            if r.get("start") and abs(p.create_time() - r["start"]) > 1:
                return None
            return p
        except (psutil.Error, OSError):
            return None

    def _error(self, e):
        if isinstance(e, psutil.AccessDenied):
            QMessageBox.warning(self, "mergen", t("access_denied"))
        elif isinstance(e, psutil.NoSuchProcess):
            QMessageBox.information(self, "mergen", t("proc_gone"))
        else:
            QMessageBox.warning(self, "mergen", str(e))

    def context_menu(self, pos):
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        r = self.model.row_for(self.proxy.mapToSource(idx))
        if r is None:
            return
        m = QMenu(self)
        m.addAction(t("end_task")).triggered.connect(lambda: self.end_task(False))
        m.addAction(t("end_tree")).triggered.connect(lambda: self.end_task(True))
        m.addSeparator()
        pm = m.addMenu(t("priority"))
        g = QActionGroup(pm)
        for key in PRIORITY_CLASS:
            a = QAction(t(key), pm)
            a.setCheckable(True)
            a.setChecked(r.get("priority") == key)
            a.setActionGroup(g)
            a.triggered.connect(lambda _c=False, k=key: self.set_priority(k))
            pm.addAction(a)
        m.addAction(t("affinity")).triggered.connect(self.set_affinity)
        m.addSeparator()
        a = m.addAction(t("open_location"))
        a.setEnabled(bool(r.get("exe")))
        a.triggered.connect(lambda: self.open_location(r))
        a = m.addAction(t("properties"))
        a.setEnabled(bool(r.get("exe")))
        a.triggered.connect(lambda: self.properties(r))
        m.addAction(t("search_online")).triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://www.bing.com/search?q=" + quote(r["name"]))))
        cm = m.addMenu(t("copy"))
        for key, val in (("col_name", r["name"]), ("col_pid", str(r["pid"])), ("col_exe", r.get("exe")),
                         ("col_cmd", r.get("cmd"))):
            a = cm.addAction(t(key))
            a.setEnabled(bool(val))
            a.triggered.connect(lambda _c=False, v=val: QGuiApplication.clipboard().setText(v))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def end_task(self, tree=False):
        r = self.selected_row()
        if r is None:
            return
        p = self._process(r)
        if p is None:
            QMessageBox.information(self, "mergen", t("proc_gone"))
            return
        targets = [p]
        if tree:
            try:
                targets += p.children(recursive=True)
            except (psutil.Error, OSError):
                pass
        name = r["name"]
        text = t("end_tree_confirm", name=name, n=len(targets)) if tree else t("end_confirm", name=name, pid=r["pid"])
        if r.get("group") == "windows":
            text += "\n\n" + t("end_system_warn")
        if r.get("self"):
            text += "\n\n" + t("end_self_warn")
        box = QMessageBox(QMessageBox.Icon.Warning, t("end_task"), text, parent=self)
        ok = box.addButton(t("end_task"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(t("cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not ok:
            return
        failed = None
        for proc in reversed(targets):           # önce çocuklar
            try:
                proc.terminate()
            except psutil.NoSuchProcess:
                pass
            except (psutil.Error, OSError) as e:
                failed = e
        if failed is not None:
            self._error(failed)

    def set_priority(self, key):
        r = self.selected_row()
        p = self._process(r) if r else None
        if p is None:
            return
        if key in ("prio_realtime", "prio_high"):
            if QMessageBox.question(self, t("priority"), t("priority_warn", name=r["name"], p=t(key))) \
                    != QMessageBox.StandardButton.Yes:
                return
        try:
            p.nice(PRIORITY_CLASS[key])
        except (psutil.Error, OSError) as e:
            self._error(e)

    def set_affinity(self):
        r = self.selected_row()
        p = self._process(r) if r else None
        if p is None:
            return
        try:
            cur = p.cpu_affinity()
        except (psutil.Error, OSError) as e:
            self._error(e)
            return
        d = AffinityDialog(self, r["name"], cur)
        if d.exec() == QDialog.DialogCode.Accepted:
            sel = d.selected()
            if not sel:
                return
            try:
                p.cpu_affinity(sel)
            except (psutil.Error, OSError) as e:
                self._error(e)

    def open_location(self, r):
        exe = r.get("exe")
        if exe and os.path.exists(exe):
            subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(exe)])

    def properties(self, r):
        exe = r.get("exe")
        if not exe:
            return

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                        ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                        ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                        ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                        ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x0000000C            # SEE_MASK_INVOKEIDLIST
        info.lpVerb = "properties"
        info.lpFile = exe
        info.nShow = 1
        try:
            ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info))
        except Exception as e:
            log_error(f"properties: {e!r}")
