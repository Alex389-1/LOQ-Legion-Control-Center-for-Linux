"""
Backend — Power profile management via power-profiles-daemon.
Uses powerprofilesctl subprocess for maximum distro compatibility.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

# Map internal profile names ↔ powerprofilesctl names
_PROFILE_ALIASES: dict[str, str] = {
    "quiet": "power-saver",
    "balanced": "balanced",
    "performance": "performance",
    # reverse
    "power-saver": "power-saver",
}

# Human-readable labels
PROFILE_LABELS: dict[str, str] = {
    "power-saver": "Quiet",
    "balanced": "Balanced",
    "performance": "Performance",
}

# Honest descriptions of what each profile actually affects
PROFILE_DESCRIPTIONS: dict[str, str] = {
    "power-saver": (
        "Reduces CPU P-state limits and disables turbo boost. "
        "NVIDIA GPU clock gating unchanged — primarily affects CPU power draw and thermals."
    ),
    "balanced": (
        "Default system profile. CPU runs at governor-selected clocks. "
        "Best balance of responsiveness and battery life."
    ),
    "performance": (
        "Removes CPU P-state limits and enables max turbo clocks. "
        "Note: NVIDIA GPU power limits are not reliably increased on Linux — "
        "gaming performance improvement is primarily from reduced CPU bottlenecking."
    ),
}


def get_active_profile() -> str | None:
    """Return the current active profile name (powerprofilesctl key), or None on error."""
    try:
        result = subprocess.run(
            ["powerprofilesctl", "get"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, KeyboardInterrupt):
        pass
    except Exception as exc:
        log.warning("get_active_profile failed: %s", exc)
    return None


def get_available_profiles() -> list[str]:
    """Return list of available profile names."""
    try:
        result = subprocess.run(
            ["powerprofilesctl", "list"],
            capture_output=True, text=True, timeout=5
        )
        profiles = []
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.endswith(":"):
                    profiles.append(line.rstrip(":").lstrip("*").strip())
        return profiles or ["power-saver", "balanced", "performance"]
    except Exception:
        return ["power-saver", "balanced", "performance"]


def set_profile(profile_name: str) -> bool:
    """
    Switch to the given profile. Accepts both internal keys (e.g. 'power-saver')
    and display aliases (e.g. 'quiet').
    Returns True on success.
    """
    canonical = _PROFILE_ALIASES.get(profile_name.lower(), profile_name)
    try:
        result = subprocess.run(
            ["powerprofilesctl", "set", canonical],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            log.info("Power profile set to: %s", canonical)
            return True
        log.warning("powerprofilesctl set failed: %s", result.stderr.strip())
    except FileNotFoundError:
        log.error("powerprofilesctl not found.")
    except Exception as exc:
        log.error("set_profile failed: %s", exc)
    return False


def label_for(profile: str) -> str:
    """Return human-readable label for a profile key."""
    return PROFILE_LABELS.get(profile, profile.capitalize())


def description_for(profile: str) -> str:
    """Return honest hardware-specific description for a profile."""
    return PROFILE_DESCRIPTIONS.get(profile, "")
