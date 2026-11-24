"""Sekme 6 — Cihaz: Windows güç planı / güç modu / parlaklık (her bilgisayarda) + üretici modülü (yalnızca desteklenen
donanımda; şu an Clevo, salt okunur).

Okumalar arka plan iş parçacığında, sekme görünürken 2 sn'de bir. Windows ayarı değiştiren her işlem onay ister
(parlaklık kaydırıcısı hariç: Windows'un kendi kaydırıcısıyla aynı, anında geri alınabilir)."""
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSlider, QVBoxLayout,
                             QWidget)

from .. import actions
from ..collect import power
from ..config import log_error
from ..i18n import t
from .base import Page

POLL_MS = 2000


class _Bridge(QObject):
    done = pyqtSignal(object, object)        # power verisi, üretici verisi (ya da hata metni)


def _card(title):
    f = QFrame()
    f.setObjectName("Card")
    f.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    v = QVBoxLayout(f)
    v.setContentsMargins(18, 12, 18, 16)
    v.setSpacing(8)
    head = QHBoxLayout()
    head.setSpacing(8)
    lbl = QLabel(title)
    lbl.setObjectName("CardTitle")
    head.addWidget(lbl)
    head.addStretch(1)
    v.addLayout(head)
    return f, v, head, lbl


def _badge(text=""):
    b = QLabel(text)
    b.setObjectName("Badge")
    return b


