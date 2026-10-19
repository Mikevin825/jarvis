"""File listing — lets JARVIS list files in a directory.

A read-only tool that lists files in a given directory. Useful for finding
files, checking what's in a folder, or locating specific file types.

This is a read-only action — it never modifies anything.
"""

from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolError


def list_files(
    path: str,
    pattern: str = "*",
    max_results: int = 50,
) -> str:
    """List files in a directory.

    Args:
        path: The directory to list.
        pattern: Glob pattern to filter files (default "*").
        max_results: Maximum number of results to return (default 50).

    Returns:
        A formatted list of files.

    Raises:
        ToolError: If the path doesn't exist or isn't a directory.
    """
    directory = Path(path).expanduser().resolve()

    if not directory.exists():
        raise ToolError(f"The path '{path}' does not exist.")

    if not directory.is_dir():
        raise ToolError(f"The path '{path}' is not a directory.")

    try:
        files = sorted(directory.glob(pattern))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Could not list files: {exc}") from exc

    # Filter to files only (not directories)
    files = [f for f in files if f.is_file()]

    if not files:
        return f"No files found in '{directory}' matching '{pattern}'."

    # Apply max results
    shown = files[:max_results]
    truncated = len(files) > max_results

    lines = [f"{len(files)} file(s) in '{directory}' matching '{pattern}':"]
    for f in shown:
        size = f.stat().st_size
        if size < 1024:
            size_str = f"{size} B"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size / (1024 * 1024):.1f} MB"
        lines.append(f"  {f.name} ({size_str})")

    if truncated:
        lines.append(f"  ... and {len(files) - max_results} more.")

    return "\n".join(lines)


def build() -> list[Tool]:
    """Assemble the file listing tool."""
    return [
        Tool(
            name="list_files",
            description=(
                "Use this to list files in a directory. "
                "Returns file names and sizes. "
                "Call it when the user asks to list files, find files, or "
                "check what's in a folder."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "The directory to list, e.g. '~/Music' or '/home/user/Documents'.",
                    },
                    "pattern": {
                        "type": "STRING",
                        "description": "Glob pattern to filter files (default '*', e.g. '*.mp3').",
                    },
                    "max_results": {
                        "type": "INTEGER",
                        "description": "Maximum number of results to return (default 50).",
                    },
                },
                "required": ["path"],
            },
            func=list_files,
        ),
    ]
