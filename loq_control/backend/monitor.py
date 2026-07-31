"""
Backend — System monitor polling thread.
=========================================
Runs in a QThread, emits StatsUpdate every <refresh_interval_ms> ms.
Gathers: CPU, RAM, Disk (psutil), NVIDIA dGPU (pynvml), Intel iGPU
(intel_gpu_top subprocess), and fan RPM (sysfs hwmon).
"""

from __future__ import annotations

import glob
import json
import logging
import shutil
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
    device: str = ""
    fstype: str = ""
    label: str = ""


@dataclass
class SystemStats:
    # CPU
    cpu_percent: float = 0.0
    cpu_per_core: list[float] = field(default_factory=list)
    cpu_freq_mhz: float = 0.0
    cpu_temp: float | None = None

    # RAM
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_percent: float = 0.0
    swap_used_gb: float = 0.0
    swap_total_gb: float = 0.0

    # Disk
    disk_mounts: list[DiskMount] = field(default_factory=list)
    disk_read_kbps: float = 0.0
    disk_write_kbps: float = 0.0
    disk_busy_percent: float = 0.0

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

    # Network
    net_rx_kbps: float = 0.0
    net_tx_kbps: float = 0.0
    net_interface: str = "wlan0"
    net_ipv4: str = "—"
    net_is_wifi: bool = True

    # Power Source
    power_plugged: bool | None = None
    battery_percent: float | None = None

    # Timestamp
    timestamp: float = 0.0


