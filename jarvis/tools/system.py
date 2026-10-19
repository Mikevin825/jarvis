"""System inspection — RAM, CPU, running processes, disk.

Read-only, stdlib-only, Linux /proc. No external dependencies.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .base import Tool, ToolError

# ── Helpers ─────────────────────────────────────────────────────────────────


def _read_proc(path: str) -> str:
    try:
        return Path(path).read_text()
    except (OSError, IOError):
        return ""


def _parse_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into a dict of kB values."""
    data: dict[str, int] = {}
    for line in _read_proc("/proc/meminfo").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            data[parts[0].rstrip(":")] = int(parts[1])
    return data


def _parse_loadavg() -> dict[str, float]:
    parts = _read_proc("/proc/loadavg").split()
    return {
        "1min": float(parts[0]),
        "5min": float(parts[1]),
        "15min": float(parts[2]),
    }


def _get_processes() -> list[dict]:
    """Get top processes by memory using ps."""
    try:
        result = subprocess.run(
            ["ps", "aux", "--sort=-%mem"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        return []

    # Skip header
    processes = []
    for line in lines[1:21]:  # Top 20
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        processes.append({
            "user": parts[0],
            "pid": parts[1],
            "cpu": parts[2],
            "mem": parts[3],
            "rss": parts[5],
            "command": parts[10][:80],
        })
    return processes


def _get_disk_usage() -> list[dict]:
    """Get disk usage for mounted filesystems."""
    try:
        result = subprocess.run(
            ["df", "-h", "--output=source,size,used,avail,pcent,target"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        return []

    filesystems = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 6:
            filesystems.append({
                "device": parts[0],
                "size": parts[1],
                "used": parts[2],
                "avail": parts[3],
                "percent": parts[4],
                "mount": parts[5],
            })
    return filesystems


def _get_uptime() -> str:
    content = _read_proc("/proc/uptime")
    if not content:
        return "unknown"
    seconds = float(content.split()[0])
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _get_cpu_info() -> str:
    """Get CPU model name."""
    for line in _read_proc("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "unknown"


# ── Tool functions ──────────────────────────────────────────────────────────


def get_ram_usage() -> str:
    """Report current RAM and swap usage."""
    mem = _parse_meminfo()
    if not mem:
        raise ToolError("Could not read memory information.")

    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    used = total - available
    percent = (used / total * 100) if total else 0

    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    swap_used = swap_total - swap_free
    swap_percent = (swap_used / swap_total * 100) if swap_total else 0

    def mb(kb: int) -> str:
        return f"{kb / 1024:.0f} MB"

    lines = [
        f"RAM: {mb(used)} / {mb(total)} used ({percent:.0f}%)",
        f"Available: {mb(available)}",
    ]
    if swap_total > 0:
        lines.append(f"Swap: {mb(swap_used)} / {mb(swap_total)} used ({swap_percent:.0f}%)")
    return "\n".join(lines)


def get_cpu_usage() -> str:
    """Report CPU load and model."""
    load = _parse_loadavg()
    cpu_count = os.cpu_count() or 1
    model = _get_cpu_info()
    return (
        f"CPU: {model}\n"
        f"Cores: {cpu_count}\n"
        f"Load average: {load['1min']:.2f} (1min), {load['5min']:.2f} (5min), {load['15min']:.2f} (15min)\n"
        f"Uptime: {_get_uptime()}"
    )


def get_top_processes() -> str:
    """Report top 15 processes by memory usage."""
    procs = _get_processes()
    if not procs:
        raise ToolError("Could not retrieve process list.")

    lines = ["Top processes by memory:"]
    lines.append(f"{'USER':<10} {'PID':>6} {'%CPU':>5} {'%MEM':>5} {'RSS':>8}  COMMAND")
    lines.append("-" * 70)
    for p in procs[:15]:
        rss_mb = int(p["rss"]) / 1024
        lines.append(
            f"{p['user']:<10} {p['pid']:>6} {p['cpu']:>5} {p['mem']:>5} {rss_mb:>7.0f}M  {p['command']}"
        )
    return "\n".join(lines)


def get_disk_usage() -> str:
    """Report disk usage for all mounted filesystems."""
    fs = _get_disk_usage()
    if not fs:
        raise ToolError("Could not retrieve disk usage.")

    lines = ["Disk usage:"]
    lines.append(f"{'DEVICE':<16} {'SIZE':>6} {'USED':>6} {'AVAIL':>6} {'%':>4}  MOUNT")
    lines.append("-" * 60)
    for f in fs:
        lines.append(
            f"{f['device']:<16} {f['size']:>6} {f['used']:>6} {f['avail']:>6} {f['percent']:>4}  {f['mount']}"
        )
    return "\n".join(lines)


def get_system_summary() -> str:
    """Report a full system summary."""
    parts = [
        get_ram_usage(),
        "",
        get_cpu_usage(),
        "",
        get_disk_usage(),
    ]
    return "\n".join(parts)


# ── Registration ────────────────────────────────────────────────────────────

_PARAMS_EMPTY = {
    "type": "OBJECT",
    "properties": {},
    "required": [],
}


def build() -> list[Tool]:
    return [
        Tool(
            name="get_ram_usage",
            description=(
                "Use this to check current memory (RAM) and swap usage on the machine "
                "JARVIS runs on. Returns total, used, and available memory."
            ),
            parameters=_PARAMS_EMPTY,
            func=get_ram_usage,
        ),
        Tool(
            name="get_cpu_usage",
            description=(
                "Use this to check CPU load, core count, processor model, and uptime."
            ),
            parameters=_PARAMS_EMPTY,
            func=get_cpu_usage,
        ),
        Tool(
            name="get_top_processes",
            description=(
                "Use this to see which processes are using the most memory. "
                "Returns the top 15 processes sorted by RAM usage."
            ),
            parameters=_PARAMS_EMPTY,
            func=get_top_processes,
        ),
        Tool(
            name="get_disk_usage",
            description=(
                "Use this to check disk space usage on all mounted filesystems."
            ),
            parameters=_PARAMS_EMPTY,
            func=get_disk_usage,
        ),
        Tool(
            name="get_system_summary",
            description=(
                "Use this for a full system overview — RAM, CPU, disk, and uptime "
                "in one call."
            ),
            parameters=_PARAMS_EMPTY,
            func=get_system_summary,
        ),
    ]
