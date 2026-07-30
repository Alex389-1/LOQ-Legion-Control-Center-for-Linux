"""
Power Profile Tab — Switch between Quiet / Balanced / Performance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

import loq_control.backend.power_profiles as pp

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

_PROFILE_ORDER = ["power-saver", "balanced", "performance"]
_PROFILE_ICONS = {
    "power-saver": "🍃",
    "balanced": "⚖️",
    "performance": "⚡",
}


class _ProfileButton(QPushButton):
    """Styled profile toggle button."""

    INACTIVE_STYLE = """
        QPushButton {
            background: #18181b;
            border: 1px solid #27272a;
            border-radius: 10px;
            color: #a1a1aa;
            font-size: 13px;
            font-weight: 500;
            padding: 18px 12px;
            text-align: center;
        }
        QPushButton:hover {
            background: #27272a;
            border-color: #3f3f46;
            color: #f4f4f5;
        }
    """

    ACTIVE_STYLE = """
        QPushButton {
            background: #18181b;
            border: 2px solid #3b82f6;
            border-radius: 10px;
            color: #f4f4f5;
            font-size: 13px;
            font-weight: 600;
            padding: 17px 12px;
        }
    """

    def __init__(self, profile: str, parent: QWidget | None = None) -> None:
        label = f"{_PROFILE_ICONS.get(profile, '●')}  {pp.label_for(profile)}"
        super().__init__(label, parent)
        self._profile = profile
        self.setCheckable(True)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        self.setStyleSheet(self.ACTIVE_STYLE if active else self.INACTIVE_STYLE)


class PowerTab(QWidget):
    """Tab for reading and switching power profiles."""

    profile_changed = Signal(str)

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._buttons: dict[str, _ProfileButton] = {}
        self._current_profile: str | None = None
        self._build_ui()

        if caps.power_profiles_available:
            self._refresh_profile()
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(5000)
            self._poll_timer.timeout.connect(self._refresh_profile)
            self._poll_timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        # Title
        title = QLabel("Power Profiles")
        title.setStyleSheet("color: #f0f0f2; font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        if not self._caps.power_profiles_available:
            warn = QLabel(
                "⚠️  power-profiles-daemon is not running or powerprofilesctl is not installed.\n"
                "Install it via your package manager to enable profile switching."
            )
            warn.setStyleSheet(
                "color: #f59e0b; background: #1a1500; border: 1px solid #4a3800; "
                "border-radius: 8px; padding: 16px; font-size: 12px;"
            )
            warn.setWordWrap(True)
            root.addWidget(warn)
            root.addStretch()
            return

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        group = QButtonGroup(self)
        group.setExclusive(True)

        available = self._caps.power_profiles_profiles or _PROFILE_ORDER
        for profile in _PROFILE_ORDER:
            if profile not in available:
                continue
            btn = _ProfileButton(profile)
            btn.clicked.connect(lambda checked, p=profile: self._on_profile_clicked(p))
            self._buttons[profile] = btn
            group.addButton(btn)
            btn_row.addWidget(btn)

        root.addLayout(btn_row)

        # Description card
        self._desc_frame = QFrame()
        self._desc_frame.setStyleSheet(
            "QFrame { background: #18181b; border: 1px solid #27272a; border-radius: 10px; }"
        )
        desc_layout = QVBoxLayout(self._desc_frame)
        desc_layout.setContentsMargins(16, 14, 16, 14)
        self._desc_label = QLabel("")
        self._desc_label.setStyleSheet("color: #a1a1aa; font-size: 12px; line-height: 1.5;")
        self._desc_label.setWordWrap(True)
        desc_layout.addWidget(self._desc_label)
        root.addWidget(self._desc_frame)

        # Current profile indicator
        self._status_label = QLabel("Detecting current profile…")
        self._status_label.setStyleSheet("color: #71717a; font-size: 11px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._status_label)

        root.addStretch()

    # ------------------------------------------------------------------

    def _refresh_profile(self) -> None:
        profile = pp.get_active_profile()
        if profile and profile != self._current_profile:
            self._set_active(profile)

    def _set_active(self, profile: str) -> None:
        self._current_profile = profile
        for p, btn in self._buttons.items():
            btn.set_active(p == profile)
        desc = pp.description_for(profile)
        self._desc_label.setText(desc)
        self._status_label.setText(
            f"Active: {pp.label_for(profile)}  ·  Changes apply system-wide"
        )

    def _on_profile_clicked(self, profile: str) -> None:
        if profile == self._current_profile:
            return
        success = pp.set_profile(profile)
        if success:
            self._set_active(profile)
            self.profile_changed.emit(profile)
        else:
            QMessageBox.warning(
                self,
                "Profile Switch Failed",
                f"Could not switch to '{pp.label_for(profile)}'.\n"
                "Check that power-profiles-daemon is running.",
            )
            self._refresh_profile()
