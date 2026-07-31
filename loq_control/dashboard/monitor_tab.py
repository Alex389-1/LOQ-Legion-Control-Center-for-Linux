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
        self._active_detail_dialog = None
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
            "CPU", "cpu", "%", warn_threshold=60, danger_threshold=85,
            sparkline_color=None
        )

        # --- RAM ---
        self._ram_card = MetricCard(
            "Memory", "memory", "%", warn_threshold=70, danger_threshold=90,
            sparkline_color="#a78bfa"
        )
        self._ram_card._sparkline.set_color("#a78bfa")

        # --- iGPU ---
        self._igpu_card = MetricCard(
            "Intel iGPU", "integrated", "%", warn_threshold=70, danger_threshold=90,
            sparkline_color="#38bdf8"
        )
        self._igpu_card._sparkline.set_color("#38bdf8")
        if not self._caps.intel_gpu_available and not self._caps.intel_gpu_top_available:
            self._igpu_card.set_unavailable("Intel iGPU not detected")

        # --- dGPU ---
        self._gpu_card = MetricCard(
            "NVIDIA dGPU", "gpu", "%", warn_threshold=70, danger_threshold=90,
            sparkline_color="#10b981"
        )
        self._gpu_card._sparkline.set_color("#10b981")
        if not self._caps.nvidia_available:
            self._gpu_card.set_unavailable("NVML not available or GPU not detected")

        # --- GPU Temp ---
        self._gpu_temp_card = MetricCard(
            "GPU Temp", "temp", "°C", warn_threshold=70, danger_threshold=88,
            sparkline_color="#f59e0b"
        )
        self._gpu_temp_card._sparkline.set_color("#f59e0b")
        if not self._caps.nvidia_available:
            self._gpu_temp_card.set_unavailable("NVIDIA GPU not detected")

        # --- GPU Power ---
        self._gpu_power_card = MetricCard(
            "GPU Power", "zap", "W", warn_threshold=80, danger_threshold=115,
            sparkline_color="#fb923c"
        )
        self._gpu_power_card._sparkline.set_color("#fb923c")
        self._gpu_power_card._sparkline.set_max_value(130.0)
        if not self._caps.nvidia_available:
            self._gpu_power_card.set_unavailable("NVIDIA GPU not detected")

        # --- Fans (if readable) ---
        self._show_fans = self._caps.fan_rpm_readable

        if self._show_fans:
            self._fan1_card = MetricCard(
                "Fan 1", "fan", " RPM", warn_threshold=99999, danger_threshold=99999, sparkline_color="#64748b"
            )
            self._fan1_card._sparkline.set_max_value(6000.0)
            self._fan1_card._sparkline.set_color("#64748b")
            self._fan2_card = MetricCard(
                "Fan 2", "fan", " RPM", warn_threshold=99999, danger_threshold=99999, sparkline_color="#475569"
            )
            self._fan2_card._sparkline.set_max_value(6000.0)
            self._fan2_card._sparkline.set_color("#475569")
        else:
            self._fan1_card = None
            self._fan2_card = None

        self._disk_card = MetricCard(
            "Disk Activity", "monitor", "%", warn_threshold=75, danger_threshold=90,
            sparkline_color="#3b82f6"
        )
        self._disk_card._sparkline.set_color("#3b82f6")

        self._net_card = MetricCard(
            "Network", "wifi", " KB/s", warn_threshold=10000, danger_threshold=50000,
            sparkline_color="#06b6d4"
        )
        self._net_card._sparkline.set_color("#06b6d4")

        # Connect clicked signals to opening detailed hardware dialog
        self._cpu_card.clicked.connect(lambda: self._open_detail_dialog("cpu"))
        self._ram_card.clicked.connect(lambda: self._open_detail_dialog("ram"))
        self._igpu_card.clicked.connect(lambda: self._open_detail_dialog("igpu"))
        self._gpu_card.clicked.connect(lambda: self._open_detail_dialog("gpu"))
        self._gpu_temp_card.clicked.connect(lambda: self._open_detail_dialog("gpu_temp"))
        self._gpu_power_card.clicked.connect(lambda: self._open_detail_dialog("gpu_power"))
        self._disk_card.clicked.connect(lambda: self._open_detail_dialog("disk"))
        self._net_card.clicked.connect(lambda: self._open_detail_dialog("net"))
        if self._show_fans:
            if self._fan1_card:
                self._fan1_card.clicked.connect(lambda: self._open_detail_dialog("fan1"))
            if self._fan2_card:
                self._fan2_card.clicked.connect(lambda: self._open_detail_dialog("fan2"))

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

        cards.append((self._disk_card, 3, 0))
        cards.append((self._net_card,  3, 1))

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
        self._latest_stats = stats
        self._latest_history = history

        # Forward live stats update to active detail modal if open
        if self._active_detail_dialog and self._active_detail_dialog.isVisible():
            self._active_detail_dialog.update_stats(stats, history)

        # CPU
        cpu_model = self._caps.cpu_model or "Intel Core Processor"
        cpu_temp_str = f"  ·  Temp: {stats.cpu_temp:.0f}°C" if stats.cpu_temp is not None else ""
        self._cpu_card.update_value(
            stats.cpu_percent,
            subtitle=f"Clock: {stats.cpu_freq_mhz / 1000.0:.2f} GHz  ·  Cores: {len(stats.cpu_per_core)}{cpu_temp_str}",
            push_history=stats.cpu_percent,
        )
        self._cpu_card.set_spec_details(
            model_name=cpu_model,
            meta_text=f"Base Clock: {stats.cpu_freq_mhz:.0f} MHz  ·  Logical Cores: {len(stats.cpu_per_core)}"
        )
        self._cpu_card.set_history(history.cpu)

        # RAM
        avail_gb = stats.ram_total_gb - stats.ram_used_gb
        self._ram_card.update_value(
            stats.ram_percent,
            subtitle=f"Used: {stats.ram_used_gb:.1f} GB  ·  Available: {avail_gb:.1f} GB",
            push_history=stats.ram_percent,
        )
        self._ram_card.set_spec_details(
            model_name=f"{stats.ram_total_gb:.1f} GB System Memory",
            meta_text=f"Physical RAM Total: {stats.ram_total_gb:.1f} GB  ·  Swap: {stats.swap_used_gb:.1f} / {stats.swap_total_gb:.1f} GB"
        )
        self._ram_card.set_history(history.ram)

        # iGPU
        if stats.igpu_util is not None:
            self._igpu_card.update_value(
                stats.igpu_util,
                subtitle="Intel Render Engine",
                push_history=stats.igpu_util,
            )
            self._igpu_card.set_spec_details(
                model_name="Intel Graphics (iGPU)",
                meta_text="Driver: i915/xe  ·  Shared System Memory Architecture"
            )
            self._igpu_card.set_history(history.igpu)
        elif not self._caps.intel_gpu_top_available:
            pass  # Already marked unavailable

        # dGPU util
        if stats.gpu_util is not None:
            vram_used = stats.gpu_vram_used_mb or 0
            vram_tot = stats.gpu_vram_total_mb or 6144
            self._gpu_card.update_value(
                float(stats.gpu_util),
                subtitle=f"VRAM: {vram_used} / {vram_tot} MB ({ (vram_used/max(vram_tot,1))*100:.1f}%)",
                push_history=float(stats.gpu_util),
            )
            gpu_name = self._caps.nvidia_device_name or "NVIDIA GeForce RTX GPU"
            self._gpu_card.set_spec_details(
                model_name=f"{gpu_name} (NVIDIA Corp)",
                meta_text=f"Dedicated VRAM: {vram_tot} MB  ·  PCIe Bus ID: 0000:01:00.0"
            )
            self._gpu_card.set_history(history.gpu_util)

        # GPU temp
        if stats.gpu_temp is not None:
            self._gpu_temp_card.update_value(
                float(stats.gpu_temp),
                subtitle="GPU Core Thermal Zone",
                push_history=float(stats.gpu_temp),
            )
            self._gpu_temp_card.set_spec_details(
                model_name="NVIDIA Thermal Sensor",
                meta_text="Thermal Limit: 88°C  ·  Target Junction Temp: < 80°C"
            )
            self._gpu_temp_card.set_history(history.gpu_temp)
            self._gpu_temp_card._sparkline.set_max_value(100.0)

        # GPU power
        if stats.gpu_power_w is not None:
            self._gpu_power_card.update_value(
                stats.gpu_power_w,
                subtitle="Real-time Power Draw",
                push_history=stats.gpu_power_w,
            )
            self._gpu_power_card.set_spec_details(
                model_name="NVIDIA Power Management (NVML)",
                meta_text="Target TGP: 95.0 W  ·  Dynamic Boost Target: 115.0 W"
            )
            self._gpu_power_card.set_history(history.gpu_power)

        # Fans update
        if self._show_fans:
            self._fan1_card.update_value(
                f"{stats.fan1_rpm}",
                subtitle="Primary Cooling Fan",
                push_history=float(stats.fan1_rpm),
            )
            self._fan1_card.set_spec_details(
                model_name="Lenovo Dual Thermal Fan 1",
                meta_text="Max Rated Speed: 5800 RPM  ·  Status: Active"
            )
            self._fan2_card.update_value(
                f"{stats.fan2_rpm}",
                subtitle="Secondary Cooling Fan",
                push_history=float(stats.fan2_rpm),
            )
            self._fan2_card.set_spec_details(
                model_name="Lenovo Dual Thermal Fan 2",
                meta_text="Max Rated Speed: 5800 RPM  ·  Status: Active"
            )

        # Disk (Real-Time I/O Activity)
        if stats.disk_mounts:
            dm = stats.disk_mounts[0]
            r_fmt = f"{stats.disk_read_kbps:.1f} KB/s" if stats.disk_read_kbps < 1024 else f"{stats.disk_read_kbps / 1024.0:.1f} MB/s"
            w_fmt = f"{stats.disk_write_kbps:.1f} KB/s" if stats.disk_write_kbps < 1024 else f"{stats.disk_write_kbps / 1024.0:.1f} MB/s"
            self._disk_card.update_value(
                stats.disk_busy_percent,
                subtitle=f"R: {r_fmt}  W: {w_fmt}  ·  Cap: {dm.used_gb:.1f}/{dm.total_gb:.1f} GB ({dm.percent:.0f}%)",
                push_history=stats.disk_busy_percent,
            )
            free_gb = dm.total_gb - dm.used_gb
            self._disk_card.set_spec_details(
                model_name=f"NVMe SSD Storage ({dm.mount})",
                meta_text=f"Total Capacity: {dm.total_gb:.1f} GB  ·  Free Space: {free_gb:.1f} GB  ·  Read: {r_fmt}  Write: {w_fmt}"
            )
            self._disk_card.set_history(history.disk)

        # Network
        rx_fmt = f"{stats.net_rx_kbps:.1f} KB/s" if stats.net_rx_kbps < 1024 else f"{stats.net_rx_kbps / 1024.0:.2f} MB/s"
        tx_fmt = f"{stats.net_tx_kbps:.1f} KB/s" if stats.net_tx_kbps < 1024 else f"{stats.net_tx_kbps / 1024.0:.2f} MB/s"
        conn_type = "Wi-Fi" if stats.net_is_wifi else "Ethernet"

        self._net_card.update_value(
            f"↓ {rx_fmt}  ↑ {tx_fmt}",
            subtitle=f"{conn_type} ({stats.net_interface})  ·  IP: {stats.net_ipv4}",
            push_history=stats.net_rx_kbps,
        )
        self._net_card.set_spec_details(
            model_name=f"{conn_type} Adapter ({stats.net_interface})",
            meta_text=f"IPv4 Address: {stats.net_ipv4}  ·  Download: {rx_fmt}  ·  Upload: {tx_fmt}"
        )
        self._net_card.set_history(history.net_rx)

    def _open_detail_dialog(self, key: str) -> None:
        if not hasattr(self, "_latest_stats") or self._latest_stats is None:
            return
        from loq_control.dashboard.widgets.metric_detail_dialog import MetricDetailDialog
        dlg = MetricDetailDialog(key, self._latest_stats, self._latest_history, self._caps, parent=self)
        self._active_detail_dialog = dlg
        dlg.finished.connect(self._on_detail_dialog_closed)
        dlg.exec()

    def _on_detail_dialog_closed(self) -> None:
        self._active_detail_dialog = None
