"""
Keyboard Lighting Tab — ITE RGB zone controls for Lenovo LOQ.
4 color zones with effect selection and brightness control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from loq_control.backend.keyboard_light import (
    Effect, KeyboardController, NUM_ZONES, ZoneColor, get_controller,
)

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

_ZONE_NAMES = ["Zone 1\n(Left)", "Zone 2\n(Center-L)", "Zone 3\n(Center-R)", "Zone 4\n(Right)"]
_EFFECT_LABELS = {
    "Static":      Effect.STATIC,
    "Breathing":   Effect.BREATHING,
    "Wave":        Effect.WAVE,
    "Color Shift": Effect.COLOR_SHIFT,
    "Off":         Effect.OFF,
}

_APPLY_BTN = """
    QPushButton {
        background: #e8182c; color: white; border: none;
        border-radius: 8px; font-size: 13px; font-weight: 600; padding: 10px 24px;
    }
    QPushButton:hover { background: #ff2a3e; }
    QPushButton:disabled { background: #2a2a35; color: #555568; }
"""

_COLOR_BTN = """
    QPushButton {{
        background: {color};
        border: 2px solid #3a3a50;
        border-radius: 6px;
        min-width: 44px;
        min-height: 44px;
        max-width: 44px;
        max-height: 44px;
    }}
    QPushButton:hover {{
        border-color: #ffffff;
    }}
"""


class _ZoneWidget(QFrame):
    """Card for a single keyboard zone with color picker."""

    def __init__(self, zone_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._zone_id = zone_id
        self._color = QColor(255, 0, 0)
        self._build()

    def _build(self) -> None:
        self.setStyleSheet(
            "QFrame { background: #16161a; border: 1px solid #2a2a35; border-radius: 10px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Zone label
        lbl = QLabel(_ZONE_NAMES[self._zone_id])
        lbl.setStyleSheet("color: #8888a0; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        # Color preview button (click to open picker)
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(44, 44)
        self._color_btn.setStyleSheet(self._btn_style())
        self._color_btn.clicked.connect(self._pick_color)
        self._color_btn.setToolTip("Click to choose color")

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._color_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # RGB value display
        self._rgb_lbl = QLabel(self._rgb_str())
        self._rgb_lbl.setStyleSheet("color: #8888a0; font-size: 10px; font-family: monospace;")
        self._rgb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._rgb_lbl)

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, f"Zone {self._zone_id + 1} Color")
        if color.isValid():
            self._color = color
            self._color_btn.setStyleSheet(self._btn_style())
            self._rgb_lbl.setText(self._rgb_str())

    def _btn_style(self) -> str:
        return _COLOR_BTN.format(color=self._color.name())

    def _rgb_str(self) -> str:
        return f"RGB({self._color.red()}, {self._color.green()}, {self._color.blue()})"

    @property
    def zone_color(self) -> ZoneColor:
        return ZoneColor(self._color.red(), self._color.green(), self._color.blue())

    def set_color(self, r: int, g: int, b: int) -> None:
        self._color = QColor(r, g, b)
        self._color_btn.setStyleSheet(self._btn_style())
        self._rgb_lbl.setText(self._rgb_str())


class KeyboardTab(QWidget):
    """Keyboard RGB lighting control tab."""

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._zone_widgets: list[_ZoneWidget] = []
        self._kb: KeyboardController | None = None
        self._build_ui()

        if caps.keyboard_rgb_available:
            self._kb = get_controller(caps.keyboard_vid, caps.keyboard_pid)
            self._kb.open()  # try to open; fails gracefully if udev rule missing

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("Keyboard Lighting")
        title.setStyleSheet("color: #f0f0f2; font-size: 18px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()

        if self._caps.keyboard_rgb_available:
            badge = QLabel("✓ ITE HID detected")
            badge.setStyleSheet(
                "color: #22c55e; background: #0a200f; border: 1px solid #22c55e40; "
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

        if not self._caps.keyboard_rgb_available:
            info = QLabel(
                "ITE keyboard controller (VID 0x048d) not detected.\n\n"
                "If it exists but isn't accessible, add a udev rule:\n\n"
                "  SUBSYSTEM==\"usb\", ATTR{idVendor}==\"048d\", "
                "ATTR{idProduct}==\"c993\", MODE=\"0666\"\n\n"
                "Save as /etc/udev/rules.d/99-ite-keyboard.rules, then:\n"
                "  sudo udevadm control --reload && sudo udevadm trigger\n\n"
                "Alternatively, install the 'hid' Python module:\n"
                "  pip install hid"
            )
            info.setStyleSheet(
                "color: #8888a0; background: #16161a; border: 1px solid #2a2a35; "
                "border-radius: 10px; padding: 20px; font-size: 12px; font-family: monospace;"
            )
            info.setWordWrap(True)
            root.addWidget(info)
            root.addStretch()
            return

        # Effect selector + brightness
        controls_frame = QFrame()
        controls_frame.setStyleSheet(
            "QFrame { background: #16161a; border: 1px solid #2a2a35; border-radius: 10px; }"
        )
        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(16, 14, 16, 14)
        controls_layout.setSpacing(20)

        eff_lbl = QLabel("Effect:")
        eff_lbl.setStyleSheet("color: #8888a0; font-size: 12px;")
        controls_layout.addWidget(eff_lbl)

        self._effect_combo = QComboBox()
        self._effect_combo.addItems(list(_EFFECT_LABELS.keys()))
        self._effect_combo.setCurrentText("Static")
        self._effect_combo.setStyleSheet("""
            QComboBox {
                background: #1e1e24; color: #f0f0f2; border: 1px solid #2a2a35;
                border-radius: 6px; padding: 6px 10px; font-size: 12px;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1e1e24; color: #f0f0f2; border: 1px solid #2a2a35;
                selection-background-color: #2a2a35;
            }
        """)
        controls_layout.addWidget(self._effect_combo)

        controls_layout.addSpacing(20)

        bright_lbl = QLabel("Brightness:")
        bright_lbl.setStyleSheet("color: #8888a0; font-size: 12px;")
        controls_layout.addWidget(bright_lbl)

        self._brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self._brightness_slider.setRange(0, 100)
        self._brightness_slider.setValue(100)
        self._brightness_slider.setStyleSheet("""
            QSlider::groove:horizontal { height:6px; background:#2a2a35; border-radius:3px; }
            QSlider::sub-page:horizontal { background:#e8182c; border-radius:3px; }
            QSlider::handle:horizontal {
                background:#e8182c; border:none;
                width:18px; height:18px; border-radius:9px; margin:-6px 0;
            }
        """)
        self._brightness_slider.setFixedWidth(120)
        controls_layout.addWidget(self._brightness_slider)

        self._bright_val_lbl = QLabel("100%")
        self._bright_val_lbl.setStyleSheet("color: #f0f0f2; font-size: 12px; min-width: 36px;")
        self._brightness_slider.valueChanged.connect(
            lambda v: self._bright_val_lbl.setText(f"{v}%")
        )
        controls_layout.addWidget(self._bright_val_lbl)
        controls_layout.addStretch()
        root.addWidget(controls_frame)

        # Zone color pickers
        zone_grid = QGridLayout()
        zone_grid.setSpacing(12)
        for i in range(NUM_ZONES):
            zw = _ZoneWidget(i)
            self._zone_widgets.append(zw)
            zone_grid.addWidget(zw, 0, i)
        root.addLayout(zone_grid)

        # Quick presets
        preset_frame = QFrame()
        preset_frame.setStyleSheet(
            "QFrame { background: #16161a; border: 1px solid #2a2a35; border-radius: 10px; }"
        )
        preset_layout = QHBoxLayout(preset_frame)
        preset_layout.setContentsMargins(16, 12, 16, 12)
        preset_layout.setSpacing(10)

        preset_lbl = QLabel("Quick presets:")
        preset_lbl.setStyleSheet("color: #8888a0; font-size: 12px;")
        preset_layout.addWidget(preset_lbl)

        presets = [
            ("🔴 Red",    (255, 0,   0)),
            ("🟢 Green",  (0,   255, 0)),
            ("🔵 Blue",   (0,   0,   255)),
            ("⚪ White",  (255, 255, 255)),
            ("🟠 Orange", (255, 100, 0)),
            ("🟣 Purple", (128, 0,   255)),
        ]
        for label, (r, g, b) in presets:
            btn = QPushButton(label)
            btn.setStyleSheet("""
                QPushButton {
                    background: #1e1e24; color: #f0f0f2; border: 1px solid #2a2a35;
                    border-radius: 6px; font-size: 11px; padding: 6px 10px;
                }
                QPushButton:hover { background: #252530; }
            """)
            btn.clicked.connect(lambda checked, rv=r, gv=g, bv=b: self._apply_preset(rv, gv, bv))
            preset_layout.addWidget(btn)

        preset_layout.addStretch()

        off_btn = QPushButton("⬛ Off")
        off_btn.setStyleSheet("""
            QPushButton {
                background: #1a0608; color: #ef4444; border: 1px solid #ef4444;
                border-radius: 6px; font-size: 11px; padding: 6px 10px;
            }
            QPushButton:hover { background: #250810; }
        """)
        off_btn.clicked.connect(self._turn_off)
        preset_layout.addWidget(off_btn)
        root.addWidget(preset_frame)

        # Apply button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        apply_btn = QPushButton("Apply Lighting")
        apply_btn.setStyleSheet(_APPLY_BTN)
        apply_btn.clicked.connect(self._apply_lighting)
        btn_row.addWidget(apply_btn)
        root.addLayout(btn_row)

        root.addStretch()

    # ------------------------------------------------------------------

    def _apply_preset(self, r: int, g: int, b: int) -> None:
        for zw in self._zone_widgets:
            zw.set_color(r, g, b)
        self._apply_lighting()

    def _turn_off(self) -> None:
        if self._kb and self._kb.is_open:
            self._kb.set_off()

    def _apply_lighting(self) -> None:
        if not self._kb:
            return
        if not self._kb.is_open:
            if not self._kb.open():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Keyboard Access Error",
                    "Cannot open the ITE keyboard HID device.\n\n"
                    "Add the udev rule from the instructions above, then reload udev:\n"
                    "  sudo udevadm control --reload && sudo udevadm trigger",
                )
                return

        effect_name = self._effect_combo.currentText()
        effect = _EFFECT_LABELS.get(effect_name, Effect.STATIC)
        brightness_pct = self._brightness_slider.value()

        if effect == Effect.OFF:
            self._kb.set_off()
        elif effect in (Effect.WAVE, Effect.COLOR_SHIFT):
            self._kb.set_wave(effect=effect, brightness_pct=brightness_pct)
        else:
            colors = [zw.zone_color for zw in self._zone_widgets]
            self._kb.set_all_zones(colors, brightness_pct=brightness_pct, effect=effect)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._kb:
            self._kb.close()
        super().closeEvent(event)
