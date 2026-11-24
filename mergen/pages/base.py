"""Sekme sayfalarının ortak tabanı: başlık, açıklama, arama süzgeci ve görünürlük kancaları."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..i18n import t


class Page(QWidget):
    key = ""            # "system", "programs", …  (locales: page_<key>, title_<key>, desc_<key>)
    icon = "info"

    @classmethod
    def available(cls):
        """Sekme bu bilgisayarda gösterilsin mi? (Cihaz sekmesi yalnızca desteklenen donanımda.)"""
        return True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_text = ""
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 18, 28, 20)
        self.root.setSpacing(4)
        self.title = QLabel(t("title_" + self.key))
        self.title.setObjectName("PageTitle")
        self.root.addWidget(self.title)
        self.desc = QLabel(t("desc_" + self.key))
        self.desc.setObjectName("Secondary")
        self.desc.setWordWrap(True)
        self.root.addWidget(self.desc)
        self.root.addSpacing(12)
        self.build()

    def build(self):
        """Alt sınıflar içeriği burada kurar. Varsayılan: yapım aşaması notu."""
        hint = QLabel(t("coming_soon"))
        hint.setObjectName("EmptyHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addWidget(hint, 1)

    def label(self):
        return t("page_" + self.key)

    def set_filter(self, text):
        """Üstteki arama kutusu: bu sekmenin listesini süzer."""
        self.filter_text = text

    def on_shown(self):
        """Sekme öne geldi: canlı güncellemeler burada başlar."""

    def on_hidden(self):
        """Sekme arkaya geçti: gizli sekmede çizim / sorgu yapılmaz."""
