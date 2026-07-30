"""
GPU Mode Tab — Switch between Integrated / Hybrid / Discrete graphics.
Routes privileged operations through pkexec loq-helper.
Shows pending-restart banner when a switch has been applied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

import loq_control.backend.gpu_switch as gs

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

_MODES = ["integrated", "hybrid", "nvidia"]

_MODE_ICONS = {
    "integrated": "🔷",
    "hybrid": "⚡",
    "nvidia": "🟢",
}

_BTN_INACTIVE = """
    QPushButton {{
        background: #16161a;
        border: 1px solid #2a2a35;
        border-radius: 10px;
        color: #8888a0;
        font-size: 13px;
        font-weight: 600;
        padding: 18px 10px;
    }}
    QPushButton:hover {{
        background: #1e1e24;
        border-color: #3a3a50;
        color: #f0f0f2;
    }}
    QPushButton:disabled {{
        background: #111116;
        color: #3a3a50;
    }}
"""

_BTN_ACTIVE = """
    QPushButton {{
        background: #0a0a14;
        border: 2px solid {color};
        border-radius: 10px;
        color: #f0f0f2;
        font-size: 13px;
        font-weight: 700;
        padding: 17px 10px;
    }}
"""

_MODE_COLORS = {
    "integrated": "#38bdf8",
    "hybrid": "#f59e0b",
    "nvidia": "#22c55e",
}


class _ConfirmDialog(QDialog):
    """Confirmation dialog before applying a GPU mode switch."""

    def __init__(self, target_mode: str, switcher: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm GPU Mode Switch")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet("""
            QDialog {
                background: #0d0d0f;
                color: #f0f0f2;
            }
            QLabel { color: #f0f0f2; }
        """)

        restart_type = gs.MODE_RESTART_REQUIREMENT.get(target_mode, "logout")
        self._reboot = restart_type == "reboot"

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 20)

        icon_lbl = QLabel(_MODE_ICONS.get(target_mode, "●"))
        icon_lbl.setStyleSheet("font-size: 36px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        heading = QLabel(f"Switch to {gs.MODE_LABELS.get(target_mode, target_mode)}")
        heading.setStyleSheet("font-size: 16px; font-weight: 700; color: #f0f0f2;")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        desc = QLabel(gs.MODE_DESCRIPTIONS.get(target_mode, ""))
        desc.setStyleSheet("color: #a0a0b8; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Tool info
        tool_info = QLabel(f"Tool: <b>{switcher}</b>  ·  Requires: <b>{restart_type}</b>")
        tool_info.setStyleSheet("color: #8888a0; font-size: 11px;")
        tool_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tool_info)

        # Warning
        warn_text = (
            "⚠️  You will need to log out and log back in for changes to take effect."
            if restart_type == "logout"
            else "⚠️  A full reboot is required for this mode to take effect."
        )
        warn_lbl = QLabel(warn_text)
        warn_lbl.setStyleSheet(
            "color: #f59e0b; background: #1a1200; border: 1px solid #4a3800; "
            "border-radius: 8px; padding: 12px; font-size: 12px;"
        )
        warn_lbl.setWordWrap(True)
        layout.addWidget(warn_lbl)

        # Reboot checkbox
        self._reboot_check = QCheckBox(
            f"{'Reboot' if self._reboot else 'Log out'} automatically after applying"
        )
        self._reboot_check.setStyleSheet("color: #a0a0b8; font-size: 12px;")
        layout.addWidget(self._reboot_check)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).setStyleSheet("""
            QPushButton {
                background: #e8182c; color: white; border: none;
                border-radius: 8px; font-weight: 600; padding: 8px 20px;
            }
            QPushButton:hover { background: #ff2a3e; }
        """)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet("""
            QPushButton {
                background: #1e1e24; color: #a0a0b8; border: 1px solid #2a2a35;
                border-radius: 8px; font-weight: 600; padding: 8px 20px;
            }
            QPushButton:hover { background: #252530; color: #f0f0f2; }
        """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def should_restart(self) -> bool:
        return self._reboot_check.isChecked()

    @property
    def is_reboot(self) -> bool:
        return self._reboot


class GpuTab(QWidget):
    """GPU mode switching tab."""

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._current_mode: str | None = None
        self._buttons: dict[str, QPushButton] = {}
        self._pending = gs.is_pending_restart()
        self._build_ui()

        if caps.gpu_switch_supported():
            self._refresh_mode()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Title
        title = QLabel("GPU Mode")
        title.setStyleSheet("color: #f0f0f2; font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        if not self._caps.gpu_switch_supported():
            warn = QLabel(
                "⚠️  No GPU switcher detected.\n\n"
                "Install envycontrol to enable GPU mode switching:\n"
                "  pip install envycontrol\n\n"
                "Or install supergfxctl from your package manager."
            )
            warn.setStyleSheet(
                "color: #f59e0b; background: #1a1200; border: 1px solid #4a3000; "
                "border-radius: 8px; padding: 20px; font-size: 12px;"
            )
            warn.setWordWrap(True)
            root.addWidget(warn)
            root.addStretch()
            return

        # Switcher info
        switcher_lbl = QLabel(
            f"Switcher: <b>{self._caps.gpu_switcher}</b>"
            + ("  ·  <span style='color:#f59e0b'>⚠ deprecated</span>"
               if self._caps.gpu_switcher == "supergfxctl" else "")
        )
        switcher_lbl.setStyleSheet("color: #8888a0; font-size: 11px;")
        root.addWidget(switcher_lbl)

        # Pending restart banner
        self._pending_banner = QFrame()
        self._pending_banner.setStyleSheet(
            "QFrame { background: #1a0d00; border: 1px solid #e8182c; border-radius: 10px; }"
        )
        pending_layout = QHBoxLayout(self._pending_banner)
        pending_layout.setContentsMargins(16, 12, 16, 12)
        pending_mode = gs.get_pending_mode()
        pending_text = QLabel(
            f"🔄  GPU mode switch to <b>{gs.MODE_LABELS.get(pending_mode or '', pending_mode or 'Unknown')}</b> "
            f"is pending. Please restart your system to apply."
        )
        pending_text.setStyleSheet("color: #f59e0b; font-size: 12px;")
        pending_text.setWordWrap(True)
        pending_layout.addWidget(pending_text)
        self._pending_banner.setVisible(self._pending)
        root.addWidget(self._pending_banner)

        # Mode buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        for mode in _MODES:
            label = f"{_MODE_ICONS[mode]}\n\n{gs.MODE_LABELS[mode]}"
            btn = QPushButton(label)
            btn.setMinimumHeight(100)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(_BTN_INACTIVE.format())
            btn.clicked.connect(lambda checked, m=mode: self._on_mode_clicked(m))
            if self._pending:
                btn.setDisabled(True)
            self._buttons[mode] = btn
            btn_row.addWidget(btn)
        root.addLayout(btn_row)

        # Current mode indicator + description
        self._mode_frame = QFrame()
        self._mode_frame.setStyleSheet(
            "QFrame { background: #16161a; border: 1px solid #2a2a35; border-radius: 10px; }"
        )
        mode_layout = QVBoxLayout(self._mode_frame)
        mode_layout.setContentsMargins(16, 14, 16, 14)
        self._mode_title = QLabel("Detecting current mode…")
        self._mode_title.setStyleSheet("color: #f0f0f2; font-size: 13px; font-weight: 700;")
        self._mode_desc = QLabel("")
        self._mode_desc.setStyleSheet("color: #a0a0b8; font-size: 12px;")
        self._mode_desc.setWordWrap(True)
        mode_layout.addWidget(self._mode_title)
        mode_layout.addWidget(self._mode_desc)
        root.addWidget(self._mode_frame)

        root.addStretch()

    # ------------------------------------------------------------------

    def _refresh_mode(self) -> None:
        mode = gs.get_current_mode(self._caps)
        if mode and mode != self._current_mode:
            self._set_current_mode(mode)

    def _set_current_mode(self, mode: str) -> None:
        self._current_mode = mode
        color = _MODE_COLORS.get(mode, "#8888a0")
        for m, btn in self._buttons.items():
            if m == mode:
                btn.setStyleSheet(_BTN_ACTIVE.format(color=color))
            else:
                btn.setStyleSheet(_BTN_INACTIVE.format())
        self._mode_title.setText(
            f"Current: {_MODE_ICONS.get(mode, '')} {gs.MODE_LABELS.get(mode, mode)}"
        )
        self._mode_desc.setText(gs.MODE_DESCRIPTIONS.get(mode, ""))

    def _on_mode_clicked(self, mode: str) -> None:
        if mode == self._current_mode:
            return

        dlg = _ConfirmDialog(mode, self._caps.gpu_switcher or "unknown", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        success, err = gs.switch_mode(mode, self._caps)
        if not success:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self, "GPU Switch Failed",
                f"Could not switch GPU mode:\n\n{err}"
            )
            return

        # Success
        self._pending = True
        self._pending_banner.setVisible(True)
        # Update pending banner text
        for btn in self._buttons.values():
            btn.setDisabled(True)

        if dlg.should_restart:
            import subprocess
            if dlg.is_reboot:
                subprocess.Popen(["systemctl", "reboot"])
            else:
                subprocess.Popen(["loginctl", "terminate-session", ""])
