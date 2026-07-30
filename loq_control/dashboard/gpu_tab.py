"""
GPU Mode Tab — Switch between Integrated / Hybrid / Discrete graphics.
Routes privileged operations through pkexec loq-helper.
Shows pending-restart banner when a switch has been applied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QLabel, QProgressDialog, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from loq_control.dashboard.widgets.icons import get_icon, get_pixmap
import loq_control.backend.gpu_switch as gs

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

_MODES = ["integrated", "hybrid", "nvidia"]
_MODE_SVG_KEYS = {
    "integrated": "integrated",
    "hybrid": "hybrid",
    "nvidia": "nvidia",
}

_BTN_INACTIVE = """
    QPushButton {{
        background: #18181b;
        border: 1px solid #27272a;
        border-radius: 10px;
        color: #a1a1aa;
        font-size: 13px;
        font-weight: 500;
        padding: 18px 10px;
    }}
    QPushButton:hover {{
        background: #27272a;
        border-color: #3f3f46;
        color: #f4f4f5;
    }}
    QPushButton:disabled {{
        background: #111114;
        color: #3f3f46;
    }}
"""

_BTN_ACTIVE = """
    QPushButton {{
        background: #18181b;
        border: 2px solid {color};
        border-radius: 10px;
        color: #f4f4f5;
        font-size: 13px;
        font-weight: 600;
        padding: 17px 10px;
    }}
"""

_MODE_COLORS = {
    "integrated": "#3b82f6",
    "hybrid": "#3b82f6",
    "nvidia": "#3b82f6",
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
                background: #09090b;
                color: #f4f4f5;
            }
            QLabel { color: #f4f4f5; }
        """)

        restart_type = gs.MODE_RESTART_REQUIREMENT.get(target_mode, "logout")
        self._reboot = restart_type == "reboot"

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 20)

        icon_lbl = QLabel()
        svg_name = _MODE_SVG_KEYS.get(target_mode, "gpu")
        icon_lbl.setPixmap(get_pixmap(svg_name, 36, color="#3b82f6"))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        heading = QLabel(f"Switch to {gs.MODE_LABELS.get(target_mode, target_mode)}")
        heading.setStyleSheet("font-size: 16px; font-weight: 600; color: #f4f4f5;")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        desc = QLabel(gs.MODE_DESCRIPTIONS.get(target_mode, ""))
        desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Tool info
        tool_info = QLabel(f"Tool: <b>{switcher}</b>  ·  Requires: <b>{restart_type}</b>")
        tool_info.setStyleSheet("color: #71717a; font-size: 11px;")
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
            "color: #eab308; background: #1c1917; border: 1px solid #44403c; "
            "border-radius: 8px; padding: 12px; font-size: 12px;"
        )
        warn_lbl.setWordWrap(True)
        layout.addWidget(warn_lbl)

        # Reboot checkbox
        self._reboot_check = QCheckBox(
            f"{'Reboot' if self._reboot else 'Log out'} automatically after applying"
        )
        self._reboot_check.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        layout.addWidget(self._reboot_check)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn:
            apply_btn.setStyleSheet("""
                QPushButton {
                    background: #2563eb; color: white; border: none;
                    border-radius: 8px; font-weight: 500; padding: 8px 20px;
                }
                QPushButton:hover { background: #1d4ed8; }
            """)
            apply_btn.clicked.connect(self.accept)

        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setStyleSheet("""
                QPushButton {
                    background: #18181b; color: #a1a1aa; border: 1px solid #27272a;
                    border-radius: 8px; font-weight: 500; padding: 8px 20px;
                }
                QPushButton:hover { background: #27272a; color: #f4f4f5; }
            """)
            cancel_btn.clicked.connect(self.reject)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def should_restart(self) -> bool:
        return self._reboot_check.isChecked()

    @property
    def is_reboot(self) -> bool:
        return self._reboot


