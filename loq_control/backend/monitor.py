"""
Backend — System monitor polling thread.
=========================================
Runs in a QThread, emits StatsUpdate every <refresh_interval_ms> ms.
Gathers: CPU, RAM, Disk (psutil), NVIDIA dGPU (pynvml), Intel iGPU
(intel_gpu_top subprocess), and fan RPM (sysfs hwmon).
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

HISTORY_LEN = 120  # samples kept for sparklines


@dataclass
class DiskMount:
    mount: str
    used_gb: float
    total_gb: float
    percent: float


@dataclass
class SystemStats:
    # CPU
    cpu_percent: float = 0.0
    cpu_per_core: list[float] = field(default_factory=list)
    cpu_freq_mhz: float = 0.0

    # RAM
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_percent: float = 0.0
    swap_used_gb: float = 0.0
    swap_total_gb: float = 0.0

    # Disk
    disk_mounts: list[DiskMount] = field(default_factory=list)

    # NVIDIA dGPU
    gpu_util: int | None = None
    gpu_vram_used_mb: int | None = None
    gpu_vram_total_mb: int | None = None
    gpu_temp: int | None = None
    gpu_power_w: float | None = None
    gpu_fan_rpm: int | None = None

    # Intel iGPU
    igpu_util: float | None = None

    # Fans (from hwmon)
    fan1_rpm: int = 0
    fan2_rpm: int = 0

    # Timestamp
    timestamp: float = 0.0


@dataclass
class StatsHistory:
    """Ring-buffer history for each monitored metric."""
    cpu: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    ram: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    gpu_util: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    gpu_temp: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    igpu: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)

    def push(self, stats: SystemStats) -> None:
        self.cpu.append(stats.cpu_percent)
        self.cpu.pop(0)
        self.ram.append(stats.ram_percent)
        self.ram.pop(0)
        self.gpu_util.append(float(stats.gpu_util or 0))
        self.gpu_util.pop(0)
        self.gpu_temp.append(float(stats.gpu_temp or 0))
        self.gpu_temp.pop(0)
        self.igpu.append(stats.igpu_util or 0.0)
        self.igpu.pop(0)


# ---------------------------------------------------------------------------
# iGPU monitoring via intel_gpu_top
# ---------------------------------------------------------------------------

class _IntelGpuReader:
    """
    Manages a long-running intel_gpu_top -J subprocess and parses its
    streaming JSON output. Gracefully degrades if not available.
    """

    def __init__(self, available: bool) -> None:
        self._available = available
        self._proc: subprocess.Popen | None = None
        self._last_util: float | None = None

    def start(self) -> None:
        if not self._available:
            return
        try:
            self._proc = subprocess.Popen(
                ["intel_gpu_top", "-J", "-s", "950"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            log.info("intel_gpu_top subprocess started (PID %d).", self._proc.pid)
        except FileNotFoundError:
            log.warning("intel_gpu_top not found; iGPU monitoring disabled.")
            self._available = False

    def read_util(self) -> float | None:
        """Non-blocking read of the latest render engine utilization."""
        if self._proc is None or self._proc.poll() is not None:
            return None
        try:
            line = self._proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                return self._last_util
            line = line.strip().lstrip(",").lstrip("[").rstrip("]")
            if not line or line in ("{", "}"):
                return self._last_util
            obj = json.loads(line)
            engines = obj.get("engines", {})
            # Prefer "Render/3D" then "Render/3D/0"
            for key in ("Render/3D", "Render/3D/0", "render", "Render"):
                if key in engines:
                    val = engines[key].get("busy", 0.0)
                    self._last_util = float(val)
                    return self._last_util
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
        return self._last_util

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


# ---------------------------------------------------------------------------
# Fan sysfs reader
# ---------------------------------------------------------------------------

def _read_fan_rpms(hwmon_path: Path | None) -> tuple[int, int]:
    if hwmon_path is None:
        return 0, 0

    def _read(name: str) -> int:
        try:
            return int((hwmon_path / name).read_text().strip())
        except (OSError, ValueError):
            return 0

    return _read("fan1_input"), _read("fan2_input")


# ---------------------------------------------------------------------------
# NVIDIA reader
# ---------------------------------------------------------------------------

class _NvidiaReader:
    def __init__(self, available: bool) -> None:
        self._available = available
        self._handle = None

    def start(self) -> None:
        if not self._available:
            return
        try:
            import pynvml
            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception as exc:
            log.warning("NVML init failed: %s", exc)
            self._available = False

    def read(self) -> tuple[int | None, int | None, int | None, int | None, float | None, int | None]:
        """Returns (util%, vram_used_mb, vram_total_mb, temp_c, power_w, fan_rpm)."""
        if not self._available or self._handle is None:
            return None, None, None, None, None, None
        try:
            import pynvml
            util = pynvml.nvmlDeviceGetUtilizationRates(self._handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            temp = pynvml.nvmlDeviceGetTemperature(self._handle, pynvml.NVML_TEMPERATURE_GPU)
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(self._handle) / 1000.0
            except pynvml.NVMLError:
                power = None
            try:
                fan_speed = pynvml.nvmlDeviceGetFanSpeed(self._handle)
                # Note: this is % not RPM; label accordingly upstream
                fan_rpm = fan_speed  # Store as % since NVML reports fan %
            except pynvml.NVMLError:
                fan_rpm = None
            return (
                util.gpu,
                mem.used // (1024 * 1024),
                mem.total // (1024 * 1024),
                temp,
                power,
                fan_rpm,
            )
        except Exception as exc:
            log.debug("NVML read error: %s", exc)
            return None, None, None, None, None, None

    def stop(self) -> None:
        if self._available:
            try:
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Monitor QThread
# ---------------------------------------------------------------------------

class MonitorThread(QThread):
    """
    Background polling thread that emits stats_updated on every tick.
    Connect to stats_updated(SystemStats) in the GUI.
    """

    stats_updated = Signal(object)  # SystemStats

    def __init__(
        self,
        caps: "Capabilities",
        refresh_ms: int = 1000,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._caps = caps
        self._refresh_ms = refresh_ms
        self._running = False

        self._nvidia = _NvidiaReader(caps.nvidia_available)
        self._igpu = _IntelGpuReader(caps.intel_gpu_top_available)

        # Tracked history
        self.history = StatsHistory()

    # --- Public API ---

    def set_refresh_interval(self, ms: int) -> None:
        self._refresh_ms = max(250, ms)

    def stop_monitoring(self) -> None:
        self._running = False

    # --- QThread ---

    def run(self) -> None:
        self._running = True
        self._nvidia.start()
        self._igpu.start()

        # Prime psutil cpu_percent (first call returns 0)
        psutil.cpu_percent(interval=None, percpu=True)
        time.sleep(0.1)

        while self._running:
            stats = self._collect()
            self.history.push(stats)
            self.stats_updated.emit(stats)
            # Sleep in small increments to respond quickly to stop()
            slept = 0
            interval = self._refresh_ms / 1000.0
            while slept < interval and self._running:
                time.sleep(0.1)
                slept += 0.1

        self._nvidia.stop()
        self._igpu.stop()
        log.info("MonitorThread stopped.")

    # --- Internal ---

    def _collect(self) -> SystemStats:
        stats = SystemStats(timestamp=time.time())

        # CPU
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        stats.cpu_per_core = per_core
        stats.cpu_percent = sum(per_core) / len(per_core) if per_core else 0.0
        freq = psutil.cpu_freq()
        stats.cpu_freq_mhz = freq.current if freq else 0.0

        # RAM
        mem = psutil.virtual_memory()
        stats.ram_used_gb = mem.used / 1e9
        stats.ram_total_gb = mem.total / 1e9
        stats.ram_percent = mem.percent
        swap = psutil.swap_memory()
        stats.swap_used_gb = swap.used / 1e9
        stats.swap_total_gb = swap.total / 1e9

        # Disk
        mounts = []
        for part in psutil.disk_partitions(all=False):
            if part.fstype in ("squashfs", "tmpfs", "devtmpfs", ""):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                mounts.append(DiskMount(
                    mount=part.mountpoint,
                    used_gb=usage.used / 1e9,
                    total_gb=usage.total / 1e9,
                    percent=usage.percent,
                ))
            except (PermissionError, OSError):
                pass
        stats.disk_mounts = mounts

        # NVIDIA
        (
            stats.gpu_util,
            stats.gpu_vram_used_mb,
            stats.gpu_vram_total_mb,
            stats.gpu_temp,
            stats.gpu_power_w,
            stats.gpu_fan_rpm,
        ) = self._nvidia.read()

        # Intel iGPU
        stats.igpu_util = self._igpu.read_util()

        # Fan RPM
        stats.fan1_rpm, stats.fan2_rpm = _read_fan_rpms(self._caps.fan_hwmon_path)

        return stats
