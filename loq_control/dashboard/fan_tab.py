"""
Fan Control Tab — Shows fan RPM, and (if supported) curve editor + manual override.
Gracefully degrades to monitoring-only when fan_curve_writable=False.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSlider, QSizePolicy, QVBoxLayout, QWidget,
)

import loq_control.backend.fan_control as fc
from loq_control.backend.monitor import SystemStats
from loq_control.dashboard.widgets.fan_curve import CurvePoint, FanCurveWidget

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

_BTN_STYLE = """
    QPushButton {
        background: #e8182c;
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        padding: 10px 24px;
    }
    QPushButton:hover { background: #ff2a3e; }
    QPushButton:pressed { background: #c01020; }
    QPushButton:disabled { background: #2a2a35; color: #555568; }
"""

_SEC_BTN_STYLE = """
    QPushButton {
        background: #1e1e24;
        color: #a0a0b8;
        border: 1px solid #2a2a35;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        padding: 9px 18px;
    }
    QPushButton:hover { background: #252530; color: #f0f0f2; }
"""


class FanTab(QWidget):
    """Fan monitoring and (optionally) control tab."""

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._last_stats: SystemStats | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Title + status row
        header = QHBoxLayout()
        title = QLabel("Fan Control")
        title.setStyleSheet("color: #f0f0f2; font-size: 18px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()

        # Status badge
        if self._caps.fan_curve_writable:
            badge_text = "✓ Full control"
            badge_color = "#22c55e"
        elif self._caps.fan_rpm_readable:
            badge_text = "⚠ Monitoring only"
            badge_color = "#f59e0b"
        else:
            badge_text = "✗ Not detected"
            badge_color = "#ef4444"

        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"color: {badge_color}; background: {badge_color}18; border: 1px solid {badge_color}40; "
            f"border-radius: 6px; font-size: 11px; font-weight: 600; padding: 4px 10px;"
        )
        header.addWidget(badge)
        root.addLayout(header)

        # RPM readout cards
        rpm_row = QHBoxLayout()
        rpm_row.setSpacing(12)
        self._fan1_lbl = self._make_rpm_card("Fan 1")
        self._fan2_lbl = self._make_rpm_card("Fan 2")
        rpm_row.addWidget(self._fan1_lbl[0])
        rpm_row.addWidget(self._fan2_lbl[0])
        root.addLayout(rpm_row)

        if not self._caps.fan_rpm_readable and not self._caps.fan_curve_writable:
            info = QLabel(
                "No fan hwmon interface detected.\n\n"
                "To enable fan monitoring, the 'legion_laptop' DKMS module or an upstream "
                "'lenovo_wmi_*' module must be loaded. Run the discovery script for details:\n\n"
                "  python -m loq_control.discovery"
            )
            info.setStyleSheet(
                "color: #8888a0; background: #16161a; border: 1px solid #2a2a35; "
                "border-radius: 10px; padding: 20px; font-size: 12px;"
            )
            info.setWordWrap(True)
            root.addWidget(info)
            root.addStretch()
            return

        if not self._caps.fan_curve_writable:
            # Monitoring-only banner
            banner = QLabel(
                "ℹ️  Fan curve write nodes are not available on this hardware or BIOS version.\n"
                "Fan speed is shown above in read-only mode. This is a known limitation on some "
                "LOQ/Legion models — check the LenovoLegionLinux issue tracker for your BIOS version."
            )
            banner.setStyleSheet(
                "color: #f59e0b; background: #1a1200; border: 1px solid #4a3000; "
                "border-radius: 8px; padding: 16px; font-size: 12px;"
            )
            banner.setWordWrap(True)
            root.addWidget(banner)
            root.addStretch()
            return

        # Full control: curve editor
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(16)
        inner_layout.setContentsMargins(0, 0, 0, 0)

        # Fan 1 curve
        self._curve1 = FanCurveWidget(fan_id=1)
        self._curve1.setMinimumHeight(220)
        inner_layout.addWidget(QLabel("Fan 1 Curve").also(lambda l: l.setStyleSheet(
            "color: #8888a0; font-size: 11px; font-weight: 600; letter-spacing: 1px;"
        )))
        inner_layout.addWidget(self._curve1)

        # Fan 2 curve
        self._curve2 = FanCurveWidget(fan_id=2)
        self._curve2.setMinimumHeight(220)
        inner_layout.addWidget(QLabel("Fan 2 Curve").also(lambda l: l.setStyleSheet(
            "color: #8888a0; font-size: 11px; font-weight: 600; letter-spacing: 1px;"
        )))
        inner_layout.addWidget(self._curve2)

        # Manual override row
        override_frame = QFrame()
        override_frame.setStyleSheet(
            "QFrame { background: #16161a; border: 1px solid #2a2a35; border-radius: 10px; }"
        )
        override_layout = QVBoxLayout(override_frame)
        override_layout.setContentsMargins(16, 14, 16, 14)
        override_layout.setSpacing(10)

        override_title = QLabel("Manual Override")
        override_title.setStyleSheet("color: #f0f0f2; font-size: 13px; font-weight: 600;")
        override_layout.addWidget(override_title)

        slider_row = QHBoxLayout()
        self._override_slider = QSlider(Qt.Orientation.Horizontal)
        self._override_slider.setRange(0, 100)
        self._override_slider.setValue(50)
        self._override_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px; background: #2a2a35; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #e8182c; border: none;
                width: 18px; height: 18px; border-radius: 9px;
                margin: -6px 0;
            }
            QSlider::sub-page:horizontal {
                background: #e8182c; border-radius: 3px;
            }
        """)
        self._override_val_lbl = QLabel("50%")
        self._override_val_lbl.setStyleSheet("color: #f0f0f2; font-size: 13px; min-width: 36px;")
        self._override_slider.valueChanged.connect(
            lambda v: self._override_val_lbl.setText(f"{v}%")
        )
        slider_row.addWidget(self._override_slider)
        slider_row.addWidget(self._override_val_lbl)
        override_layout.addLayout(slider_row)

        btn_row = QHBoxLayout()
        apply_override_btn = QPushButton("Apply Manual Speed")
        apply_override_btn.setStyleSheet(_BTN_STYLE)
        apply_override_btn.clicked.connect(self._apply_manual)

        restore_auto_btn = QPushButton("Restore Auto")
        restore_auto_btn.setStyleSheet(_SEC_BTN_STYLE)
        restore_auto_btn.clicked.connect(self._restore_auto)

        btn_row.addWidget(apply_override_btn)
        btn_row.addWidget(restore_auto_btn)
        btn_row.addStretch()
        override_layout.addLayout(btn_row)
        inner_layout.addWidget(override_frame)

        # Apply curve button
        apply_btn_row = QHBoxLayout()
        apply_curve_btn = QPushButton("Apply Curve")
        apply_curve_btn.setStyleSheet(_BTN_STYLE)
        apply_curve_btn.clicked.connect(self._apply_curves)
        apply_btn_row.addStretch()
        apply_btn_row.addWidget(apply_curve_btn)
        inner_layout.addLayout(apply_btn_row)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll)

    def _make_rpm_card(self, label: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #16161a; border: 1px solid #2a2a35; border-radius: 10px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        lbl_title = QLabel(label)
        lbl_title.setStyleSheet("color: #8888a0; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        val = QLabel("—")
        val.setStyleSheet("color: #f0f0f2; font-size: 24px; font-weight: 700;")
        unit = QLabel("RPM")
        unit.setStyleSheet("color: #8888a0; font-size: 11px;")
        layout.addWidget(lbl_title)
        layout.addWidget(val)
        layout.addWidget(unit)
        return frame, val

    # ------------------------------------------------------------------

    def on_stats_updated(self, stats: SystemStats) -> None:
        self._last_stats = stats
        if self._caps.fan_rpm_readable:
            self._fan1_lbl[1].setText(str(stats.fan1_rpm))
            self._fan2_lbl[1].setText(str(stats.fan2_rpm))
        if self._caps.fan_curve_writable and stats.gpu_temp:
            self._curve1.set_current_stats(float(stats.gpu_temp), stats.fan1_rpm)
            self._curve2.set_current_stats(float(stats.gpu_temp), stats.fan2_rpm)

    def _apply_curves(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        pts1 = [fc.FanCurvePoint(p.temp, p.pwm) for p in self._curve1.get_points()]
        pts2 = [fc.FanCurvePoint(p.temp, p.pwm) for p in self._curve2.get_points()]
        ok1, err1 = fc.apply_fan_curve(pts1, fan_id=1, caps=self._caps)
        ok2, err2 = fc.apply_fan_curve(pts2, fan_id=2, caps=self._caps)
        if ok1 and ok2:
            QMessageBox.information(self, "Fan Curves Applied", "Fan curves applied successfully.")
        else:
            errors = "\n".join(filter(None, [err1, err2]))
            QMessageBox.critical(self, "Fan Curve Error", f"Failed to apply fan curves:\n{errors}")

    def _apply_manual(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        val = self._override_slider.value()
        ok1, err1 = fc.set_fan_manual(1, val, caps=self._caps)
        ok2, err2 = fc.set_fan_manual(2, val, caps=self._caps)
        if not (ok1 and ok2):
            QMessageBox.critical(self, "Fan Control Error", f"{err1 or err2}")

    def _restore_auto(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        ok, err = fc.restore_fan_auto(0)
        if not ok:
            QMessageBox.critical(self, "Fan Control Error", err)
        else:
            QMessageBox.information(self, "Fan Control", "Automatic fan control restored.")


# Monkey-patch QLabel.also for inline style application
def _also(self, fn):
    fn(self)
    return self

QLabel.also = _also  # type: ignore[attr-defined]
