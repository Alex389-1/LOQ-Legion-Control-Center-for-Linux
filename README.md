# LOQ Control Center for Linux

A unified, modern GUI control center and hardware inspector for **Lenovo LOQ & Legion laptops** on Linux.

Built with **PySide6 / Qt6**, providing real-time hardware telemetry, per-core CPU thread inspectors, GPU mode switching, power profiles, and 4-zone RGB keyboard lighting control.

---

## Highlights & Features

- **Windows Task Manager-Style Telemetry**: Real-time cubic bezier history graphs with gridlines and Y-axis scale bounds for CPU, RAM, Disk, Intel iGPU, NVIDIA dGPU, and Network I/O.
- **Interactive Per-Core Hardware Inspector**: Click any metric card to open a high-resolution modal with individual per-core CPU thread bars (`Core 00` through `Core 15`), minimum/average/maximum statistics, and deep hardware specifications.
- **Wi-Fi & Ethernet Network Monitoring**: Real-time download & upload speeds, interface detection (`wlan0` / `enp7s0`), IPv4 local address, and total session traffic tracking.
- **GPU Mode Switching**: Integrated (iGPU only), Hybrid (PRIME render offload), and Discrete (NVIDIA only) switching via `envycontrol` with non-blocking initramfs rebuild dialogs.
- **NVIDIA dGPU Telemetry**: Real-time VRAM allocation, GPU core clock, memory clock, PCIe link generation & width, thermal junction temperature, and power draw (TGP).
- **Power Profile Management**: One-click switching between `Quiet` (Power Saver), `Balance` (Adaptive), and `Performance` with instant GUI response and live PL1/PL2/cTGP target context.
- **ITE RGB Keyboard Control**: Full 4-zone RGB keyboard lighting control with zone selection, custom color pickers, brightness control, and quick presets.
- **Clean Dark Design System**: Modern Zinc dark theme (`#09090b`), vector SVG icons, unified blue active states (`#3b82f6`), and dynamic status badges (`NORMAL`, `WARM`, `HOT`, `BUSY`, `SATURATED`).

---

## Feature Overview Matrix

| Component / Feature | Support | Requirements / Details |
|---|---|---|
| **CPU Monitoring** | ✅ Live | Clock speed, package temperature, per-core utilization |
| **Memory & Swap** | ✅ Live | Used, available, cached, buffers, and swap breakdown |
| **Network (Wi-Fi & Ethernet)** | ✅ Live | Download/Upload rates, active interface, IPv4 address |
| **NVIDIA dGPU Telemetry** | ✅ Live | NVML, VRAM, GPU/Mem clocks, PCIe Gen4 link width, TGP power |
| **Intel iGPU Telemetry** | ✅ Live | Render engine utilization via `sysfs` & `intel_gpu_top` fallback |
| **GPU Mode Switcher** | ✅ Non-blocking | `envycontrol` backend with background initramfs rebuilding |
| **Power Profile Switching** | ✅ Non-blocking | `power-profiles-daemon` integration with PL1/PL2 context |
| **4-Zone RGB Keyboard** | ✅ No Root | ITE HID (`VID 048d PID c993`) via custom `udev` rules |
| **Cooling Fan Monitoring** | ✅ Live | `legion_laptop` hwmon fan speeds (Fan 1 & Fan 2 RPMs) |

---

## Quick Start & Installation

### 1. Prerequisites (Package Managers)

**Arch Linux / EndeavourOS:**
```bash
sudo pacman -S python intel-gpu-tools power-profiles-daemon
pip install envycontrol
```

**Ubuntu / Debian / Pop!_OS:**
```bash
sudo apt install python3 python3-venv intel-gpu-tools power-profiles-daemon
pip install envycontrol
```

**Fedora:**
```bash
sudo dnf install python3 intel-gpu-tools power-profiles-daemon
pip install envycontrol
```

---

### 2. Single-Command Automated Installer

Clone the repository and run the automated installer:

