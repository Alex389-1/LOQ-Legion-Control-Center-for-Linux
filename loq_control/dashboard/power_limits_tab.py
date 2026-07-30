"""
Power Limits Tab — CPU and GPU power limit sliders.
Reads current values from WMI firmware-attributes sysfs.
Writes via pkexec loq-helper power-limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

import loq_control.backend.power_limits as pl

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

_APPLY_BTN = """
    QPushButton {
        background: #2563eb;
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        padding: 10px 24px;
    }
    QPushButton:hover { background: #1d4ed8; }
    QPushButton:pressed { background: #1e40af; }
    QPushButton:disabled { background: #27272a; color: #71717a; }
"""

_RESET_BTN = """
    QPushButton {
        background: #18181b;
        color: #a1a1aa;
        border: 1px solid #27272a;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 500;
        padding: 9px 18px;
    }
    QPushButton:hover { background: #27272a; color: #f4f4f5; }
"""

_SLIDER_STYLE = """
    QSlider::groove:horizontal {
        height: 6px;
        background: #27272a;
        border-radius: 3px;
    }
    QSlider::sub-page:horizontal {
        background: {color};
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: {color};
        border: none;
        width: 18px;
        height: 18px;
        border-radius: 9px;
        margin: -6px 0;
    }
"""


class _LimitRow(QWidget):
    """A single power-limit slider row."""

    def __init__(
        self,
        limit: pl.LimitValue,
        color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._limit = limit
        self._original = limit.current
        self._build(color)

    def _build(self, color: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)

        # Label
        label = QLabel(self._limit.label)
        label.setStyleSheet("color: #f0f0f2; font-size: 12px;")
        label.setFixedWidth(160)
        layout.addWidget(label)

        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(self._limit.min_val, self._limit.max_val)
        self._slider.setValue(self._limit.current)
        self._slider.setEnabled(self._limit.writable)
        self._slider.setStyleSheet(_SLIDER_STYLE.replace("{color}", color))
        self._slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self._slider)

        # Value label
        self._val_lbl = QLabel(f"{self._limit.current} {self._limit.unit}")
        self._val_lbl.setStyleSheet("color: #f0f0f2; font-size: 13px; font-weight: 600; min-width: 52px;")
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._val_lbl)

        # Range hint
        hint = QLabel(f"{self._limit.min_val}–{self._limit.max_val} {self._limit.unit}")
        hint.setStyleSheet("color: #555568; font-size: 10px; min-width: 64px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(hint)

    def _on_value_changed(self, value: int) -> None:
        self._val_lbl.setText(f"{value} {self._limit.unit}")
        changed = value != self._original
        self._val_lbl.setStyleSheet(
            f"color: {'#f59e0b' if changed else '#f0f0f2'}; "
            "font-size: 13px; font-weight: 600; min-width: 52px;"
        )

    @property
    def current_value(self) -> int:
        return self._slider.value()

    @property
    def key(self) -> str:
        return self._limit.key

    def refresh(self, new_val: int) -> None:
        self._original = new_val
        self._slider.blockSignals(True)
        self._slider.setValue(new_val)
        self._slider.blockSignals(False)
        self._val_lbl.setText(f"{new_val} {self._limit.unit}")
        self._val_lbl.setStyleSheet(
            "color: #f0f0f2; font-size: 13px; font-weight: 600; min-width: 52px;"
        )


class PowerLimitsTab(QWidget):
    """CPU + GPU power limit sliders with live read-back."""

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._rows: dict[str, _LimitRow] = {}
        self._attrs = pl.resolve_attrs(caps) if caps.power_limits_available else {}
        self._build_ui()

        # Refresh values every 5 seconds
        if self._attrs:
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setInterval(5000)
            self._refresh_timer.timeout.connect(self._refresh_values)
            self._refresh_timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("Power Limits")
        title.setStyleSheet("color: #f0f0f2; font-size: 18px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()

        if self._caps.power_limits_writable:
            badge = QLabel("✓ Writable")
            badge.setStyleSheet(
                "color: #22c55e; background: #0a200f; border: 1px solid #22c55e40; "
                "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 4px 10px;"
            )
        elif self._caps.power_limits_available:
            badge = QLabel("⚠ Read-only")
            badge.setStyleSheet(
                "color: #f59e0b; background: #1a1200; border: 1px solid #f59e0b40; "
                "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 4px 10px;"
            )
        else:
            badge = QLabel("✗ Not detected")
            badge.setStyleSheet(
                "color: #ef4444; background: #1a0608; border: 1px solid #ef444440; "
                "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 4px 10px;"
            )
        header.addWidget(badge)
        root.addLayout(header)

        if not self._caps.power_limits_available:
            warn = QLabel(
                "No power limit sysfs attributes were detected.\n\n"
                "Run  loq-control --discover  for full diagnostics.\n\n"
                "On some kernels, power limits are exposed via:\n"
                "  /sys/module/legion_laptop/drivers/platform:legion/…\n"
                "or  /sys/class/firmware-attributes/…"
            )
            warn.setStyleSheet(
                "color: #8888a0; background: #16161a; border: 1px solid #2a2a35; "
                "border-radius: 10px; padding: 20px; font-size: 12px;"
            )
            warn.setWordWrap(True)
            root.addWidget(warn)
            root.addStretch()
            return

        # Honesty note
        if self._caps.power_limits_writable:
            note_text = (
                "ℹ️  Changes apply immediately to the current session. "
                "Values revert to firmware defaults on reboot. "
                "GPU cTGP/PPAB affect dynamic TGP allocation."
            )
        else:
            note_text = (
                "ℹ️  Read-Only Mode — Live factory power & thermal targets are displayed below. "
                "Dynamic WMI attribute writes return EBUSY on this BIOS version, so values are managed by Lenovo firmware."
            )

        note = QLabel(note_text)
        note.setStyleSheet(
            "color: #8888a0; background: #16161a; border: 1px solid #2a2a35; "
            "border-radius: 8px; padding: 12px 16px; font-size: 11px;"
        )
        note.setWordWrap(True)
        root.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(12)
        inner_layout.setContentsMargins(0, 0, 0, 0)

        # CPU section
        cpu_attrs = {k: v for k, v in self._attrs.items() if k in pl.CPU_ATTRS}
        if cpu_attrs:
            inner_layout.addWidget(self._section_header("🖥️  CPU Power Limits"))
            cpu_card = self._make_card()
            card_layout = QVBoxLayout(cpu_card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            for key, limit in cpu_attrs.items():
                row = _LimitRow(limit, "#3b82f6")
                self._rows[key] = row
                card_layout.addWidget(row)
            inner_layout.addWidget(cpu_card)

        # GPU section
        gpu_attrs = {k: v for k, v in self._attrs.items() if k in pl.GPU_ATTRS}
        if gpu_attrs:
            inner_layout.addWidget(self._section_header("🎮  GPU Power Limits"))
            gpu_card = self._make_card()
            card_layout = QVBoxLayout(gpu_card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            for key, limit in gpu_attrs.items():
                row = _LimitRow(limit, "#10b981")
                self._rows[key] = row
                card_layout.addWidget(row)
            inner_layout.addWidget(gpu_card)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll)

        # Action buttons
        if self._caps.power_limits_writable:
            btn_row = QHBoxLayout()
            btn_row.addStretch()

            reset_btn = QPushButton("Read Current")
            reset_btn.setStyleSheet(_RESET_BTN)
            reset_btn.clicked.connect(self._refresh_values)
            btn_row.addWidget(reset_btn)

            apply_btn = QPushButton("Apply All")
            apply_btn.setStyleSheet(_APPLY_BTN)
            apply_btn.clicked.connect(self._apply_all)
            btn_row.addWidget(apply_btn)
            root.addLayout(btn_row)

    # ------------------------------------------------------------------

    def _section_header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;")
        return lbl

    def _make_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #18181b; border: 1px solid #27272a; border-radius: 10px; }"
        )
        return card

    def _refresh_values(self) -> None:
        new_vals = pl.read_current_values(self._attrs)
        for key, val in new_vals.items():
            if val is not None and key in self._rows:
                self._rows[key].refresh(val)

    def _apply_all(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        errors = []
        for key, row in self._rows.items():
            ok, err = pl.set_limit(key, row.current_value, self._caps)
            if not ok:
                errors.append(f"{pl.ATTR_LABELS.get(key, key)}: {err}")

        if errors:
            QMessageBox.critical(
                self, "Apply Failed",
                "Some limits could not be applied:\n\n" + "\n".join(errors)
            )
        else:
            QMessageBox.information(self, "Power Limits", "All power limits applied successfully.")
        self._refresh_values()
