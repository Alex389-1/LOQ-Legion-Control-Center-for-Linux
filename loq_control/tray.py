"""
System tray icon and context menu.
Left-click: show/raise dashboard.
Right-click: quick profile switch + open + quit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPainter, QPixmap, QColor, QFont
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QApplication

import loq_control.backend.power_profiles as pp
from loq_control.backend.monitor import SystemStats

if TYPE_CHECKING:
    from loq_control.dashboard.window import DashboardWindow
    from loq_control.discovery import Capabilities


def _make_icon(gpu_temp: int | None = None) -> QIcon:
    """
    Generate a monochrome tray icon dynamically.
    Shows a small 'L' badge (for LOQ) in crimson.
    """
    size = 22
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))  # transparent

    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Outer circle
    painter.setPen(QColor("#e8182c"))
    painter.setBrush(QColor("#e8182c"))
    painter.drawEllipse(2, 2, size - 4, size - 4)

    # 'L' letter
    font = QFont()
    font.setPixelSize(12)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(px.rect(), 0x84, "L")  # AlignCenter = 0x84

    painter.end()
    return QIcon(px)


class TrayIcon(QSystemTrayIcon):
    """System tray icon with context menu for quick profile switching."""

    def __init__(self, caps: "Capabilities", window: "DashboardWindow") -> None:
        super().__init__()
        self._caps = caps
        self._window = window
        self._current_profile: str | None = None
        self._last_gpu_temp: int | None = None

        self.setIcon(_make_icon())
        self.setToolTip("LOQ Control Center")

        self._build_menu()
        self.activated.connect(self._on_activated)

        # Refresh tooltip every 3s
        self._tip_timer = QTimer()
        self._tip_timer.setInterval(3000)
        self._tip_timer.timeout.connect(self._refresh_profile)
        self._tip_timer.start()

        self._refresh_profile()
        self.show()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: #16161a;
                color: #f0f0f2;
                border: 1px solid #2a2a35;
                border-radius: 8px;
                padding: 4px 0;
            }
            QMenu::item {
                padding: 8px 20px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background: #1e1e24;
                color: #f0f0f2;
            }
            QMenu::item:disabled {
                color: #555568;
            }
            QMenu::separator {
                height: 1px;
                background: #2a2a35;
                margin: 4px 0;
            }
        """)

        # Dashboard
        open_action = QAction("◈  Open Dashboard", self)
        open_action.triggered.connect(self._show_window)
        menu.addAction(open_action)
        menu.addSeparator()

        # Profile submenu
        if self._caps.power_profiles_available:
            profile_menu = menu.addMenu("⚡  Power Profile")
            profile_menu.setStyleSheet(menu.styleSheet())
            group = QActionGroup(self)
            group.setExclusive(True)
            self._profile_actions: dict[str, QAction] = {}
            for profile in ["power-saver", "balanced", "performance"]:
                act = QAction(
                    f"{pp.label_for(profile)}", self, checkable=True
                )
                act.triggered.connect(lambda checked, p=profile: pp.set_profile(p))
                group.addAction(act)
                profile_menu.addAction(act)
                self._profile_actions[profile] = act
            menu.addSeparator()

        # Quit
        quit_action = QAction("✕  Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

    def _show_window(self) -> None:
        self._window.show()
        self._window.activateWindow()
        self._window.raise_()

    def _quit(self) -> None:
        import loq_control.config as cfg_mod
        cfg_mod.save()
        QApplication.quit()

    def on_stats(self, stats: SystemStats) -> None:
        """Called on each monitoring tick to update tooltip."""
        self._last_gpu_temp = stats.gpu_temp
        self._update_tooltip()

    def _refresh_profile(self) -> None:
        if not self._caps.power_profiles_available:
            return
        profile = pp.get_active_profile()
        if profile and profile != self._current_profile:
            self._current_profile = profile
            for p, act in self._profile_actions.items():
                act.setChecked(p == profile)
            self._update_tooltip()

    def _update_tooltip(self) -> None:
        parts = ["LOQ Control Center"]
        if self._current_profile:
            parts.append(f"Profile: {pp.label_for(self._current_profile)}")
        if self._last_gpu_temp is not None:
            parts.append(f"GPU: {self._last_gpu_temp}°C")
        self.setToolTip("  ·  ".join(parts))
