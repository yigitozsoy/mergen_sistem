"""Büyük listeler için ortak tablo: QAbstractTableModel + süzgeç/sıralama proksisi + QTreeView.

Sütunlar Col ile tanımlanır; görünürlük ve sıralama tercihlerde tablo adına göre saklanır (cols_<ad>, sort_<ad>).
Rozet sütunları (badge=True) gri hap olarak çizilir (sorunlu sürücü, devre dışı başlangıç öğesi vb.)."""
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractItemView, QMenu, QStyle, QStyledItemDelegate, QTreeView

from ..config import prefs
from ..i18n import t
from ..theme import qcolor

SortRole = Qt.ItemDataRole.UserRole + 1
RowRole = Qt.ItemDataRole.UserRole + 2


class Col:
    def __init__(self, cid, header, text, sort=None, right=False, visible=True, width=140, badge=False, tip=None,
                 stretch=False, icon=None):
        self.id, self.header, self.text, self.right = cid, header, text, right
        self.sort = sort or (lambda r, f=text: (f(r) or "").casefold() if isinstance(f(r), str) or f(r) is None
                             else f(r))
        self.visible, self.width, self.badge, self.tip, self.stretch, self.icon = \
            visible, width, badge, tip, stretch, icon


class DataModel(QAbstractTableModel):
    def __init__(self, cols, muted=None):
        super().__init__()
        self.cols = cols
        self.rows = []
        self.muted = muted          # r -> True ise satır soluk (devre dışı / var olmayan)

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def update_row(self, row_id, **changes):
        for i, r in enumerate(self.rows):
            if r.get("id") == row_id:
                r.update(changes)
                self.dataChanged.emit(self.index(i, 0), self.index(i, len(self.cols) - 1))
                return True
        return False

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.cols)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            c = self.cols[section]
            if role == Qt.ItemDataRole.DisplayRole:
                return t(c.header)
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return (Qt.AlignmentFlag.AlignRight if c.right else Qt.AlignmentFlag.AlignLeft) \
                    | Qt.AlignmentFlag.AlignVCenter
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        c = self.cols[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            v = c.text(r)
            return "" if v is None else str(v)
        if role == SortRole:
            v = c.sort(r)
            return "" if v is None else v
        if role == RowRole:
            return r
        if role == Qt.ItemDataRole.ToolTipRole:
            if c.tip:
                return c.tip(r)
            v = c.text(r)
            return str(v) if v and len(str(v)) > 30 else None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return (Qt.AlignmentFlag.AlignRight if c.right else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and self.muted and self.muted(r):
            return qcolor("text3")
        if role == Qt.ItemDataRole.DecorationRole and c.icon:
            return c.icon(r)
        return None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setSortRole(SortRole)
        self.text = ""
        self.extra = None       # r -> bool (ek süzgeç, ör. "yalnızca sorunlu")

    def set_text(self, text):
        self.text = (text or "").strip().casefold()
        self.invalidateFilter()

    def set_extra(self, fn):
        self.extra = fn
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        m = self.sourceModel()
        r = m.rows[row]
        if self.extra and not self.extra(r):
            return False
        if not self.text:
            return True
        hay = r.get("_hay")
        if hay is None:
            hay = " ".join(str(c.text(r) or "") for c in m.cols).casefold()
            r["_hay"] = hay
        return all(w in hay for w in self.text.split())

    def lessThan(self, left, right):
        a, b = left.data(SortRole), right.data(SortRole)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class BadgeDelegate(QStyledItemDelegate):
    """Rozet sütunlarında metni gri hap olarak çizer (kırmızı değil — tamga ailesi kuralı)."""

    def __init__(self, view, cols):
        super().__init__(view)
        self.cols = cols

    def paint(self, painter, option, index):
        c = self.cols[index.column()]
        text = index.data(Qt.ItemDataRole.DisplayRole)
        badge = c.badge(index.data(RowRole)) if callable(c.badge) else c.badge
        if not badge or not text:
            return super().paint(painter, option, index)
        # seçim/üzerinde arka planı için boş metinle varsayılan çizim
        opt = option.__class__(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        w = opt.widget
        (w.style() if w else None).drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, w)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fm = option.fontMetrics
        tw = fm.horizontalAdvance(text) + 16
        h = fm.height() + 4
        rect = QRectF(option.rect.left() + 4, option.rect.center().y() - h / 2 + 0.5, min(tw, option.rect.width() - 8), h)
        bg = QColor(qcolor("surface_hover"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, h / 2, h / 2)
        painter.setPen(qcolor("text"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, fm.elidedText(text, Qt.TextElideMode.ElideRight,
                                                                           int(rect.width()) - 10))
        painter.restore()


class DataTable(QTreeView):
    """Ortak tablo görünümü. name: tercih anahtarları için kimlik."""
    activated_row = pyqtSignal(dict)
    selection_changed = pyqtSignal()

    def __init__(self, name, cols, muted=None, parent=None, sort=None):
        super().__init__(parent)
        self.name = name
        self.cols = cols
        self.setObjectName("DataView")
        self.model_ = DataModel(cols, muted)
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model_)
        self.setModel(self.proxy)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(True)
        self.setAllColumnsShowFocus(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setItemDelegate(BadgeDelegate(self, cols))
        h = self.header()
        h.setStretchLastSection(False)
        h.setSectionsMovable(True)
        h.setMinimumSectionSize(40)
        h.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        h.customContextMenuRequested.connect(self._header_menu)
        visible = prefs.get("cols_" + name) or [c.id for c in cols if c.visible]
        for i, c in enumerate(cols):
            self.setColumnWidth(i, c.width)
            self.setColumnHidden(i, c.id not in visible and i != 0)
        self._stretch = next((i for i, c in enumerate(cols) if c.stretch), None)
        h.sectionResized.connect(self._user_resized)
        self._fitting = False
        saved = prefs.get("sort_" + name) or sort
        ids = [c.id for c in cols]
        if saved and saved[0] in ids:
            self.sortByColumn(ids.index(saved[0]), Qt.SortOrder(saved[1]))
        else:
            self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        h.sortIndicatorChanged.connect(lambda i, o: prefs.set("sort_" + name, [ids[i], o.value]))
        self.doubleClicked.connect(self._double)
        self.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit())

    # ---- veri
    def set_rows(self, rows):
        cur = self.current()
        self.model_.set_rows(rows)
        if cur is not None:
            self.select_id(cur.get("id"))

    def rows(self):
        return self.model_.rows

    def visible_count(self):
        return self.proxy.rowCount()

    def current(self):
        idx = self.selectionModel().selectedRows() if self.selectionModel() else []
        return idx[0].data(RowRole) if idx else None

    def row_at(self, pos):
        idx = self.indexAt(pos)
        return idx.data(RowRole) if idx.isValid() else None

    def select_id(self, row_id):
        for i in range(self.proxy.rowCount()):
            idx = self.proxy.index(i, 0)
            if idx.data(RowRole).get("id") == row_id:
                self.setCurrentIndex(idx)
                return True
        return False

    def set_filter(self, text):
        self.proxy.set_text(text)

    def _double(self, idx):
        r = idx.data(RowRole)
        if r is not None:
            self.activated_row.emit(r)

    # ---- genişleyen sütun: kalan boşluğu doldurur ama tanımlı genişliğin altına inmez (çok sütunda ezilmesin)
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()

    def _user_resized(self, i, _old, _new):
        if self._fitting:
            return
        if i == self._stretch:
            self._stretch = None          # kullanıcı elle boyutlandırdı: artık dokunma
        else:
            self._fit()

    def _fit(self):
        i = self._stretch
        if i is None or self.isColumnHidden(i):
            return
        others = sum(self.columnWidth(j) for j in range(len(self.cols)) if j != i and not self.isColumnHidden(j))
        self._fitting = True
        self.setColumnWidth(i, max(self.cols[i].width, self.viewport().width() - others - 2))
        self._fitting = False

    # ---- sütunlar
    def columns_menu(self, parent):
        m = QMenu(t("columns"), parent)
        for i, c in enumerate(self.cols):
            if i == 0:
                continue
            a = m.addAction(t(c.header))
            a.setCheckable(True)
            a.setChecked(not self.isColumnHidden(i))
            a.toggled.connect(lambda on, i=i: self._toggle(i, on))
        return m

    def _header_menu(self, pos):
        self.columns_menu(self).exec(self.header().mapToGlobal(pos))

    def _toggle(self, i, on):
        self.setColumnHidden(i, not on)
        self._fit()
        prefs.set("cols_" + self.name, [c.id for j, c in enumerate(self.cols) if not self.isColumnHidden(j)])
