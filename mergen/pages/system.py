"""Sekme 1 — Sistem bilgisi (dxdiag gibi, salt okunur).

Açılışta önbellekten (cache/system.json) hemen gösterir, arka planda (ayrı iş parçacığı) WMI / DXGI'dan tazeler;
bölümler geldikçe kartlar güncellenir. Kişisel bilgiler (seri no, MAC, IP…) varsayılan gizli: satıra tıklayınca ya
da üstteki göz düğmesiyle hepsi birden görünür (seçim hatırlanır)."""
import datetime
import os
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
                             QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..collect import fmt, report
from ..config import CACHE_DIR, log_error, prefs, read_json, write_json
from ..i18n import t
from ..widgets import IconButton
from .base import Page

CACHE_FILE = os.path.join(CACHE_DIR, "system.json")
CACHE_VERSION = 1


def _fold(s):
    return (s or "").replace("İ", "i").replace("I", "ı").casefold()


class _Bridge(QObject):
    section = pyqtSignal(dict)
    done = pyqtSignal(dict)


class ValueLabel(QLabel):
    """Değer metni; kişisel bilgiyse gizli başlar, tıklayınca görünür."""

    def __init__(self, text, sensitive, page):
        super().__init__()
        self._text = text
        self.sensitive = sensitive
        self.page = page
        self.revealed = False
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.refresh()

    def hidden(self):
        return self.sensitive and not self.revealed and not self.page.show_personal

    def refresh(self):
        if self.hidden():
            self.setObjectName("HiddenValue")
            self.setText(t("hidden_value"))
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        else:
            self.setObjectName("RowValue")
            self.setText(self._text)
            self.unsetCursor()
            self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        if self.hidden() and e.button() == Qt.MouseButton.LeftButton:
            self.revealed = True
            self.refresh()
            return
        super().mousePressEvent(e)

    def full_text(self):
        return self._text


class Card(QFrame):
    """Bir bölüm: başlık + Kopyala, satırlar (etiket: değer) ve alt gruplar (ör. her bellek modülü)."""

    def __init__(self, sid, page):
        super().__init__()
        self.sid = sid
        self.page = page
        self.data = None
        self.wanted = True                # arama süzgecine göre gösterilsin mi (CardColumns yerleştirir)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 12, 12, 14)
        v.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(4)
        self.title = QLabel(t("sec_" + sid))
        self.title.setObjectName("CardTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.btn_copy = IconButton("copy", t("copy"), 32, 18)
        self.btn_copy.clicked.connect(self.copy)
        head.addWidget(self.btn_copy)
        v.addLayout(head)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 2, 0, 0)
        self.body_lay.setSpacing(2)
        v.addWidget(self.body)
        self.blocks = []        # [(grup başlık widget'ı | None, başlık metni, [(etiket, değer, satır metni)], ızgara)]
        self.values = []

    def set_data(self, data):
        self.data = data
        while self.body_lay.count():
            w = self.body_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.blocks, self.values = [], []
        if data.get("rows"):
            self._add_block(None, data["rows"])
        for g in data.get("groups", []):
            self._add_block(g, g.get("rows", []))
        if not self.blocks:
            self._add_block(None, [fmt.row("lbl_status", None)], keep_empty=True)
        self.apply_filter(self.page.filter_text)

    def _add_block(self, group, rows, keep_empty=False):
        head = None
        gtitle = ""
        if group is not None:
            head = QWidget()
            hl = QHBoxLayout(head)
            hl.setContentsMargins(0, 8, 0, 2)
            hl.setSpacing(8)
            gtitle = fmt.text(group.get("title"))
            lab = QLabel(gtitle)
            lab.setObjectName("GroupTitle")
            lab.setWordWrap(True)
            hl.addWidget(lab, 1)
            if group.get("badge"):
                b = QLabel(fmt.text(group["badge"]))
                b.setObjectName("Badge")
                hl.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.body_lay.addWidget(head)
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)
        items = []
        for r in rows:
            if r.get("v") in (None, "") and not keep_empty:
                continue                 # boş satırları gösterme; raporda "—" olarak kalır
            lab = QLabel(fmt.label(r))
            lab.setObjectName("RowLabel")
            lab.setMinimumWidth(150)
            lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            val = ValueLabel(fmt.text(r.get("v")), r.get("s") is True, self.page)
            n = grid.rowCount()
            grid.addWidget(lab, n, 0)
            grid.addWidget(val, n, 1)
            items.append((lab, val))
            self.values.append(val)
        self.body_lay.addWidget(grid_w)
        if not items and head is None:
            grid_w.hide()
        self.blocks.append((head, gtitle, items, grid_w))

    def refresh_hidden(self):
        for v in self.values:
            v.refresh()

    def apply_filter(self, text):
        """Kart en az bir eşleşme içeriyorsa görünür kalır. Bölüm adı eşleşirse hepsi görünür."""
        q = _fold(text.strip())
        if not q or q in _fold(self.title.text()):
            for head, _g, items, grid_w in self.blocks:
                if head:
                    head.show()
                grid_w.setVisible(bool(items) or head is None)
                for lab, val in items:
                    lab.show()
                    val.show()
            self.wanted = True
            return True
        any_hit = False
        for head, gtitle, items, grid_w in self.blocks:
            group_hit = bool(gtitle) and q in _fold(gtitle)
            hits = 0
            for lab, val in items:
                hit = group_hit or q in _fold(lab.text()) or (not val.hidden() and q in _fold(val.full_text()))
                lab.setVisible(hit)
                val.setVisible(hit)
                hits += hit
            show = group_hit or hits > 0
            if head:
                head.setVisible(show)
            grid_w.setVisible(show and bool(items))
            any_hit = any_hit or show
        self.wanted = any_hit
        return any_hit

    def copy(self):
        if not self.data:
            return
        sec = self.data
        if not self.page.show_personal:          # görünmeyen kişisel bilgiler panoya da gitmesin
            sec = report._strip({"sections": [self.data]}, only_hidden=True)["sections"][0]
        QGuiApplication.clipboard().setText(report.section_text(sec, t))
        self.page.flash(t("copied"))


