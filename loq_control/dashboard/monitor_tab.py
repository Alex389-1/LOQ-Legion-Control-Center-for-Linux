"""
Monitor Tab — Live system metrics dashboard.
Grid of MetricCards for CPU, RAM, Disk, iGPU, dGPU, and Fans.
Receives SystemStats from MonitorThread via signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget,
)

from loq_control.backend.monitor import StatsHistory, SystemStats
from loq_control.dashboard.widgets.metric_card import MetricCard

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities


class MonitorTab(QWidget):
    """Tab showing live hardware metrics in a responsive card grid."""

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._build_ui()

    def _build_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        grid = QGridLayout(container)
        grid.setContentsMargins(20, 20, 20, 20)
        grid.setSpacing(14)

        # --- CPU ---
        self._cpu_card = MetricCard(
            "CPU", "🖥️", "%", warn_threshold=60, danger_threshold=85,
            sparkline_color=None
        )

        # --- RAM ---
        self._ram_card = MetricCard(
            "Memory", "🧮", "%", warn_threshold=70, danger_threshold=90,
            sparkline_color="#a78bfa"
        )
        self._ram_card._sparkline.set_color("#a78bfa")

        # --- iGPU ---
        self._igpu_card = MetricCard(
            "Intel iGPU", "🔷", "%", warn_threshold=70, danger_threshold=90,
            sparkline_color="#38bdf8"
        )
        self._igpu_card._sparkline.set_color("#38bdf8")
        if not self._caps.intel_gpu_top_available:
            self._igpu_card.set_unavailable("intel_gpu_top not installed")

        # --- dGPU ---
        self._gpu_card = MetricCard(
            "NVIDIA dGPU", "🟢", "%", warn_threshold=70, danger_threshold=90,
            sparkline_color="#22c55e"
        )
        self._gpu_card._sparkline.set_color("#22c55e")
        if not self._caps.nvidia_available:
            self._gpu_card.set_unavailable("NVML not available or GPU not detected")

        # --- GPU Temp ---
        self._gpu_temp_card = MetricCard(
            "GPU Temp", "🌡️", "°C", warn_threshold=70, danger_threshold=88,
            sparkline_color="#f59e0b"
        )
        self._gpu_temp_card._sparkline.set_color("#f59e0b")
        if not self._caps.nvidia_available:
            self._gpu_temp_card.set_unavailable("NVIDIA GPU not detected")

        # --- GPU Power ---
        self._gpu_power_card = MetricCard(
            "GPU Power", "⚡", "W", warn_threshold=80, danger_threshold=115,
            sparkline_color="#fb923c"
        )
        self._gpu_power_card._sparkline.set_color("#fb923c")
        self._gpu_power_card._sparkline.set_max_value(130.0)
        if not self._caps.nvidia_available:
            self._gpu_power_card.set_unavailable("NVIDIA GPU not detected")

        # --- Fans or Power Limit Targets ---
        self._show_fans = self._caps.fan_rpm_readable
        self._show_limits = not self._caps.fan_rpm_readable and self._caps.power_limits_available

        if self._show_fans:
            self._fan1_card = MetricCard(
                "Fan 1", "🌀", " RPM", warn_threshold=99999, danger_threshold=99999, sparkline_color="#64748b"
            )
            self._fan1_card._sparkline.set_max_value(6000.0)
            self._fan1_card._sparkline.set_color("#64748b")
            self._fan2_card = MetricCard(
                "Fan 2", "🌀", " RPM", warn_threshold=99999, danger_threshold=99999, sparkline_color="#475569"
            )
            self._fan2_card._sparkline.set_max_value(6000.0)
            self._fan2_card._sparkline.set_color("#475569")
        elif self._show_limits:
            self._pl1_card = MetricCard(
                "CPU PL1 Target", "🔋", " W", warn_threshold=999, danger_threshold=999, sparkline_color="#e8182c"
            )
            self._pl1_card._sparkline.set_color("#e8182c")
            self._pl1_card._sparkline.set_max_value(120.0)

            self._ctgp_card = MetricCard(
                "GPU cTGP Target", "⚡", " W", warn_threshold=999, danger_threshold=999, sparkline_color="#38bdf8"
            )
            self._ctgp_card._sparkline.set_color("#38bdf8")
            self._ctgp_card._sparkline.set_max_value(120.0)
        else:
            self._fan1_card = None
            self._fan2_card = None

        # --- Disk mounts placeholder ---
        self._disk_card = MetricCard(
            "Disk", "💾", "%", warn_threshold=75, danger_threshold=90,
            sparkline_color="#94a3b8"
        )
        self._disk_card._sparkline.set_color("#94a3b8")

        # --- Layout (2-column responsive grid) ---
        cards = [
            (self._cpu_card,       0, 0),
            (self._ram_card,       0, 1),
            (self._igpu_card,      1, 0),
            (self._gpu_card,       1, 1),
            (self._gpu_temp_card,  2, 0),
            (self._gpu_power_card, 2, 1),
        ]
        if self._show_fans:
            cards.append((self._fan1_card, 3, 0))
            cards.append((self._fan2_card, 3, 1))
        elif self._show_limits:
            cards.append((self._pl1_card,  3, 0))
            cards.append((self._ctgp_card, 3, 1))

        cards.append((self._disk_card, 4, 0, 1, 2))

        for entry in cards:
            card = entry[0]
            row, col = entry[1], entry[2]
            rowspan = entry[3] if len(entry) > 3 else 1
            colspan = entry[4] if len(entry) > 4 else 1
            grid.addWidget(card, row, col, rowspan, colspan)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------
    # Update slot (connected to MonitorThread.stats_updated)
    # ------------------------------------------------------------------

    def on_stats_updated(self, stats: SystemStats, history: StatsHistory) -> None:
        # CPU
        self._cpu_card.update_value(
            stats.cpu_percent,
            subtitle=f"{stats.cpu_freq_mhz:.0f} MHz  ·  {len(stats.cpu_per_core)} cores",
            push_history=stats.cpu_percent,
        )
        self._cpu_card.set_history(history.cpu)

        # RAM
        self._ram_card.update_value(
            stats.ram_percent,
            subtitle=f"{stats.ram_used_gb:.1f} / {stats.ram_total_gb:.1f} GB",
            push_history=stats.ram_percent,
        )
        self._ram_card.set_history(history.ram)

        # iGPU
        if stats.igpu_util is not None:
            self._igpu_card.update_value(
                stats.igpu_util,
                subtitle="Intel Render Engine",
                push_history=stats.igpu_util,
            )
            self._igpu_card.set_history(history.igpu)
        elif not self._caps.intel_gpu_top_available:
            pass  # Already marked unavailable

        # dGPU util
        if stats.gpu_util is not None:
            vram_str = ""
            if stats.gpu_vram_used_mb and stats.gpu_vram_total_mb:
                vram_str = f"  ·  VRAM {stats.gpu_vram_used_mb} / {stats.gpu_vram_total_mb} MB"
            self._gpu_card.update_value(
                float(stats.gpu_util),
                subtitle=f"{self._caps.nvidia_device_name or 'NVIDIA GPU'}{vram_str}",
                push_history=float(stats.gpu_util),
            )
            self._gpu_card.set_history(history.gpu_util)

        # GPU temp
        if stats.gpu_temp is not None:
            self._gpu_temp_card.update_value(
                float(stats.gpu_temp),
                subtitle="GPU Core",
                push_history=float(stats.gpu_temp),
            )
            self._gpu_temp_card.set_history(history.gpu_temp)
            self._gpu_temp_card._sparkline.set_max_value(100.0)

        # GPU power
        if stats.gpu_power_w is not None:
            self._gpu_power_card.update_value(
                stats.gpu_power_w,
                subtitle="Power draw",
                push_history=stats.gpu_power_w,
            )

        # Fans / Limits update
        if self._show_fans:
            self._fan1_card.update_value(
                f"{stats.fan1_rpm}",
                subtitle="Fan 1",
                push_history=float(stats.fan1_rpm),
            )
            self._fan2_card.update_value(
                f"{stats.fan2_rpm}",
                subtitle="Fan 2",
                push_history=float(stats.fan2_rpm),
            )
        elif self._show_limits:
            import loq_control.backend.power_limits as pl
            vals = pl.read_current_values(pl.resolve_attrs(self._caps))
            pl1_val = vals.get("cpu_pl1")
            ctgp_val = vals.get("gpu_ctgp")

            if pl1_val is not None:
                self._pl1_card.update_value(
                    float(pl1_val),
                    subtitle="CPU Sustained Power Limit",
                    push_history=float(pl1_val),
                )
            if ctgp_val is not None:
                self._ctgp_card.update_value(
                    float(ctgp_val),
                    subtitle="GPU Configurable TGP Target",
                    push_history=float(ctgp_val),
                )

        # Disk — show first mount for simplicity
        if stats.disk_mounts:
            dm = stats.disk_mounts[0]
            others = ""
            if len(stats.disk_mounts) > 1:
                others = "  ·  " + "  ".join(
                    f"{m.mount} {m.percent:.0f}%" for m in stats.disk_mounts[1:3]
                )
            self._disk_card.update_value(
                dm.percent,
                subtitle=f"{dm.mount}  {dm.used_gb:.1f} / {dm.total_gb:.1f} GB{others}",
                push_history=dm.percent,
            )
