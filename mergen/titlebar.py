"""Üst çubuk (kamug / yazıt ile aynı): solda logo, ortada arama, sağda tema / tercihler ve pencere düğmeleri."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QToolButton, QWidget

from .i18n import t
from .theme import current_name, theme, tinted_logo
from .widgets import IconButton


class TitleBar(QWidget):
    search_changed = pyqtSignal(str)
    theme_clicked = pyqtSignal()
    prefs_clicked = pyqtSignal()
    minimize = pyqtSignal()
    maximize = pyqtSignal()
    close = pyqtSignal()

    HEIGHT = 56

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(4)

        brand = QWidget(self)
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(8, 0, 4, 0)
        bl.setSpacing(6)
        self.logo = QLabel()
        theme.bind(self.logo, lambda w: w.setPixmap(tinted_logo(22, w.devicePixelRatioF())))
        bl.addWidget(self.logo)
        self.wordmark = QLabel("mergen")
        self.wordmark.setObjectName("Wordmark")
        bl.addWidget(self.wordmark)
        self.brand = brand
        lay.addWidget(brand)

        lay.addStretch(1)
        self.search = QLineEdit(self)
        self.search.setObjectName("SearchBox")
        self.search.setFixedHeight(40)
        self.search.setMinimumWidth(180)
        self.search.setMaximumWidth(540)
        self.search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search.setClearButtonEnabled(True)
        self.search.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.search.textChanged.connect(self.search_changed.emit)
        lay.addWidget(self.search, 3)
        self.btn_search = QToolButton(self)
        self.btn_search.setObjectName("SearchBtn")
        self.btn_search.setFixedSize(64, 40)
        self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_search.setToolTip(t("search"))
        theme.icon(self.btn_search, "search", "text", 22)
        self.btn_search.clicked.connect(lambda: self.search_changed.emit(self.search.text()))
        lay.addWidget(self.btn_search)
        lay.addStretch(1)

        self.btn_theme = IconButton("moon", "", 40, 22)
        self.btn_theme.clicked.connect(self.theme_clicked.emit)
        lay.addWidget(self.btn_theme)
        self.btn_prefs = IconButton("more_horiz", t("preferences"), 40, 24)
        self.btn_prefs.clicked.connect(self.prefs_clicked.emit)
        lay.addWidget(self.btn_prefs)
        lay.addSpacing(10)

        self.btn_min = self._win_btn("win_min", "WinBtn", self.minimize, t("minimize"))
        self.btn_max = self._win_btn("win_max", "WinBtn", self.maximize, t("maximize"))
        self.btn_close = self._win_btn("close", "WinClose", self.close, t("close"))
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        self.update_theme_icon()
        theme.changed.connect(lambda _: self.update_theme_icon())

    def set_search_hint(self, page_label):
        self.search.setPlaceholderText(t("search_placeholder", page=page_label))

    def is_drag_area(self, widget):
        """Pencereyi sürüklemek / Windows Snap için başlık çubuğunun boş alanı mı?"""
        return widget is self or widget is None or widget is self.brand or widget in (self.logo, self.wordmark)

    def _win_btn(self, icon_name, obj, sig, tip):
        b = QToolButton(self)
        b.setObjectName(obj)
        b.setFixedSize(46, 34)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setToolTip(tip)
        theme.icon(b, icon_name, "text", 16)
        b.clicked.connect(sig.emit)
        return b

    def update_theme_icon(self):
        dark = current_name() == "dark"
        self.btn_theme.set_icon_name("sun" if dark else "moon")
        self.btn_theme.setToolTip(t("light_mode") if dark else t("dark_mode"))

    def set_maximized(self, on):
        theme.icon(self.btn_max, "win_restore" if on else "win_max", "text", 16)
        self.btn_max.setToolTip(t("restore") if on else t("maximize"))

    # Sürükleme / Snap normalde Windows'ta: MainWindow.nativeEvent bu alan için HTCAPTION döndürür.
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self.window().windowHandle()
            if h:
                h.startSystemMove()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.maximize.emit()
            return
        super().mouseDoubleClickEvent(e)
