"""Sekmeler (soldaki çubukta bu sırayla)."""
from .device import DevicePage
from .performance import PerformancePage
from .processes import ProcessesPage
from .programs import ProgramsPage
from .sensors import SensorsPage
from .system import SystemPage
from .tweaks import TweaksPage

PAGES = [SystemPage, ProgramsPage, SensorsPage, PerformancePage, ProcessesPage, DevicePage, TweaksPage]
