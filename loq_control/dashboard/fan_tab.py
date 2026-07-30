"""
Fan Tab — Read-only fan RPM display.

Fan curve control is NOT exposed on this hardware platform (Lenovo LOQ).
This tab shows monitoring-only RPM readout if the hwmon node is available,
or a clear explanation if the fan interface is not present.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from loq_control.backend.monitor import SystemStats

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities


class FanTab(QWidget):
    """Fan monitoring-only tab."""

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("Fan Speed")
        title.setStyleSheet("color: #f0f0f2; font-size: 18px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        badge_text = "👁 Monitoring only" if self._caps.fan_rpm_readable else "✗ Not available"
        badge_color = "#f59e0b" if self._caps.fan_rpm_readable else "#ef4444"
        badge_bg = "#1a1200" if self._caps.fan_rpm_readable else "#1a0608"
        badge_border = "#4a3000" if self._caps.fan_rpm_readable else "#4a0010"
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"color: {badge_color}; background: {badge_bg}; border: 1px solid {badge_border}; "
            f"border-radius: 6px; font-size: 11px; font-weight: 600; padding: 4px 10px;"
        )
        header.addWidget(badge)
        root.addLayout(header)

        # Notice banner
        banner = QFrame()
        banner.setStyleSheet(
            "QFrame { background: #16161a; border: 1px solid #2a2a35; border-radius: 10px; }"
        )
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(20, 16, 20, 16)
        banner_layout.setSpacing(8)

        notice = QLabel(
            "Fan curve control is not exposed on this hardware.\n\n"
            "The Lenovo LOQ does not provide writable fan curve sysfs nodes via "
            "legion_laptop or lenovo_wmi_* drivers on this BIOS version. "
            "Thermal management is handled entirely by the firmware.\n\n"
            "Fan RPM is shown below in read-only mode if the hwmon interface is available."
        )
        notice.setStyleSheet("color: #8888a0; font-size: 12px; line-height: 1.6;")
        notice.setWordWrap(True)
        banner_layout.addWidget(notice)
        root.addWidget(banner)

        # RPM cards
        if self._caps.fan_rpm_readable:
            rpm_row = QHBoxLayout()
            rpm_row.setSpacing(12)
            self._fan1_card, self._fan1_val = self._make_rpm_card("Fan 1")
            self._fan2_card, self._fan2_val = self._make_rpm_card("Fan 2")
            rpm_row.addWidget(self._fan1_card)
            rpm_row.addWidget(self._fan2_card)
            root.addLayout(rpm_row)
        else:
            no_data = QLabel(
                "No fan hwmon interface detected on this system.\n"
                "Run  loq-control --discover  to check fan module status."
            )
            no_data.setStyleSheet(
                "color: #555568; background: #111114; border: 1px solid #1e1e28; "
                "border-radius: 8px; padding: 16px; font-size: 11px;"
            )
            no_data.setWordWrap(True)
            root.addWidget(no_data)

        root.addStretch()

    def _make_rpm_card(self, label: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #16161a; border: 1px solid #2a2a35; border-radius: 10px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(4)
        lbl_title = QLabel(label.upper())
        lbl_title.setStyleSheet(
            "color: #8888a0; font-size: 10px; font-weight: 600; letter-spacing: 1.2px;"
        )
        val = QLabel("—")
        val.setStyleSheet("color: #f0f0f2; font-size: 32px; font-weight: 700;")
        unit = QLabel("RPM")
        unit.setStyleSheet("color: #8888a0; font-size: 12px;")
        layout.addWidget(lbl_title)
        layout.addWidget(val)
        layout.addWidget(unit)
        return frame, val

    def on_stats_updated(self, stats: SystemStats) -> None:
        if self._caps.fan_rpm_readable:
            self._fan1_val.setText(str(stats.fan1_rpm) if stats.fan1_rpm else "—")
            self._fan2_val.setText(str(stats.fan2_rpm) if stats.fan2_rpm else "—")
