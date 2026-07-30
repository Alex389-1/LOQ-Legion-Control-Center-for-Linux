"""
Dashboard window — Main QMainWindow with custom dark title bar and tab layout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

from loq_control.backend.monitor import MonitorThread, SystemStats
from loq_control.dashboard.fan_tab import FanTab
from loq_control.dashboard.gpu_tab import GpuTab
from loq_control.dashboard.keyboard_tab import KeyboardTab
from loq_control.dashboard.monitor_tab import MonitorTab
from loq_control.dashboard.power_limits_tab import PowerLimitsTab
from loq_control.dashboard.power_tab import PowerTab
from loq_control.dashboard.widgets.icons import get_icon
import loq_control.config as cfg_mod

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

_TAB_STYLE = """
QTabWidget::pane {
    border: none;
    background: #09090b;
}
QTabBar::tab {
    background: transparent;
    color: #71717a;
    font-size: 13px;
    font-weight: 500;
    padding: 12px 22px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #f4f4f5;
    font-weight: 600;
    border-bottom: 2px solid #3b82f6;
}
QTabBar::tab:hover:!selected {
    color: #a1a1aa;
}
"""


class DashboardWindow(QMainWindow):
    """
    Main dashboard window.
    Uses a frameless design with a custom title bar for a modern look,
    or falls back to the native title bar when frameless is disabled.
    """

    def __init__(
        self,
        caps: "Capabilities",
        monitor: MonitorThread,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._caps = caps
        self._monitor = monitor
        self._drag_pos = None

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet("QMainWindow { background-color: #09090b; color: #f4f4f5; }")

        cfg = cfg_mod.get()
        self.setWindowTitle("LOQ Control Center")
        self.resize(cfg.window_width, cfg.window_height)
        if cfg.window_x >= 0 and cfg.window_y >= 0:
            self.move(cfg.window_x, cfg.window_y)

        self._build_ui()

        # Connect monitor thread
        monitor.stats_updated.connect(self._on_stats)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("DashboardRoot")
        central.setStyleSheet("QWidget#DashboardRoot { background-color: #09090b; }")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Custom title bar
        root.addWidget(self._make_title_bar())

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #27272a;")
        root.addWidget(sep)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_TAB_STYLE)
        self._tabs.setDocumentMode(True)

        self._monitor_tab = MonitorTab(self._caps)
        self._power_tab = PowerTab(self._caps)
        self._power_limits_tab = PowerLimitsTab(self._caps)
        self._fan_tab = FanTab(self._caps)
        self._gpu_tab = GpuTab(self._caps)
        self._keyboard_tab = KeyboardTab(self._caps)

        self._tabs.addTab(self._monitor_tab,       get_icon("monitor", 16, "#a1a1aa"), "Monitor")
        self._tabs.addTab(self._power_tab,          get_icon("power", 16, "#a1a1aa"), "Power")
        self._tabs.addTab(self._power_limits_tab,   get_icon("limits", 16, "#a1a1aa"), "Limits")
        self._tabs.addTab(self._fan_tab,            get_icon("fan", 16, "#a1a1aa"), "Fan")
        self._tabs.addTab(self._gpu_tab,            get_icon("gpu", 16, "#a1a1aa"), "GPU Mode")
        self._tabs.addTab(self._keyboard_tab,       get_icon("keyboard", 16, "#a1a1aa"), "Lighting")

        root.addWidget(self._tabs)

    def _make_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(50)
        bar.setStyleSheet("""
            QWidget#TitleBar {
                background: #09090b;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(8)

        # Logo + title
        logo = QLabel("◈")
        logo.setStyleSheet("color: #3b82f6; font-size: 18px; font-weight: 700;")
        layout.addWidget(logo)

        title = QLabel("LOQ Control Center")
        title.setStyleSheet("color: #f4f4f5; font-size: 14px; font-weight: 600;")
        layout.addWidget(title)

        layout.addStretch()

        # Capability badges
        if not self._caps.nvidia_available:
            badge = QLabel("No NVIDIA")
            badge.setStyleSheet(
                "color: #8888a0; background: #1a1a22; border: 1px solid #2a2a35; "
                "border-radius: 4px; font-size: 10px; padding: 2px 8px;"
            )
            layout.addWidget(badge)

        if not self._caps.power_profiles_available:
            badge2 = QLabel("No PPD")
            badge2.setStyleSheet(
                "color: #f59e0b; background: #1a1200; border: 1px solid #4a3000; "
                "border-radius: 4px; font-size: 10px; padding: 2px 8px;"
            )
            layout.addWidget(badge2)

        layout.addSpacing(8)
        return bar

    # ------------------------------------------------------------------
    # Stats routing
    # ------------------------------------------------------------------

    def _on_stats(self, stats: SystemStats) -> None:
        self._monitor_tab.on_stats_updated(stats, self._monitor.history)
        self._fan_tab.on_stats_updated(stats)

    # ------------------------------------------------------------------
    # Window events
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        """Minimize to tray instead of closing."""
        event.ignore()
        self.hide()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.activateWindow()
        self.raise_()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        cfg = cfg_mod.get()
        cfg.window_x = self.x()
        cfg.window_y = self.y()
