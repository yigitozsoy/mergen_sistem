"""Ana pencere: çerçevesiz (Windows Snap korunur), üst çubuk, solda dikey sekme çubuğu, sağda sayfalar."""
import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QActionGroup, QCursor, QIcon
from PyQt6.QtWidgets import (QButtonGroup, QHBoxLayout, QMainWindow, QMenu, QMessageBox, QStackedWidget,
                             QToolButton, QVBoxLayout, QWidget)

from . import __version__
from .config import asset, log_error, prefs
from .i18n import LANGS, t
from .pages import PAGES
from .theme import ACCENTS, VARIANTS, current_name, current_variant, theme, variant_label
from .titlebar import TitleBar

user32 = ctypes.windll.user32
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
user32.GetWindowLongW.restype = ctypes.c_long
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
GWL_STYLE = -16
WS_THICKFRAME, WS_CAPTION, WS_MAXIMIZEBOX, WS_MINIMIZEBOX, WS_SYSMENU = 0x40000, 0xC00000, 0x10000, 0x20000, 0x80000
WM_NCCALCSIZE, WM_NCHITTEST = 0x0083, 0x0084


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


class NavButton(QToolButton):
    """Soldaki dar sekme çubuğunun düğmesi: üstte simge, altta ad (YouTube'un dar menüsü gibi)."""

    def __init__(self, icon_name, text, parent=None):
        super().__init__(parent)
        self.setObjectName("NavBtn")
        self.setCheckable(True)
        self.setText(text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setFixedSize(72, 64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        theme.icon(self, icon_name, "text", 22)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window |
                            Qt.WindowType.WindowMinMaxButtonsHint)
        self.setWindowTitle("mergen")
        self.setWindowIcon(QIcon(asset("logo.ico")))
        self.setMinimumSize(820, 520)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.titlebar = TitleBar(self)
        self.titlebar.minimize.connect(self.showMinimized)
        self.titlebar.maximize.connect(self.toggle_maximized)
        self.titlebar.close.connect(self.close)
        self.titlebar.theme_clicked.connect(self.toggle_theme)
        self.titlebar.prefs_clicked.connect(self.show_prefs_menu)
        self.titlebar.search_changed.connect(self._on_search)
        v.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        v.addLayout(body, 1)

        side = QWidget()
        side.setObjectName("SideBar")
        side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        side.setFixedWidth(88)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 4, 8, 8)
        sl.setSpacing(4)
        body.addWidget(side)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        # Sayfalar ilk açıldıklarında kurulur (açılış hızlı kalsın)
        self.page_classes = [cls for cls in PAGES if self._available(cls)]
        self.pages = {}
        self.filters = {}
        self.nav = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for cls in self.page_classes:
            b = NavButton(cls.icon, t("page_" + cls.key))
            b.clicked.connect(lambda _c=False, k=cls.key: self.show_page(k))
            self.group.addButton(b)
            sl.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
            self.nav[cls.key] = b
        sl.addStretch(1)

        self.current = None
        self._restore_geometry()
        start = prefs.get("last_page", "system")
        self.show_page(start if start in self.nav else self.page_classes[0].key)

    @staticmethod
    def _available(cls):
        try:
            return cls.available()
        except Exception as e:
            log_error(f"{cls.__name__}.available: {e!r}")
            return False

    # ------------------------------------------------------------------ sayfalar
    def page(self, key):
        p = self.pages.get(key)
        if p is None:
            cls = next(c for c in self.page_classes if c.key == key)
            p = cls()
            self.pages[key] = p
            self.stack.addWidget(p)
        return p

    def show_page(self, key):
        if key not in self.nav:
            return
        if self.current == key:
            self.nav[key].setChecked(True)
            return
        old = self.pages.get(self.current)
        if old is not None:
            old.on_hidden()
        p = self.page(key)
        self.current = key
        self.nav[key].setChecked(True)
        self.stack.setCurrentWidget(p)
        tb = self.titlebar
        tb.set_search_hint(p.label())
        tb.search.blockSignals(True)
        tb.search.setText(self.filters.get(key, ""))
        tb.search.blockSignals(False)
        p.on_shown()
        prefs.set("last_page", key)

    def _on_search(self, text):
        if self.current is None:
            return
        self.filters[self.current] = text
        self.page(self.current).set_filter(text)

    # ------------------------------------------------------------------ tema / tercihler
    def toggle_theme(self):
        theme.apply("light" if current_name() == "dark" else "dark")

    def build_prefs_menu(self):
        m = QMenu(self)
        tm = m.addMenu(t("theme"))
        g = QActionGroup(tm)
        cur = current_variant()
        for fam in ("dark", "light"):
            if fam == "light":
                tm.addSeparator()
            for vid, info in VARIANTS.items():
                if info[2] != fam:
                    continue
                a = tm.addAction(variant_label(vid))
                a.setCheckable(True)
                a.setChecked(vid == cur)
                a.setActionGroup(g)
                a.triggered.connect(lambda _c=False, x=vid: theme.apply(x))
        am = m.addMenu(t("accent"))
        g2 = QActionGroup(am)
        cur_acc = prefs.get("accent", "gray")
        for key in ACCENTS:
            a = am.addAction(t("accent_" + key))
            a.setCheckable(True)
            a.setChecked(key == cur_acc)
            a.setActionGroup(g2)
            a.triggered.connect(lambda _c=False, x=key: theme.set_accent(x))
        lm = m.addMenu(t("language"))
        g3 = QActionGroup(lm)
        names = {"tr": "Türkçe", "en": "English"}
        for code in LANGS:
            a = lm.addAction(names[code])
            a.setCheckable(True)
            a.setChecked(prefs.get("language", "tr") == code)
            a.setActionGroup(g3)
            a.triggered.connect(lambda _c=False, x=code: self.set_language(x))
        m.addSeparator()
        m.addAction(t("about")).triggered.connect(self.show_about)
        return m

    def show_prefs_menu(self):
        m = self.build_prefs_menu()
        b = self.titlebar.btn_prefs
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))

    def set_language(self, code):
        if prefs.get("language", "tr") == code:
            return
        prefs.set("language", code)
        QMessageBox.information(self, "mergen", t("lang_restart"))

    def show_about(self):
        QMessageBox.about(self, t("about"), t("about_text", v=__version__))

    # ------------------------------------------------------------------ pencere
    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _restore_geometry(self):
        g = prefs.get("window_geometry")
        ok = False
        if g:
            try:
                ok = self.restoreGeometry(QByteArray.fromHex(g.encode()))
            except Exception:
                ok = False
        if not ok:
            self.resize(QSize(1180, 760))

    def closeEvent(self, e):
        if self.current in self.pages:
            self.pages[self.current].on_hidden()
        prefs.update({"window_geometry": bytes(self.saveGeometry().toHex()).decode(),
                      "window_maximized": self.isMaximized()})
        super().closeEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange:
            self.titlebar.set_maximized(self.isMaximized())
            QTimer.singleShot(0, self._apply_native_frame)
        super().changeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_native_frame()
        self._apply_corners()

    def _apply_native_frame(self):
        """Çerçevesiz pencereye Windows'un yeniden boyutlandırma / Snap / animasyon stillerini geri verir;
        görünür çerçeve WM_NCCALCSIZE ile gizlenir (kamug ile aynı yöntem)."""
        try:
            hwnd = int(self.winId())
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            want = style | WS_THICKFRAME | WS_CAPTION | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU
            if want != style:
                user32.SetWindowLongW(hwnd, GWL_STYLE, want)
                user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020)
        except Exception:
            pass

    def _apply_corners(self):
        """Windows 11'de yuvarlak köşe (Windows 10'da sessizce yok sayılır)."""
        try:
            pref = ctypes.c_int(2)   # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

    def nativeEvent(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_NCCALCSIZE and msg.wParam:
            if user32.IsZoomed(msg.hWnd):
                # Büyütülmüş pencere ekran dışına taşmasın: istemci alanını çalışma alanına eşitle
                params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
                mon = user32.MonitorFromWindow(msg.hWnd, 2)
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                    params.rgrc[0] = mi.rcWork
            return True, 0
        if msg.message == WM_NCHITTEST:
            gp = QCursor.pos()
            if not self.isMaximized():
                g = self.frameGeometry()
                m = 6
                left, right = gp.x() <= g.left() + m, gp.x() >= g.right() - m
                top, bottom = gp.y() <= g.top() + m, gp.y() >= g.bottom() - m
                code = {(True, False, True, False): 13, (False, True, True, False): 14,
                        (True, False, False, True): 16, (False, True, False, True): 17}.get((left, right, top, bottom))
                if code is None:
                    code = 10 if left else 11 if right else 12 if top else 15 if bottom else None
                if code is not None:
                    return True, code
            tb = self.titlebar
            local = tb.mapFromGlobal(gp)
            if tb.rect().contains(local) and tb.is_drag_area(tb.childAt(local)):
                return True, 2  # HTCAPTION
        return False, 0
