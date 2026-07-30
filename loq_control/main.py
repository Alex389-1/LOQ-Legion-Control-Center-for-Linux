"""
Entry point — LOQ Control Center.
Usage:
  loq-control            # normal start (tray + dashboard)
  loq-control --discover # run Phase 0 discovery and print capability matrix
  loq-control --no-tray  # show dashboard without tray (useful for testing)
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="LOQ Control Center")
    parser.add_argument("--discover", action="store_true", help="Run hardware discovery and exit")
    parser.add_argument("--no-tray", action="store_true", help="Show dashboard without tray icon")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Phase 0 — always run discovery
    from loq_control.discovery import discover, save_capabilities
    from loq_control import config as cfg_mod
    from pathlib import Path

    caps = discover()

    if args.discover:
        # CLI-only discovery mode
        print(caps.summary())
        save_capabilities(caps, cfg_mod.CONFIG_DIR / "capabilities.json")
        return

    # Load config
    cfg = cfg_mod.load()

    # Launch GUI
    from loq_control.app import create_application
    app = create_application(sys.argv)

    # Start monitor thread
    from loq_control.backend.monitor import MonitorThread
    monitor = MonitorThread(caps, refresh_ms=cfg.refresh_interval_ms)

    # Create dashboard window
    from loq_control.dashboard.window import DashboardWindow
    window = DashboardWindow(caps, monitor)

    # System tray
    if not args.no_tray:
        from PySide6.QtWidgets import QSystemTrayIcon
        if QSystemTrayIcon.isSystemTrayAvailable():
            from loq_control.tray import TrayIcon
            tray = TrayIcon(caps, window)
            monitor.stats_updated.connect(tray.on_stats)
        else:
            log.warning("System tray not available — starting in windowed mode.")
            window.show()
    else:
        window.show()

    # Restore profile on login if configured
    if cfg.restore_profile_on_login and cfg.last_power_profile and caps.power_profiles_available:
        import loq_control.backend.power_profiles as pp
        pp.set_profile(cfg.last_power_profile)
        log.info("Restored power profile: %s", cfg.last_power_profile)

    if cfg.start_minimized:
        log.info("Starting minimized to tray.")
    else:
        window.show()

    # Start monitoring
    monitor.start()

    ret = app.exec()

    # Cleanup
    monitor.stop_monitoring()
    monitor.wait(3000)
    cfg_mod.save()
    sys.exit(ret)


if __name__ == "__main__":
    main()
