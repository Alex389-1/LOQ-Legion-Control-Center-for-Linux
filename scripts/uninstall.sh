#!/usr/bin/env bash
# =============================================================================
# LOQ Control Center — Uninstall Script
# =============================================================================
# Usage: sudo ./scripts/uninstall.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[info]${NC} $*"; }
success() { echo -e "${GREEN}[ok]${NC}   $*"; }

REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

info "Removing LOQ Control Center..."

REAL_UID=$(id -u "$REAL_USER")
USER_XDG_DIR="/run/user/$REAL_UID"
USER_DBUS_ADDR="unix:path=$USER_XDG_DIR/bus"

# Stop user service
if [ -d "$USER_XDG_DIR" ]; then
    sudo -u "$REAL_USER" DBUS_SESSION_BUS_ADDRESS="$USER_DBUS_ADDR" XDG_RUNTIME_DIR="$USER_XDG_DIR" systemctl --user stop loq-control.service 2>/dev/null || true
    sudo -u "$REAL_USER" DBUS_SESSION_BUS_ADDRESS="$USER_DBUS_ADDR" XDG_RUNTIME_DIR="$USER_XDG_DIR" systemctl --user disable loq-control.service 2>/dev/null || true
fi

# Remove installed files
rm -rf "$REAL_HOME/.local/share/loq-control"
rm -f "$REAL_HOME/.local/bin/loq-control"
rm -f "$REAL_HOME/.config/systemd/user/loq-control.service"
rm -f "$REAL_HOME/.local/share/applications/loq-control.desktop"
rm -f /usr/local/bin/loq-helper
rm -f /etc/sudoers.d/99-loq-control
rm -f /etc/udev/rules.d/99-ite-keyboard.rules
rm -f /usr/share/polkit-1/actions/com.github.loq-control.policy

udevadm control --reload-rules 2>/dev/null || true
udevadm trigger 2>/dev/null || true

echo ""
success "LOQ Control Center uninstalled successfully."
