"""
Backend — CPU and GPU power limit control via WMI firmware-attributes / legion sysfs.

Reads and writes the following limits (where exposed by the kernel):

  CPU:
    cpu_longterm_powerlimit   / CPULongTermPowerLimit    (PL1, sustained watts)
    cpu_shortterm_powerlimit  / CPUShortTermPowerLimit   (PL2, burst watts)
    cpu_peak_powerlimit       / CPUPeakPowerLimit        (tau burst cap)
    cpu_cross_loading_powerlimit / CPUCrossLoadingPowerLimit

  GPU:
    gpu_ctgp_powerlimit       / cTGP   (Configurable Total Graphics Power)
    gpu_ppab_powerlimit       / PPAB   (Platform Power Allocation Budget)
    gpu_ac_offset_powerlimit  / ACOffset (AC power offset for dynamic TGP)

Writes go through the privileged helper (pkexec loq-helper power-limit <attr> <value>)
since sysfs write permissions are typically root-only even when readable as user.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attribute registry: internal key → possible sysfs node names
# ---------------------------------------------------------------------------

ATTR_MAP: dict[str, list[str]] = {
    # CPU
    "cpu_pl1":       ["ppt_pl1_spl", "cpu_longterm_powerlimit",  "CPULongTermPowerLimit"],
    "cpu_pl2":       ["ppt_pl2_sppt", "cpu_shortterm_powerlimit", "CPUShortTermPowerLimit"],
    "cpu_peak":      ["ppt_pl1_tau", "cpu_peak_powerlimit",      "CPUPeakPowerLimit"],
    "cpu_crossload": ["ppt_cpu_cl", "cpu_cross_loading_powerlimit", "CPUCrossLoadingPowerLimit"],
    "cpu_temp":      ["cpu_temp"],
    # GPU
    "gpu_ctgp":      ["gpu_nv_ctgp", "gpu_ctgp_powerlimit", "cTGP"],
    "gpu_ppab":      ["gpu_nv_ppab", "gpu_ppab_powerlimit", "PPAB"],
    "gpu_ac_offset": ["gpu_nv_ac_offset", "gpu_ac_offset_powerlimit", "ACOffset"],
    "gpu_temp":      ["gpu_temp"],
}

ATTR_LABELS: dict[str, str] = {
    "cpu_pl1":       "CPU PL1 (Sustained)",
    "cpu_pl2":       "CPU PL2 (Burst)",
    "cpu_peak":      "CPU PL1 Tau (Duration)",
    "cpu_crossload": "CPU Cross-Load",
    "cpu_temp":      "CPU Temp Limit",
    "gpu_ctgp":      "GPU cTGP",
    "gpu_ppab":      "GPU Dynamic Boost (PPAB)",
    "gpu_ac_offset": "GPU AC Offset",
    "gpu_temp":      "GPU Temp Limit",
}

ATTR_UNITS: dict[str, str] = {
    "cpu_pl1": "W", "cpu_pl2": "W", "cpu_peak": "s", "cpu_crossload": "W", "cpu_temp": "°C",
    "gpu_ctgp": "W", "gpu_ppab": "W", "gpu_ac_offset": "W", "gpu_temp": "°C",
}

# Conservative default ranges (overridden by sysfs min_value/max_value if present)
ATTR_DEFAULT_RANGE: dict[str, tuple[int, int]] = {
    "cpu_pl1":       (50, 95),
    "cpu_pl2":       (60, 167),
    "cpu_peak":      (0,  56),
    "cpu_crossload": (30, 55),
    "cpu_temp":      (85, 100),
    "gpu_ctgp":      (55, 95),
    "gpu_ppab":      (10, 25),
    "gpu_ac_offset": (10, 80),
    "gpu_temp":      (75, 87),
}

# Group for UI layout
CPU_ATTRS = ["cpu_pl1", "cpu_pl2", "cpu_peak", "cpu_crossload", "cpu_temp"]
GPU_ATTRS = ["gpu_ctgp", "gpu_ppab", "gpu_ac_offset", "gpu_temp"]


@dataclass
class LimitValue:
    key: str
    label: str
    unit: str
    current: int
    min_val: int
    max_val: int
    path: Path
    writable: bool


def resolve_attrs(caps: "Capabilities") -> dict[str, LimitValue]:
    """
    Build a dict of available limit attributes from the capability map.
    Returns only the attrs that were actually found during discovery.
    """
    result: dict[str, LimitValue] = {}
    found = caps.power_limit_attrs  # {sysfs_name: Path}

    for key, candidates in ATTR_MAP.items():
        path: Path | None = None
        for candidate in candidates:
            if candidate in found:
                path = found[candidate]
                break
        if path is None:
            continue

        current = _read_int(path)
        if current is None:
            continue

        # Try reading min_value and max_value from firmware-attributes directory if available
        min_f = path.parent / "min_value"
        max_f = path.parent / "max_value"
        min_val = _read_int(min_f) if min_f.exists() else None
        max_val = _read_int(max_f) if max_f.exists() else None

        def_min, def_max = ATTR_DEFAULT_RANGE.get(key, (0, 255))
        min_val = min_val if min_val is not None else def_min
        max_val = max_val if max_val is not None else def_max

        writable = caps.power_limits_writable

        result[key] = LimitValue(
            key=key,
            label=ATTR_LABELS.get(key, key),
            unit=ATTR_UNITS.get(key, ""),
            current=current,
            min_val=min_val,
            max_val=max_val,
            path=path,
            writable=writable,
        )

    return result


def read_current_values(attrs: dict[str, LimitValue]) -> dict[str, int | None]:
    """Read all attribute values from sysfs. Returns {key: value_or_None}."""
    return {key: _read_int(lv.path) for key, lv in attrs.items()}


def set_limit(attr_key: str, value: int, caps: "Capabilities") -> tuple[bool, str]:
    """
    Write a power limit value. Routes through pkexec loq-helper.
    Returns (success, error_message).
    """
    if not caps.helper_installed:
        return False, "Privileged helper not installed. Run install.sh first."

    # Find the sysfs node name
    candidates = ATTR_MAP.get(attr_key, [])
    sysfs_name: str | None = None
    for c in candidates:
        if c in caps.power_limit_attrs:
            sysfs_name = c
            break
    if sysfs_name is None:
        return False, f"Attribute '{attr_key}' not found on this hardware."

    try:
        result = subprocess.run(
            ["pkexec", "/usr/local/bin/loq-helper", "power-limit", sysfs_name, str(value)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            log.info("Power limit %s set to %d", sysfs_name, value)
            return True, ""
        err = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        log.error("power-limit set failed: %s", err)
        return False, err
    except FileNotFoundError:
        return False, "pkexec not found."
    except subprocess.TimeoutExpired:
        return False, "Operation timed out."
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None
