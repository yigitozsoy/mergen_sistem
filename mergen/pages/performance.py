"""Sekme 4 — Performans (Görev Yöneticisi'nin Performans sekmesi gibi).

Solda kaynak başına mini grafik (CPU, bellek, her disk, her ağ bağdaştırıcısı, her GPU), sağda seçilenin büyük
grafikleri + sayıları. Veri monitor.history'den (sekme gizliyken de birikir); gizli sekmede çizim yapılmaz.
Grafikler QPainter ile çizilir (pyqtgraph'a gerek kalmadı: 60-600 nokta için daha hafif, temaya birebir uyar)."""
import math
import winreg

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)

from ..collect.fmt import human_bytes
from ..config import prefs
from ..i18n import is_tr, t
from ..monitor import monitor
from ..theme import qcolor, theme
from .base import Page

WINDOWS = (60, 300, 600)
GPU_ENGINE_ORDER = ["3D", "Copy", "VideoDecode", "VideoEncode", "VideoProcessing", "Compute_0", "Compute_1"]
ENGINE_LABEL = {"VideoDecode": "Video Decode", "VideoEncode": "Video Encode", "VideoProcessing": "Video Processing"}


# ---------------------------------------------------------------------------------------------- biçim
def _num(x, d=1):
    s = f"{x:.{d}f}"
    return s.replace(".", ",") if is_tr() else s


def pct(v):
    if v is None:
        return "—"
    return ("%" + _num(v, 0)) if is_tr() else (_num(v, 0) + "%")


def gb(v, d=1):
    return "—" if v is None else f"{_num(v / 1073741824, d)} GB"


def size(v):
    return "—" if v is None else human_bytes(v, is_tr())


def byte_rate(v):
    """Bayt/sn -> "12,3 MB/sn"."""
    if v is None:
        return "—"
    units = ["B", "KB", "MB", "GB"]
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{_num(v, 0 if i == 0 or v >= 100 else 1)} {units[i]}/{t('per_s')}"


def bit_rate(v):
    """Bit/sn -> "12,3 Mbps"."""
    if v is None:
        return "—"
    units = ["bps", "Kbps", "Mbps", "Gbps"]
    i = 0
    while v >= 1000 and i < len(units) - 1:
        v /= 1000
        i += 1
    return f"{_num(v, 0 if i == 0 or v >= 100 else 1)} {units[i]}"


def mhz(v):
    return "—" if not v else f"{_num(v / 1000, 2)} GHz"


def duration(sec):
    sec = int(sec or 0)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}:{h:02}:{m:02}:{s:02}"


def nice_ceil(v, floor):
    """Otomatik ölçek için 1-2-5 dizisinde v'den büyük ilk değer."""
    v = max(v, floor)
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def cpu_name():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return " ".join(str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).split())
    except OSError:
        return ""


# ---------------------------------------------------------------------------------------------- kaynaklar
def pick(s, key):
    """Bir örnekten anahtarın (cpu, mem, disk:<id>, net:<ad>, gpu:<luid>) verisini seçer."""
    if s is None:
        return None
    if key == "cpu":
        return s.get("cpu")
    if key == "mem":
        return s.get("mem")
    kind, _, ident = key.partition(":")
    for item in s.get(kind + "s", []):
        if str(item.get({"disk": "id", "net": "name", "gpu": "luid"}[kind])) == ident:
            return item
    return None


def resources(s):
    """Örnekteki kaynakların sıralı anahtarları."""
    keys = ["cpu", "mem"]
    keys += [f"disk:{d['id']}" for d in s.get("disks", [])]
    keys += [f"net:{n['name']}" for n in s.get("nets", [])]
    keys += [f"gpu:{g['luid']}" for g in s.get("gpus", [])]
    return keys


def tile_text(key, d):
    """(başlık, alt başlık, değer satırı, ana seri değeri, ymax) — sol mini kart için."""
    if d is None:
        return "", "", "—", None, 100
    if key == "cpu":
        return t("perf_cpu"), "", f"{pct(d['util'])}  {mhz(d.get('mhz'))}", d["util"], 100
    if key == "mem":
        return t("perf_mem"), "", f"{gb(d['used'])} / {gb(d['total'])} ({pct(d['util'])})", d["util"], 100
    kind = key.split(":")[0]
    if kind == "disk":
        title = f"{t('perf_disk')} {d['id']}" + (f" ({d['letters']})" if d.get("letters") else "")
        return title, d.get("model") or "", pct(d["active"]), d["active"], 100
    if kind == "net":
        return d["name"], "", f"{t('perf_send_short')} {bit_rate(d['send'])}  {t('perf_recv_short')} " \
                              f"{bit_rate(d['recv'])}", d["send"] + d["recv"], None
    if kind == "gpu":
        return f"GPU {d['index']}", d["name"], pct(d["util"]), d["util"], 100
    return key, "", "", None, 100


