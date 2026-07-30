# LOQ Control Center for Linux

A unified GUI control center for **Lenovo LOQ / Legion laptops** on Linux.

Monitor CPU, RAM, Disk, Intel iGPU, and NVIDIA dGPU in real time.  
Switch power profiles. Control fan curves. Manage GPU modes. All in one place.

---

## Features

| Feature | Status |
|---|---|
| Live CPU/RAM/Disk monitoring | ✅ Always available |
| NVIDIA dGPU monitoring (util, VRAM, temp, power) | ✅ If NVIDIA drivers present |
| Intel iGPU monitoring | ✅ If `intel_gpu_top` installed |
| Fan RPM monitoring | ✅ If `legion_laptop` module loaded |
| Fan curve + manual control | ⚙️ Hardware-dependent (Phase 0 auto-detects) |
| Power profile switching | ✅ If `power-profiles-daemon` running |
| GPU mode switching (Integrated/Hybrid/Discrete) | ✅ If `envycontrol` installed |
| System tray + background service | ✅ |
| Privilege escalation via polkit | ✅ Root-only for fan/GPU writes |

---

## Quick Start

### 1. Install system dependencies

**Arch Linux:**
```bash
sudo pacman -S python intel-gpu-tools power-profiles-daemon
pip install envycontrol          # GPU switching
```

**Ubuntu/Debian:**
```bash
sudo apt install python3 intel-gpu-tools power-profiles-daemon
pip install envycontrol
```

### 2. Install the legion_laptop module (recommended)

If your kernel doesn't already have `lenovo_wmi_*` modules, install the DKMS module from [LenovoLegionLinux](https://github.com/johnfanv2/LenovoLegionLinux).

### 3. Install LOQ Control Center

```bash
git clone <this-repo> ~/Documents/LOQ
cd ~/Documents/LOQ
sudo ./scripts/install.sh
```

### 4. Run

```bash
loq-control                 # Start with tray icon
loq-control --discover      # Print hardware capability matrix
loq-control --no-tray       # Windowed mode (useful for testing)
loq-control --debug         # Verbose logging
```

### 5. Run as a background service

```bash
systemctl --user start loq-control
systemctl --user status loq-control
journalctl --user -u loq-control -f   # View logs
```

---

## Architecture

```
loq_control/
├── main.py           Entry point (Phase 0 + launch GUI)
├── discovery.py      Hardware capability detection
├── config.py         TOML config persistence
├── app.py            QApplication + global stylesheet
├── tray.py           System tray icon + quick menu
├── backend/
│   ├── monitor.py    QThread polling (CPU/RAM/GPU/fans)
│   ├── power_profiles.py  powerprofilesctl wrapper
│   ├── gpu_switch.py      envycontrol/supergfxctl wrapper
│   └── fan_control.py     sysfs hwmon fan read/write
└── dashboard/
    ├── window.py     Main QMainWindow
    ├── monitor_tab.py   Live metrics grid
    ├── power_tab.py     Power profile buttons
    ├── fan_tab.py       Fan RPM + curve editor
    ├── gpu_tab.py       GPU mode switcher
    └── widgets/
        ├── sparkline.py    QPainter history graph
        ├── metric_card.py  Reusable stat card
        └── fan_curve.py    Interactive curve editor

helper/
└── loq_helper.py     Root-owned privileged helper (installed to /usr/local/bin/)

polkit/
└── com.github.loq-control.policy

systemd/
└── loq-control.service
```

---

## Phase 0 — Hardware Discovery

Run this before using any hardware control features:

```bash
loq-control --discover
```

Example output:
```
=== LOQ Control Center — Capability Matrix ===
  Kernel          : 6.9.3-arch1-1
  CPU             : Intel(R) Core(TM) i5-13450HX

  Fan module      : legion_laptop
  Fan hwmon path  : /sys/class/hwmon/hwmon4
  Fan RPM read    : YES
  Fan curve read  : YES
  Fan curve write : YES (control enabled)

  Power profiles  : YES
  Profiles        : power-saver, balanced, performance

  NVIDIA (NVML)   : YES — NVIDIA GeForce RTX 4050 Laptop GPU
  intel_gpu_top   : YES

  GPU switcher    : envycontrol
  Priv helper     : INSTALLED
==============================================
```

---

## Privilege Model

The GUI process **never runs as root**. Hardware writes go through a minimal privileged helper:

```
GUI (unprivileged)
    └─ pkexec /usr/local/bin/loq-helper <subcommand>
           └─ polkit prompts once per session (auth_admin_keep)
```

The helper only accepts a whitelist of subcommands with strict input validation. No arbitrary file paths, no shell=True.

---

## Known Limitations

- **Fan curve writes**: Not functional on all LOQ BIOS versions. Run `--discover` to check. The UI shows monitoring-only mode with an explanation when unsupported.
- **GPU power limits**: NVIDIA GPU clock/wattage is not reliably increased by `performance` mode on Linux — the UI describes this honestly rather than overpromising.
- **GPU mode switching** requires logout (Integrated/Hybrid) or reboot (Discrete). The UI warns and offers to trigger the restart.

---

## Config

Config stored at `~/.config/loq-control/config.toml`:

```toml
[general]
refresh_interval_ms = 1000
restore_profile_on_login = false
last_power_profile = "balanced"
start_minimized = false

[ui]
x = 100
y = 100
width = 1100
height = 720
```

---

## License

GPL-3.0-or-later