@dataclass
class StatsHistory:
    """Ring-buffer history for each monitored metric."""
    cpu: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    ram: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    gpu_util: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    gpu_temp: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    gpu_power: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    igpu: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    disk: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    net_rx: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)

    def push(self, stats: SystemStats) -> None:
        self.cpu.append(stats.cpu_percent)
        self.cpu.pop(0)
        self.ram.append(stats.ram_percent)
        self.ram.pop(0)
        self.gpu_util.append(float(stats.gpu_util or 0))
        self.gpu_util.pop(0)
        self.gpu_temp.append(float(stats.gpu_temp or 0))
        self.gpu_temp.pop(0)
        self.gpu_power.append(float(stats.gpu_power_w or 0))
        self.gpu_power.pop(0)
        self.igpu.append(stats.igpu_util or 0.0)
        self.igpu.pop(0)
        self.disk.append(stats.disk_busy_percent)
        self.disk.pop(0)
        self.net_rx.append(stats.net_rx_kbps)
        self.net_rx.pop(0)


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
        self._top_available = shutil.which("intel_gpu_top") is not None
        self._proc: subprocess.Popen | None = None
        self._last_util: float | None = None
        self._sysfs_paths = self._find_sysfs_paths()

    def _find_sysfs_paths(self) -> tuple[Path, Path | None, Path] | None:
        for card_dir in glob.glob("/sys/class/drm/card*"):
            p = Path(card_dir)
            act_f = p / "gt_act_freq_mhz"
            if not act_f.exists():
                act_f = p / "gt/gt0/rps_act_freq_mhz"
            if not act_f.exists():
                act_f = p / "gt_cur_freq_mhz"

            max_f = p / "gt_max_freq_mhz"
            if not max_f.exists():
                max_f = p / "gt/gt0/rps_max_freq_mhz"

            min_f = p / "gt_min_freq_mhz"
            if not min_f.exists():
                min_f = p / "gt/gt0/rps_min_freq_mhz"

            if act_f.exists() and max_f.exists():
                return act_f, min_f if min_f.exists() else None, max_f
        return None

    def start(self) -> None:
        if not self._available:
            return
        if self._top_available:
            try:
                self._proc = subprocess.Popen(
                    ["intel_gpu_top", "-J", "-s", "950"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                log.info("intel_gpu_top subprocess started (PID %d).", self._proc.pid)
            except FileNotFoundError:
                self._top_available = False

    def read_util(self) -> float | None:
        if self._top_available and self._proc and self._proc.poll() is None:
            try:
                line = self._proc.stdout.readline()
                if line:
                    line = line.strip().lstrip(",").lstrip("[").rstrip("]")
                    if line and line not in ("{", "}"):
                        obj = json.loads(line)
                        engines = obj.get("engines", {})
                        for key in ("Render/3D", "Render/3D/0", "render", "Render"):
                            if key in engines:
                                val = engines[key].get("busy", 0.0)
                                self._last_util = float(val)
                                return self._last_util
            except Exception:
                pass

        # Fallback to sysfs frequency scaling utilization
        if self._sysfs_paths:
            act_f, min_f, max_f = self._sysfs_paths
            try:
                act = float(act_f.read_text().strip())
                mx = float(max_f.read_text().strip())
                mn = float(min_f.read_text().strip()) if min_f and min_f.exists() else 0.0
                if mx > mn:
                    pct = max(0.0, min(100.0, ((act - mn) / (mx - mn)) * 100.0))
                else:
                    pct = 0.0
                self._last_util = pct
                return self._last_util
            except Exception:
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
# CPU & Fan sysfs readers
# ---------------------------------------------------------------------------

def _read_cpu_temp() -> float | None:
    try:
        temps = psutil.sensors_temperatures()
        if "coretemp" in temps and temps["coretemp"]:
            for item in temps["coretemp"]:
                if "Package" in item.label or item.label == "":
                    return item.current
            return temps["coretemp"][0].current
        if "cpu_thermal" in temps and temps["cpu_thermal"]:
            return temps["cpu_thermal"][0].current
        if "k10temp" in temps and temps["k10temp"]:
            return temps["k10temp"][0].current
    except Exception:
        pass

    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        p = Path(zone)
        type_f = p / "type"
        temp_f = p / "temp"
        if type_f.exists() and temp_f.exists():
            try:
                t_type = type_f.read_text().strip().lower()
                if t_type in ("x86_pkg_temp", "tcpu", "coretemp", "cpu_thermal"):
                    return float(temp_f.read_text().strip()) / 1000.0
            except Exception:
                pass
    return None


def _read_fan_rpms(hwmon_path: Path | None) -> tuple[int, int]:
    if hwmon_path is None:
        return 0, 0

    def _read(name: str) -> int:
        try:
            return int((hwmon_path / name).read_text().strip())
        except (OSError, ValueError):
            return 0

    return _read("fan1_input"), _read("fan2_input")


_partition_cache: tuple[float, list[DiskMount]] = (0.0, [])


def _read_all_partitions() -> list[DiskMount]:
    """Discover all physical disk partitions (Windows NTFS, Linux BTRFS/EXT4, EFI). Cached for 10s."""
    global _partition_cache
    now = time.time()
    last_time, cached_mounts = _partition_cache

    if cached_mounts and (now - last_time) < 10.0:
        return cached_mounts

    mounts = []
    seen = set()

    try:
        res = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,SIZE,FSTYPE,MOUNTPOINTS,LABEL,MODEL,TYPE"],
            capture_output=True, text=True, timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            for dev in data.get("blockdevices", []):
                children = dev.get("children", [dev])
                for child in children:
                    name = child.get("name", "")
                    fstype = child.get("fstype", "")
                    if not name or fstype in ("swap", "squashfs", "tmpfs", "devtmpfs", "overlay"):
                        continue
                    size_bytes = child.get("size") or 0
                    if size_bytes < 32 * 1024 * 1024 and not fstype:
                        continue

                    dev_path = f"/dev/{name}"
                    if dev_path in seen:
                        continue

                    fstype_str = fstype or "Partition"
                    label = child.get("label") or ""
                    mountpoints = [m for m in child.get("mountpoints", []) if m]

                    if "/" in mountpoints:
                        mount_path = "/"
                    elif mountpoints:
                        mount_path = mountpoints[0]
                    else:
                        mount_path = f"Unmounted ({label})" if label else "Unmounted"

                    total_gb = size_bytes / 1e9
                    used_gb = 0.0
                    percent = 0.0

                    if mountpoints:
                        for mp in mountpoints:
                            try:
                                usage = psutil.disk_usage(mp)
                                used_gb = usage.used / 1e9
                                total_gb = usage.total / 1e9
                                percent = usage.percent
                                break
                            except Exception:
                                pass

                    seen.add(dev_path)
                    mounts.append(DiskMount(
                        mount=mount_path,
                        used_gb=used_gb,
                        total_gb=total_gb,
                        percent=percent,
                        device=dev_path,
                        fstype=fstype_str,
                        label=label,
                    ))
            if mounts:
                _partition_cache = (now, mounts)
                return mounts
    except Exception:
        pass

    seen_devs = set()
    for part in psutil.disk_partitions(all=True):
        if part.fstype in ("squashfs", "tmpfs", "devtmpfs", "overlay", ""):
            continue
        if part.device in seen_devs:
            continue
        seen_devs.add(part.device)
        try:
            usage = psutil.disk_usage(part.mountpoint)
            mounts.append(DiskMount(
                mount=part.mountpoint,
                used_gb=usage.used / 1e9,
                total_gb=usage.total / 1e9,
                percent=usage.percent,
                device=part.device,
                fstype=part.fstype,
            ))
        except (PermissionError, OSError):
            pass
    _partition_cache = (now, mounts)
    return mounts


def _read_power_supply() -> tuple[bool | None, float | None]:
    """Returns (power_plugged, battery_percent)."""
    power_plugged = None
    battery_percent = None

    for ac_path in glob.glob("/sys/class/power_supply/*"):
        type_f = Path(ac_path) / "type"
        online_f = Path(ac_path) / "online"
        if type_f.exists() and online_f.exists():
            try:
                ps_type = type_f.read_text().strip().lower()
                if ps_type in ("mains", "ac"):
                    val = int(online_f.read_text().strip())
                    power_plugged = (val == 1)
                    break
            except Exception:
                pass

    for bat_path in glob.glob("/sys/class/power_supply/BAT*"):
        cap_f = Path(bat_path) / "capacity"
        if cap_f.exists():
            try:
                battery_percent = float(cap_f.read_text().strip())
                break
            except Exception:
                pass

    try:
        batt = psutil.sensors_battery()
        if batt is not None:
            if power_plugged is None:
                power_plugged = batt.power_plugged
            if battery_percent is None:
                battery_percent = batt.percent
    except Exception:
        pass

    return power_plugged, battery_percent


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
        stats.cpu_temp = _read_cpu_temp()

        # RAM
        mem = psutil.virtual_memory()
        stats.ram_used_gb = mem.used / 1e9
        stats.ram_total_gb = mem.total / 1e9
        stats.ram_percent = mem.percent
        swap = psutil.swap_memory()
        stats.swap_used_gb = swap.used / 1e9
        stats.swap_total_gb = swap.total / 1e9

        # Disk (Discover all physical partitions including Windows NTFS & Linux)
        stats.disk_mounts = _read_all_partitions()

        # Real-time Disk I/O Activity
        now = stats.timestamp
        try:
            io_counters = psutil.disk_io_counters()
            if io_counters and hasattr(self, "_last_disk_io"):
                dt = max(now - getattr(self, "_last_disk_time", now - 1.0), 0.1)
                last_io = self._last_disk_io
                r_bytes = max(0, io_counters.read_bytes - last_io.read_bytes)
                w_bytes = max(0, io_counters.write_bytes - last_io.write_bytes)
                io_time = max(0, (io_counters.read_time - last_io.read_time) + (io_counters.write_time - last_io.write_time))

                stats.disk_read_kbps = (r_bytes / 1024.0) / dt
                stats.disk_write_kbps = (w_bytes / 1024.0) / dt
                stats.disk_busy_percent = min(100.0, (io_time / (dt * 1000.0)) * 100.0)

            self._last_disk_io = io_counters
            self._last_disk_time = now
        except Exception:
            pass

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

        # Battery / AC Adapter
        stats.power_plugged, stats.battery_percent = _read_power_supply()

        # Network
        now = stats.timestamp
        try:
            import socket
            net_stats = psutil.net_if_stats()
            net_io = psutil.net_io_counters(pernic=True)
            net_addrs = psutil.net_if_addrs()

            active_iface = None
            for iface, st in net_stats.items():
                if iface == "lo" or not st.isup:
                    continue
                active_iface = iface
                if any(w in iface for w in ("wlan", "wlp", "wifi")):
                    break

            if active_iface and active_iface in net_io:
                io = net_io[active_iface]
                dt = max(now - getattr(self, "_last_net_time", now - 1.0), 0.1)
                last_rx = getattr(self, "_last_net_rx", io.bytes_recv)
                last_tx = getattr(self, "_last_net_tx", io.bytes_sent)

                stats.net_rx_kbps = max((io.bytes_recv - last_rx) / dt / 1024.0, 0.0)
                stats.net_tx_kbps = max((io.bytes_sent - last_tx) / dt / 1024.0, 0.0)
                stats.net_interface = active_iface
                stats.net_is_wifi = any(w in active_iface for w in ("wlan", "wlp", "wifi"))

                if active_iface in net_addrs:
                    for a in net_addrs[active_iface]:
                        if a.family == socket.AF_INET:
                            stats.net_ipv4 = a.address
                            break

                self._last_net_time = now
                self._last_net_rx = io.bytes_recv
                self._last_net_tx = io.bytes_sent
        except Exception:
            pass

        # Fan RPM
        stats.fan1_rpm, stats.fan2_rpm = _read_fan_rpms(self._caps.fan_hwmon_path)

        return stats
