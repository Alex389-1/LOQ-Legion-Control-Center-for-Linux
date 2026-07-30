"""
Backend — Fan curve and manual override control.
Reads RPM from sysfs (always). Writes curves/overrides via pkexec loq-helper
(only when fan_curve_writable capability is confirmed).

Safety guard: refuses curves with any PWM < 20% at temps ≥ 80°C.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

log = logging.getLogger(__name__)

MIN_PWM_HIGH_TEMP = 20   # % — minimum fan speed when temp ≥ HIGH_TEMP_THRESHOLD
HIGH_TEMP_THRESHOLD = 80  # °C
MAX_CURVE_POINTS = 10


@dataclass
class FanCurvePoint:
    temp_c: int
    pwm_percent: int


def read_fan_rpms(hwmon_path: Path | None) -> tuple[int, int]:
    """Read fan1 and fan2 RPM from hwmon sysfs. Returns (0,0) if unavailable."""
    if hwmon_path is None:
        return 0, 0

    def _r(name: str) -> int:
        try:
            return int((hwmon_path / name).read_text().strip())
        except (OSError, ValueError):
            return 0

    return _r("fan1_input"), _r("fan2_input")


def validate_curve(points: list[FanCurvePoint]) -> tuple[bool, str]:
    """
    Validate a fan curve for safety.
    Returns (is_valid, error_message).
    """
    if len(points) < 2:
        return False, "Curve must have at least 2 points."
    if len(points) > MAX_CURVE_POINTS:
        return False, f"Curve can have at most {MAX_CURVE_POINTS} points."

    sorted_pts = sorted(points, key=lambda p: p.temp_c)
    for pt in sorted_pts:
        if pt.temp_c >= HIGH_TEMP_THRESHOLD and pt.pwm_percent < MIN_PWM_HIGH_TEMP:
            return False, (
                f"Safety guard: fan speed {pt.pwm_percent}% at {pt.temp_c}°C is below the "
                f"minimum safe threshold of {MIN_PWM_HIGH_TEMP}% for temperatures ≥{HIGH_TEMP_THRESHOLD}°C."
            )
    return True, ""


def apply_fan_curve(
    points: list[FanCurvePoint],
    fan_id: int = 1,
    caps: "Capabilities | None" = None,
) -> tuple[bool, str]:
    """
    Apply a fan curve via the privileged helper.
    fan_id: 1 or 2.
    Returns (success, error_message).
    """
    if caps and not caps.helper_installed:
        return False, "Privileged helper not installed. Run install.sh first."

    valid, err = validate_curve(points)
    if not valid:
        return False, err

    payload = json.dumps([
        {"temp": p.temp_c, "pwm": p.pwm_percent}
        for p in sorted(points, key=lambda p: p.temp_c)
    ])

    try:
        result = subprocess.run(
            ["pkexec", "/usr/local/bin/loq-helper", "fan-curve", str(fan_id), payload],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            log.info("Fan curve applied to fan%d.", fan_id)
            return True, ""
        err = result.stderr.strip() or "Unknown error"
        return False, err
    except FileNotFoundError:
        return False, "pkexec not found."
    except subprocess.TimeoutExpired:
        return False, "Operation timed out."
    except Exception as exc:
        return False, str(exc)


def set_fan_manual(fan_id: int, pwm_percent: int, caps: "Capabilities | None" = None) -> tuple[bool, str]:
    """Set a manual fan speed (0–100%). Bypasses the curve."""
    if not 0 <= pwm_percent <= 100:
        return False, "PWM must be 0–100%."
    try:
        result = subprocess.run(
            ["pkexec", "/usr/local/bin/loq-helper", "fan-manual", str(fan_id), str(pwm_percent)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()
    except Exception as exc:
        return False, str(exc)


def restore_fan_auto(fan_id: int = 0) -> tuple[bool, str]:
    """Restore automatic fan control (pwmN_enable=2)."""
    try:
        result = subprocess.run(
            ["pkexec", "/usr/local/bin/loq-helper", "fan-auto", str(fan_id)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()
    except Exception as exc:
        return False, str(exc)
