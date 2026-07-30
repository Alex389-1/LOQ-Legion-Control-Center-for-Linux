"""
Config persistence — TOML-backed user settings.
Stored at ~/.config/loq-control/config.toml.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

log = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "loq-control"
CONFIG_PATH = CONFIG_DIR / "config.toml"
CAPABILITIES_CACHE = CONFIG_DIR / "capabilities.json"
PENDING_GPU_SWITCH = CONFIG_DIR / "pending_gpu_switch"


@dataclass
class FanCurvePoint:
    temp_c: int
    pwm_percent: int


@dataclass
class FanCurve:
    name: str = "Custom"
    points: list[FanCurvePoint] = field(default_factory=lambda: [
        FanCurvePoint(40, 20),
        FanCurvePoint(55, 35),
        FanCurvePoint(65, 50),
        FanCurvePoint(75, 70),
        FanCurvePoint(85, 90),
        FanCurvePoint(95, 100),
    ])


@dataclass
class AppConfig:
    # General
    refresh_interval_ms: int = 1000
    restore_profile_on_login: bool = False
    last_power_profile: str = "balanced"

    # UI
    window_x: int = -1
    window_y: int = -1
    window_width: int = 1100
    window_height: int = 720
    start_minimized: bool = False

    # Fan
    saved_fan_curves: list[FanCurve] = field(default_factory=list)
    active_fan_curve_name: str | None = None

    # Custom power profiles (future)
    custom_profiles: list[dict] = field(default_factory=list)


_config: AppConfig | None = None


def load() -> AppConfig:
    """Load config from disk, creating defaults if absent."""
    global _config
    if _config is not None:
        return _config

    cfg = AppConfig()

    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("rb") as f:
                data = tomllib.load(f)
            _apply_dict(cfg, data)
            log.info("Config loaded from %s", CONFIG_PATH)
        except Exception as exc:
            log.warning("Failed to load config (%s), using defaults.", exc)
    else:
        log.info("No config found, using defaults.")

    _config = cfg
    return cfg


def save(cfg: AppConfig | None = None) -> None:
    """Persist config to disk."""
    global _config
    if cfg is None:
        cfg = _config or AppConfig()
    _config = cfg

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = _to_dict(cfg)
    try:
        CONFIG_PATH.write_bytes(tomli_w.dumps(data).encode())
        log.info("Config saved to %s", CONFIG_PATH)
    except Exception as exc:
        log.error("Failed to save config: %s", exc)


def get() -> AppConfig:
    """Return cached config (load if needed)."""
    global _config
    if _config is None:
        _config = load()
    return _config


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _apply_dict(cfg: AppConfig, data: dict) -> None:
    general = data.get("general", {})
    cfg.refresh_interval_ms = general.get("refresh_interval_ms", cfg.refresh_interval_ms)
    cfg.restore_profile_on_login = general.get("restore_profile_on_login", cfg.restore_profile_on_login)
    cfg.last_power_profile = general.get("last_power_profile", cfg.last_power_profile)
    cfg.start_minimized = general.get("start_minimized", cfg.start_minimized)

    ui = data.get("ui", {})
    cfg.window_x = ui.get("x", cfg.window_x)
    cfg.window_y = ui.get("y", cfg.window_y)
    cfg.window_width = ui.get("width", cfg.window_width)
    cfg.window_height = ui.get("height", cfg.window_height)

    fan = data.get("fan", {})
    cfg.active_fan_curve_name = fan.get("active_curve", cfg.active_fan_curve_name)
    cfg.saved_fan_curves = []
    for curve_data in fan.get("curves", []):
        points = [FanCurvePoint(p["temp"], p["pwm"]) for p in curve_data.get("points", [])]
        cfg.saved_fan_curves.append(FanCurve(name=curve_data.get("name", "Custom"), points=points))


def _to_dict(cfg: AppConfig) -> dict[str, Any]:
    return {
        "general": {
            "refresh_interval_ms": cfg.refresh_interval_ms,
            "restore_profile_on_login": cfg.restore_profile_on_login,
            "last_power_profile": cfg.last_power_profile,
            "start_minimized": cfg.start_minimized,
        },
        "ui": {
            "x": cfg.window_x,
            "y": cfg.window_y,
            "width": cfg.window_width,
            "height": cfg.window_height,
        },
        "fan": {
            "active_curve": cfg.active_fan_curve_name or "",
            "curves": [
                {
                    "name": curve.name,
                    "points": [{"temp": p.temp_c, "pwm": p.pwm_percent} for p in curve.points],
                }
                for curve in cfg.saved_fan_curves
            ],
        },
    }
