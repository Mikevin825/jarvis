"""System resource monitoring checks for the heartbeat.

These checks monitor CPU, memory, disk, and battery to provide
proactive alerts about system health.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fallback when psutil is not available
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class CheckResult:
    """Check result dataclass."""
    surfaced: bool = False
    title: str = ""
    body: str = ""
    level: str = "normal"
    summary: str = ""


class CPUCheck:
    """Monitor CPU utilization and identify high-consuming processes."""

    name = "cpu"

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings

    def _get_threshold(self, key: str, default: float) -> float:
        try:
            return float(self.settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def run(self, ctx) -> CheckResult:
        if not HAS_PSUTIL:
            return CheckResult(summary="psutil not available for CPU monitoring")

        warning_threshold = self._get_threshold("warning_percent", 85.0)
        critical_threshold = self._get_threshold("critical_percent", 95.0)

        try:
            cpu_percent = psutil.cpu_percent(interval=1.0)
            cpu_count = psutil.cpu_count() or 1
            top_processes = self._get_top_cpu_processes(5)
        except Exception:
            return CheckResult(summary="Failed to read CPU metrics")

        if cpu_percent >= critical_threshold:
            return self._critical_result(cpu_percent, top_processes, cpu_count, critical_threshold)
        elif cpu_percent >= warning_threshold:
            return self._warning_result(cpu_percent, top_processes, cpu_count, warning_threshold)
        else:
            return CheckResult(summary=f"CPU utilization at {cpu_percent:.1f}%")

    def _get_top_cpu_processes(self, count: int) -> list:
        try:
            processes = []
            for proc in list(psutil.process_iter(['name', 'cpu_percent'])):
                try:
                    name = proc.info.get('name', 'unknown')
                    cpu = proc.info.get('cpu_percent', 0) or 0
                    processes.append((name, cpu))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if len(processes) >= count:
                    break
            return sorted(processes, key=lambda x: x[1], reverse=True)
        except Exception:
            return []

    def _critical_result(self, percent, processes, cpu_count, critical_threshold) -> CheckResult:
        from jarvis.heartbeat.inbox import URGENT
        proc_info = ""
        if processes:
            top = processes[0]
            proc_info = f"\n   Top consumer: {top[0]} ({top[1]:.1f}% CPU)"
        return CheckResult(
            surfaced=True,
            title=f"CPU critical: {percent:.1f}% utilization",
            body=f"Sir, CPU utilization is at {percent:.1f}%, exceeding the critical threshold of {critical_threshold:.1f}%.{proc_info} System has {cpu_count} CPU cores available.",
            level=URGENT,
            summary=f"critical CPU {percent:.1f}%"
        )

    def _warning_result(self, percent, processes, cpu_count, warning_threshold) -> CheckResult:
        from jarvis.heartbeat.inbox import NORMAL
        proc_info = ""
        if processes:
            top = processes[0]
            proc_info = f"\n   Top consumer: {top[0]} ({top[1]:.1f}% CPU)"
        return CheckResult(
            surfaced=True,
            title=f"CPU warning: {percent:.1f}% utilization",
            body=f"Sir, CPU utilization has reached {percent:.1f}%, approaching the warning threshold of {warning_threshold:.1f}%.{proc_info}",
            level=NORMAL,
            summary=f"warning CPU {percent:.1f}%"
        )


class MemoryCheck:
    """Monitor system memory and swap usage."""

    name = "memory"

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings

    def _get_threshold(self, key: str, default: float) -> float:
        try:
            return float(self.settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def run(self, ctx) -> CheckResult:
        if not HAS_PSUTIL:
            return CheckResult(summary="psutil not available for memory monitoring")

        mem_warn = self._get_threshold("memory_warning_percent", 15.0)
        mem_crit = self._get_threshold("memory_critical_percent", 7.0)
        swap_warn = self._get_threshold("swap_wear_percent", 20.0)
        swap_crit = self._get_threshold("swap_critical_percent", 50.0)

        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
        except Exception:
            return CheckResult(summary="Failed to read memory metrics")

        mem_available_pct = mem.available / mem.total * 100
        swap_pct = swap.percent

        if mem_available_pct <= mem_crit or swap_pct >= swap_crit:
            return self._critical_result(mem, swap, mem_crit)
        elif mem_available_pct <= mem_warn or swap_pct >= swap_warn:
            return self._warning_result(mem, swap, mem_warn, swap_warn)
        else:
            return CheckResult(summary=f"Memory: {mem.percent:.0f}% used, swap: {swap.percent:.0f}%")

    def _critical_result(self, mem, swap, mem_crit) -> CheckResult:
        from jarvis.heartbeat.inbox import URGENT
        processes = self._get_top_memory_processes(3)
        proc_info = ""
        if processes:
            proc_info = "\n   Top consumers: " + ", ".join(
                f"{p[0]} ({p[1]:.0f}%) " for p in processes[:3]
            ).rstrip()
        return CheckResult(
            surfaced=True,
            title=f"Memory critical: only {mem.available / mem.total * 100:.1f}% available",
            body=f"Sir, system memory is under severe pressure.\n   Available: {mem.available / (1024**3):.1f}GB of {mem.total / (1024**3):.1f}GB ({mem.percent:.1f}% used).\n   Swap: {swap.percent:.1f}%.\n{proc_info}",
            level=URGENT,
            summary=f"critical memory {mem.available / mem.total * 100:.1f}% available"
        )

    def _warning_result(self, mem, swap, mem_warn, swap_warn) -> CheckResult:
        from jarvis.heartbeat.inbox import NORMAL
        processes = self._get_top_memory_processes(3)
        proc_info = ""
        if processes:
            proc_info = "\n   Top consumers: " + ", ".join(
                f"{p[0]} ({p[1]:.0f}%) " for p in processes[:3]
            ).rstrip()
        return CheckResult(
            surfaced=True,
            title=f"Memory warning: {mem.available / mem.total * 100:.1f}% available",
            body=f"Sir, memory availability is low.\n   Available: {mem.available / (1024**3):.1f}GB ({mem.percent:.1f}% used).\n   Swap: {swap.percent:.1f}%.\n{proc_info}",
            level=NORMAL,
            summary=f"warning memory {mem.available / mem.total * 100:.1f}% available"
        )

    def _get_top_memory_processes(self, count: int) -> list:
        try:
            processes = []
            for proc in list(psutil.process_iter(['name', 'memory_percent'])):
                try:
                    name = proc.info.get('name', 'unknown')
                    mem = proc.info.get('memory_percent', 0) or 0
                    processes.append((name, mem))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if len(processes) >= count:
                    break
            return sorted(processes, key=lambda x: x[1], reverse=True)
        except Exception:
            return []


class DiskCheck:
    """Monitor disk space on relevant filesystems."""

    name = "disk"

    MONITORED_PATHS = ['/', '/home']

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings

    def _get_threshold(self, key: str, default: float) -> float:
        try:
            return float(self.settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def run(self, ctx) -> CheckResult:
        if not HAS_PSUTIL:
            return CheckResult(summary="psutil not available for disk monitoring")

        warn_threshold = self._get_threshold("disk_warning_percent", 85.0)
        crit_threshold = self._get_threshold("disk_critical_percent", 95.0)

        alerts = []
        try:
            for path in self.MONITORED_PATHS:
                try:
                    usage = psutil.disk_usage(path)
                    pct = usage.percent
                    free_gb = usage.free / (1024**3)
                    if pct >= crit_threshold:
                        alerts.append(f"{path}: CRITICAL {pct:.0f}% ({free_gb:.1f}GB free)")
                    elif pct >= warn_threshold:
                        alerts.append(f"{path}: warning {pct:.0f}% ({free_gb:.1f}GB free)")
                except Exception:
                    continue
        except Exception:
            return CheckResult(summary="Failed to read disk metrics")

        if alerts:
            from jarvis.heartbeat.inbox import URGENT, NORMAL
            level = URGENT if any("CRITICAL" in a for a in alerts) else NORMAL
            return CheckResult(
                surfaced=True,
                title="Disk space warning",
                body="Sir, disk usage is elevated on:\n   " + "\n   ".join(alerts),
                level=level,
                summary="; ".join(alerts)
            )

        return CheckResult(summary="Disk space OK")


class TemperatureCheck:
    """Monitor system temperature (where available)."""

    name = "temperature"

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings

    def _get_threshold(self, key: str, default: float) -> float:
        try:
            return float(self.settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def run(self, ctx) -> CheckResult:
        if not HAS_PSUTIL:
            return CheckResult(summary="psutil not available for temperature monitoring")

        warn_threshold = self._get_threshold("temp_warning_celsius", 75.0)
        crit_threshold = self._get_threshold("temp_critical_celsius", 85.0)

        temps = self._get_temperatures()
        if not temps:
            return CheckResult(summary="No temperature sensors available")

        max_temp = max(t[1] for t in temps)

        if max_temp >= crit_threshold:
            return self._critical_result(temps, max_temp)
        elif max_temp >= warn_threshold:
            return self._warning_result(temps, max_temp, warn_threshold)
        else:
            return CheckResult(summary=f"System temperature: {max_temp:.1f}°C")

    def _get_temperatures(self) -> list:
        try:
            temps = []
            for entry in psutil.sensors_temperatures().values():
                for t in entry:
                    if t.current is not None and t.current > 0:
                        temps.append((t.label or "sensor", t.current))
            return temps
        except Exception:
            return []

    def _critical_result(self, temps, max_temp) -> CheckResult:
        from jarvis.heartbeat.inbox import URGENT
        hot_sensors = [f"{t[0]}: {t[1]:.1f}°C" for t in temps if t[1] >= 80]
        return CheckResult(
            surfaced=True,
            title=f"System temperature critical: {max_temp:.1f}°C",
            body=f"Sir, system temperature is elevated.\n   Critical sensors: {', '.join(hot_sensors) if hot_sensors else f'{max_temp:.1f}°C'}.",
            level=URGENT,
            summary=f"critical temp {max_temp:.1f}°C"
        )

    def _warning_result(self, temps, max_temp, warn_threshold) -> CheckResult:
        from jarvis.heartbeat.inbox import NORMAL
        return CheckResult(
            surfaced=True,
            title=f"System temperature warning: {max_temp:.1f}°C",
            body=f"Sir, temperature has reached {max_temp:.1f}°C, approaching the warning threshold of {warn_threshold:.1f}°C.",
            level=NORMAL,
            summary=f"warning temp {max_temp:.1f}°C"
        )


class BatteryCheck:
    """Monitor battery status for laptops."""

    name = "battery"

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings

    def _get_threshold(self, key: str, default: float) -> float:
        try:
            return float(self.settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def run(self, ctx) -> CheckResult:
        if not HAS_PSUTIL:
            return CheckResult(summary="psutil not available for battery monitoring")

        battery = psutil.sensors_battery()
        if battery is None:
            return CheckResult(summary="No battery detected")

        warn_percent = self._get_threshold("battery_warning_percent", 20.0)
        crit_percent = self._get_threshold("battery_critical_percent", 10.0)

        percent = battery.percent

        if battery.power_plugged:
            if percent >= 95:
                return CheckResult(summary=f"Battery at {percent}% and charging")
            return CheckResult(summary=f"Battery at {percent}% (plugged in)")
        else:
            if percent <= crit_percent:
                from jarvis.heartbeat.inbox import URGENT
                return CheckResult(
                    surfaced=True,
                    title=f"Battery critical: {percent}% remaining",
                    body=f"Sir, battery level has dropped to {percent}%. Consider plugging in soon.",
                    level=URGENT,
                    summary=f"crit battery {percent}%"
                )
            elif percent <= warn_percent:
                from jarvis.heartbeat.inbox import NORMAL
                return CheckResult(
                    surfaced=True,
                    title=f"Battery low: {percent}% remaining",
                    body=f"Sir, battery is at {percent}%. Find a charger before it depletes.",
                    level=NORMAL,
                    summary=f"warning battery {percent}%"
                )
            return CheckResult(summary=f"Battery at {percent}% (not plugged in)")