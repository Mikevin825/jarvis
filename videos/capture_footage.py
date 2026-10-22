#!/usr/bin/env python3
"""Capture real footage of the JARVIS interfaces from the X display.

The video should show him actually running, not a description of it. So this
opens each interface in Chrome at a known position and records that window
region with ffmpeg's x11grab.

Geometry is discovered rather than assumed: the script reads the X screen size
and lays the captures out inside it, so a different monitor resolution still
produces correctly framed footage.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = Path("/tmp/jarvis-footage")
CHROME = shutil.which("google-chrome") or shutil.which("chromium")
DASHBOARD = "http://127.0.0.1:8790/"
GALAXY = "http://127.0.0.1:8790/galaxy/"
MIND = "http://127.0.0.1:8792/"

# The display must be passed explicitly: subprocesses here do not inherit it.
DISPLAY = os.environ.get("DISPLAY", ":0")


def screen_size() -> tuple[int, int]:
    """The X screen size in pixels, via xdpyinfo."""
    out = subprocess.run(
        ["xdpyinfo", "-display", DISPLAY], capture_output=True, text=True
    )
    for line in out.stdout.splitlines():
        if line.strip().startswith("dimensions:"):
            dims = line.split()[1]  # e.g. 1920x1080
            w, h = dims.split("x")
            return int(w), int(h)
    # Fall back to a sane 1080p assumption, but say so.
    print(f"  ! could not read screen size ({out.stderr.strip()[:80]}), assuming 1920x1080",
          file=sys.stderr)
    return 1920, 1080


# Software WebGL. The galaxy and the mind map are three.js, and this machine's
# Intel HD 4400 has no working GL — without SwiftShader the canvas renders
# black and the "footage" is a dark screen with a cursor on it.
#
# --disable-gpu-sandbox is deliberately absent: Chrome shows a full-width
# warning banner for it, and that banner would be burned into every frame.
CHROME_FLAGS = [
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--autoplay-policy=no-user-gesture-required",
]


def kill_chrome() -> None:
    """Close every Chrome window before the next shot.

    `--app` windows can survive a terminate() on the launcher process, and a
    leftover window from an earlier shot then sits on top of the next one and
    the recording captures the wrong interface.
    """
    subprocess.run(
        ["pkill", "-f", "chrome.*--app="],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)


def launch(url: str, x: int, y: int, w: int, h: int, profile: Path) -> subprocess.Popen:
    """Open a Chrome app window at an exact position and size.

    Each capture gets its own profile directory: two Chrome instances sharing
    one profile do not open two windows, and the second launch just adds a tab
    to the first — which leaves one of the recordings pointing at the wrong
    thing.
    """
    cmd = [
        CHROME,
        "--app=" + url,
        f"--window-position={x},{y}",
        f"--window-size={w},{h}",
        "--new-window",
        "--disable-session-crashed-bubble",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
        *CHROME_FLAGS,
    ]
    env = {**os.environ, "DISPLAY": DISPLAY}
    return subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
    )


def record(x: int, y: int, w: int, h: int, out: Path, seconds: float) -> None:
    """Record a screen region to mp4.

    DISPLAY is passed through the environment rather than as an ffmpeg flag —
    x11grab has no -display option, and adding one makes ffmpeg exit 8.
    """
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "x11grab",
            "-framerate", "30",
            "-video_size", f"{w}x{h}",
            "-i", f"{DISPLAY}+{x},{y}",
            "-t", str(seconds),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(out),
        ],
        check=True,
        env={**os.environ, "DISPLAY": DISPLAY},
    )


def frame_brightness(x: int, y: int, w: int, h: int) -> float:
    """Mean brightness (0-1) of the current screen region.

    Used to tell "the canvas is drawing" from "the canvas is still black".
    Software WebGL on this machine renders at roughly 10fps and takes tens of
    seconds to come up, so waiting a fixed time is not enough — the recording
    has to wait for the render itself.
    """
    tmp = WORK / "_probe.png"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "x11grab", "-video_size", f"{w}x{h}",
            "-i", f"{DISPLAY}+{x},{y}", "-frames:v", "1", str(tmp),
        ],
        check=True,
        env={**os.environ, "DISPLAY": DISPLAY},
    )
    out = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp), "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    tmp.unlink(missing_ok=True)
    for line in out.stderr.splitlines():
        if "YAVG" in line:
            try:
                return float(line.split("=")[1])
            except (IndexError, ValueError):
                pass
    return 0.0


def wait_for_render(
    x: int, y: int, w: int, h: int,
    *, threshold: float = 3.0, timeout: float = 90.0, poll: float = 4.0,
) -> bool:
    """Block until the region is drawing something, or the timeout expires.

    Returns True if it rendered in time. A black canvas averages near zero, so
    a threshold of a few units means "there is content here".
    """
    deadline = time.time() + timeout
    best = 0.0
    while time.time() < deadline:
        brightness = frame_brightness(x, y, w, h)
        best = max(best, brightness)
        if brightness >= threshold:
            return True
        time.sleep(poll)
    print(f"  ! region never reached brightness {threshold} (best {best:.1f})",
          file=sys.stderr)
    return False


def settle(seconds: float = 3.0) -> None:
    time.sleep(seconds)


def main() -> int:
    if not CHROME:
        print("no Chrome/Chromium found", file=sys.stderr)
        return 1

    WORK.mkdir(parents=True, exist_ok=True)
    W, H = screen_size()
    print(f"screen: {W}x{H}")

    shots = WORK / "shots"
    shots.mkdir(exist_ok=True)

    # ---- 1. the combined dashboard: galaxy + mind map side by side --------
    print("capturing dashboard")
    win = launch(DASHBOARD, 0, 0, W, H, WORK / "profile_dash")
    settle(6)
    wait_for_render(0, 0, W, H, timeout=120)
    settle(4)
    record(0, 0, W, H, shots / "dashboard.mp4", 16)
    win.terminate()
    settle(2)

    # ---- 2. the galaxy full screen ---------------------------------------
    print("capturing galaxy")
    win = launch(GALAXY, 0, 0, W, H, WORK / "profile_galaxy")
    settle(6)
    # Software WebGL needs far longer than a GL-accelerated machine; the
    # brightness probe is what actually tells us the orb is on screen.
    wait_for_render(0, 0, W, H, timeout=150, threshold=4.0)
    settle(6)
    import threading

    driver = threading.Thread(target=drive_galaxy, args=(WORK,), daemon=True)
    driver.start()
    record(0, 0, W, H, shots / "galaxy.mp4", 18)
    win.terminate()
    settle(2)

    # ---- 3. the living mind map -------------------------------------------
    print("capturing mind map")
    win = launch(MIND, 0, 0, W, H, WORK / "profile_mind")
    settle(6)
    wait_for_render(0, 0, W, H, timeout=120, threshold=4.0)
    settle(4)
    record(0, 0, W, H, shots / "mindmap.mp4", 16)
    win.terminate()

    settle(2)
    print(f"\nfootage in {shots}")
    for f in sorted(shots.glob("*.mp4")):
        print(f"  {f.name}: {f.stat().st_size:,} bytes")
    return 0


def drive_galaxy(work: Path) -> None:
    """Write state files so the orb visibly changes during the recording."""
    import json

    state_dir = ROOT / "state"

    def write(name: str, payload) -> None:
        (state_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    # A short sequence: thinking -> speaking -> idle, which is the arc the
    # galaxy is built to animate.
    write("galaxy-state.json", {"state": "thinking", "ts": time.time()})
    time.sleep(3)
    write("galaxy-state.json", {"state": "speaking", "ts": time.time()})
    time.sleep(3)
    write("galaxy-state.json", {"state": "idle", "ts": time.time()})


if __name__ == "__main__":
    raise SystemExit(main())
