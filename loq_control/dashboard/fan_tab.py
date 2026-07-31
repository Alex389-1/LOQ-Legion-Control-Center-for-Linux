"""
Fan Tab — Read-only fan RPM & thermal status display.
Provides live thermal activity estimates (Low/Medium/High/Turbo) based on
CPU/GPU load & active power profiles when raw hwmon RPM registers are masked by Lenovo EC.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from loq_control.backend.monitor import SystemStats

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities


class FanTab(QWidget):
    """Fan status and thermal activity tab."""

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
        title = QLabel("Fan Speed & Thermal Status")
        title.setStyleSheet("color: #f0f0f2; font-size: 18px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()

        badge_text = "👁 Direct HW RPM" if self._caps.fan_rpm_readable else "⚡ EC Thermal Active"
        badge_color = "#3b82f6" if self._caps.fan_rpm_readable else "#10b981"
        badge_bg = "#1e3a8a" if self._caps.fan_rpm_readable else "#064e3b"
        badge_border = "#2563eb" if self._caps.fan_rpm_readable else "#059669"
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
            "QFrame { background: #18181b; border: 1px solid #27272a; border-radius: 10px; }"
        )
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(20, 16, 20, 16)
        banner_layout.setSpacing(8)

        notice = QLabel(
            "The Lenovo LOQ Embedded Controller (EC) automatically manages fan speeds based on real-time thermal loads "
            "and active power profiles.\n\n"
            "• Performance Profile: Unlocks maximum fan speed and sustained PL1/PL2 power.\n"
            "• Balanced Profile: Dynamically scales fan activity according to CPU & GPU thermal loads.\n"
            "• Quiet Profile: Limits fan speeds for low acoustic noise."
        )
        notice.setStyleSheet("color: #a1a1aa; font-size: 12px; line-height: 1.6;")
        notice.setWordWrap(True)
        banner_layout.addWidget(notice)
        root.addWidget(banner)

        # Fan speed / status cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self._cpu_fan_card, self._cpu_fan_state, self._cpu_fan_bar, self._cpu_fan_temp = self._make_fan_card("CPU FAN ACTIVITY")
        self._gpu_fan_card, self._gpu_fan_state, self._gpu_fan_bar, self._gpu_fan_temp = self._make_fan_card("GPU FAN ACTIVITY")

        cards_row.addWidget(self._cpu_fan_card)
        cards_row.addWidget(self._gpu_fan_card)
        root.addLayout(cards_row)

        root.addStretch()

    def _make_fan_card(self, title: str) -> tuple[QFrame, QLabel, QProgressBar, QLabel]:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #18181b; border: 1px solid #27272a; border-radius: 10px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(
            "color: #8888a0; font-size: 10px; font-weight: 600; letter-spacing: 1.2px;"
        )

        state_lbl = QLabel("Active")
        state_lbl.setStyleSheet("color: #f0f0f2; font-size: 24px; font-weight: 700;")

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(40)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setStyleSheet("""
            QProgressBar {
                background: #27272a;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: #3b82f6;
                border-radius: 4px;
            }
        """)

        temp_lbl = QLabel("Temp: — °C")
        temp_lbl.setStyleSheet("color: #a1a1aa; font-size: 12px;")

        layout.addWidget(lbl_title)
        layout.addWidget(state_lbl)
        layout.addWidget(bar)
        layout.addWidget(temp_lbl)

        return frame, state_lbl, bar, temp_lbl

    def on_stats_updated(self, stats: SystemStats) -> None:
        if self._caps.fan_rpm_readable and stats.fan1_rpm is not None:
            self._cpu_fan_state.setText(f"{stats.fan1_rpm} RPM")
            if stats.fan2_rpm is not None:
                self._gpu_fan_state.setText(f"{stats.fan2_rpm} RPM")
            return

        # Calculate CPU fan activity state based on CPU temp
        cpu_t = stats.cpu_temp or 45.0
        if cpu_t < 45:
            c_state = "Low / Quiet"
            c_pct = 25
            c_color = "#3b82f6"
        elif cpu_t < 65:
            c_state = "Moderate"
            c_pct = 50
            c_color = "#10b981"
        elif cpu_t < 80:
            c_state = "High"
            c_pct = 75
            c_color = "#f59e0b"
        else:
            c_state = "Turbo / Max"
            c_pct = 95
            c_color = "#ef4444"

        self._cpu_fan_state.setText(c_state)
        self._cpu_fan_bar.setValue(c_pct)
        self._cpu_fan_bar.setStyleSheet(f"""
            QProgressBar {{ background: #27272a; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {c_color}; border-radius: 4px; }}
        """)
        self._cpu_fan_temp.setText(f"CPU Temp: {cpu_t:.1f} °C")

        # Calculate GPU fan activity state based on GPU temp
        gpu_t = stats.gpu_temp or 40.0
        if gpu_t < 45:
            g_state = "Idle / Passive"
            g_pct = 20
            g_color = "#3b82f6"
        elif gpu_t < 60:
            g_state = "Active"
            g_pct = 50
            g_color = "#10b981"
        elif gpu_t < 75:
            g_state = "High"
            g_pct = 75
            g_color = "#f59e0b"
        else:
            g_state = "Max Speed"
            g_pct = 95
            g_color = "#ef4444"

        self._gpu_fan_state.setText(g_state)
        self._gpu_fan_bar.setValue(g_pct)
        self._gpu_fan_bar.setStyleSheet(f"""
            QProgressBar {{ background: #27272a; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {g_color}; border-radius: 4px; }}
        """)
        self._gpu_fan_temp.setText(f"GPU Temp: {gpu_t:.1f} °C" if stats.gpu_temp else "GPU Temp: N/A")
