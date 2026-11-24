"""Ortak küçük arayüz parçaları."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QToolButton

from ..theme import theme


class IconButton(QToolButton):
    def __init__(self, name, tip="", size=40, icon_size=22, role="text", parent=None, checkable=False):
        super().__init__(parent)
        self.setObjectName("IconBtn")
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCheckable(checkable)
        self.setToolTip(tip)
        self._icon_size = icon_size
        self._role = role
        theme.icon(self, name, role, icon_size)

    def set_icon_name(self, name, role=None):
        theme.icon(self, name, role or self._role, self._icon_size)


class Chip(QPushButton):
    def __init__(self, text, parent=None, checkable=True):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
