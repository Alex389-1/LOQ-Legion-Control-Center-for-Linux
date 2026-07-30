"""
Backend — ITE keyboard RGB lighting controller.
================================================
Integrates the ITE 8291 HID protocol used by the Lenovo LOQ keyboard
(USB VID 0x048d, PID 0xc993 and related variants).

Protocol notes (reverse-engineered, as used by LegionAura / LenovoRGB):
  - Uses HID SET_FEATURE_REPORT with Report ID 0xCC
  - 65-byte payload: [report_id, subcmd, mode, speed, brightness, r, g, b, ...]
  - LOQ has 4 keyboard zones (zone 0–3 from left to right)
  - Effects: STATIC=0x01, BREATHING=0x03, WAVE=0x04, COLOR_SHIFT=0x06, OFF=0x00

Privilege model:
  - Requires read/write access to the HID device
  - Without root: add udev rule (install.sh does this):
      SUBSYSTEM=="usb", ATTR{idVendor}=="048d", ATTR{idProduct}=="c993", MODE="0666"
  - Falls back to logging a clear error if permissions are denied

Usage:
    from loq_control.backend.keyboard_light import KeyboardController
    kb = KeyboardController(vid=0x048d, pid=0xc993)
    if kb.open():
        kb.set_static(zone=0, r=255, g=0, b=0)   # zone 0 = red
        kb.close()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPORT_ID = 0xCC
PAYLOAD_LEN = 65      # full HID feature report length (1 report ID + 64 data bytes)

NUM_ZONES = 4         # LOQ has 4-zone keyboard lighting

class Effect(IntEnum):
    OFF          = 0x00
    STATIC       = 0x01
    BREATHING    = 0x03
    WAVE         = 0x04
    COLOR_SHIFT  = 0x06

# Command byte for setting lighting
CMD_SET_LIGHTING = 0x01
# Commit command — send after all zone writes
CMD_COMMIT = 0x02

# Default speeds / brightness
DEFAULT_SPEED      = 0x01  # 0x01=slow, 0x02=medium, 0x03=fast
DEFAULT_BRIGHTNESS = 0x64  # 100 = max


@dataclass
class ZoneColor:
    r: int = 255
    g: int = 0
    b: int = 0


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class KeyboardController:
    """
    Wraps the ITE HID keyboard lighting protocol.
    Call open() before use, close() when done.
    """

    def __init__(self, vid: int = 0x048d, pid: int = 0xc993) -> None:
        self._vid = vid
        self._pid = pid
        self._device = None
        self._available = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> bool:
        """Open HID device. Returns True on success."""
        try:
            import hid
            if hasattr(hid, "Device"):
                self._device = hid.Device(self._vid, self._pid)
            elif hasattr(hid, "device"):
                self._device = hid.device()
                self._device.open(self._vid, self._pid)
                if hasattr(self._device, "set_nonblocking"):
                    self._device.set_nonblocking(1)
            else:
                raise AttributeError("Module 'hid' has no Device or device class")
            self._available = True
            log.info("ITE keyboard opened: VID=%04x PID=%04x", self._vid, self._pid)
            return True
        except ImportError:
            log.error("'hid' module not installed. Run: pip install hid")
        except OSError as exc:
            log.error(
                "Cannot open ITE keyboard (VID=%04x PID=%04x): %s\n"
                "  → Add udev rule: "
                'SUBSYSTEM=="usb", ATTR{idVendor}=="%04x", ATTR{idProduct}=="%04x", MODE="0666"',
                self._vid, self._pid, exc, self._vid, self._pid,
            )
        except Exception as exc:
            log.error("HID open error: %s", exc)
        self._available = False
        return False

    def close(self) -> None:
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
        self._available = False

    @property
    def is_open(self) -> bool:
        return self._available and self._device is not None

    # ------------------------------------------------------------------
    # High-level lighting API
    # ------------------------------------------------------------------

    def set_static(self, zone: int, r: int, g: int, b: int) -> bool:
        """Set a single zone to a static color."""
        return self._send_zone(zone, Effect.STATIC, r, g, b)

    def set_all_static(self, r: int, g: int, b: int) -> bool:
        """Set all zones to the same static color."""
        ok = True
        for zone in range(NUM_ZONES):
            ok = self._send_zone(zone, Effect.STATIC, r, g, b) and ok
        return self._commit() and ok

    def set_all_zones(
        self,
        colors: list[ZoneColor],
        brightness_pct: int = 100,
        effect: Effect = Effect.STATIC,
        speed: int = DEFAULT_SPEED,
    ) -> bool:
        """Set each zone color, brightness (0-100%), and effect."""
        ok = True
        for zone, color in enumerate(colors[:NUM_ZONES]):
            ok = self._send_zone(
                zone, effect, color.r, color.g, color.b,
                speed=speed, brightness_pct=brightness_pct
            ) and ok
        return self._commit() and ok

    def set_wave(self, effect: Effect = Effect.WAVE, speed: int = DEFAULT_SPEED, brightness_pct: int = 100) -> bool:
        """Set wave / color shift effect (all zones)."""
        ok = True
        for zone in range(NUM_ZONES):
            ok = self._send_zone(
                zone, effect, 0, 0, 0,
                speed=speed, brightness_pct=brightness_pct
            ) and ok
        return self._commit() and ok

    def set_off(self) -> bool:
        """Turn off all keyboard lighting."""
        ok = True
        for zone in range(NUM_ZONES):
            ok = self._send_zone(zone, Effect.OFF, 0, 0, 0, brightness_pct=0) and ok
        return self._commit() and ok

    # ------------------------------------------------------------------
    # Low-level protocol
    # ------------------------------------------------------------------

    def _send_zone(
        self,
        zone: int,
        effect: Effect,
        r: int, g: int, b: int,
        speed: int = DEFAULT_SPEED,
        brightness_pct: int = 100,
    ) -> bool:
        """
        Build and send a zone-control HID report.
        Brightness percentage (0-100%) mapped to 1-4 level scale expected by ITE.
        """
        if brightness_pct <= 0 or effect == Effect.OFF:
            bright_level = 0
        else:
            bright_level = max(1, min(4, int((brightness_pct + 24) // 25)))

        data = bytes([
            CMD_SET_LIGHTING,
            zone & 0xFF,
            int(effect),
            speed & 0xFF,
            bright_level & 0xFF,
            r & 0xFF,
            g & 0xFF,
            b & 0xFF,
        ]) + bytes(PAYLOAD_LEN - 1 - 8)

        return self._write(data)

    def _commit(self) -> bool:
        """Send commit command to apply all pending zone writes."""
        data = bytes([CMD_COMMIT]) + bytes(PAYLOAD_LEN - 2)
        return self._write(data)

    def _make_payload(self, subcmd: int, **kwargs: int) -> bytes:
        """Generic payload builder for non-zone commands."""
        buf = bytearray(PAYLOAD_LEN - 1)
        buf[0] = subcmd
        for i, (_, v) in enumerate(kwargs.items(), start=1):
            if i < len(buf):
                buf[i] = v & 0xFF
        return bytes(buf)

    def _write(self, data: bytes) -> bool:
        """Send HID feature report. Prepends REPORT_ID."""
        if not self.is_open:
            return False
        try:
            report = bytes([REPORT_ID]) + data
            # Pad/truncate to exactly PAYLOAD_LEN bytes
            report = report[:PAYLOAD_LEN].ljust(PAYLOAD_LEN, b'\x00')
            self._device.send_feature_report(report)  # type: ignore[union-attr]
            return True
        except Exception as exc:
            log.error("HID write error: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Convenience: global singleton pattern for the monitoring thread
# ---------------------------------------------------------------------------

_controller: KeyboardController | None = None


def get_controller(vid: int = 0x048d, pid: int = 0xc993) -> KeyboardController:
    """Return (or create) the global keyboard controller instance."""
    global _controller
    if _controller is None:
        _controller = KeyboardController(vid, pid)
    return _controller