class FanTile(QFrame):
    """Bir fan: devir (büyük), görev oranı ve ilgili sıcaklık."""

    def __init__(self, title):
        super().__init__()
        self.setObjectName("PerfTile")
        self.setProperty("selected", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("TileTitle")
        self.rpm = QLabel("—")
        self.rpm.setObjectName("StatValue")
        self.sub = QLabel("")
        self.sub.setObjectName("Secondary")
        for w in (self.title, self.rpm, self.sub):
            v.addWidget(w)

    def set(self, fan):
        self.rpm.setText(t("dev_rpm", v=fan["rpm"]) if fan.get("rpm") else t("dev_fan_stopped"))
        parts = [t("dev_duty", v=fan.get("duty", 0))]
        if fan.get("temp"):
            parts.append(f"{fan['temp']} °C")
        self.sub.setText(" · ".join(parts))


class DevicePage(Page):
    key = "device"
    icon = "laptop"

    @classmethod
    def available(cls):
        # Windows güç ayarları her bilgisayarda var; üretici kartı yalnızca desteklenen donanımda görünür.
        return True

    def build(self):
        from ..vendors import detect_any
        self.vendor = None
        try:
            self.vendor = detect_any()
        except Exception as e:
            log_error(f"vendor detect: {e!r}")
        self.bridge = _Bridge()
        self.bridge.done.connect(self._on_data)
        self._busy = False
        self._visible = False
        self._power = None
        self._updating = False
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.refresh)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)
        scroll.setWidget(inner)
        self.root.addWidget(scroll, 1)

        if self.vendor is not None:
            lay.addWidget(self._build_vendor())
        lay.addWidget(self._build_power())
        lay.addStretch(1)

    # ---- üretici kartı (salt okunur)
    def _build_vendor(self):
        f, v, head, _ = _card(t("dev_vendor_title", name=self.vendor.name))
        self.cc_badge = _badge(t("dev_cc_running"))
        self.cc_badge.setToolTip(t("dev_cc_running_tip"))
        self.cc_badge.hide()
        head.insertWidget(1, self.cc_badge)
        self.ro_badge = _badge(t("dev_read_only"))
        head.addWidget(self.ro_badge)
        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self.fan_tiles = []
        caps = {}
        try:
            caps = self.vendor.capabilities()
        except Exception as e:
            log_error(f"vendor caps: {e!r}")
        for i in range(caps.get("fans", 2)):
            tile = FanTile(t("dev_fan_" + ("cpu", "gpu", "gpu2")[i]))
            self.fan_tiles.append(tile)
            tiles.addWidget(tile, 1)
        tiles.addStretch(0)
        v.addLayout(tiles)
        g = QGridLayout()
        g.setHorizontalSpacing(24)
        g.setVerticalSpacing(6)
        g.setColumnStretch(1, 1)
        self.v_rows = {}
        for r, k in enumerate(("dev_power_mode", "dev_fan_mode", "dev_fan_offset", "dev_keyboard")):
            lbl = QLabel(t(k))
            lbl.setObjectName("RowLabel")
            val = QLabel("—")
            val.setObjectName("RowValue")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            g.addWidget(lbl, r, 0)
            g.addWidget(val, r, 1)
            self.v_rows[k] = val
        settable = caps.get("settable_power_modes") or []
        self.ro_badge.setVisible(not caps.get("write"))
        self.cb_pm = None
        if settable:
            # Güç modu yazılabilir: etiket yerine onaylı seçim kutusu
            from ..vendors.clevo import POWER_MODES
            self.v_rows["dev_power_mode"].hide()
            self.cb_pm = QComboBox()
            self.cb_pm.setMinimumWidth(260)
            for m in settable:
                self.cb_pm.addItem(t("pm_" + POWER_MODES[m]), m)
            self.cb_pm.activated.connect(self._pm_chosen)
            g.addWidget(self.cb_pm, 0, 1, Qt.AlignmentFlag.AlignLeft)
        self._vendor = None
        kt = caps.get("keyboard_type")
        self.v_rows["dev_keyboard"].setText(t("dev_kb_present", n=kt) if kt else t("dev_kb_none"))
        v.addLayout(g)
        self.vendor_note = QLabel(t("dev_vendor_note_pm" if settable else "dev_vendor_note"))
        self.vendor_note.setObjectName("Secondary")
        self.vendor_note.setWordWrap(True)
        v.addWidget(self.vendor_note)
        return f

    # ---- Windows güç kartı
    def _build_power(self):
        f, v, head, _ = _card(t("dev_power_title"))
        self.src_badge = _badge("")
        head.insertWidget(1, self.src_badge)
        g = QGridLayout()
        g.setHorizontalSpacing(24)
        g.setVerticalSpacing(8)
        g.setColumnStretch(2, 1)

        def label(k, r):
            lbl = QLabel(t(k))
            lbl.setObjectName("RowLabel")
            g.addWidget(lbl, r, 0)
            return lbl

        label("dev_plan", 0)
        self.cb_plan = QComboBox()
        self.cb_plan.setMinimumWidth(260)
        self.cb_plan.activated.connect(self._plan_chosen)
        g.addWidget(self.cb_plan, 0, 1)

        label("dev_overlay", 1)
        self.cb_overlay = QComboBox()
        self.cb_overlay.setMinimumWidth(260)
        self.cb_overlay.activated.connect(self._overlay_chosen)
        g.addWidget(self.cb_overlay, 1, 1)
        self.overlay_hint = QLabel(t("dev_overlay_balanced_only"))
        self.overlay_hint.setObjectName("Secondary")
        self.overlay_hint.hide()
        g.addWidget(self.overlay_hint, 1, 2)

        self.lbl_bright = label("dev_brightness", 2)
        bl = QHBoxLayout()
        bl.setSpacing(10)
        self.sl_bright = QSlider(Qt.Orientation.Horizontal)
        self.sl_bright.setRange(0, 100)
        self.sl_bright.setMinimumWidth(260)
        self.sl_bright.sliderReleased.connect(self._brightness_released)
        self.sl_bright.valueChanged.connect(lambda x: self.v_bright.setText(f"{x} %"))
        self.v_bright = QLabel("—")
        self.v_bright.setObjectName("RowValue")
        self.v_bright.setMinimumWidth(48)
        bl.addWidget(self.sl_bright)
        bl.addWidget(self.v_bright)
        self.bright_wrap = QWidget()
        self.bright_wrap.setLayout(bl)
        bl.setContentsMargins(0, 0, 0, 0)
        g.addWidget(self.bright_wrap, 2, 1)
        for w in (self.lbl_bright, self.bright_wrap):
            w.hide()
        v.addLayout(g)
        return f

    # ---- görünürlük / yenileme
    def on_shown(self):
        self._visible = True
        self.refresh()
        self.timer.start()

    def on_hidden(self):
        self._visible = False
        self.timer.stop()

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True, name="mergen-device").start()

    def _work(self):
        pw = vd = None
        try:
            pw = power.collect()
        except Exception as e:
            log_error(f"power collect: {e!r}")
        if self.vendor is not None:
            try:
                vd = self.vendor.read()
            except Exception as e:
                log_error(f"vendor read: {e!r}")
                vd = str(e)
        self.bridge.done.emit(pw, vd)

    def _on_data(self, pw, vd):
        self._busy = False
        if pw is not None:
            self._apply_power(pw)
        if self.vendor is not None:
            self._apply_vendor(vd)

    def _apply_vendor(self, d):
        if not isinstance(d, dict):
            self.vendor_note.setText(t("dev_vendor_error"))
            return
        for tile, fan in zip(self.fan_tiles, d["fans"]):
            tile.set(fan)
        self.cc_badge.setVisible(bool(d.get("control_center")))
        self._vendor = d
        pm = d.get("power_mode_key")
        self.v_rows["dev_power_mode"].setText(t("pm_" + pm) if pm else t("dev_unknown", n=d.get("power_mode")))
        fm = d.get("fan_mode_key")
        self.v_rows["dev_fan_mode"].setText(t("fm_" + fm) if fm else t("dev_unknown", n=d.get("fan_mode")))
        self.v_rows["dev_fan_offset"].setText(f"{d.get('fan_offset', 0)} %")
        if self.cb_pm is not None:
            i = self.cb_pm.findData(d.get("power_mode"))
            if i < 0 and d.get("power_mode") is not None:            # ör. Sessiz+ (yalnızca okunur)
                self.cb_pm.addItem(self.v_rows["dev_power_mode"].text(), d["power_mode"])
                i = self.cb_pm.count() - 1
            self.cb_pm.setCurrentIndex(i)

    def _apply_power(self, pw):
        self._power = pw
        self._updating = True
        try:
            st = pw.get("status") or {}
            if st.get("ac") is None:
                self.src_badge.hide()
            else:
                txt = t("dev_on_ac") if st["ac"] else t("dev_on_battery")
                if st.get("battery") is not None:
                    txt += f" · {st['battery']} %"
                if st.get("saver"):
                    txt += " · " + t("dev_saver")
                self.src_badge.setText(txt)
                self.src_badge.show()
            plans = pw.get("plans") or []
            if [self.cb_plan.itemData(i) for i in range(self.cb_plan.count())] != [p[0] for p in plans]:
                self.cb_plan.clear()
                for guid, name in plans:
                    self.cb_plan.addItem(name, guid)
            i = self.cb_plan.findData(pw.get("active"))
            self.cb_plan.setCurrentIndex(i)
            ov = pw.get("overlay")
            on_battery = st.get("ac") is False
            keys = [(g, k) for g, k in power.OVERLAYS if k != "better_battery" or on_battery or g == ov]
            if [self.cb_overlay.itemData(i) for i in range(self.cb_overlay.count())] != [g for g, _ in keys]:
                self.cb_overlay.clear()
                for g, k in keys:
                    self.cb_overlay.addItem(t("ov_" + k), g)
            self.cb_overlay.setCurrentIndex(self.cb_overlay.findData(ov))
            balanced = pw.get("active") == power.BALANCED
            self.cb_overlay.setEnabled(ov is not None and balanced)
            self.overlay_hint.setVisible(ov is not None and not balanced)
            b = pw.get("brightness")
            for w in (self.lbl_bright, self.bright_wrap):
                w.setVisible(b is not None)
            if b is not None and not self.sl_bright.isSliderDown():
                self.sl_bright.setValue(b)
                self.v_bright.setText(f"{b} %")
        finally:
            self._updating = False

    # ---- yazma (onaylı)
    def _plan_chosen(self, i):
        guid, name = self.cb_plan.itemData(i), self.cb_plan.itemText(i)
        cur = (self._power or {}).get("active")
        if not guid or guid == cur:
            return
        if actions.confirm(self, t("dev_plan"), t("dev_plan_confirm", name=name), t("apply"), destructive=False):
            if not power.set_plan(guid):
                actions.report(self, False, "PowerSetActiveScheme")
        self.refresh()

    def _pm_chosen(self, i):
        mode = self.cb_pm.itemData(i)
        cur = (self._vendor or {}).get("power_mode")
        if mode is None or mode == cur:
            return
        if actions.confirm(self, t("dev_power_mode"), t("dev_pm_confirm", name=self.cb_pm.itemText(i)), t("apply"),
                           destructive=False, details=f"OutLog / PowerBIOSServer_Out: clevocc30^101^{mode}"):
            try:
                self.vendor.set_power_mode(mode)
            except Exception as e:
                log_error(f"vendor power mode: {e!r}")
                actions.report(self, False, type(e).__name__)
            QTimer.singleShot(1500, self.refresh)        # FnKey ~1 sn'de uygular
        self.refresh()

    def _overlay_chosen(self, i):
        guid = self.cb_overlay.itemData(i)
        cur = (self._power or {}).get("overlay")
        if guid is None or guid == cur:
            return
        if actions.confirm(self, t("dev_overlay"), t("dev_overlay_confirm", name=self.cb_overlay.itemText(i)),
                           t("apply"), destructive=False):
            if not power.set_overlay(guid):
                actions.report(self, False, "PowerSetActiveOverlayScheme")
        self.refresh()

    def _brightness_released(self):
        val = self.sl_bright.value()

        def work():
            try:
                power.set_brightness(val)
            except Exception as e:
                log_error(f"brightness: {e!r}")
        threading.Thread(target=work, daemon=True).start()

    def set_filter(self, text):
        self.filter_text = text