# ---------------------------------------------------------------------------------------------- grafik
def line_color():
    """Grafik rengi = vurgu; ama arka planla karşıtlığı zayıfsa (açık temada gri vurgu) ikincil metin rengi."""
    acc, bg = qcolor("accent"), qcolor("bg")
    if abs(acc.lightnessF() - bg.lightnessF()) < 0.35:
        return qcolor("text2")
    return acc


class Graph(QWidget):
    """Sağa yaslı zaman serisi: en yeni değer sağ kenarda. series = [(değerler, kalın/dolu mu, kesikli mi)]."""

    def __init__(self, parent=None, mini=False, label=""):
        super().__init__(parent)
        self.mini = mini
        self.label = label             # sol üst köşe
        self.max_label = ""            # sağ üst köşe (ölçek)
        self.series = []
        self.window = 60
        self.ymax = 100.0
        self.setMinimumHeight(38 if mini else 70)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, series, window, ymax, max_label=""):
        self.series, self.window, self.ymax, self.max_label = series, window, ymax or 1.0, max_label
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = 0 if self.mini else 16
        r = QRectF(0.5, top + 0.5, self.width() - 1, self.height() - top - 1)
        grid = qcolor("grid")
        acc = line_color()
        if not self.mini:
            f = QFont(self.font())
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
            p.setFont(f)
            p.setPen(qcolor("text2"))
            p.drawText(QRectF(0, 0, self.width(), 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self.label)
            p.drawText(QRectF(0, 0, self.width(), 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self.max_label)
            # ızgara: 10 dikey, 4 yatay bölme (ince)
            gpen = QPen(QColor(grid))
            gc = QColor(grid)
            gc.setAlphaF(gc.alphaF() * 0.45)
            gpen.setColor(gc)
            gpen.setWidthF(1)
            p.setPen(gpen)
            for i in range(1, 4):
                y = r.top() + r.height() * i / 4
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            for i in range(1, 10):
                x = r.left() + r.width() * i / 10
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        n = max(2, self.window)
        step = r.width() / (n - 1)
        for si, (values, fill, dashed) in enumerate(self.series):
            vals = list(values)[-n:]
            if not vals:
                continue
            x0 = r.right() - (len(vals) - 1) * step
            path = QPainterPath()
            started = False
            first_x = last_x = None
            for i, v in enumerate(vals):
                if v is None:
                    continue
                x = x0 + i * step
                y = r.bottom() - max(0.0, min(1.0, v / self.ymax)) * r.height()
                if not started:
                    path.moveTo(x, y)
                    started = True
                    first_x = x
                else:
                    path.lineTo(x, y)
                last_x = x
            if not started:
                continue
            if fill:
                area = QPainterPath(path)
                area.lineTo(last_x, r.bottom())
                area.lineTo(first_x, r.bottom())
                area.closeSubpath()
                c = QColor(acc)
                c.setAlphaF(0.22)
                p.fillPath(area, c)
            pen = QPen(acc)
            pen.setWidthF(1.2 if self.mini else 1.6)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawPath(path)
        frame = QPen(QColor(grid))
        frame.setWidthF(1)
        p.setPen(frame)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 3, 3)
        p.end()


class Tile(QFrame):
    """Sol listede bir kaynak: mini grafik + başlık + değer."""
    clicked = pyqtSignal(str)

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.setObjectName("PerfTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 8, 10, 8)
        h.setSpacing(10)
        self.graph = Graph(mini=True)
        self.graph.setFixedSize(64, 42)
        h.addWidget(self.graph)
        v = QVBoxLayout()
        v.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("TileTitle")
        self.sub = QLabel()
        self.sub.setObjectName("Secondary")
        self.value = QLabel()
        self.value.setObjectName("Secondary")
        for w in (self.title, self.sub, self.value):
            w.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            v.addWidget(w)
        h.addLayout(v, 1)
        self.set_selected(False)

    def set_selected(self, on):
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)

    def set_text(self, title, sub, value):
        self.title.setText(title)
        fm = self.sub.fontMetrics()
        self.sub.setText(fm.elidedText(sub, Qt.TextElideMode.ElideRight, 150))
        self.sub.setVisible(bool(sub))
        self.value.setText(value)


# ---------------------------------------------------------------------------------------------- ayrıntı
class Detail(QWidget):
    """Sağdaki büyük görünüm: başlık, grafikler, sayı ızgarası. Grafik düzeni yalnızca kaynak/kip değişince kurulur."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.key = None
        self.layout_sig = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("CardTitle")
        self.title.setStyleSheet("font-size: 22px;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("Secondary")
        self.subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(self.subtitle)
        v.addLayout(head)
        self.graphs_box = QWidget()
        self.graphs = QGridLayout(self.graphs_box)
        self.graphs.setContentsMargins(0, 0, 0, 0)
        self.graphs.setSpacing(8)
        v.addWidget(self.graphs_box, 1)
        self.foot = QLabel()
        self.foot.setObjectName("Secondary")
        v.addWidget(self.foot)
        self.stats_box = QWidget()
        self.stats = QGridLayout(self.stats_box)
        self.stats.setContentsMargins(0, 6, 0, 0)
        self.stats.setHorizontalSpacing(28)
        self.stats.setVerticalSpacing(2)
        v.addWidget(self.stats_box)
        self.graph_widgets = []
        self.stat_widgets = {}

    # ---- düzen
    def _rebuild(self, sig, specs):
        while self.graphs.count():
            w = self.graphs.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.graph_widgets = []
        for r in range(self.graphs.rowCount()):
            self.graphs.setRowStretch(r, 0)
        cols = sig[2]
        # "cell" grafikler cols sütunlu ızgarada, diğerleri ardından tam genişlikte birer satır
        cells = [s for s in specs if s.get("cell")]
        row = 0
        for i, spec in enumerate(specs):
            g = Graph(label=spec["label"])
            self.graph_widgets.append(g)
            if spec.get("cell"):
                r, c = divmod(cells.index(spec), cols)
                self.graphs.addWidget(g, r, c)
                self.graphs.setRowStretch(r, spec.get("stretch", 1))
                row = max(row, r + 1)
            else:
                self.graphs.addWidget(g, row, 0, 1, cols)
                self.graphs.setRowStretch(row, spec.get("stretch", 1))
                row += 1
        self.layout_sig = sig

    def _set_stats(self, stats):
        keys = [k for k, _ in stats]
        if list(self.stat_widgets) != keys:
            while self.stats.count():
                w = self.stats.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            self.stat_widgets = {}
            per_col = 4
            for i, (k, _v) in enumerate(stats):
                col, row = divmod(i, per_col)
                lab = QLabel(k)
                lab.setObjectName("Secondary")
                val = QLabel()
                val.setObjectName("StatValue")
                box = QVBoxLayout()
                box.setSpacing(0)
                w = QWidget()
                w.setLayout(box)
                box.setContentsMargins(0, 0, 0, 6)
                box.addWidget(lab)
                box.addWidget(val)
                self.stats.addWidget(w, row, col)
                self.stat_widgets[k] = val
            self.stats.setColumnStretch(self.stats.columnCount(), 1)
        for k, v in stats:
            self.stat_widgets[k].setText(v)

    # ---- güncelleme
    def show_key(self, key, history, window):
        self.key = key
        cur = history[-1] if history else None
        d = pick(cur, key)
        hist = list(history)[-window:]
        series = lambda f: [f(x) if x is not None else None for x in (pick(s, key) for s in hist)]  # noqa: E731
        specs, stats, title, subtitle, foot, cols = [], [], "", "", "", 1
        if key == "cpu":
            title, subtitle = t("perf_cpu"), self.page.cpu_name
            per_core = self.page.cpu_per_core
            ncores = len(d["cores"]) if d else 0
            if per_core and ncores:
                cols = max(1, min(8, math.ceil(math.sqrt(ncores * 1.6))))
                for i in range(ncores):
                    specs.append({"label": f"CPU {i}", "cell": True, "ymax": 100,
                                  "series": [(series(lambda x, i=i: x["cores"][i] if i < len(x["cores"]) else None),
                                              True, False)]})
            else:
                specs.append({"label": t("perf_util_over", s=window), "ymax": 100, "max_label": "100%",
                              "series": [(series(lambda x: x["util"]), True, False)]})
            if d:
                stats = [(t("perf_usage"), pct(d["util"])), (t("perf_speed"), mhz(d.get("mhz"))),
                         (t("perf_base_speed"), mhz(d.get("base_mhz"))),
                         (t("perf_logical"), str(ncores or "—")),
                         (t("perf_procs"), str(d.get("procs") or "—")),
                         (t("perf_threads"), str(d.get("threads") or "—")),
                         (t("perf_handles"), str(d.get("handles") or "—")),
                         (t("perf_uptime"), duration(d.get("uptime")))]
        elif key == "mem":
            title, subtitle = t("perf_mem"), gb(d["total"]) if d else ""
            specs.append({"label": t("perf_mem_usage"), "ymax": 100, "max_label": gb(d["total"]) if d else "",
                          "series": [(series(lambda x: x["util"]), True, False)]})
            if d:
                stats = [(t("perf_in_use"), gb(d["used"])), (t("perf_available"), gb(d["avail"])),
                         (t("perf_committed"), f"{gb(d.get('commit'))} / {gb(d.get('commit_limit'))}"),
                         (t("perf_cached"), gb(d.get("cached"))),
                         (t("perf_paged"), size(d.get("paged"))), (t("perf_nonpaged"), size(d.get("nonpaged")))]
        elif key.startswith("disk:"):
            title = tile_text(key, d)[0] if d else key
            subtitle = (d or {}).get("model") or ""
            specs.append({"label": t("perf_active_time"), "ymax": 100, "max_label": "100%", "stretch": 2,
                          "series": [(series(lambda x: x["active"]), True, False)]})
            rd, wr = series(lambda x: x["read"]), series(lambda x: x["write"])
            top = nice_ceil(max([v for v in rd + wr if v is not None] or [0]), 1048576)
            specs.append({"label": t("perf_transfer"), "ymax": top, "max_label": byte_rate(top),
                          "series": [(wr, True, False), (rd, False, True)]})
            foot = t("perf_transfer_legend")
            if d:
                stats = [(t("perf_active_time"), pct(d["active"])), (t("perf_resp"), f"{_num(d['resp_ms'])} ms"),
                         (t("perf_read"), byte_rate(d["read"])), (t("perf_write"), byte_rate(d["write"]))]
        elif key.startswith("net:"):
            title = key.split(":", 1)[1]
            sp = (d or {}).get("speed")
            subtitle = bit_rate(sp) if sp else ""
            snd, rcv = series(lambda x: x["send"]), series(lambda x: x["recv"])
            top = nice_ceil(max([v for v in snd + rcv if v is not None] or [0]), 100_000)
            specs.append({"label": t("perf_throughput"), "ymax": top, "max_label": bit_rate(top),
                          "series": [(rcv, True, False), (snd, False, True)]})
            foot = t("perf_net_legend")
            if d:
                stats = [(t("perf_send"), bit_rate(d["send"])), (t("perf_recv"), bit_rate(d["recv"]))]
                if sp:
                    stats.append((t("perf_link_speed"), bit_rate(sp)))
        elif key.startswith("gpu:"):
            title = f"GPU {d['index']}" if d else "GPU"
            subtitle = (d or {}).get("name") or ""
            types = list((d or {}).get("types", {}))
            engines = [e for e in GPU_ENGINE_ORDER if e in types] + sorted(e for e in types if e not in GPU_ENGINE_ORDER)
            engines = (engines or ["3D"])[:4]
            cols = 2 if len(engines) > 1 else 1
            for e in engines:
                specs.append({"label": ENGINE_LABEL.get(e, e), "cell": True, "ymax": 100, "stretch": 2,
                              "series": [(series(lambda x, e=e: x["types"].get(e, 0.0)), True, False)]})
            if d and d.get("ded_total"):
                tot = d["ded_total"]
                specs.append({"label": t("perf_gpu_ded"), "ymax": tot, "max_label": gb(tot),
                              "series": [(series(lambda x: x.get("ded_used")), True, False)]})
            if d and d.get("shared_total"):
                tot = d["shared_total"]
                specs.append({"label": t("perf_gpu_shared"), "ymax": tot, "max_label": gb(tot),
                              "series": [(series(lambda x: x.get("shared_used")), True, False)]})
            if d:
                stats = [(t("perf_usage"), pct(d["util"])),
                         (t("perf_gpu_ded"), f"{gb(d.get('ded_used'))} / {gb(d.get('ded_total'))}"),
                         (t("perf_gpu_shared"), f"{gb(d.get('shared_used'))} / {gb(d.get('shared_total'))}")]
        sig = (key, len(specs), cols, self.page.cpu_per_core if key == "cpu" else None)
        if sig != self.layout_sig:
            self._rebuild(sig, specs)
        for g, spec in zip(self.graph_widgets, specs):
            g.set_data(spec["series"], window, spec["ymax"], spec.get("max_label", ""))
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.foot.setText(foot)
        self.foot.setVisible(bool(foot))
        self._set_stats(stats)


# ---------------------------------------------------------------------------------------------- sayfa
class PerformancePage(Page):
    key = "performance"
    icon = "show_chart"

    def build(self):
        self.cpu_name = cpu_name()
        self.cpu_per_core = bool(prefs.get("perf_cpu_cores", False))
        w = int(prefs.get("perf_window", 60) or 60)
        self.window = w if w in WINDOWS else 60
        self.selected = prefs.get("perf_selected") or "cpu"
        self.tiles = {}

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.status = QLabel(t("loading"))
        self.status.setObjectName("Secondary")
        bar.addWidget(self.status, 1)
        self.btn_cores = QPushButton()
        self.btn_cores.setObjectName("Pill")
        self.btn_cores.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cores.clicked.connect(self.toggle_cores)
        bar.addWidget(self.btn_cores)
        self.btn_window = QPushButton()
        self.btn_window.setObjectName("Pill")
        self.btn_window.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_window.clicked.connect(self.window_menu)
        bar.addWidget(self.btn_window)
        self.root.addLayout(bar)
        self.root.addSpacing(6)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        self.list_area.setFixedWidth(250)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lw = QWidget()
        self.list_box = QVBoxLayout(lw)
        self.list_box.setContentsMargins(0, 0, 6, 0)
        self.list_box.setSpacing(4)
        self.list_box.addStretch(1)
        self.list_area.setWidget(lw)
        body.addWidget(self.list_area)
        self.detail = Detail(self)
        body.addWidget(self.detail, 1)
        self.root.addLayout(body, 1)
        self._update_buttons()

        self._mon = monitor()
        self._mon.sample.connect(self._on_sample)
        theme.bind(self, lambda _w: self.redraw())

    # ---- veri
    def on_shown(self):
        self._mon.want("perf", True)         # geçmiş, sekme gizliyken de birikir (Görev Yöneticisi gibi)
        self.redraw()

    def _on_sample(self, _s):
        if self.isVisible():
            self.redraw()

    def redraw(self):
        hist = self._mon.history
        if not hist:
            return
        cur = hist[-1]
        keys = resources(cur)
        if list(self.tiles) != keys:
            self._rebuild_tiles(keys)
        if self.selected not in self.tiles:
            self.selected = "cpu"
        q = self.filter_text.strip().casefold()
        hist_w = list(hist)[-self.window:]
        for key, tile in self.tiles.items():
            d = pick(cur, key)
            title, sub, value, _main, ymax = tile_text(key, d)
            tile.set_text(title, sub, value)
            tile.setVisible(not q or q in f"{title} {sub}".casefold())
            vals = []
            for s in hist_w:
                x = pick(s, key)
                vals.append(tile_text(key, x)[3] if x is not None else None)
            if ymax is None:
                ymax = nice_ceil(max([v for v in vals if v is not None] or [0]), 100_000)
            tile.graph.set_data([(vals, True, False)], self.window, ymax)
            tile.set_selected(key == self.selected)
        self.detail.show_key(self.selected, hist, self.window)
        c = cur["cpu"]
        self.status.setText(t("perf_status", cpu=pct(c["util"]), mem=pct(cur["mem"]["util"]),
                              up=duration(c.get("uptime"))))

    def _rebuild_tiles(self, keys):
        for tile in self.tiles.values():
            tile.deleteLater()
        self.tiles = {}
        for i, key in enumerate(keys):
            tile = Tile(key)
            tile.clicked.connect(self.select)
            self.list_box.insertWidget(i, tile)
            self.tiles[key] = tile

    def select(self, key):
        self.selected = key
        prefs.set("perf_selected", key)
        self._update_buttons()
        self.redraw()

    # ---- arama / ayarlar
    def set_filter(self, text):
        super().set_filter(text)
        self.redraw()

    def _update_buttons(self):
        self.btn_cores.setVisible(self.selected == "cpu")
        self.btn_cores.setText(t("perf_show_total") if self.cpu_per_core else t("perf_show_cores"))
        self.btn_window.setText(t("perf_window", w=self._window_text(self.window)))

    @staticmethod
    def _window_text(w):
        return t("sec_n", n=w) if w < 120 else t("min_n", n=w // 60)

    def toggle_cores(self):
        self.cpu_per_core = not self.cpu_per_core
        prefs.set("perf_cpu_cores", self.cpu_per_core)
        self._update_buttons()
        self.redraw()

    def window_menu(self):
        m = QMenu(self)
        for w in WINDOWS:
            a = m.addAction(self._window_text(w))
            a.setCheckable(True)
            a.setChecked(w == self.window)
            a.triggered.connect(lambda _c=False, w=w: self.set_window(w))
        b = self.btn_window
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))

    def set_window(self, w):
        self.window = w
        prefs.set("perf_window", w)
        self._update_buttons()
        self.redraw()
