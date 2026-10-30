# JARVIS Background Sentinel

The Background Sentinel provides independent system monitoring and reminder processing, separate from the interactive JARVIS assistant.

## What it does

- **System monitoring**: CPU, memory, disk, temperature, and battery
- **Reminder processing**: Triggers due reminders via desktop notifications
- **Alert deduplication**: Prevents alert spam with configurable cooldowns

## Usage

### One-shot check
```bash
jarvis-sentinel --once
# or: .venv/bin/python -m jarvis.sentinel --once
```

### Check a specific metric
```bash
jarvis-sentinel --check-cpu
```

### View status
```bash
jarvis-sentinel --status
```

### Continuous monitoring
```bash
jarvis-sentinel  # runs as daemon
```

## As a systemd user service

### Install
```bash
# Copy the service file
cp jarvis-sentinel.service ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable (starts at login)
systemctl --user enable jarvis-sentinel.service

# Start now
systemctl --user start jarvis-sentinel.service
```

### Control
```bash
systemctl --user status jarvis-sentinel.service
systemctl --user stop jarvis-sentinel.service
systemctl --user restart jarvis-sentinel.service
systemctl --user disable jarvis-sentinel.service  # don't start automatically
```

### Uninstall
```bash
systemctl --user stop jarvis-sentinel.service
systemctl --user disable jarvis-sentinel.service
rm ~/.config/systemd/user/jarvis-sentinel.service
systemctl --user daemon-reload
```

## Configuration

Edit `config.yaml` under `heartbeat.checks`:

```yaml
heartbeat:
  enabled: true
  poll_seconds: 60
  checks:
    cpu:
      enabled: true
      warning_percent: 85.0
      critical_percent: 95.0
      interval_seconds: 60
    memory:
      enabled: true
      memory_warning_percent: 15.0
      memory_critical_percent: 7.0
      interval_seconds: 60
    disk:
      enabled: true
      disk_warning_percent: 85.0
      disk_critical_percent: 95.0
      interval_seconds: 300
    battery:
      enabled: true
      battery_warning_percent: 20.0
      battery_critical_percent: 10.0
      interval_seconds: 60
```

## Requirements

- `psutil` Python package
- `notify-send` (libnotify-bin on Ubuntu/Debian) for desktop notifications
- `pyyaml` for config parsing

## State files

Located in `~/.jarvis/state/`:
- `sentinel.pid` - PID file (deleted when stopped)
- `inbox.json` - Shared notices with interactive assistant
- `sentinel_debounce.json` - Alert deduplication state

## Safety

The sentinel is read-only by default. It will:
- Only display warnings, not kill processes
- Only notify about reminders, not create them
- Never modify files without explicit permission

## Known limitations

- Temperature monitoring requires working sensors
- Notification delivery depends on desktop notification daemon
- Does not monitor during system suspend