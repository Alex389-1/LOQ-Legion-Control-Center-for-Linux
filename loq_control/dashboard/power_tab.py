"""
Power Profile Tab — Switch between Quiet / Balanced / Performance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from loq_control.dashboard.widgets.icons import get_icon
import loq_control.backend.power_profiles as pp

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

_PROFILE_ORDER = ["power-saver", "balanced", "performance"]
_PROFILE_SVG_KEYS = {
    "power-saver": "leaf",
    "balanced": "scale",
    "performance": "zap",
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
        super().__init__(pp.label_for(profile), parent)
        self._profile = profile
        self.setCheckable(True)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        self.setStyleSheet(self.ACTIVE_STYLE if active else self.INACTIVE_STYLE)
        color = "#3b82f6" if active else "#a1a1aa"
        svg_name = _PROFILE_SVG_KEYS.get(self._profile, "power")
        self.setIcon(get_icon(svg_name, 20, color=color))


class PowerTab(QWidget):
    """Tab for reading and switching power profiles."""

    profile_changed = Signal(str)

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._buttons: dict[str, _ProfileButton] = {}
        self._current_profile: str | None = None
        self._build_ui()
        self._init_power_source()

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

        # Power Source Badge / Status Card (AC Adapter vs Battery)
        self._power_source_frame = QFrame()
        self._power_source_frame.setStyleSheet(
            "QFrame { background: #18181b; border: 1px solid #27272a; border-radius: 10px; }"
        )
        ps_layout = QHBoxLayout(self._power_source_frame)
        ps_layout.setContentsMargins(16, 12, 16, 12)
        ps_layout.setSpacing(12)

        self._power_source_icon = QLabel("⚡")
        self._power_source_icon.setStyleSheet("font-size: 16px;")

        self._power_source_text = QLabel("Power Source: Detecting…")
        self._power_source_text.setStyleSheet("color: #f4f4f5; font-size: 13px; font-weight: 600;")

        self._power_source_badge = QLabel("DETECTING")
        self._power_source_badge.setStyleSheet(
            "color: #3b82f6; background: #1e3a8a; border: 1px solid #2563eb; "
            "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 3px 8px;"
        )

        ps_layout.addWidget(self._power_source_icon)
        ps_layout.addWidget(self._power_source_text)
        ps_layout.addStretch()
        ps_layout.addWidget(self._power_source_badge)

        root.addWidget(self._power_source_frame)

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
        desc_layout.addWidget(self._desc_label)
        root.addWidget(self._desc_frame)

        # Live Profile Context Readout (P3.2)
        context_frame = QFrame()
        context_frame.setStyleSheet(
            "QFrame { background: #18181b; border: 1px solid #27272a; border-radius: 10px; }"
        )
        context_layout = QVBoxLayout(context_frame)
        context_layout.setContentsMargins(16, 14, 16, 14)
        context_layout.setSpacing(8)

        ctx_title = QLabel("ACTIVE PROFILE HARDWARE POWER TARGETS")
        ctx_title.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;")
        context_layout.addWidget(ctx_title)

        self._ctx_grid = QHBoxLayout()
        self._ctx_grid.setSpacing(20)

        self._pl1_ctx = QLabel("PL1 Target: — W")
        self._pl1_ctx.setStyleSheet("color: #3b82f6; font-size: 12px; font-weight: 600;")

        self._pl2_ctx = QLabel("PL2 Target: — W")
        self._pl2_ctx.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 600;")

        self._ctgp_ctx = QLabel("cTGP Target: — W")
        self._ctgp_ctx.setStyleSheet("color: #10b981; font-size: 12px; font-weight: 600;")

        self._ctx_grid.addWidget(self._pl1_ctx)
        self._ctx_grid.addWidget(self._pl2_ctx)
        self._ctx_grid.addWidget(self._ctgp_ctx)
        self._ctx_grid.addStretch()

        context_layout.addLayout(self._ctx_grid)
        root.addWidget(context_frame)

        # Battery Conservation Mode Card (Charge Limit / Capping at 80%)
        if self._caps.battery_conservation_available:
            self._cons_frame = QFrame()
            self._cons_frame.setStyleSheet(
                "QFrame { background: #18181b; border: 1px solid #27272a; border-radius: 10px; }"
            )
            cons_layout = QVBoxLayout(self._cons_frame)
            cons_layout.setContentsMargins(16, 14, 16, 14)
            cons_layout.setSpacing(10)

            header_row = QHBoxLayout()
            cons_title = QLabel("BATTERY CONSERVATION MODE (80% CHARGE CAPPING)")
            cons_title.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;")
            header_row.addWidget(cons_title)
            header_row.addStretch()

            self._cons_badge = QLabel("DETECTING")
            header_row.addWidget(self._cons_badge)
            cons_layout.addLayout(header_row)

            cons_desc = QLabel(
                "Caps battery charging at ~80% to extend battery health and prevent high-voltage degradation "
                "when running on AC power continuously. Disable to charge fully to 100% for travel."
            )
            cons_desc.setStyleSheet("color: #71717a; font-size: 12px;")
            cons_desc.setWordWrap(True)
            cons_layout.addWidget(cons_desc)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(10)

            self._cons_enable_btn = QPushButton("Enable Capping (80%)")
            self._cons_disable_btn = QPushButton("Disable Capping (100%)")

            self._update_cons_badge(self._caps.battery_conservation_enabled)
            self._update_cons_buttons(self._caps.battery_conservation_enabled)

            self._cons_enable_btn.clicked.connect(lambda: self._on_toggle_conservation(True))
            self._cons_disable_btn.clicked.connect(lambda: self._on_toggle_conservation(False))

            btn_row.addWidget(self._cons_enable_btn)
            btn_row.addWidget(self._cons_disable_btn)
            btn_row.addStretch()

            cons_layout.addLayout(btn_row)
            root.addWidget(self._cons_frame)

        # Current profile indicator
        self._status_label = QLabel("Detecting current profile…")
        self._status_label.setStyleSheet("color: #71717a; font-size: 11px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._status_label)

        root.addStretch()

    # ------------------------------------------------------------------

    def _refresh_profile(self) -> None:
        if hasattr(self, "_query_worker") and self._query_worker.isRunning():
            return
        self._query_worker = _ProfileQueryWorker(self)
        self._query_worker.result.connect(self._on_query_result)
        self._query_worker.start()

    def _on_query_result(self, profile: str) -> None:
        if profile and profile != self._current_profile:
            self._set_active_profile(profile)

    def _set_active_profile(self, profile: str) -> None:
        self._current_profile = profile
        for p, btn in self._buttons.items():
            btn.set_active(p == profile)
        desc = pp.description_for(profile)
        self._desc_label.setText(desc)

        # Update live context values per profile (P3.2)
        if profile == "power-saver":
            self._pl1_ctx.setText("PL1 Target: 45 W (Sustained)")
            self._pl2_ctx.setText("PL2 Target: 65 W (Burst)")
            self._ctgp_ctx.setText("cTGP Target: 60 W (Quiet)")
        elif profile == "performance":
            self._pl1_ctx.setText("PL1 Target: 115 W (Sustained)")
            self._pl2_ctx.setText("PL2 Target: 135 W (Burst)")
            self._ctgp_ctx.setText("cTGP Target: 95 W (Max Performance)")
        else:  # balanced
            self._pl1_ctx.setText("PL1 Target: 85 W (Sustained)")
            self._pl2_ctx.setText("PL2 Target: 105 W (Burst)")
            self._ctgp_ctx.setText("cTGP Target: 80 W (Balanced)")
        self._status_label.setText(
            f"Active: {pp.label_for(profile)}  ·  Changes apply system-wide"
        )

    def _init_power_source(self) -> None:
        from loq_control.backend.monitor import _read_power_supply
        plugged, pct = _read_power_supply()
        class StatsStub:
            power_plugged = plugged
            battery_percent = pct
        self.on_stats_updated(StatsStub())

    def _update_cons_badge(self, enabled: bool) -> None:
        if enabled:
            self._cons_badge.setText("ENABLED (80% CAPPED)")
            self._cons_badge.setStyleSheet(
                "color: #10b981; background: #064e3b; border: 1px solid #059669; "
                "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 3px 8px;"
            )
        else:
            self._cons_badge.setText("DISABLED (100% FULL)")
            self._cons_badge.setStyleSheet(
                "color: #f59e0b; background: #451a03; border: 1px solid #d97706; "
                "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 3px 8px;"
            )

    def _update_cons_buttons(self, enabled: bool) -> None:
        active_style = """
            QPushButton {
                background: #2563eb; color: white; border: 1px solid #3b82f6;
                border-radius: 6px; font-size: 12px; font-weight: 600; padding: 8px 16px;
            }
        """
        inactive_style = """
            QPushButton {
                background: #18181b; color: #a1a1aa; border: 1px solid #27272a;
                border-radius: 6px; font-size: 12px; font-weight: 500; padding: 8px 16px;
            }
            QPushButton:hover { background: #27272a; color: #f4f4f5; }
        """
        if enabled:
            self._cons_enable_btn.setStyleSheet(active_style)
            self._cons_disable_btn.setStyleSheet(inactive_style)
        else:
            self._cons_enable_btn.setStyleSheet(inactive_style)
            self._cons_disable_btn.setStyleSheet(active_style)

    def _on_toggle_conservation(self, enable: bool) -> None:
        import subprocess
        val_str = "1" if enable else "0"
        try:
            res = subprocess.run(
                ["sudo", "-n", "/usr/local/bin/loq-helper", "battery-conservation", val_str],
                capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                self._caps.battery_conservation_enabled = enable
                self._update_cons_badge(enable)
                self._update_cons_buttons(enable)
                return
        except Exception:
            pass

        try:
            res = subprocess.run(
                ["pkexec", "/usr/local/bin/loq-helper", "battery-conservation", val_str],
                capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0:
                self._caps.battery_conservation_enabled = enable
                self._update_cons_badge(enable)
                self._update_cons_buttons(enable)
                return
            err = res.stderr.strip() or res.stdout.strip() or "Permission denied"
            QMessageBox.critical(
                self, "Error — LOQ Control Center",
                f"Failed to set battery conservation mode:\n\n{err}\n\nPlease run 'sudo ./scripts/install.sh' in terminal to update system helpers."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error — LOQ Control Center", f"Failed to set battery conservation mode:\n\n{exc}")

    def on_stats_updated(self, stats: any) -> None:
        if hasattr(stats, "power_plugged") and stats.power_plugged is not None:
            if stats.power_plugged:
                self._power_source_icon.setText("⚡")
                pct_str = f" ({stats.battery_percent:.0f}%)" if getattr(stats, "battery_percent", None) is not None else ""
                self._power_source_text.setText(f"Power Source: AC Adapter Connected{pct_str}")
                self._power_source_badge.setText("AC ADAPTER")
                self._power_source_badge.setStyleSheet(
                    "color: #38bdf8; background: #0c4a6e; border: 1px solid #0284c7; "
                    "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 3px 8px;"
                )
            else:
                self._power_source_icon.setText("🔋")
                pct_str = f" ({stats.battery_percent:.0f}%)" if getattr(stats, "battery_percent", None) is not None else ""
                self._power_source_text.setText(f"Power Source: On Battery Power{pct_str}")
                self._power_source_badge.setText("ON BATTERY")
                self._power_source_badge.setStyleSheet(
                    "color: #f59e0b; background: #451a03; border: 1px solid #d97706; "
                    "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 3px 8px;"
                )

    def _on_profile_clicked(self, profile: str) -> None:
        if profile == self._current_profile:
            return

        # Optimistically update UI state instantly for zero-latency GUI response
        self._set_active_profile(profile)
        self._status_label.setText(f"Applying {pp.label_for(profile)} profile…")

        # Run profile switch in background thread
        worker = _ProfileSwitchWorker(profile, self)
        worker.finished.connect(self._on_switch_finished)
        worker.start()

    def _on_switch_finished(self, profile: str, ok: bool) -> None:
        if ok:
            self._set_active_profile(profile)
            self.profile_changed.emit(profile)
        else:
            QMessageBox.warning(
                self,
                "Profile Switch Failed",
                f"Could not switch to '{pp.label_for(profile)}'.\n"
                "Check that power-profiles-daemon is running.",
            )
            self._refresh_profile()


class _ProfileSwitchWorker(QThread):
    finished = Signal(str, bool)

    def __init__(self, profile: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._profile = profile

    def run(self) -> None:
        ok = pp.set_profile(self._profile)
        self.finished.emit(self._profile, ok)


class _ProfileQueryWorker(QThread):
    result = Signal(str)

    def run(self) -> None:
        p = pp.get_active_profile()
        if p:
            self.result.emit(p)
