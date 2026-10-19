"""Read the contents of the active browser window.

Uses xdotool to focus the window and xclip to read the clipboard after
selecting all text. Works on any application that supports Ctrl+A / Ctrl+C.
"""

from __future__ import annotations

import subprocess
import time

from .base import Tool, ToolError


def _run_cmd(cmd: list[str], timeout: float = 5) -> str:
    """Run a command and return stdout, or raise ToolError."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except FileNotFoundError as exc:
        raise ToolError(f"Required tool not found: {exc.filename}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Command timed out: {' '.join(cmd)}") from exc


def _get_active_window() -> tuple[str, str]:
    """Get the active window ID and title.

    Tries wmctrl first (more reliable), then falls back to xdotool.
    """
    # Try wmctrl first
    try:
        result = subprocess.run(
            ["wmctrl", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().splitlines()
        # wmctrl -l format: <id> <desktop> <machine> <title>
        # The active window is typically the last one in the list or
        # we can use wmctrl -a to activate it
        for line in lines:
            parts = line.split(None, 3)
            if len(parts) >= 4:
                return parts[0], parts[3]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: use xdotool to find visible windows
    try:
        result = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--class", ""],
            capture_output=True,
            text=True,
            timeout=5,
        )
        window_ids = result.stdout.strip().splitlines()
        if window_ids:
            # Use the last visible window (most recently created/focused)
            window_id = window_ids[-1]
            title = _run_cmd(["xdotool", "getwindowname", window_id])
            return window_id, title
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    raise ToolError("Could not determine the active window.")


def read_active_window() -> str:
    """Read the text content of the currently active window.

    Focuses the window, selects all text, copies it, and reads the clipboard.
    Returns the text content, or raises ToolError if it cannot be read.
    """
    window_id, window_title = _get_active_window()

    # Focus the window
    _run_cmd(["wmctrl", "-i", "-a", window_id])
    time.sleep(0.3)

    # Select all text
    _run_cmd(["xdotool", "key", "--window", window_id, "ctrl+a"])
    time.sleep(0.2)

    # Copy to clipboard
    _run_cmd(["xdotool", "key", "--window", window_id, "ctrl+c"])
    time.sleep(0.3)

    # Read the clipboard
    content = _run_cmd(["xclip", "-o", "-selection", "clipboard"])

    if not content:
        raise ToolError(
            f"The active window ('{window_title}') returned no text. "
            "It may be a canvas-based app (like Google Maps) that does not "
            "support text selection."
        )

    return content


def build() -> list[Tool]:
    return [
        Tool(
            name="read_browser_page",
            description=(
                "Use this to read the text content of the currently active "
                "browser window. Works on most web pages and applications that "
                "support text selection. May not work on canvas-based apps like "
                "Google Maps."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {},
                "required": [],
            },
            func=read_active_window,
        ),
    ]
