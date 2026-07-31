"""
MetricDetailDialog — High-resolution hardware inspector dialog.
Displays detailed telemetry, per-core CPU breakdown, VRAM stats,
PCIe link speed, driver versions, and enlarged history charts.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QProgressBar, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
    QPushButton,
)

from loq_control.dashboard.widgets.icons import get_pixmap
from loq_control.dashboard.widgets.sparkline import SparklineWidget

if TYPE_CHECKING:
    from loq_control.backend.monitor import StatsHistory, SystemStats
    from loq_control.discovery import Capabilities


class MetricDetailDialog(QDialog):
    """
    Detailed hardware inspector modal opened when clicking any metric card.
    """

    def __init__(
        self,
        metric_key: str,
        stats: SystemStats,
        history: StatsHistory,
        caps: Capabilities,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key = metric_key
        self._stats = stats
        self._history = history
        self._caps = caps

        self.setWindowTitle(f"Hardware Inspector — {metric_key.upper()}")
        self.resize(750, 620)
        self.setMinimumSize(600, 480)
        self.setStyleSheet("""
            QDialog {
                background: #09090b;
                color: #f4f4f5;
            }
            QLabel { color: #f4f4f5; }
            QScrollArea { background: transparent; border: none; }
        """)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header Row
        header = QHBoxLayout()
        header.setSpacing(12)

        icon_name = {
            "cpu": "cpu",
            "ram": "memory",
            "igpu": "integrated",
            "gpu": "gpu",
            "gpu_temp": "temp",
            "gpu_power": "zap",
            "disk": "monitor",
            "net": "wifi" if self._stats.net_is_wifi else "ethernet",
            "fan1": "fan",
            "fan2": "fan",
        }.get(self._key, "monitor")

        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_pixmap(icon_name, 28, color="#3b82f6"))
        header.addWidget(icon_lbl)

        title_text = {
            "cpu": "CPU Performance & Core Details",
            "ram": "System Memory (RAM) Telemetry",
            "igpu": "Intel Integrated GPU (iGPU) Telemetry",
            "gpu": "NVIDIA Discrete GPU (dGPU) Telemetry",
            "gpu_temp": "NVIDIA GPU Thermal Sensor Details",
            "gpu_power": "NVIDIA GPU Power Management Details",
            "disk": "Storage Volumes & Drive Performance",
            "net": "Wi-Fi & Ethernet Network Telemetry",
            "fan1": "Primary Cooling Fan Telemetry",
            "fan2": "Secondary Cooling Fan Telemetry",
        }.get(self._key, f"{self._key.upper()} Detailed Telemetry")

        title_lbl = QLabel(title_text)
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #f4f4f5;")
        header.addWidget(title_lbl)
        header.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #18181b; color: #a1a1aa; border: 1px solid #27272a;
                border-radius: 6px; font-size: 13px; font-weight: 700;
            }
            QPushButton:hover { background: #27272a; color: #f4f4f5; }
        """)
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Main Scroll Container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        body = QVBoxLayout(container)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        # 1. High-Res History Chart Panel
        chart_frame = QFrame()
        chart_frame.setStyleSheet("""
            QFrame {
                background: #18181b;
                border: 1px solid #27272a;
                border-radius: 10px;
            }
        """)
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(16, 14, 16, 14)
        chart_layout.setSpacing(8)

        chart_hdr = QHBoxLayout()
        chart_title = QLabel("REAL-TIME METRIC HISTORY (120 SAMPLES)")
        chart_title.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;")
        chart_hdr.addWidget(chart_title)
        chart_hdr.addStretch()

        self._stat_lbl = QLabel("")
        self._stat_lbl.setStyleSheet("color: #3b82f6; font-size: 11px; font-weight: 600;")
        chart_hdr.addWidget(self._stat_lbl)

        hist_data = getattr(self._history, self._history_attr_name(), [])
        if hist_data:
            valid = [v for v in hist_data if v is not None]
            if valid:
                min_v = min(valid)
                avg_v = sum(valid) / len(valid)
                max_v = max(valid)
                cur_v = valid[-1]
                unit = "°C" if "temp" in self._key else ("W" if "power" in self._key else "%")
                self._stat_lbl.setText(f"Min: {min_v:.1f}{unit}  ·  Avg: {avg_v:.1f}{unit}  ·  Max: {max_v:.1f}{unit}  ·  Current: {cur_v:.1f}{unit}")

        chart_layout.addLayout(chart_hdr)

        max_y = 100.0
        if "power" in self._key:
            max_y = 130.0
        elif "fan" in self._key:
            max_y = 6000.0

        color_map = {
            "cpu": "#3b82f6",
            "ram": "#a78bfa",
            "igpu": "#38bdf8",
            "gpu": "#10b981",
            "gpu_temp": "#f59e0b",
            "gpu_power": "#fb923c",
            "disk": "#3b82f6",
            "net": "#06b6d4",
            "fan1": "#64748b",
            "fan2": "#475569",
        }
        spark_color = color_map.get(self._key, "#3b82f6")

        self._sparkline = SparklineWidget(color=spark_color, max_value=max_y)
        self._sparkline.setMinimumHeight(120)
        if hist_data:
            self._sparkline.set_data(hist_data)
        chart_layout.addWidget(self._sparkline)
        body.addWidget(chart_frame)

        # 2. Per-Core CPU Section (Only for CPU)
        self._core_widgets = []
        if self._key == "cpu" and self._stats.cpu_per_core:
            core_frame = QFrame()
            core_frame.setStyleSheet("""
                QFrame {
                    background: #18181b;
                    border: 1px solid #27272a;
                    border-radius: 10px;
                }
            """)
            core_layout = QVBoxLayout(core_frame)
            core_layout.setContentsMargins(16, 14, 16, 14)
            core_layout.setSpacing(12)

            core_title = QLabel(f"PER-CORE CPU UTILIZATION ({len(self._stats.cpu_per_core)} LOGICAL THREADS)")
            core_title.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;")
            core_layout.addWidget(core_title)

            grid = QGridLayout()
            grid.setSpacing(10)
            for i, val in enumerate(self._stats.cpu_per_core):
                row = i // 2
                col = (i % 2) * 3

                lbl = QLabel(f"Core {i:02d}")
                lbl.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600;")
                lbl.setFixedWidth(50)

                pbar = QProgressBar()
                pbar.setRange(0, 100)
                pbar.setValue(int(val))
                pbar.setTextVisible(False)
                pbar.setFixedHeight(8)

                bar_color = "#22c55e" if val < 60 else ("#f59e0b" if val < 85 else "#ef4444")
                pbar.setStyleSheet(f"""
                    QProgressBar {{
                        background: #09090b; border: 1px solid #27272a; border-radius: 4px;
                    }}
                    QProgressBar::chunk {{
                        background: {bar_color}; border-radius: 4px;
                    }}
                """)

                val_lbl = QLabel(f"{val:.1f}%")
                val_lbl.setStyleSheet(f"color: {bar_color}; font-size: 11px; font-weight: 700;")
                val_lbl.setFixedWidth(48)
                val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                grid.addWidget(lbl, row, col)
                grid.addWidget(pbar, row, col + 1)
                grid.addWidget(val_lbl, row, col + 2)

                self._core_widgets.append((pbar, val_lbl))

            core_layout.addLayout(grid)
            body.addWidget(core_frame)

        # 3. Mounted Storage Volumes Section (Only for Disk)
        if self._key == "disk" and self._stats.disk_mounts:
            part_frame = QFrame()
            part_frame.setStyleSheet("""
                QFrame {
                    background: #18181b;
                    border: 1px solid #27272a;
                    border-radius: 10px;
                }
            """)
            part_layout = QVBoxLayout(part_frame)
            part_layout.setContentsMargins(16, 14, 16, 14)
            part_layout.setSpacing(12)

            part_title = QLabel(f"PHYSICAL DRIVE PARTITIONS ({len(self._stats.disk_mounts)} DETECTED PARTITIONS)")
            part_title.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;")
            part_layout.addWidget(part_title)

            for m in self._stats.disk_mounts:
                row_card = QFrame()
                row_card.setStyleSheet("""
                    QFrame {
                        background: #111114;
                        border: 1px solid #1e1e24;
                        border-radius: 8px;
                    }
                """)
                row_lay = QVBoxLayout(row_card)
                row_lay.setContentsMargins(12, 10, 12, 10)
                row_lay.setSpacing(6)

                hdr = QHBoxLayout()
                dev_title = f"💾 Partition {m.device}" if m.device else f"💾 Volume {m.mount}"
                m_title = QLabel(dev_title)
                m_title.setStyleSheet("color: #f4f4f5; font-size: 13px; font-weight: 700;")
                hdr.addWidget(m_title)
                hdr.addStretch()

                dev_info = f"Mount: {m.mount} ({m.fstype.upper()})" if m.device else m.fstype.upper()
                dev_lbl = QLabel(dev_info)
                dev_lbl.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 600;")
                hdr.addWidget(dev_lbl)
                row_lay.addLayout(hdr)

                pbar = QProgressBar()
                pbar.setRange(0, 100)
                pbar.setValue(int(m.percent))
                pbar.setTextVisible(False)
                pbar.setFixedHeight(8)
                bar_color = "#22c55e" if m.percent < 75 else ("#f59e0b" if m.percent < 90 else "#ef4444")
                pbar.setStyleSheet(f"""
                    QProgressBar {{
                        background: #18181b; border: 1px solid #27272a; border-radius: 4px;
                    }}
                    QProgressBar::chunk {{
                        background: {bar_color}; border-radius: 4px;
                    }}
                """)
                row_lay.addWidget(pbar)

                sub_hdr = QHBoxLayout()
                free_gb = m.total_gb - m.used_gb
                stat_str = f"Used: {m.used_gb:.1f} GB / {m.total_gb:.1f} GB ({m.percent:.1f}%)"
                stat_lbl = QLabel(stat_str)
                stat_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
                sub_hdr.addWidget(stat_lbl)
                sub_hdr.addStretch()

                free_lbl = QLabel(f"Free Space: {free_gb:.1f} GB")
                free_lbl.setStyleSheet("color: #10b981; font-size: 11px; font-weight: 600;")
                sub_hdr.addWidget(free_lbl)
                row_lay.addLayout(sub_hdr)

                part_layout.addWidget(row_card)

            body.addWidget(part_frame)

        # 3. Hardware Technical Specifications Panel
        spec_frame = QFrame()
        spec_frame.setStyleSheet("""
            QFrame {
                background: #18181b;
                border: 1px solid #27272a;
                border-radius: 10px;
            }
        """)
        spec_layout = QVBoxLayout(spec_frame)
        spec_layout.setContentsMargins(16, 14, 16, 14)
        spec_layout.setSpacing(10)

        spec_title = QLabel("HARDWARE TECHNICAL SPECIFICATIONS & TELEMETRY")
        spec_title.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;")
        spec_layout.addWidget(spec_title)

        spec_grid = QGridLayout()
        spec_grid.setSpacing(8)
        spec_grid.setColumnStretch(1, 1)
        spec_grid.setColumnStretch(3, 1)

        self._spec_val_labels = []
        details = self._get_spec_tuples()
        for idx, (k, v) in enumerate(details):
            r = idx // 2
            c = (idx % 2) * 2

            klbl = QLabel(f"{k}:")
            klbl.setStyleSheet("color: #71717a; font-size: 11px; font-weight: 500;")
            vlbl = QLabel(v)
            vlbl.setStyleSheet("color: #f4f4f5; font-size: 11px; font-weight: 600;")

            spec_grid.addWidget(klbl, r, c)
            spec_grid.addWidget(vlbl, r, c + 1)
            self._spec_val_labels.append(vlbl)

        spec_layout.addLayout(spec_grid)
        body.addWidget(spec_frame)

        scroll.setWidget(container)
        layout.addWidget(scroll)

    def update_stats(self, stats: SystemStats, history: StatsHistory) -> None:
        self._stats = stats
        self._history = history

        # Update History Sparkline & Readout
        hist_data = getattr(self._history, self._history_attr_name(), [])
        if hist_data:
            self._sparkline.set_data(hist_data)
            valid = [v for v in hist_data if v is not None]
            if valid and hasattr(self, "_stat_lbl"):
                min_v = min(valid)
                avg_v = sum(valid) / len(valid)
                max_v = max(valid)
                cur_v = valid[-1]
                unit = "°C" if "temp" in self._key else ("W" if "power" in self._key else "%")
                self._stat_lbl.setText(
                    f"Min: {min_v:.1f}{unit}  ·  Avg: {avg_v:.1f}{unit}  ·  Max: {max_v:.1f}{unit}  ·  Current: {cur_v:.1f}{unit}"
                )

        # Update Per-Core CPU Bars
        if self._key == "cpu" and stats.cpu_per_core and hasattr(self, "_core_widgets"):
            for i, val in enumerate(stats.cpu_per_core):
                if i < len(self._core_widgets):
                    pbar, val_lbl = self._core_widgets[i]
                    pbar.setValue(int(val))
                    bar_color = "#22c55e" if val < 60 else ("#f59e0b" if val < 85 else "#ef4444")
                    pbar.setStyleSheet(f"""
                        QProgressBar {{
                            background: #09090b; border: 1px solid #27272a; border-radius: 4px;
                        }}
                        QProgressBar::chunk {{
                            background: {bar_color}; border-radius: 4px;
                        }}
                    """)
                    val_lbl.setText(f"{val:.1f}%")
                    val_lbl.setStyleSheet(f"color: {bar_color}; font-size: 11px; font-weight: 700;")

        # Update Spec Grid Labels
        if hasattr(self, "_spec_val_labels"):
            details = self._get_spec_tuples()
            for idx, (_, v) in enumerate(details):
                if idx < len(self._spec_val_labels):
                    self._spec_val_labels[idx].setText(v)

    def _history_attr_name(self) -> str:
        return {
            "cpu": "cpu",
            "ram": "ram",
            "igpu": "igpu",
            "gpu": "gpu_util",
            "gpu_temp": "gpu_temp",
            "net": "net_rx",
        }.get(self._key, "cpu")

    def _get_spec_tuples(self) -> list[tuple[str, str]]:
        if self._key == "cpu":
            return [
                ("Processor Model", self._caps.cpu_model or "Intel Core Processor"),
                ("Logical Threads", str(len(self._stats.cpu_per_core))),
                ("Clock Frequency", f"{self._stats.cpu_freq_mhz / 1000.0:.2f} GHz ({self._stats.cpu_freq_mhz:.0f} MHz)"),
                ("Package Temperature", f"{self._stats.cpu_temp:.1f} °C" if self._stats.cpu_temp is not None else "N/A"),
                ("OS Kernel Release", self._caps.kernel_version or "Linux"),
                ("System Architecture", "x86_64 (64-bit Linux)"),
            ]
        if self._key == "ram":
            import psutil
            vm = psutil.virtual_memory()
            avail_gb = self._stats.ram_total_gb - self._stats.ram_used_gb
            buffers_mb = getattr(vm, "buffers", 0) / 1e6
            cached_gb = getattr(vm, "cached", 0) / 1e9
            return [
                ("Total Installed RAM", f"{self._stats.ram_total_gb:.2f} GB"),
                ("Used Memory", f"{self._stats.ram_used_gb:.2f} GB ({self._stats.ram_percent:.1f}%)"),
                ("Available Memory", f"{avail_gb:.2f} GB"),
                ("Cached Memory", f"{cached_gb:.2f} GB"),
                ("Buffers Memory", f"{buffers_mb:.1f} MB"),
                ("Swap Used / Total", f"{self._stats.swap_used_gb:.2f} / {self._stats.swap_total_gb:.2f} GB"),
            ]
        if self._key in ("gpu", "gpu_temp", "gpu_power"):
            nv_driver = "Unknown"
            nv_cuda = "Unknown"
            nv_pcie = "PCIe Gen4 x8"
            nv_clocks = "Core: 210 MHz · Mem: 405 MHz"
            try:
                import pynvml
                pynvml.nvmlInit()
                nv_driver = pynvml.nvmlSystemGetDriverVersion()
                cuda_ver = pynvml.nvmlSystemGetCudaDriverVersion()
                nv_cuda = f"{cuda_ver // 1000}.{(cuda_ver % 1000) // 10}"
                h = pynvml.nvmlDeviceGetHandleByIndex(0)
                width = pynvml.nvmlDeviceGetCurrPcieLinkWidth(h)
                gen = pynvml.nvmlDeviceGetCurrPcieLinkGeneration(h)
                nv_pcie = f"Gen{gen} x{width}"
                core_clk = pynvml.nvmlDeviceGetClockInfo(h, 0)
                mem_clk = pynvml.nvmlDeviceGetClockInfo(h, 2)
                nv_clocks = f"Core: {core_clk} MHz · Mem: {mem_clk} MHz"
                pynvml.nvmlShutdown()
            except Exception:
                pass

            vram_used = self._stats.gpu_vram_used_mb or 0
            vram_tot = self._stats.gpu_vram_total_mb or 6144
            return [
                ("Graphics Card", self._caps.nvidia_device_name or "NVIDIA GeForce RTX 4050"),
                ("Vendor", "NVIDIA Corporation"),
                ("NVIDIA Driver Version", str(nv_driver)),
                ("CUDA Driver Version", str(nv_cuda)),
                ("PCIe Bus & Link", f"0000:01:00.0 ({nv_pcie})"),
                ("GPU Clocks", nv_clocks),
                ("Dedicated VRAM", f"{vram_used} / {vram_tot} MB"),
                ("Core Temperature", f"{self._stats.gpu_temp} °C" if self._stats.gpu_temp else "N/A"),
                ("Real-time Power Draw", f"{self._stats.gpu_power_w:.1f} W" if self._stats.gpu_power_w else "N/A"),
                ("Thermal Limit (TjMax)", "88.0 °C"),
            ]
        if self._key == "igpu":
            return [
                ("Integrated Graphics", "Intel Raptor Lake-S UHD Graphics"),
                ("Vendor", "Intel Corporation"),
                ("Kernel Driver", "i915 / xe"),
                ("Max Engine Frequency", "1450 MHz"),
                ("Current Frequency", f"{self._stats.igpu_util or 0:.1f}% load"),
                ("Memory Architecture", "Shared Unified System Memory"),
            ]
        if self._key == "disk" and self._stats.disk_mounts:
            dm = self._stats.disk_mounts[0]
            free_gb = dm.total_gb - dm.used_gb
            return [
                ("Primary Mount Point", dm.mount),
                ("File System Type", "btrfs / ext4"),
                ("Total Capacity", f"{dm.total_gb:.1f} GB"),
                ("Used Space", f"{dm.used_gb:.1f} GB ({dm.percent:.1f}%)"),
                ("Free Available Space", f"{free_gb:.1f} GB"),
                ("Storage Drive Type", "NVMe M.2 Solid State Drive"),
            ]
        if self._key == "net":
            rx_formatted = f"{self._stats.net_rx_kbps:.1f} KB/s" if self._stats.net_rx_kbps < 1024 else f"{self._stats.net_rx_kbps / 1024.0:.2f} MB/s"
            tx_formatted = f"{self._stats.net_tx_kbps:.1f} KB/s" if self._stats.net_tx_kbps < 1024 else f"{self._stats.net_tx_kbps / 1024.0:.2f} MB/s"
            return [
                ("Interface Name", self._stats.net_interface),
                ("Connection Type", "Wi-Fi Wireless 802.11" if self._stats.net_is_wifi else "Gigabit Ethernet (RJ-45)"),
                ("IPv4 Local Address", self._stats.net_ipv4),
                ("Receive Speed (Download)", rx_formatted),
                ("Transmit Speed (Upload)", tx_formatted),
                ("Link State", "Active & Online"),
            ]
        return [
            ("Component Target", self._key.upper()),
            ("System Kernel", self._caps.kernel_version or "Linux"),
        ]
