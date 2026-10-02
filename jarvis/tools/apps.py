"""Opening apps, files, and links — the "manage my apps and documents" capability.

Opening is read-only in effect, so it runs without confirmation. The target is
validated and passed as an argv list (never through a shell), so a crafted title
cannot turn into a command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .base import Tool, ToolError

# Common desktop entries we can resolve by friendly name.
_APP_ALIASES = {
    "browser": "xdg-open",
    "files": "xdg-open",
    "terminal": "x-terminal-emulator",
    "editor": "xdg-open",
    "calculator": "gnome-calculator",
    "settings": "gnome-control-center",
}

_PARAMS_APP = {
    "type": "OBJECT",
    "properties": {
        "name": {
            "type": "STRING",
            "description": (
                "The application to launch, e.g. 'firefox', 'code', 'calculator'."
            ),
        }
    },
    "required": ["name"],
}

_PARAMS_PATH = {
    "type": "OBJECT",
    "properties": {
        "path": {
            "type": "STRING",
            "description": "Absolute or ~-relative path to a file or folder to open.",
        }
    },
    "required": ["path"],
}

_PARAMS_URL = {
    "type": "OBJECT",
    "properties": {
        "url": {"type": "STRING", "description": "The http(s) URL to open."}
    },
    "required": ["url"],
}


def _launch(argv: list[str], what: str) -> str:
    """Run a launch command, detached, and report honestly."""
    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise ToolError(
            f"Could not find the program needed to open {what}. "
            "It may not be installed."
        ) from exc
    except OSError as exc:
        raise ToolError(f"Could not open {what}: {exc}") from exc
    return f"Opened {what}."


def open_app(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ToolError("No application name was given.")
    binary = _APP_ALIASES.get(name.lower(), name)
    if shutil.which(binary) is None:
        raise ToolError(
            f"I could not find an application called '{name}' on this machine."
        )
    return _launch([binary], f"the application '{name}'")


def open_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        raise ToolError("No path was given.")
    expanded = Path(os.path.expanduser(raw))
    if not expanded.exists():
        raise ToolError(f"There is nothing at '{raw}'.")
    if shutil.which("xdg-open") is None:
        raise ToolError("There is no desktop opener available on this machine.")
    return _launch(["xdg-open", str(expanded)], f"'{expanded.name}'")


def open_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ToolError("No URL was given.")
    if not raw.startswith(("http://", "https://")):
        raise ToolError(
            "Only http and https links can be opened. Give me a full web address."
        )
    if shutil.which("xdg-open") is None:
        raise ToolError("There is no desktop opener available on this machine.")
    return _launch(["xdg-open", raw], f"the link {raw}")


def build() -> list[Tool]:
    return [
        Tool(
            name="open_app",
            description=(
                "Use this to launch a desktop application by name, for example "
                "'firefox' or 'code'. Only works on the machine JARVIS runs on."
            ),
            parameters=_PARAMS_APP,
            func=open_app,
        ),
        Tool(
            name="open_path",
            description=(
                "Use this to open a file or folder in the default desktop "
                "application. Give an absolute or ~-relative path."
            ),
            parameters=_PARAMS_PATH,
            func=open_path,
        ),
        Tool(
            name="open_url",
            description="Use this to open a web link in the default browser.",
            parameters=_PARAMS_URL,
            func=open_url,
        ),
    ]