class CardColumns(QWidget):
    """Kartları genişliğe göre 1 ya da 2 sütuna yerleştirir (kısa sütuna ekleyerek)."""

    def __init__(self):
        super().__init__()
        self.cards = []
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(14)
        self.cols = []
        self._ncols = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.relayout)

    def set_cards(self, cards):
        self.cards = cards
        self._ncols = 0
        self.relayout()

    def schedule(self):
        self._timer.start()

    def relayout(self):
        """Kartlar yeniden dağıtılır; görünürlük Card.wanted'dan gelir (arama süzgeci)."""
        n = 2 if self.width() >= 980 else 1
        for c in self.cards:
            c.setParent(self)               # eski sütunlardan çıkar (sütunlar silinirken kartlar silinmesin)
            c.hide()
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cols = []
        for _ in range(n):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(14)
            self.cols.append((v, [0]))
            self.lay.addWidget(w, 1)
        for c in self.cards:
            if not c.wanted:
                continue
            v, h = min(self.cols, key=lambda x: x[1][0])
            v.addWidget(c)
            c.show()
            h[0] += max(c.sizeHint().height(), 60) + 14
        for v, _h in self.cols:
            v.addStretch(1)
        self._ncols = n

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if (2 if self.width() >= 980 else 1) != self._ncols:   # sütun sayısı değişince
            self.schedule()


