"""
Phase 0 — Hardware Discovery
=============================
Probes the running system for available kernel modules, hwmon sysfs nodes,
installed backend tools, and D-Bus services. Produces a ``Capabilities``
dataclass that gates every hardware-specific feature in the application.

Runs in ~100 ms at startup. Results are cached in memory for the session;
use ``discover(force=True)`` to re-probe.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Capabilities:
    # --- Fan ---
    fan_module: str | None = None          # "legion_laptop" | "lenovo_wmi_fan" | None
    fan_hwmon_path: Path | None = None     # /sys/class/hwmon/hwmonN
    fan_curve_readable: bool = False
    fan_curve_writable: bool = False
    fan_rpm_readable: bool = False

    # --- Power profiles ---
    power_profiles_available: bool = False
    power_profiles_profiles: list[str] = field(default_factory=list)

    # --- GPU ---
    nvidia_available: bool = False
    nvidia_device_name: str | None = None
    intel_gpu_top_available: bool = False

    # --- GPU switcher ---
    envycontrol_available: bool = False
    supergfxctl_available: bool = False
    gpu_switcher: str | None = None        # "envycontrol" | "supergfxctl" | None

    # --- System ---
    kernel_version: str = ""
    cpu_model: str = ""

    # --- Helper ---
    helper_installed: bool = False

    def gpu_switch_supported(self) -> bool:
        return self.gpu_switcher is not None

    def fan_control_supported(self) -> bool:
        return self.fan_curve_writable

    def fan_monitoring_supported(self) -> bool:
        return self.fan_rpm_readable

    def summary(self) -> str:
        lines = [
            "=== LOQ Control Center — Capability Matrix ===",
            f"  Kernel          : {self.kernel_version}",
            f"  CPU             : {self.cpu_model}",
            "",
            f"  Fan module      : {self.fan_module or 'NOT DETECTED'}",
            f"  Fan hwmon path  : {self.fan_hwmon_path or 'N/A'}",
            f"  Fan RPM read    : {'YES' if self.fan_rpm_readable else 'NO'}",
            f"  Fan curve read  : {'YES' if self.fan_curve_readable else 'NO'}",
            f"  Fan curve write : {'YES (control enabled)' if self.fan_curve_writable else 'NO (monitoring only)'}",
            "",
            f"  Power profiles  : {'YES' if self.power_profiles_available else 'NO'}",
            f"  Profiles        : {', '.join(self.power_profiles_profiles) or 'N/A'}",
            "",
            f"  NVIDIA (NVML)   : {'YES — ' + (self.nvidia_device_name or '') if self.nvidia_available else 'NO'}",
            f"  intel_gpu_top   : {'YES' if self.intel_gpu_top_available else 'NO'}",
            "",
            f"  GPU switcher    : {self.gpu_switcher or 'NOT DETECTED'}",
            f"  envycontrol     : {'YES' if self.envycontrol_available else 'NO'}",
            f"  supergfxctl     : {'YES' if self.supergfxctl_available else 'NO'}",
            "",
            f"  Priv helper     : {'INSTALLED' if self.helper_installed else 'NOT INSTALLED (install.sh needed)'}",
            "==============================================",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal probes
# ---------------------------------------------------------------------------

_KNOWN_FAN_MODULE_NAMES = [
    "legion_laptop",
    "lenovo_wmi_fan",
    "lenovo_wmi_other",
    "ideapad_laptop",
]

_HELPER_PATH = Path("/usr/local/bin/loq-helper")


def _probe_fan(caps: Capabilities) -> None:
    """Detect hwmon path for Legion fan control."""
    # Check which module is loaded
    try:
        result = subprocess.run(
            ["lsmod"], capture_output=True, text=True, timeout=3
        )
        loaded = result.stdout
        for name in _KNOWN_FAN_MODULE_NAMES:
            if name in loaded:
                caps.fan_module = name
                break
    except Exception as exc:
        log.warning("lsmod failed: %s", exc)

    # Scan hwmon entries for known Legion driver names
    for hwmon_path in glob.glob("/sys/class/hwmon/hwmon*"):
        name_file = Path(hwmon_path) / "name"
        try:
            name = name_file.read_text().strip()
        except OSError:
            continue

        if name in ("legion_laptop", "lenovo_wmi_fan", "lenovo_wmi_other", "ideapad"):
            caps.fan_hwmon_path = Path(hwmon_path)
            log.info("Fan hwmon found: %s (driver: %s)", hwmon_path, name)
            break

    if caps.fan_hwmon_path is None:
        log.info("No Legion fan hwmon node found.")
        return

    hwmon = caps.fan_hwmon_path

    # Check RPM readability
    fan_input = hwmon / "fan1_input"
    if fan_input.exists():
        try:
            val = int(fan_input.read_text().strip())
            caps.fan_rpm_readable = True
            log.info("fan1_input readable, value=%d RPM", val)
        except (OSError, ValueError):
            pass

    # Check curve readability (pwm1_auto_point1_pwm)
    curve_pwm = hwmon / "pwm1_auto_point1_pwm"
    if curve_pwm.exists():
        try:
            curve_pwm.read_text()
            caps.fan_curve_readable = True
            log.info("Fan curve node readable.")
        except OSError:
            pass

    # Check curve writability — open in write mode without actually writing
    if caps.fan_curve_readable:
        try:
            fd = os.open(str(curve_pwm), os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
            caps.fan_curve_writable = True
            log.info("Fan curve node is writable (control enabled).")
        except OSError as exc:
            log.info("Fan curve not writable (%s) — monitoring only.", exc)


def _probe_power_profiles(caps: Capabilities) -> None:
    """Check power-profiles-daemon availability via powerprofilesctl."""
    if shutil.which("powerprofilesctl") is None:
        log.info("powerprofilesctl not found.")
        return
    try:
        result = subprocess.run(
            ["powerprofilesctl", "list"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            caps.power_profiles_available = True
            profiles = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.endswith(":"):
                    profiles.append(line.rstrip(":").lstrip("*").strip())
            caps.power_profiles_profiles = profiles or ["power-saver", "balanced", "performance"]
            log.info("Power profiles available: %s", caps.power_profiles_profiles)
    except Exception as exc:
        log.warning("powerprofilesctl probe failed: %s", exc)


def _probe_nvidia(caps: Capabilities) -> None:
    """Try to initialize NVML and get device info."""
    try:
        import pynvml  # nvidia-ml-py exposes as pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        if count > 0:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            caps.nvidia_available = True
            caps.nvidia_device_name = name if isinstance(name, str) else name.decode()
            log.info("NVIDIA NVML: found %s", caps.nvidia_device_name)
        pynvml.nvmlShutdown()
    except Exception as exc:
        log.info("NVIDIA NVML not available: %s", exc)


def _probe_intel_gpu_top(caps: Capabilities) -> None:
    if shutil.which("intel_gpu_top"):
        caps.intel_gpu_top_available = True
        log.info("intel_gpu_top found.")


def _probe_gpu_switcher(caps: Capabilities) -> None:
    if shutil.which("envycontrol"):
        caps.envycontrol_available = True
        caps.gpu_switcher = "envycontrol"
        log.info("GPU switcher: envycontrol")
    elif shutil.which("supergfxctl"):
        caps.supergfxctl_available = True
        caps.gpu_switcher = "supergfxctl"
        log.info("GPU switcher: supergfxctl (deprecated fallback)")


def _probe_system(caps: Capabilities) -> None:
    uname = platform.uname()
    caps.kernel_version = uname.release
    # Read CPU model from /proc/cpuinfo
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                caps.cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        caps.cpu_model = uname.processor or "Unknown"


def _probe_helper(caps: Capabilities) -> None:
    caps.helper_installed = _HELPER_PATH.is_file()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_cached: Capabilities | None = None


def discover(force: bool = False) -> Capabilities:
    """
    Run all hardware probes and return a ``Capabilities`` instance.
    Results are cached in-memory after the first call.
    Pass ``force=True`` to re-probe.
    """
    global _cached
    if _cached is not None and not force:
        return _cached

    caps = Capabilities()
    log.info("Starting hardware discovery…")

    _probe_system(caps)
    _probe_fan(caps)
    _probe_power_profiles(caps)
    _probe_nvidia(caps)
    _probe_intel_gpu_top(caps)
    _probe_gpu_switcher(caps)
    _probe_helper(caps)

    log.info("Discovery complete.")
    _cached = caps
    return caps


def save_capabilities(caps: Capabilities, path: Path) -> None:
    """Serialize capabilities to JSON for debugging."""
    data = asdict(caps)
    # Convert Path objects to strings
    if data.get("fan_hwmon_path"):
        data["fan_hwmon_path"] = str(data["fan_hwmon_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    caps = discover()
    print(caps.summary())
