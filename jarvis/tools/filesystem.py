"""Filesystem — the "look at my files" capability.

Read-only and needs no API key. Lets JARVIS list files in a directory, read
file contents, and search for files by name. All paths are resolved safely —
a path that escapes the user's home directory is refused.

This is the tool that makes JARVIS useful for real work: looking at files,
reading documents, finding things.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import Tool, ToolError

_HOME = Path.home()


def _safe_path(path_str: str) -> Path:
    """Resolve a path safely, refusing anything outside the home directory.

    A path that escapes the user's home directory is refused. This is the
    security boundary — without it, a tool that reads files is a tool that
    reads everything.
    """
    path = Path(path_str).expanduser().resolve()
    try:
        path.relative_to(_HOME)
    except ValueError:
        raise ToolError(
            f"Access denied: {path} is outside your home directory."
        )
    return path


def list_files(directory: str, pattern: str = "*") -> str:
    """List files in a directory, optionally filtered by a glob pattern.

    Free, no API key. Returns a plain-text list of files.
    """
    directory = (directory or "").strip()
    if not directory:
        raise ToolError("No directory was given.")

    path = _safe_path(directory)
    if not path.exists():
        raise ToolError(f"There is no directory called '{directory}'.")
    if not path.is_dir():
        raise ToolError(f"'{directory}' is not a directory.")

    try:
        files = sorted(path.glob(pattern))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Could not list files: {exc}") from exc

    if not files:
        return f"No files found in '{directory}' matching '{pattern}'."

    lines = []
    for f in files:
        if f.is_dir():
            lines.append(f"  📁 {f.name}/")
        else:
            size = f.stat().st_size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            lines.append(f"  📄 {f.name} ({size_str})")

    return f"{len(files)} item(s) in '{directory}':\n" + "\n".join(lines)


def read_file(path: str, max_chars: int = 10000) -> str:
    """Read the contents of a file.

    Free, no API key. Returns the file contents, truncated to max_chars.
    """
    path_str = (path or "").strip()
    if not path_str:
        raise ToolError("No file path was given.")

    file_path = _safe_path(path_str)
    if not file_path.exists():
        raise ToolError(f"There is no file called '{path_str}'.")
    if not file_path.is_file():
        raise ToolError(f"'{path_str}' is not a file.")

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = file_path.read_text(encoding="latin-1")
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Could not read '{path_str}': {exc}") from exc
    except OSError as exc:
        raise ToolError(f"Could not read '{path_str}': {exc}") from exc

    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n… (truncated, {len(content)} characters total)"
    return content


def search_files(directory: str, name_pattern: str) -> str:
    """Search for files by name pattern in a directory.

    Free, no API key. Returns a plain-text list of matching files.
    """
    directory = (directory or "").strip()
    if not directory:
        raise ToolError("No directory was given.")
    if not name_pattern:
        raise ToolError("No name pattern was given.")

    path = _safe_path(directory)
    if not path.exists():
        raise ToolError(f"There is no directory called '{directory}'.")
    if not path.is_dir():
        raise ToolError(f"'{directory}' is not a directory.")

    try:
        matches = sorted(path.rglob(name_pattern))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Could not search files: {exc}") from exc

    if not matches:
        return f"No files found matching '{name_pattern}' in '{directory}'."

    lines = []
    for f in matches:
        if f.is_file():
            lines.append(f"  {f.relative_to(_HOME)}")

    return f"{len(matches)} match(es) for '{name_pattern}':\n" + "\n".join(lines)


def build() -> list[Tool]:
    """Assemble the filesystem tools."""
    return [
        Tool(
            name="list_files",
            description=(
                "Use this to list files in a directory. "
                "Returns a list of files with sizes. "
                "Call it when the user asks what files are in a folder."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "directory": {
                        "type": "STRING",
                        "description": "The directory to list, e.g. '~/Music' or '~/Documents'.",
                    },
                    "pattern": {
                        "type": "STRING",
                        "description": "Optional glob pattern to filter by, e.g. '*.mp3' or '*.pdf'.",
                    },
                },
                "required": ["directory"],
            },
            func=list_files,
        ),
        Tool(
            name="read_file",
            description=(
                "Use this to read the contents of a file. "
                "Returns the file contents, truncated to a reasonable length. "
                "Call it when the user asks to read or open a file."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "The file path to read, e.g. '~/Documents/notes.txt'.",
                    },
                    "max_chars": {
                        "type": "INTEGER",
                        "description": "Maximum characters to return (default 10000).",
                    },
                },
                "required": ["path"],
            },
            func=read_file,
        ),
        Tool(
            name="search_files",
            description=(
                "Use this to search for files by name in a directory. "
                "Returns a list of matching files. "
                "Call it when the user asks to find a file."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "directory": {
                        "type": "STRING",
                        "description": "The directory to search in, e.g. '~' or '~/Documents'.",
                    },
                    "name_pattern": {
                        "type": "STRING",
                        "description": "The name pattern to search for, e.g. '*.pdf' or '*report*'.",
                    },
                },
                "required": ["directory", "name_pattern"],
            },
            func=search_files,
        ),
    ]