```bash
git clone https://github.com/Alex389-1/LOQ-Legion-Control-Center-for-Linux.git ~/Documents/LOQ
cd ~/Documents/LOQ
sudo ./scripts/install.sh
```

#### What the installer configures:
1. Creates an isolated Python virtual environment at `~/.local/share/loq-control/venv`.
2. Installs required dependencies (`PySide6`, `psutil`, `nvidia-ml-py`, `envycontrol`, `hid`).
3. Installs the root-owned privileged backend helper at `/usr/local/bin/loq-helper`.
4. Configures `/etc/sudoers.d/99-loq-control` for non-blocking sub-second helper execution.
5. Installs `/etc/udev/rules.d/99-ite-keyboard.rules` for no-root ITE keyboard RGB access.
6. Installs application desktop shortcut and systemd user background service.

---

## Running LOQ Control Center

After installation, launch the application from your desktop launcher or terminal:

```bash
loq-control                 # Start GUI in system tray / main window
loq-control --no-tray       # Launch directly in windowed mode
loq-control --discover      # Inspect hardware capability matrix
loq-control --debug         # Launch with verbose logging
```

### Run as a User Background Service
```bash
systemctl --user start loq-control
systemctl --user enable loq-control
journalctl --user -u loq-control -f   # View background service logs
```

---

## Uninstallation

To cleanly remove LOQ Control Center, sudoers rules, udev rules, and desktop integration:

```bash
cd ~/Documents/LOQ
sudo ./scripts/uninstall.sh
```

---

## Architecture Overview

```
LOQ/
├── main.py                   # App entry point & Phase 0 hardware discovery
├── discovery.py              # System & hardware capability matrix detection
├── config.py                 # Persistent TOML configuration manager
├── app.py                    # QApplication setup & global dark QSS theme
├── tray.py                   # System tray icon & context menu
├── backend/
│   ├── monitor.py            # Real-time background telemetry polling thread
│   ├── power_profiles.py     # power-profiles-daemon wrapper
│   ├── gpu_switch.py         # envycontrol wrapper with non-blocking QThread
│   ├── keyboard_light.py     # ITE HID keyboard RGB controller
│   └── fan_control.py        # sysfs hwmon fan read/write module
└── dashboard/
    ├── window.py             # Frameless QMainWindow with solid opacity
    ├── monitor_tab.py        # Task Manager-style hardware monitoring grid
    ├── power_tab.py          # Non-blocking power profile selector
    ├── gpu_tab.py            # GPU mode switching panel
    ├── keyboard_tab.py       # 4-zone RGB lighting editor with preset scopes
    ├── power_limits_tab.py   # Read-only / interactive power limit gauges
    └── widgets/
        ├── sparkline.py      # QPainter cubic bezier chart with gridlines
        ├── metric_card.py    # Clickable hardware metric card container
        ├── metric_detail_dialog.py # High-resolution interactive inspector modal
        └── icons.py          # Vector SVG icon renderer
```

---

## Hardware Discovery (`--discover`)

To view your laptop's detected hardware capabilities, run:

```bash
loq-control --discover
```

Example Output:
```
=== LOQ Control Center — Capability Matrix ===
  Kernel          : 6.11.1-arch1-1
  CPU             : 13th Gen Intel(R) Core(TM) i5-13450HX
  Logical Cores   : 16
  RAM Capacity    : 24.9 GB
  NVIDIA GPU      : NVIDIA GeForce RTX 4050 Laptop GPU (Driver: 610.43.03)
  Intel iGPU      : Intel Raptor Lake-S UHD Graphics
  Network         : wlan0 (Wi-Fi 6) · IP: 10.181.202.18
  Power Profiles  : YES (power-saver, balanced, performance)
  GPU Switcher    : envycontrol
  Priv Helper     : INSTALLED (/usr/local/bin/loq-helper)
==============================================
```

---

## License

Distributed under the **GPL-3.0-or-later** License.

---

## Author & Credit

Made with ❤️ by **ALEX** ([@Alex389-1](https://github.com/Alex389-1))
