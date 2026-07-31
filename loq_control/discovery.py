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
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Capabilities:
    # --- Fan (monitoring only on LOQ — no hwmon exposure) ---
    fan_module: str | None = None          # "legion_laptop" | "lenovo_wmi_fan" | None
    fan_hwmon_path: Path | None = None     # /sys/class/hwmon/hwmonN
    fan_curve_readable: bool = False
    fan_curve_writable: bool = False
    fan_rpm_readable: bool = False

    # --- Power profiles ---
    power_profiles_available: bool = False
    power_profiles_profiles: list[str] = field(default_factory=list)

    # --- Battery Conservation Mode (Charge Limit) ---
    battery_conservation_available: bool = False
    battery_conservation_enabled: bool = False

    # --- Power limits (WMI firmware-attributes) ---
    power_limits_available: bool = False
    power_limits_writable: bool = False
    power_limits_base_path: Path | None = None  # path to firmware-attributes or legion sysfs dir
    power_limit_attrs: dict[str, Path] = field(default_factory=dict)  # attr_name -> sysfs path

    # --- GPU ---
    nvidia_available: bool = False
    nvidia_device_name: str | None = None
    intel_gpu_top_available: bool = False
    intel_gpu_available: bool = False

    # --- GPU switcher ---
    envycontrol_available: bool = False
    supergfxctl_available: bool = False
    gpu_switcher: str | None = None        # "envycontrol" | "supergfxctl" | None

    # --- Keyboard RGB (ITE HID) ---
    keyboard_rgb_available: bool = False
    keyboard_hid_path: str | None = None   # hidraw or hidapi path
    keyboard_vid: int = 0x048d
    keyboard_pid: int = 0xc993

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
        attrs_str = ", ".join(self.power_limit_attrs.keys()) if self.power_limit_attrs else "none"
        lines = [
            "=== LOQ Control Center — Capability Matrix ===",
            f"  Kernel          : {self.kernel_version}",
            f"  CPU             : {self.cpu_model}",
            "",
            f"  Fan module      : {self.fan_module or 'NOT DETECTED'}",
            f"  Fan hwmon path  : {self.fan_hwmon_path or 'N/A'}",
            f"  Fan RPM read    : {'YES' if self.fan_rpm_readable else 'NO'}",
            f"  Fan curve write : {'YES (control enabled)' if self.fan_curve_writable else 'NO (not exposed on this hardware)'}",
            "",
            f"  Power limits    : {'YES — ' + attrs_str if self.power_limits_available else 'NO'}",
            f"  Limits writable : {'YES' if self.power_limits_writable else 'NO'}",
            f"  Limits base     : {self.power_limits_base_path or 'N/A'}",
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
            f"  Keyboard RGB    : {'YES — ' + (self.keyboard_hid_path or '') if self.keyboard_rgb_available else 'NO (udev rule or hid module needed)'}",
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


def _probe_battery_conservation(caps: Capabilities) -> None:
    """Probe for Lenovo battery conservation mode / charge capping node."""
    candidates = [
        Path("/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode"),
        Path("/sys/devices/platform/ideapad_laptop/conservation_mode"),
        Path("/sys/bus/platform/devices/ideapad_laptop/conservation_mode"),
        Path("/sys/class/power_supply/BAT0/charge_control_end_threshold"),
        Path("/sys/class/power_supply/BAT1/charge_control_end_threshold"),
    ]
    for c in candidates:
        if c.exists():
            caps.battery_conservation_available = True
            try:
                val = c.read_text().strip()
                if "charge_control_end_threshold" in str(c):
                    caps.battery_conservation_enabled = (val == "80")
                else:
                    caps.battery_conservation_enabled = (val == "1")
                log.info("Battery conservation mode found at %s (enabled=%s)", c, caps.battery_conservation_enabled)
            except OSError:
                pass
            break


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
        caps.intel_gpu_available = True
        log.info("intel_gpu_top found.")

    for card_dir in glob.glob("/sys/class/drm/card*"):
        p = Path(card_dir)
        if (p / "gt_act_freq_mhz").exists() or (p / "gt/gt0/rps_act_freq_mhz").exists() or (p / "gt_cur_freq_mhz").exists():
            caps.intel_gpu_available = True
            log.info("Intel iGPU sysfs frequency node found at %s", card_dir)
            break


# Power limit attribute names to look for (in order of preference)
_POWER_LIMIT_ATTR_NAMES = [
    # WMI firmware-attributes names (Lenovo LOQ / Legion 2024+)
    "ppt_pl1_spl",
    "ppt_pl2_sppt",
    "ppt_pl1_tau",
    "ppt_cpu_cl",
    "gpu_nv_ctgp",
    "gpu_nv_ppab",
    "gpu_nv_ac_offset",
    "cpu_temp",
    "gpu_temp",
    # Legion-laptop sysfs (upstream or DKMS module)
    "cpu_longterm_powerlimit",
    "cpu_shortterm_powerlimit",
    "cpu_peak_powerlimit",
    "cpu_cross_loading_powerlimit",
    "cpu_apu_spl",
    "gpu_ctgp_powerlimit",
    "gpu_ppab_powerlimit",
    "gpu_ac_offset_powerlimit",
    "CPULongTermPowerLimit",
    "CPUShortTermPowerLimit",
    "CPUPeakPowerLimit",
    "CPUCrossLoadingPowerLimit",
    "cTGP",
    "PPAB",
    "ACOffset",
]

# Base sysfs path patterns to search
_POWER_LIMIT_BASE_PATTERNS = [
    # firmware-attributes class
    "/sys/class/firmware-attributes/*/attributes",
    # legion-laptop DKMS / upstream
    "/sys/module/legion_laptop/drivers/platform:legion/legion",
    "/sys/module/legion_laptop/drivers/platform:legion/PNP0C09:00",
    # ideapad / WMI platform driver
    "/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00",
    # WMI other
    "/sys/bus/wmi/drivers/lenovo-wmi-other/*/*",
    "/sys/bus/wmi/drivers/lenovo-wmi-gamezone/*/*",
]


def _probe_power_limits(caps: Capabilities) -> None:
    """Detect WMI firmware-attributes or legion-laptop power limit sysfs nodes."""
    found_attrs: dict[str, Path] = {}
    base_found: Path | None = None

    for pattern in _POWER_LIMIT_BASE_PATTERNS:
        for base_str in glob.glob(pattern):
            base = Path(base_str)
            for attr_name in _POWER_LIMIT_ATTR_NAMES:
                attr_dir_or_file = base / attr_name
                target_file: Path | None = None

                if (attr_dir_or_file / "current_value").is_file():
                    target_file = attr_dir_or_file / "current_value"
                elif attr_dir_or_file.is_file():
                    target_file = attr_dir_or_file

                if target_file is not None:
                    try:
                        target_file.read_text()  # verify readable
                        found_attrs[attr_name] = target_file
                        if base_found is None:
                            base_found = base
                    except OSError:
                        pass

    if not found_attrs:
        log.info("No power limit sysfs attributes found.")
        return

    caps.power_limits_available = True
    caps.power_limits_base_path = base_found
    caps.power_limit_attrs = found_attrs
    log.info("Power limit attrs found: %s", list(found_attrs.keys()))

    # WMI firmware-attributes on LOQ BIOS return EBUSY on dynamic writes
    # Keep writable = False so UI presents a clean read-only monitoring dashboard
    caps.power_limits_writable = False
    log.info("Power limits probed in read-only monitoring mode.")


# ITE keyboard USB device identifiers
_ITE_VID = 0x048d
_ITE_KEYBOARD_PIDS = [0xc993, 0xc994, 0xc995, 0xc996, 0xc997, 0x6004, 0x6006, 0x6007]


def _probe_keyboard_rgb(caps: Capabilities) -> None:
    """Detect ITE keyboard HID device via hidapi or /dev/hidraw."""
    # Try hidapi enumerate
    try:
        import hid
        for pid in _ITE_KEYBOARD_PIDS:
            devices = hid.enumerate(_ITE_VID, pid)
            if devices:
                target_dev = None
                for d in devices:
                    if d.get("interface_number") == 0 or b"hidraw0" in d.get("path", b""):
                        target_dev = d
                        break
                if target_dev is None and devices:
                    target_dev = devices[0]

                caps.keyboard_rgb_available = True
                caps.keyboard_vid = _ITE_VID
                caps.keyboard_pid = pid
                raw_path = target_dev.get("path", b"")
                caps.keyboard_hid_path = raw_path.decode(errors="replace") if isinstance(raw_path, bytes) else str(raw_path)
                log.info("ITE keyboard HID found: VID=%04x PID=%04x path=%s",
                         _ITE_VID, pid, caps.keyboard_hid_path)
                return
    except ImportError:
        log.info("'hid' module not available — keyboard RGB detection requires: pip install hid")
    except Exception as exc:
        log.warning("HID enumerate failed: %s", exc)

    # Fallback: scan /sys/bus/usb/devices for matching VID/PID
    for device_dir in glob.glob("/sys/bus/usb/devices/*"):
        idVendor_path = Path(device_dir) / "idVendor"
        idProduct_path = Path(device_dir) / "idProduct"
        try:
            vid = int(idVendor_path.read_text().strip(), 16)
            pid = int(idProduct_path.read_text().strip(), 16)
            if vid == _ITE_VID and pid in _ITE_KEYBOARD_PIDS:
                caps.keyboard_rgb_available = True
                caps.keyboard_vid = vid
                caps.keyboard_pid = pid
                caps.keyboard_hid_path = device_dir
                log.info("ITE keyboard found via USB sysfs: %s VID=%04x PID=%04x",
                         device_dir, vid, pid)
                return
        except (OSError, ValueError):
            pass


def _probe_gpu_switcher(caps: Capabilities) -> None:
    venv_envy = Path(sys.prefix) / "bin" / "envycontrol"
    if shutil.which("envycontrol") or venv_envy.exists():
        caps.envycontrol_available = True
        caps.gpu_switcher = "envycontrol"
        log.info("GPU switcher: envycontrol found.")
    elif shutil.which("supergfxctl"):
        caps.supergfxctl_available = True
        caps.gpu_switcher = "supergfxctl"
        log.info("GPU switcher: supergfxctl found.")


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
    _probe_battery_conservation(caps)
    _probe_power_limits(caps)
    _probe_nvidia(caps)
    _probe_intel_gpu_top(caps)
    _probe_gpu_switcher(caps)
    _probe_keyboard_rgb(caps)
    _probe_helper(caps)

    log.info("Discovery complete.")
    _cached = caps
    return caps


def _stringify_paths(obj: any) -> any:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _stringify_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_paths(v) for v in obj]
    return obj


def save_capabilities(caps: Capabilities, path: Path) -> None:
    """Serialize capabilities to JSON for debugging."""
    data = _stringify_paths(asdict(caps))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    caps = discover()
    print(caps.summary())