class SystemPage(Page):
    key = "system"
    icon = "desktop"

    def build(self):
        from ..collect.system import SECTIONS
        self.show_personal = bool(prefs.get("system_show_personal", False))
        self.data = None
        self._running = False
        self._bridge = _Bridge()
        self._bridge.section.connect(self._on_section)
        self._bridge.done.connect(self._on_done)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.status = QLabel("")
        self.status.setObjectName("Secondary")
        bar.addWidget(self.status, 1)
        self.btn_eye = IconButton("visibility", "", 36, 20)
        self.btn_eye.clicked.connect(self.toggle_personal)
        bar.addWidget(self.btn_eye)
        self.btn_refresh = IconButton("refresh", t("refresh"), 36, 20)
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.btn_refresh)
        self.btn_export = QPushButton(t("export"))
        self.btn_export.setObjectName("Pill")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.clicked.connect(self.show_export_menu)
        bar.addWidget(self.btn_export)
        self.root.addLayout(bar)
        self.root.addSpacing(6)

        self.cards = {sid: Card(sid, self) for sid in SECTIONS}
        self.columns = CardColumns()
        self.columns.set_cards(list(self.cards.values()))
        self.no_match = QLabel(t("no_match"))
        self.no_match.setObjectName("EmptyHint")
        self.no_match.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_match.hide()
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 6, 12)
        iv.addWidget(self.no_match)
        iv.addWidget(self.columns)
        iv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        self.scroll = scroll
        self.root.addWidget(scroll, 1)
        self._update_eye()

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._restore_status)
        self._status_text = ""

        cached = read_json(CACHE_FILE)
        if cached and cached.get("cache_version") == CACHE_VERSION and cached.get("sections"):
            self._apply(cached)
            self._set_status(t("cached_at", t=self._when(cached.get("collected"))))
        self._started = False

    # ------------------------------------------------------------------ veri
    def on_shown(self):
        if not self._started:
            self._started = True
            self.refresh()

    def refresh(self):
        if self._running:
            return
        self._running = True
        self.btn_refresh.setEnabled(False)
        if self.data is None:
            self._set_status(t("refreshing"))

        def work():
            from ..collect import system
            try:
                data = system.collect(progress=lambda s: self._bridge.section.emit(s))
            except Exception as e:
                log_error(f"system.collect: {e!r}")
                data = {}
            self._bridge.done.emit(data)
        threading.Thread(target=work, name="mergen-system", daemon=True).start()

    def _on_section(self, s):
        card = self.cards.get(s.get("id"))
        if card is not None:
            card.set_data(s)
            self.columns.schedule()

    def _on_done(self, data):
        self._running = False
        self.btn_refresh.setEnabled(True)
        if not data.get("sections"):
            return
        self.data = data
        self.columns.schedule()
        self._set_status(t("updated_at", t=self._when(data.get("collected")),
                           s=str(data.get("seconds", "")).replace(".", ",")))
        try:
            write_json(CACHE_FILE, dict(data, cache_version=CACHE_VERSION))
        except OSError as e:
            log_error(f"system cache: {e!r}")
        self._apply_filter()

    def _apply(self, data):
        self.data = data
        for s in data.get("sections", []):
            if s.get("id") in self.cards:
                self.cards[s["id"]].set_data(s)
        self.columns.relayout()

    @staticmethod
    def _when(iso):
        try:
            d = datetime.datetime.fromisoformat(iso)
            return d.strftime("%d.%m.%Y %H:%M")
        except (TypeError, ValueError):
            return "—"

    # ------------------------------------------------------------------ durum satırı
    def _set_status(self, text):
        self._status_text = text
        if not self._flash_timer.isActive():
            self.status.setText(text)

    def flash(self, text):
        self.status.setText(text)
        self._flash_timer.start(1800)

    def _restore_status(self):
        self.status.setText(self._status_text)

    # ------------------------------------------------------------------ kişisel bilgiler
    def toggle_personal(self):
        self.show_personal = not self.show_personal
        prefs.set("system_show_personal", self.show_personal)
        self._update_eye()
        for c in self.cards.values():
            c.refresh_hidden()
        self._apply_filter()

    def _update_eye(self):
        on = self.show_personal
        self.btn_eye.set_icon_name("visibility_off" if on else "visibility")
        self.btn_eye.setToolTip(t("hide_personal") if on else t("show_personal"))

    # ------------------------------------------------------------------ arama
    def set_filter(self, text):
        super().set_filter(text)
        self._apply_filter()

    def _apply_filter(self):
        any_visible = False
        for c in self.cards.values():
            if c.data is None:
                c.wanted = not self.filter_text.strip()
                continue
            any_visible = c.apply_filter(self.filter_text) or any_visible
        self.no_match.setVisible(bool(self.filter_text.strip()) and not any_visible and self.data is not None)
        self.columns.relayout()

    # ------------------------------------------------------------------ dışa aktarım
    def show_export_menu(self):
        m = QMenu(self)
        for kind in ("txt", "html", "json"):
            m.addAction(t("export_" + kind)).triggered.connect(lambda _c=False, k=kind: self.export(k))
        m.addSeparator()
        strip = QAction(t("export_strip"), m)
        strip.setCheckable(True)
        strip.setChecked(bool(prefs.get("export_strip", True)))
        strip.toggled.connect(lambda on: prefs.set("export_strip", on))
        m.addAction(strip)
        b = self.btn_export
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))

    def export(self, kind):
        if not self.data:
            return
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        name = f"mergen-{datetime.date.today():%Y%m%d}.{kind}"
        path, _ = QFileDialog.getSaveFileName(self, t("export"), os.path.join(docs, name),
                                              f"{kind.upper()} (*.{kind})")
        if not path:
            return
        try:
            report.write(path, kind, self.data, t, strip=bool(prefs.get("export_strip", True)))
            self.flash(t("export_done", p=os.path.basename(path)))
        except OSError as e:
            self.flash(t("export_failed", e=e.strerror or str(e)))
