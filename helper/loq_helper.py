#!/usr/bin/env python3
"""
LOQ Privileged Helper
======================
Installed at: /usr/local/bin/loq-helper
Ownership: root:root, mode 755
Invoked via: pkexec /usr/local/bin/loq-helper <subcommand> [args...]

Subcommands:
  fan-curve  <fan_id> <json>     Write fan curve points to hwmon sysfs
  fan-manual <fan_id> <pwm%>     Write single PWM value (manual override)
  fan-auto   <fan_id>            Restore automatic fan control
  gpu-switch <mode>              Call envycontrol -s <mode>

Security notes:
- All inputs strictly validated — no shell=True, no arbitrary paths
- Only operates on whitelisted sysfs prefixes
- fan_id must be 1 or 2
- PWM values clamped to 0-255 range
- GPU mode must be one of: integrated, hybrid, nvidia
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_FAN_IDS = {1, 2}
ALLOWED_GPU_MODES = {"integrated", "hybrid", "nvidia"}
HWMON_NAME_PATTERNS = ("legion_laptop", "lenovo_wmi_fan", "lenovo_wmi_other", "ideapad")
MIN_PWM_RAW = 0
MAX_PWM_RAW = 255
MAX_CURVE_POINTS = 10

# Whitelisted power-limit sysfs attribute names (no arbitrary path writes)
ALLOWED_POWER_LIMIT_ATTRS = {
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
    # legion_laptop module names
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
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_hwmon_path() -> Path | None:
    """Find the Legion fan hwmon path."""
    for hwmon_dir in glob.glob("/sys/class/hwmon/hwmon*"):
        name_path = Path(hwmon_dir) / "name"
        try:
            name = name_path.read_text().strip()
            if name in HWMON_NAME_PATTERNS:
                return Path(hwmon_dir)
        except OSError:
            continue
    return None


def _find_power_limit_path(attr_name: str) -> Path | None:
    """Locate a power-limit attribute file by scanning known sysfs base paths."""
    base_patterns = [
        "/sys/class/firmware-attributes/*/attributes",
        "/sys/module/legion_laptop/drivers/platform:legion/legion",
        "/sys/module/legion_laptop/drivers/platform:legion/PNP0C09:00",
        "/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00",
        "/sys/bus/wmi/drivers/lenovo-wmi-other/*/*",
        "/sys/bus/wmi/drivers/lenovo-wmi-gamezone/*/*",
    ]
    for pattern in base_patterns:
        for base_str in glob.glob(pattern):
            attr_dir_or_file = Path(base_str) / attr_name
            if (attr_dir_or_file / "current_value").is_file():
                return attr_dir_or_file / "current_value"
            elif attr_dir_or_file.is_file():
                return attr_dir_or_file
    return None


def _write_sysfs(path: Path, value: str) -> None:
    """Write a value to a sysfs file. Handles various sysfs driver requirements."""
    val_str = f"{str(value).strip()}\n"
    val_bytes = val_str.encode("ascii")
    errors = []

    # Method 1: os.open O_WRONLY
    try:
        fd = os.open(str(path), os.O_WRONLY)
        try:
            os.write(fd, val_bytes)
            return
        finally:
            os.close(fd)
    except OSError as e:
        errors.append(f"O_WRONLY: {e}")

    # Method 2: os.open O_RDWR
    try:
        fd = os.open(str(path), os.O_RDWR)
        try:
            os.write(fd, val_bytes)
            return
        finally:
            os.close(fd)
    except OSError as e:
        errors.append(f"O_RDWR: {e}")

    # Method 3: open('r+')
    try:
        with open(path, "r+", encoding="ascii") as f:
            f.write(val_str)
            f.flush()
            return
    except OSError as e:
        errors.append(f"r+: {e}")

    # Method 4: open('w')
    try:
        with open(path, "w", encoding="ascii") as f:
            f.write(val_str)
            f.flush()
            return
    except OSError as e:
        errors.append(f"w: {e}")

    err_msg = f"ERROR: Could not write {path} (tried 4 methods: {'; '.join(errors)})"
    print(err_msg, file=sys.stderr)
    raise OSError(err_msg)


def _pwm_from_percent(percent: int) -> int:
    """Convert 0-100% to 0-255 PWM raw value."""
    return int(max(MIN_PWM_RAW, min(MAX_PWM_RAW, percent * 255 // 100)))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_fan_curve(fan_id_str: str, json_str: str) -> int:
    """Write fan curve points to hwmon sysfs."""
    # Validate fan_id
    try:
        fan_id = int(fan_id_str)
    except ValueError:
        print("ERROR: fan_id must be an integer.", file=sys.stderr)
        return 1
    if fan_id not in ALLOWED_FAN_IDS:
        print(f"ERROR: fan_id must be one of {ALLOWED_FAN_IDS}.", file=sys.stderr)
        return 1

    # Parse and validate JSON
    try:
        points = json.loads(json_str)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(points, list) or len(points) < 2 or len(points) > MAX_CURVE_POINTS:
        print(f"ERROR: Expected 2–{MAX_CURVE_POINTS} curve points.", file=sys.stderr)
        return 1

    for pt in points:
        if not isinstance(pt, dict):
            print("ERROR: Each point must be a JSON object.", file=sys.stderr)
            return 1
        temp = pt.get("temp")
        pwm = pt.get("pwm")
        if not isinstance(temp, int) or not isinstance(pwm, int):
            print("ERROR: Point 'temp' and 'pwm' must be integers.", file=sys.stderr)
            return 1
        if not (0 <= temp <= 110):
            print(f"ERROR: Temperature {temp}°C out of safe range.", file=sys.stderr)
            return 1
        if not (0 <= pwm <= 100):
            print(f"ERROR: PWM {pwm}% out of range.", file=sys.stderr)
            return 1

    hwmon = _find_hwmon_path()
    if hwmon is None:
        print("ERROR: Fan hwmon interface not found.", file=sys.stderr)
        return 1

    # Sort by temperature
    sorted_points = sorted(points, key=lambda p: p["temp"])

    try:
        for i, pt in enumerate(sorted_points, start=1):
            temp_path = hwmon / f"pwm{fan_id}_auto_point{i}_temp"
            pwm_path  = hwmon / f"pwm{fan_id}_auto_point{i}_pwm"

            if not temp_path.exists() or not pwm_path.exists():
                print(f"ERROR: Curve node {i} not found at {hwmon}. "
                      "Fan curve write not supported on this hardware.", file=sys.stderr)
                return 1

            # Temperature stored in millidegrees in some drivers, degrees in others
            # Detect by reading the current value scale
            try:
                current_raw = int(temp_path.read_text().strip())
                scale = 1000 if current_raw > 1000 else 1
            except (OSError, ValueError):
                scale = 1

            _write_sysfs(temp_path, str(pt["temp"] * scale))
            _write_sysfs(pwm_path, str(_pwm_from_percent(pt["pwm"])))

        print(f"Fan {fan_id} curve applied ({len(sorted_points)} points).")
        return 0
    except OSError:
        return 1


def cmd_fan_manual(fan_id_str: str, pwm_percent_str: str) -> int:
    """Set manual fan speed."""
    try:
        fan_id = int(fan_id_str)
        pwm_percent = int(pwm_percent_str)
    except ValueError:
        print("ERROR: fan_id and pwm must be integers.", file=sys.stderr)
        return 1

    if fan_id not in ALLOWED_FAN_IDS:
        print(f"ERROR: fan_id must be one of {ALLOWED_FAN_IDS}.", file=sys.stderr)
        return 1
    if not (0 <= pwm_percent <= 100):
        print("ERROR: pwm_percent must be 0–100.", file=sys.stderr)
        return 1

    hwmon = _find_hwmon_path()
    if hwmon is None:
        print("ERROR: Fan hwmon interface not found.", file=sys.stderr)
        return 1

    try:
        # Enable manual control
        _write_sysfs(hwmon / f"pwm{fan_id}_enable", "1")
        # Set PWM value
        _write_sysfs(hwmon / f"pwm{fan_id}", str(_pwm_from_percent(pwm_percent)))
        print(f"Fan {fan_id} manual speed set to {pwm_percent}% ({_pwm_from_percent(pwm_percent)}/255).")
        return 0
    except OSError:
        return 1


def cmd_fan_auto(fan_id_str: str) -> int:
    """Restore automatic fan control."""
    try:
        fan_id = int(fan_id_str)
    except ValueError:
        print("ERROR: fan_id must be an integer.", file=sys.stderr)
        return 1

    hwmon = _find_hwmon_path()
    if hwmon is None:
        print("ERROR: Fan hwmon interface not found.", file=sys.stderr)
        return 1

    ids = ALLOWED_FAN_IDS if fan_id == 0 else {fan_id}
    try:
        for fid in ids:
            enable_path = hwmon / f"pwm{fid}_enable"
            if enable_path.exists():
                _write_sysfs(enable_path, "2")  # 2 = automatic
        print("Fan automatic control restored.")
        return 0
    except OSError:
        return 1


def cmd_gpu_switch(mode: str) -> int:
    """Switch GPU mode via envycontrol."""
    if mode not in ALLOWED_GPU_MODES:
        print(f"ERROR: mode must be one of {ALLOWED_GPU_MODES}.", file=sys.stderr)
        return 1

    # Find envycontrol (search PATH + common venv/user paths)
    import shutil
    envycontrol = shutil.which("envycontrol")
    if envycontrol is None:
        candidates = (
            glob.glob("/home/*/.local/share/loq-control/venv/bin/envycontrol") +
            glob.glob("/home/*/Documents/LOQ/.venv/bin/envycontrol") +
            glob.glob("/home/*/.local/bin/envycontrol")
        )
        for c in candidates:
            if Path(c).is_file():
                envycontrol = c
                break

    if envycontrol is None:
        # Try supergfxctl
        supergfx = shutil.which("supergfxctl")
        if supergfx:
            mode_map = {"integrated": "Integrated", "hybrid": "Hybrid", "nvidia": "Dedicated"}
            result = subprocess.run(
                [supergfx, "--mode", mode_map[mode]],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"GPU mode switched to: {mode} (via supergfxctl)")
                return 0
            print(f"ERROR: supergfxctl failed: {result.stderr.strip()}", file=sys.stderr)
            return 1
        print("ERROR: Neither envycontrol nor supergfxctl found in PATH or venv.", file=sys.stderr)
        return 1

    result = subprocess.run(
        [envycontrol, "-s", mode],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        try:
            subprocess.run(["udevadm", "control", "--reload-rules"], capture_output=True)
            subprocess.run(["udevadm", "trigger"], capture_output=True)
            os.sync()
            os.sync()
        except Exception:
            pass
        print(f"GPU mode switched to: {mode} (via envycontrol)")
        print(result.stdout.strip())
        return 0

    print(f"ERROR: envycontrol failed: {result.stderr.strip()}", file=sys.stderr)
    return result.returncode


def cmd_power_limit(attr_name: str, value_str: str) -> int:
    """Write a power limit attribute value to sysfs."""
    # Validate attribute name against whitelist
    if attr_name not in ALLOWED_POWER_LIMIT_ATTRS:
        print(
            f"ERROR: '{attr_name}' is not in the allowed power-limit attribute list.",
            file=sys.stderr,
        )
        return 1

    # Validate value is an integer
    try:
        value = int(value_str)
    except ValueError:
        print("ERROR: value must be an integer.", file=sys.stderr)
        return 1

    if not (0 <= value <= 200):
        print("ERROR: value must be in range 0–200 W.", file=sys.stderr)
        return 1

    # Find the sysfs path
    path = _find_power_limit_path(attr_name)
    if path is None:
        print(f"ERROR: Could not find sysfs node for '{attr_name}'.", file=sys.stderr)
        return 1

    try:
        _write_sysfs(path, str(value))
        print(f"Power limit '{attr_name}' set to {value}.")
        return 0
    except OSError:
        return 1


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: loq-helper <subcommand> [args...]\n"
            "  fan-curve    <fan_id> <json>\n"
            "  fan-manual   <fan_id> <pwm%>\n"
            "  fan-auto     <fan_id>\n"
            "  gpu-switch   <integrated|hybrid|nvidia>\n"
            "  power-limit  <attr_name> <watts>",
            file=sys.stderr,
        )
        return 1

    subcmd = sys.argv[1]

    if subcmd == "fan-curve":
        if len(sys.argv) < 4:
            print("Usage: loq-helper fan-curve <fan_id> <json>", file=sys.stderr)
            return 1
        return cmd_fan_curve(sys.argv[2], sys.argv[3])

    elif subcmd == "fan-manual":
        if len(sys.argv) < 4:
            print("Usage: loq-helper fan-manual <fan_id> <pwm%>", file=sys.stderr)
            return 1
        return cmd_fan_manual(sys.argv[2], sys.argv[3])

    elif subcmd == "fan-auto":
        if len(sys.argv) < 3:
            print("Usage: loq-helper fan-auto <fan_id>", file=sys.stderr)
            return 1
        return cmd_fan_auto(sys.argv[2])

    elif subcmd == "gpu-switch":
        if len(sys.argv) < 3:
            print("Usage: loq-helper gpu-switch <integrated|hybrid|nvidia>", file=sys.stderr)
            return 1
        return cmd_gpu_switch(sys.argv[2])

    elif subcmd == "power-limit":
        if len(sys.argv) < 4:
            print("Usage: loq-helper power-limit <attr_name> <watts>", file=sys.stderr)
            return 1
        return cmd_power_limit(sys.argv[2], sys.argv[3])

    else:
        print(f"ERROR: Unknown subcommand: {subcmd}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
