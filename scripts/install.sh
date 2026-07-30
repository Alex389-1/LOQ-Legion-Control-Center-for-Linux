#!/usr/bin/env bash
# =============================================================================
# LOQ Control Center — Install Script
# =============================================================================
# Usage: sudo ./scripts/install.sh
#
# What this does:
#   1. Creates a Python venv at ~/.local/share/loq-control/venv
#   2. Installs the package and dependencies into it
#   3. Creates a launcher wrapper at ~/.local/bin/loq-control
#   4. Installs the privileged helper at /usr/local/bin/loq-helper (root-owned)
#   5. Installs the polkit policy
#   6. Installs the systemd user service
#   7. Installs the .desktop file
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[info]${NC} $*"; }
success() { echo -e "${GREEN}[ok]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC} $*"; }
error()   { echo -e "${RED}[err]${NC}  $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Determine the real user (works even when run as sudo)
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

VENV_DIR="$REAL_HOME/.local/share/loq-control/venv"
BIN_DIR="$REAL_HOME/.local/bin"
DATA_DIR="$REAL_HOME/.local/share/loq-control"
CONFIG_DIR="$REAL_HOME/.config/loq-control"
SYSTEMD_USER_DIR="$REAL_HOME/.config/systemd/user"
DESKTOP_DIR="$REAL_HOME/.local/share/applications"

info "Installing LOQ Control Center…"
info "Project: $PROJECT_DIR"
info "User:    $REAL_USER ($REAL_HOME)"
echo ""

# ---------------------------------------------------------------------------
# 1. Python venv + package
# ---------------------------------------------------------------------------
info "Creating Python virtual environment at $VENV_DIR…"
sudo -u "$REAL_USER" mkdir -p "$VENV_DIR"
sudo -u "$REAL_USER" python3 -m venv --system-site-packages "$VENV_DIR"

info "Installing Python dependencies…"
sudo -u "$REAL_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip
sudo -u "$REAL_USER" "$VENV_DIR/bin/pip" install --quiet -r "$PROJECT_DIR/requirements.txt" git+https://github.com/bayasdev/envycontrol.git
sudo -u "$REAL_USER" "$VENV_DIR/bin/pip" install --quiet -e "$PROJECT_DIR"
success "Python package installed."

# ---------------------------------------------------------------------------
# 2. Launcher wrapper
# ---------------------------------------------------------------------------
info "Creating launcher at $BIN_DIR/loq-control…"
sudo -u "$REAL_USER" mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/loq-control" << EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python" -m loq_control.main "\$@"
EOF
chmod +x "$BIN_DIR/loq-control"
success "Launcher created."

# ---------------------------------------------------------------------------
# 3. Privileged helper
# ---------------------------------------------------------------------------
info "Installing privileged helper at /usr/local/bin/loq-helper…"
cp "$PROJECT_DIR/helper/loq_helper.py" /usr/local/bin/loq-helper
chown root:root /usr/local/bin/loq-helper
chmod 755 /usr/local/bin/loq-helper
# Patch shebang to use system python3
sed -i '1s|.*|#!/usr/bin/env python3|' /usr/local/bin/loq-helper
success "Privileged helper installed."

# ---------------------------------------------------------------------------
# 4. Polkit policy & Sudoers rule
# ---------------------------------------------------------------------------
info "Installing sudoers rule for privileged helper…"
cat > /etc/sudoers.d/99-loq-control << EOF
$REAL_USER ALL=(ALL) NOPASSWD: /usr/local/bin/loq-helper, /usr/local/bin/envycontrol, $VENV_DIR/bin/envycontrol
EOF
chmod 0440 /etc/sudoers.d/99-loq-control
success "Sudoers rule configured."
POLKIT_DIR="/usr/share/polkit-1/actions"
if [ -d "$POLKIT_DIR" ]; then
    cp "$PROJECT_DIR/polkit/com.github.loq-control.policy" "$POLKIT_DIR/"
    success "Polkit policy installed."
else
    warn "Polkit actions directory not found at $POLKIT_DIR. Skipping."
    warn "Privileged operations (fan control, GPU switch) will not work without polkit."
fi

# ---------------------------------------------------------------------------
# 5. udev rule for ITE keyboard RGB (no-root HID access)
# ---------------------------------------------------------------------------
info "Installing udev rule for ITE keyboard (VID 048d, PID c993)…"
UDEV_RULES_DIR="/etc/udev/rules.d"
cat > "$UDEV_RULES_DIR/99-ite-keyboard.rules" << 'UDEV_EOF'
# LOQ Control Center — ITE keyboard RGB (unprivileged access)
SUBSYSTEM=="usb", ATTR{idVendor}=="048d", ATTR{idProduct}=="c993", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="048d", ATTR{idProduct}=="c994", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="048d", ATTR{idProduct}=="c995", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="048d", ATTR{idProduct}=="c996", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="048d", ATTR{idProduct}=="c997", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="048d", ATTRS{idProduct}=="c993", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="048d", ATTRS{idProduct}=="c996", MODE="0666", TAG+="uaccess"
UDEV_EOF
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger 2>/dev/null || true
success "udev rule installed. Re-plug keyboard if it was already connected."

# ---------------------------------------------------------------------------
# 6. Systemd user service
# ---------------------------------------------------------------------------
info "Installing systemd user service…"
sudo -u "$REAL_USER" mkdir -p "$SYSTEMD_USER_DIR"
# Substitute %h with real home in the service file
sed "s|%h|$REAL_HOME|g" "$PROJECT_DIR/systemd/loq-control.service" \
    > "$SYSTEMD_USER_DIR/loq-control.service"
sudo -u "$REAL_USER" systemctl --user daemon-reload
sudo -u "$REAL_USER" systemctl --user enable loq-control.service 2>/dev/null || true
success "Systemd user service installed and enabled."

# ---------------------------------------------------------------------------
# 6. Desktop file
# ---------------------------------------------------------------------------
info "Installing .desktop file…"
sudo -u "$REAL_USER" mkdir -p "$DESKTOP_DIR"
cp "$PROJECT_DIR/desktop/loq-control.desktop" "$DESKTOP_DIR/"
sudo -u "$REAL_USER" update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
success ".desktop file installed."

# ---------------------------------------------------------------------------
# 7. Config dir
# ---------------------------------------------------------------------------
sudo -u "$REAL_USER" mkdir -p "$CONFIG_DIR"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}Installation complete!${NC}"
echo ""
echo -e "  Start now:        ${CYAN}loq-control${NC}"
echo -e "  Run discovery:    ${CYAN}loq-control --discover${NC}"
echo -e "  Start at login:   ${CYAN}systemctl --user start loq-control${NC}"
echo -e "  View logs:        ${CYAN}journalctl --user -u loq-control -f${NC}"
echo ""

# Check for system dependencies
echo -e "${BOLD}Checking optional system dependencies:${NC}"
command -v envycontrol    &>/dev/null && echo -e "  ${GREEN}✓${NC} envycontrol" \
    || echo -e "  ${YELLOW}✗${NC} envycontrol  (install: pip install envycontrol)"
command -v intel_gpu_top  &>/dev/null && echo -e "  ${GREEN}✓${NC} intel_gpu_top" \
    || echo -e "  ${YELLOW}✗${NC} intel_gpu_top (install: intel-gpu-tools package)"
command -v powerprofilesctl &>/dev/null && echo -e "  ${GREEN}✓${NC} powerprofilesctl" \
    || echo -e "  ${YELLOW}✗${NC} powerprofilesctl (install: power-profiles-daemon)"
echo ""
