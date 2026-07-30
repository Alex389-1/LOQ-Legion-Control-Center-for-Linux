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
        """Open HID LED control device (hidraw0 / Interface 0). Returns True on success."""
        try:
            import hid
            devices = hid.enumerate(self._vid, self._pid)
            target_path = None
            for d in devices:
                # Target hidraw0 / Interface 0 (which accepts 65-byte feature & output reports)
                if d.get("interface_number") == 0 or b"hidraw0" in d.get("path", b""):
                    target_path = d.get("path")
                    break
            if target_path is None and devices:
                target_path = devices[0].get("path")

            if hasattr(hid, "Device"):
                self._device = hid.Device(path=target_path) if target_path else hid.Device(self._vid, self._pid)
            elif hasattr(hid, "device"):
                self._device = hid.device()
                if target_path:
                    self._device.open_path(target_path)
                else:
                    self._device.open(self._vid, self._pid)
                if hasattr(self._device, "set_nonblocking"):
                    self._device.set_nonblocking(1)
            else:
                raise AttributeError("Module 'hid' has no Device or device class")
            self._available = True
            log.info("ITE keyboard LED device opened: VID=%04x PID=%04x path=%s",
                     self._vid, self._pid, target_path)
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
        """Set 4-zone colors using Lenovo ITE 0x16 packet protocol."""
        return self._send_lenovo_packet(
            colors=colors,
            effect=effect,
            speed=speed,
            brightness_pct=brightness_pct,
        )

    def set_wave(self, effect: Effect = Effect.WAVE, speed: int = DEFAULT_SPEED, brightness_pct: int = 100) -> bool:
        """Set wave or color shift effect."""
        return self._send_lenovo_packet(
            colors=[ZoneColor(0, 0, 0)] * NUM_ZONES,
            effect=effect,
            speed=speed,
            brightness_pct=brightness_pct,
            direction="ltr",
        )

    def set_off(self) -> bool:
        """Turn off all keyboard lighting."""
        return self._send_lenovo_packet(
            colors=[ZoneColor(0, 0, 0)] * NUM_ZONES,
            effect=Effect.OFF,
        )

    def _send_lenovo_packet(
        self,
        colors: list[ZoneColor],
        effect: Effect = Effect.STATIC,
        speed: int = 1,
        brightness_pct: int = 100,
        direction: str = "ltr",
    ) -> bool:
        """
        Build and send Lenovo 33-byte ITE feature report packet:
          [0xCC, 0x16, effect_code, speed, brightness_level,
           R1, G1, B1, R2, G2, B2, R3, G3, B3, R4, G4, B4,
           0, dir1, dir2, 0, ...]
        """
        data = bytearray(33)
        data[0] = REPORT_ID  # 0xCC (204)
        data[1] = 0x16       # Lenovo SET_OPTIONS command (22)

        if effect == Effect.OFF or brightness_pct <= 0:
            data[2] = int(Effect.STATIC)
            # data[3..32] remain 0x00
        else:
            eff_code = int(effect)
            bright_level = max(1, min(2, int((brightness_pct + 49) // 50)))

            data[2] = eff_code & 0xFF
            data[3] = speed & 0xFF
            data[4] = bright_level & 0xFF

            if effect in (Effect.STATIC, Effect.BREATHING):
                for idx, color in enumerate(colors[:NUM_ZONES]):
                    offset = 5 + (idx * 3)
                    if offset + 2 < len(data):
                        data[offset] = color.r & 0xFF
                        data[offset + 1] = color.g & 0xFF
                        data[offset + 2] = color.b & 0xFF

            data[17] = 0
            if direction == "rtl":
                data[18], data[19] = 1, 0
            elif direction == "ltr":
                data[18], data[19] = 0, 1
            else:
                data[18], data[19] = 0, 0

        return self._write_raw(bytes(data))

    def _write_raw(self, report: bytes) -> bool:
        """Send 33-byte HID feature report or output report to ITE controller."""
        if not self.is_open:
            return False
        ok = False
        try:
            self._device.send_feature_report(report)  # type: ignore[union-attr]
            ok = True
        except Exception as exc:
            log.debug("send_feature_report failed: %s", exc)

        try:
            self._device.write(report)  # type: ignore[union-attr]
            ok = True
        except Exception as exc:
            log.debug("dev.write failed: %s", exc)

        return ok


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