class _GpuSwitchWorker(QThread):
    """Background worker thread for long-running GPU switch + initramfs rebuild."""

    finished_signal = Signal(bool, str)

    def __init__(self, mode: str, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._caps = caps

    def run(self) -> None:
        success, err = gs.switch_mode(self._mode, self._caps)
        self.finished_signal.emit(success, err)


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
        self._pending_text = QLabel()
        self._pending_text.setStyleSheet("color: #f59e0b; font-size: 12px;")
        self._pending_text.setWordWrap(True)
        self._update_pending_text(gs.get_pending_mode())
        pending_layout.addWidget(self._pending_text)
        self._pending_banner.setVisible(self._pending)
        root.addWidget(self._pending_banner)

        # Mode buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        for mode in _MODES:
            btn = QPushButton(gs.MODE_LABELS[mode])
            btn.setIcon(get_icon(_MODE_SVG_KEYS[mode], 22, color="#a1a1aa"))
            btn.setMinimumHeight(80)
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
            "QFrame { background: #18181b; border: 1px solid #27272a; border-radius: 10px; }"
        )
        mode_layout = QVBoxLayout(self._mode_frame)
        mode_layout.setContentsMargins(16, 14, 16, 14)
        self._mode_title = QLabel("Detecting current mode…")
        self._mode_title.setStyleSheet("color: #f4f4f5; font-size: 13px; font-weight: 600;")
        self._mode_desc = QLabel("")
        self._mode_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        self._mode_desc.setWordWrap(True)
        mode_layout.addWidget(self._mode_title)
        mode_layout.addWidget(self._mode_desc)

        # Bios note
        bios_note = QLabel(
            "ℹ️  Note: GPU mode switching is managed in software via envycontrol (driver configuration & PCIe power states). "
            "The physical UEFI BIOS setup option remains on 'Dynamic Graphics', which is normal and recommended for Linux."
        )
        bios_note.setStyleSheet("color: #71717a; font-size: 11px;")
        bios_note.setWordWrap(True)
        mode_layout.addWidget(bios_note)

        root.addWidget(self._mode_frame)

        root.addStretch()

    # ------------------------------------------------------------------

    def _update_pending_text(self, mode: str | None) -> None:
        label = gs.MODE_LABELS.get(mode or "", mode or "Unknown")
        self._pending_text.setText(
            f"🔄  GPU mode switch to <b>{label}</b> is pending. Please restart your system to apply."
        )

    def _refresh_mode(self) -> None:
        mode = gs.get_current_mode(self._caps)
        pending = gs.get_pending_mode()
        if pending:
            self._update_pending_text(pending)
        if pending and mode == pending:
            gs.clear_pending()
            self._pending = False
            if hasattr(self, "_pending_banner"):
                self._pending_banner.setVisible(False)
            for btn in self._buttons.values():
                btn.setDisabled(False)

        if mode and mode != self._current_mode:
            self._set_current_mode(mode)

    def _set_current_mode(self, mode: str) -> None:
        self._current_mode = mode
        color = _MODE_COLORS.get(mode, "#8888a0")
        for m, btn in self._buttons.items():
            if m == mode:
                btn.setStyleSheet(_BTN_ACTIVE.format(color=color))
                btn.setIcon(get_icon(_MODE_SVG_KEYS.get(m, "gpu"), 22, color="#f4f4f5"))
            else:
                btn.setStyleSheet(_BTN_INACTIVE.format())
                btn.setIcon(get_icon(_MODE_SVG_KEYS.get(m, "gpu"), 22, color="#a1a1aa"))
        self._mode_title.setText(
            f"Current: {gs.MODE_LABELS.get(mode, mode)}"
        )
        self._mode_desc.setText(gs.MODE_DESCRIPTIONS.get(mode, ""))

    def _on_mode_clicked(self, mode: str) -> None:
        if mode == self._current_mode:
            return

        dlg = _ConfirmDialog(mode, self._caps.gpu_switcher or "unknown", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        progress = QProgressDialog(
            f"Switching GPU mode to {gs.MODE_LABELS.get(mode, mode)}…\n\n"
            "Rebuilding Linux kernel initramfs image.\n"
            "This takes ~30–40 seconds. Please wait.",
            None, 0, 0, self
        )
        progress.setWindowTitle("Applying GPU Mode Switch")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setCancelButton(None)
        progress.setStyleSheet("""
            QProgressDialog { background: #09090b; color: #f4f4f5; }
            QLabel { color: #f4f4f5; font-size: 12px; }
            QProgressBar {
                background: #18181b; border: 1px solid #27272a; border-radius: 4px;
                height: 8px; text-align: center;
            }
            QProgressBar::chunk { background: #3b82f6; border-radius: 4px; }
        """)
        progress.show()
        QApplication.processEvents()

        self._worker = _GpuSwitchWorker(mode, self._caps, self)
        self._worker.finished_signal.connect(
            lambda success, err: self._on_switch_finished(
                success, err, mode, progress, dlg.should_restart, dlg.is_reboot
            )
        )
        self._worker.start()

    def _on_switch_finished(
        self,
        success: bool,
        err: str,
        mode: str,
        progress: QProgressDialog,
        should_restart: bool,
        is_reboot: bool,
    ) -> None:
        progress.close()
        if not success:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self, "GPU Switch Failed",
                f"Could not switch GPU mode:\n\n{err}"
            )
            return

        # Success
        self._pending = True
        self._update_pending_text(mode)
        self._pending_banner.setVisible(True)
        for btn in self._buttons.values():
            btn.setDisabled(True)

        if should_restart:
            import os, subprocess
            try:
                os.sync()
                os.sync()
            except Exception:
                pass

            if is_reboot:
                cmd = "sync; sleep 0.5; systemctl reboot || loginctl reboot || reboot"
                subprocess.Popen(
                    ["nohup", "sh", "-c", cmd],
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                QApplication.quit()
            else:
                session_id = os.environ.get("XDG_SESSION_ID")
                if session_id:
                    cmd = f"sync; sleep 0.5; loginctl terminate-session {session_id}"
                else:
                    user = os.environ.get("USER", "")
                    if user:
                        cmd = f"sync; sleep 0.5; loginctl terminate-user {user}"
                    else:
                        cmd = "sync; sleep 0.5; systemctl restart display-manager"
                subprocess.Popen(
                    ["nohup", "sh", "-c", cmd],
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                QApplication.quit()
