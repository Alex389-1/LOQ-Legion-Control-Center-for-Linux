"""
Backend — GPU mode switching via envycontrol (preferred) or supergfxctl.
Privileged operations are routed through the loq-helper via pkexec.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from loq_control.config import PENDING_GPU_SWITCH

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

log = logging.getLogger(__name__)

GPU_MODES = ["integrated", "hybrid", "nvidia"]

MODE_LABELS = {
    "integrated": "Integrated (iGPU only)",
    "hybrid": "Hybrid (PRIME offload)",
    "nvidia": "Discrete (dGPU only)",
}

MODE_DESCRIPTIONS = {
    "integrated": (
        "Only the Intel iGPU is active. Best battery life. "
        "NVIDIA GPU is fully powered off. Requires logout to apply."
    ),
    "hybrid": (
        "Intel iGPU drives the display; NVIDIA dGPU is available for offloaded workloads "
        "via PRIME (e.g. DRI_PRIME=1 or game launch options). Good balance. "
        "Requires logout to apply."
    ),
    "nvidia": (
        "NVIDIA dGPU drives the display directly. Maximum GPU performance for gaming/rendering. "
        "Higher power draw and heat. Requires reboot to apply."
    ),
}

MODE_RESTART_REQUIREMENT = {
    "integrated": "logout",
    "hybrid": "logout",
    "nvidia": "reboot",
}


def get_current_mode(caps: "Capabilities") -> str | None:
    """Return current GPU mode string, or None if undetermined."""
    if caps.gpu_switcher == "envycontrol":
        return _envycontrol_status()
    if caps.gpu_switcher == "supergfxctl":
        return _supergfxctl_status()
    return None


def _find_envycontrol() -> str | None:
    import shutil
    import glob
    envy = shutil.which("envycontrol")
    if envy:
        return envy
    candidates = (
        glob.glob("/home/*/.local/share/loq-control/venv/bin/envycontrol") +
        glob.glob("/home/*/Documents/LOQ/.venv/bin/envycontrol") +
        glob.glob("/home/*/.local/bin/envycontrol") +
        ["/usr/local/bin/envycontrol", "/usr/bin/envycontrol"]
    )
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


def switch_mode(mode: str, caps: "Capabilities") -> tuple[bool, str]:
    """
    Invoke privileged helper via sudo -n or pkexec to switch GPU mode.
    Returns (success, error_message).
    Writes PENDING_GPU_SWITCH marker file on success.
    """
    if mode not in GPU_MODES:
        return False, f"Unknown mode: {mode}"

    # 1. Try non-interactive sudo loq-helper first
    try:
        res = subprocess.run(
            ["sudo", "-n", "/usr/local/bin/loq-helper", "gpu-switch", mode],
            capture_output=True, text=True, timeout=120
        )
        if res.returncode == 0:
            _set_pending(mode)
            log.info("GPU mode switch to '%s' applied via sudo loq-helper.", mode)
            return True, ""
    except Exception as exc:
        log.debug("sudo -n loq-helper failed: %s", exc)

    # 2. Try non-interactive sudo envycontrol
    envy_bin = _find_envycontrol()
    if envy_bin:
        try:
            res = subprocess.run(
                ["sudo", "-n", envy_bin, "-s", mode],
                capture_output=True, text=True, timeout=120
            )
            if res.returncode == 0:
                _set_pending(mode)
                log.info("GPU mode switch to '%s' applied via sudo envycontrol (%s).", mode, envy_bin)
                return True, ""
        except Exception as exc:
            log.debug("sudo -n envycontrol failed: %s", exc)

    # 3. Fallback to pkexec loq-helper (interactive GUI auth)
    try:
        result = subprocess.run(
            ["pkexec", "/usr/local/bin/loq-helper", "gpu-switch", mode],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            _set_pending(mode)
            log.info("GPU mode switch to '%s' applied via pkexec loq-helper.", mode)
            return True, ""
        err = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        log.error("loq-helper gpu-switch failed: %s", err)
        return False, err
    except FileNotFoundError:
        return False, "pkexec not found. Is polkit installed?"
    except subprocess.TimeoutExpired:
        return False, "Operation timed out during initramfs rebuild."
    except Exception as exc:
        return False, str(exc)


def is_pending_restart() -> bool:
    """Return True if a GPU mode switch is pending and requires restart."""
    return PENDING_GPU_SWITCH.exists()


def get_pending_mode() -> str | None:
    if PENDING_GPU_SWITCH.exists():
        try:
            return PENDING_GPU_SWITCH.read_text().strip()
        except OSError:
            return None
    return None


def clear_pending() -> None:
    try:
        PENDING_GPU_SWITCH.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Backend-specific helpers
# ---------------------------------------------------------------------------

def _envycontrol_status() -> str | None:
    try:
        envy_bin = _find_envycontrol() or "envycontrol"
        result = subprocess.run(
            [envy_bin, "--query"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            out = result.stdout.strip().lower()
            if "integrated" in out:
                return "integrated"
            if "hybrid" in out:
                return "hybrid"
            if "nvidia" in out:
                return "nvidia"
    except Exception as exc:
        log.warning("envycontrol --query failed: %s", exc)
    return None


def _supergfxctl_status() -> str | None:
    try:
        result = subprocess.run(
            ["supergfxctl", "--get"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            out = result.stdout.strip().lower()
            if "integrated" in out:
                return "integrated"
            if "hybrid" in out:
                return "hybrid"
            if "dedicated" in out or "discrete" in out:
                return "nvidia"
    except Exception as exc:
        log.warning("supergfxctl --get failed: %s", exc)
    return None


def _set_pending(mode: str) -> None:
    PENDING_GPU_SWITCH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_GPU_SWITCH.write_text(mode)
