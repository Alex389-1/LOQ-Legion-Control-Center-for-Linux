# LOQ Control Center for Linux

A unified, modern GUI control center, process manager, and hardware inspector for **Lenovo LOQ & Legion laptops** on Linux.

Built with **PySide6 / Qt6**, providing real-time hardware telemetry, process management, dual-boot storage inspector, GPU mode switching, power profiles, battery charge capping, and 4-zone RGB keyboard lighting control.

---

## Highlights & Features

- **Windows Task Manager-Style Telemetry**: Real-time cubic bezier history graphs with gridlines and Y-axis scale bounds for CPU, RAM, Disk I/O, Intel iGPU, NVIDIA dGPU, and Network I/O.
- **Process Manager (Task Inspector)**: Live system task manager with process search filtering, CPU & Memory usage columns, application brand logos (VS Code, Chrome, Firefox, Discord, Steam, Studio, Terminal, Python, etc.), and `End Task` process termination controls.
- **Power Profile & AC/Battery Detection**: Instant AC Adapter vs Battery power source badge detection, with one-click thermal profile switching (`🌱 Quiet`, `⚖ Balanced`, `⚡ Performance`) via kernel ACPI platform profiles and `power-profiles-daemon`.
- **Battery Conservation Mode (80% Charge Capping)**: One-click battery charge limit capping (~80% charge threshold) to extend battery lifespan and prevent thermal degradation when running on AC power continuously.
- **Dual-Boot & Physical Storage Inspector**: Hardware-level block device scanner via `lsblk` and `psutil`. Automatically detects and displays **Windows NTFS partitions** (Windows C: System Drive, Data Volumes), **Linux BTRFS/EXT4 partitions**, and **EFI system drives** with usage progress bars, free space readouts, and filesystem metrics.
- **Interactive High-Res Inspector Modals**: Click any metric card on the dashboard to open an interactive hardware inspector with per-core CPU thread bars (`Core 00` through `Core 15`), physical drive partition lists, min/avg/max telemetry, and deep hardware spec readouts.
- **Wi-Fi & Ethernet Network Telemetry**: Real-time download & upload speeds, active interface detection (`wlan0` / `enp7s0`), IPv4 local address, and session traffic tracking.
- **GPU Mode Switching**: Integrated (iGPU only), Hybrid (PRIME render offload), and Discrete (NVIDIA only) switching via `envycontrol` with non-blocking initramfs rebuild dialogs.
- **NVIDIA dGPU Telemetry**: Real-time VRAM allocation, GPU core clock, memory clock, PCIe link generation & width, thermal junction temperature, and power draw (TGP).
- **ITE RGB Keyboard Control**: Full 4-zone RGB keyboard lighting control with zone selection, custom color pickers, brightness control, and quick presets.
- **Sub-100ms Ultra-Fast Startup**: Optimized kernel sysfs probes and partition ring-caching deliver sub-100ms hardware discovery and instantaneous app launching.
- **Clean Dark Design System**: Modern Zinc dark theme (`#09090b`), vector SVG icons, unified blue active states (`#3b82f6`), and dynamic status badges (`NORMAL`, `WARM`, `HOT`, `BUSY`, `SATURATED`).

---

## Feature Overview Matrix

| Component / Feature | Support | Requirements / Details |
|---|---|---|
| **CPU Monitoring** | ✅ Live | Clock speed, package temperature, per-core utilization |
| **Process Manager** | ✅ Live | Task list, PID, CPU%, Memory, Search filter, App logos, `End Task` |
| **Memory & Swap** | ✅ Live | Used, available, cached, buffers, and swap breakdown |
| **Storage Inspector** | ✅ Live | Physical drive partitions, Windows NTFS, Linux BTRFS/EXT4, EFI, Read/Write MB/s |
| **Network (Wi-Fi & Ethernet)** | ✅ Live | Download/Upload rates, active interface, IPv4 address |
| **NVIDIA dGPU Telemetry** | ✅ Live | NVML, VRAM, GPU/Mem clocks, PCIe Gen4 link width, TGP power |
| **Intel iGPU Telemetry** | ✅ Live | Render engine utilization via `sysfs` & `intel_gpu_top` fallback |
| **Battery Conservation Mode** | ✅ 80% Cap | Lenovo charge capping toggle (`conservation_mode` / `charge_control_end_threshold`) |
| **Power Profile Switching** | ✅ Sub-ms | AC/Battery detection + `power-profiles-daemon` / ACPI platform_profile (`Quiet`, `Balanced`, `Performance`) |
| **GPU Mode Switcher** | ✅ Non-blocking | `envycontrol` backend with background initramfs rebuilding |
| **4-Zone RGB Keyboard** | ✅ No Root | ITE HID (`VID 048d PID c993`) via custom `udev` rules |
| **Cooling Fan Monitoring** | ✅ Live | Dual thermal fans (Fan 1 & Fan 2 RPMs) via sysfs hwmon |

---

## Quick Start & Installation

### 1. Prerequisites (Package Managers)

**Arch Linux / EndeavourOS / CachyOS:**
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

## Architecture Overview

```
LOQ/
├── main.py                   # App entry point & Phase 0 hardware discovery
├── discovery.py              # System & hardware capability matrix detection
├── config.py                 # Persistent TOML configuration manager
├── app.py                    # QApplication setup & global dark QSS theme
├── tray.py                   # System tray icon & context menu
├── helper/
│   └── loq_helper.py         # Root privileged backend helper script
├── backend/
│   ├── monitor.py            # Real-time background telemetry polling thread
│   ├── power_profiles.py     # ACPI platform_profile & power-profiles-daemon wrapper
│   ├── gpu_switch.py         # envycontrol wrapper with non-blocking QThread
│   ├── keyboard_light.py     # ITE HID keyboard RGB controller
│   └── fan_control.py        # sysfs hwmon fan read/write module
└── dashboard/
    ├── window.py             # Main QMainWindow container
    ├── monitor_tab.py        # Hardware monitoring dashboard grid
    ├── processes_tab.py      # Process Manager tab (Task Inspector & End Task controls)
    ├── power_tab.py          # Power Profiles & Battery Conservation Mode (80% capping)
    ├── gpu_tab.py            # GPU Mode switcher panel (Integrated / Hybrid / Discrete)
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
  Battery Cap 80% : YES (conservation_mode enabled)
  GPU Switcher    : envycontrol
  Priv Helper     : INSTALLED (/usr/local/bin/loq-helper)
==============================================
```

---

## Uninstallation

To cleanly remove LOQ Control Center, sudoers rules, udev rules, and desktop integration:

```bash
cd ~/Documents/LOQ
sudo ./scripts/install.sh --uninstall  # or ./scripts/uninstall.sh
```

---

## License

Distributed under the **GPL-3.0-or-later** License.

---

## Author & Credit

Made with ❤️ by **ALEX** ([@Alex389-1](https://github.com/Alex389-1))
