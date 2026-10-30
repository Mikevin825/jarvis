"""External system control — closing apps, terminal commands, file access, GUI interaction.

These tools are powerful and potentially disruptive. All must be confirmed by the user
before running, and attempts are logged for safety.

**Warning**: These capabilities break the sandbox model. Use carefully.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .base import Tool, ToolError


# ── Close application ─────────────────────────────────────────────────--------


# Friendly names -> window classes. A window's *title* changes with what it is
# showing (a folder name, a document name, a page title), but its WM_CLASS is
# fixed for the life of the app. Matching on the class is what makes "close
# Files" work when the window says "Documents".
APP_ALIASES: dict[str, tuple[str, ...]] = {
    "files": ("nautilus", "org.gnome.nautilus", "nemo", "caja", "dolphin",
              "thunar", "pcmanfm", "files"),
    "file manager": ("nautilus", "org.gnome.nautilus", "nemo", "caja",
                     "dolphin", "thunar", "pcmanfm"),
    "browser": ("navigator", "zen", "firefox", "chrome", "chromium",
                "brave", "edge", "epiphany"),
    "terminal": ("gnome-terminal", "terminal", "konsole", "xterm",
                 "alacritty", "kitty", "tilix"),
    "editor": ("code", "sublime", "gedit", "kate", "mousepad", "atom"),
    "music": ("vlc", "spotify", "rhythmbox", "lollypop", "celluloid", "mpv"),
    "settings": ("gnome-control-center", "control-center", "settings"),
    "calculator": ("gnome-calculator", "calculator"),
    "text editor": ("gedit", "mousepad", "code", "kate"),
}


def _matches_window(query: str, win_class: str, win_title: str) -> bool:
    """Does this window match what the user asked for?

    Checks the title and the class directly, then the friendly-name aliases —
    so "files" reaches a window whose title is "Documents" but whose class is
    nautilus.Nautilus.
    """
    q = query.strip().lower()
    if not q:
        return False
    if q in win_class.lower() or q in win_title.lower():
        return True
    for alias in APP_ALIASES.get(q, ()):
        if alias in win_class.lower():
            return True
    return False


def close_app(window_title: str, by_name: bool = False) -> str:
    """Close a desktop application by window title, class, or common name.

    May require the app to be closed manually if it has unsaved work.
    Uses wmctrl or xdotool to find and close windows.

    A window's *title* is the worst thing to match on: it changes with whatever
    the app is showing — a folder name, a document name, a page title. The
    Files window is called "Documents" or "Home", never "Files". So matching
    also covers the WM_CLASS, which is fixed for the life of the app, plus a
    table of friendly names ("files" -> nautilus) so plain speech works.

    Args:
        window_title: The title, class, or common name of the window to close.
        by_name: If True, treat window_title as a process name to kill.

    Returns:
        A confirmation message.

    Raises:
        ToolError: If no suitable tool is available or the app could not be closed.
    """
    window_title = window_title.strip()
    if not window_title:
        raise ToolError("No window title or application name was provided.")

    if by_name:
        # Kill by process name
        try:
            result = subprocess.run(
                ["pkill", "-f", window_title],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return f"Sent termination signal to processes matching '{window_title}'."
            else:
                return f"No processes matching '{window_title}' were found."
        except FileNotFoundError:
            raise ToolError(
                "pkill is not available on this system. Cannot close applications "
                "by process name."
            )
        except subprocess.TimeoutExpired:
            raise ToolError("Command timed out while trying to close the application.")

    # Close by window title using wmctrl
    try:
        # First, try to find the window. wmctrl may not be installed at all, so
        # a missing binary and a failed run must both fall through to xdotool.
        try:
            find_result = subprocess.run(
                ["wmctrl", "-lx"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            find_result = None

        if find_result is None or find_result.returncode != 0:
            # wmctrl is unavailable or failed, try xdotool
            try:
                subprocess.run(
                    ["xdotool", "search", "--name", window_title, "windowclose"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return f"Sent close command to windows matching '{window_title}'."
            except FileNotFoundError:
                raise ToolError(
                    "Neither wmctrl nor xdotool is available. "
                    "Cannot close windows by title."
                )
            except subprocess.TimeoutExpired:
                raise ToolError("Timed out trying to close the window.")

        # Format with -lx: <window_id> <desktop> <WM_CLASS> <title...>
        # The title is everything after the class, because it can contain spaces.
        matching_windows = []
        for line in find_result.stdout.strip().splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            _win_id, _desktop, win_class, win_title = parts
            if _matches_window(window_title, win_class, win_title):
                matching_windows.append(_win_id)

        if not matching_windows:
            return (
                f"No windows found matching '{window_title}'. "
                "Try the app's name (for example 'files', 'terminal', 'browser')."
            )

        # Close each matching window
        for wid in matching_windows:
            try:
                subprocess.run(
                    ["wmctrl", "-i", "-c", wid],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except Exception:
                pass  # Continue to close others even if one fails

        return f"Closed {len(matching_windows)} window(s) matching '{window_title}'."

    except subprocess.TimeoutExpired:
        raise ToolError("Timed out while searching for windows.")
    except FileNotFoundError as e:
        raise ToolError(
            f"Required tool not found: {e}. "
            "Install wmctrl or xdotool to close windows by title."
        )


# ── Terminal command execution ─────────────────────────────────-------------


def run_command(command: str, timeout: int = 30) -> str:
    """Execute a shell command and return the output.

    **WARNING**: This is a dangerous tool that can do anything on the system.
    Commands run with your user's permissions and can read, write, or delete files.

    Args:
        command: The shell command to execute.
        timeout: Maximum seconds to wait before terminating (default 30).

    Returns:
        The command stdout if successful, or a description of the result.

    Raises:
        ToolError: If the command fails or times out.
    """
    command = command.strip()
    if not command:
        raise ToolError("No command was provided.")

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = []
        if result.stdout:
            output.append(result.stdout.strip())
        if result.stderr:
            output.append(f"stderr: {result.stderr.strip()}")

        if result.returncode == 0:
            return "\n".join(output) if output else "(command completed with no output)"

        return "\n".join(output) if output else f"Exit code: {result.returncode}"

    except subprocess.TimeoutExpired:
        raise ToolError(
            f"Command timed out after {timeout} seconds. "
            "It did not complete in time."
        )
    except Exception as e:
        raise ToolError(f"Command failed to execute: {e}")


# ── External file system access ─────────────────────────────────------------


def read_file(path: str, bytes_limit: int = 1048576) -> str:
    """Read the contents of any file accessible on the system.

    Can read files outside the usual workspace/directory restrictions.
    Binary files are described rather than shown as text.

    Args:
        path: Absolute path to the file, or ~-relative path.
        bytes_limit: Maximum bytes to read (default 1MB).

    Returns:
        The file contents as text, or information about a binary file.

    Raises:
        ToolError: If the file cannot be read.
    """
    path = Path(os.path.expanduser(path)).resolve()

    if not path.exists():
        raise ToolError(f"File not found: {path}")

    if not path.is_file():
        raise ToolError(f"Not a file: {path}")

    try:
        # Check file size
        size = path.stat().st_size
        if size > bytes_limit:
            raise ToolError(
                f"File is {size} bytes, which exceeds the limit of {bytes_limit} bytes. "
                "Use a smaller file or a larger bytes_limit."
            )

        # Try to read as text with different encodings
        encodings = ["utf-8", "utf-16", "latin-1", "cp1252"]
        for encoding in encodings:
            try:
                content = path.read_text(encoding=encoding)
                return content
            except UnicodeDecodeError:
                continue

        # Fallback: describe as binary
        return f"(Binary file, {size} bytes. Content not shown.)"

    except PermissionError as e:
        raise ToolError(f"Permission denied reading {path}: {e}")
    except Exception as e:
        raise ToolError(f"Could not read file: {e}")


def write_file(path: str, content: str, append: bool = False) -> str:
    """Write content to any file accessible on the system.

    Can write files outside the usual workspace/directory restrictions.
    Creates parent directories if they don't exist.

    Args:
        path: Absolute path to the file, or ~-relative path.
        content: The text content to write.
        append: If True, append to the file instead of overwriting.

    Returns:
        A confirmation message.

    Raises:
        ToolError: If the file cannot be written.
    """
    path = Path(os.path.expanduser(path)).resolve()

    if not content:
        raise ToolError("No content was provided to write.")

    try:
        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        path.write_text(content, encoding="utf-8")

        return f"Wrote content to {path}"

    except PermissionError as e:
        raise ToolError(f"Permission denied writing to {path}: {e}")
    except Exception as e:
        raise ToolError(f"Could not write file: {e}")


def delete_file(path: str) -> str:
    """Delete a file from anywhere on the system.

    **WARNING**: This action is irreversible and cannot be undone.
    Only deletes files, not directories (use remove_path for directories).

    Args:
        path: Absolute path to the file, or ~-relative path.

    Returns:
        A confirmation message.

    Raises:
        ToolError: If the file cannot be deleted.
    """
    path = Path(os.path.expanduser(path)).resolve()

    if not path.exists():
        raise ToolError(f"File not found: {path}")

    if not path.is_file():
        raise ToolError(f"Not a file: {path}. Use remove_path for directories.")

    try:
        path.unlink()
        return f"Deleted {path}"
    except PermissionError as e:
        raise ToolError(f"Permission denied deleting {path}: {e}")
    except Exception as e:
        raise ToolError(f"Could not delete file: {e}")


def remove_path(path: str, recursive: bool = True) -> str:
    """Remove a file or directory from anywhere on the system.

    **WARNING**: This action is irreversible. Directories are deleted recursively.
    Use with extreme caution.

    Args:
        path: Absolute path to the file/directory, or ~-relative path.
        recursive: If True (default), remove directories recursively.

    Returns:
        A confirmation message.

    Raises:
        ToolError: If the path cannot be removed.
    """
    import shutil

    path = Path(os.path.expanduser(path)).resolve()

    if not path.exists():
        raise ToolError(f"Path not found: {path}")

    try:
        if path.is_file():
            path.unlink()
            return f"Deleted file {path}"
        elif path.is_dir():
            shutil.rmtree(path)
            return f"Deleted directory {path} and all contents"
    except PermissionError as e:
        raise ToolError(f"Permission denied removing {path}: {e}")
    except Exception as e:
        raise ToolError(f"Could not remove path: {e}")


# ── GUI interaction ─────────────────────────────────────────────────────────


def mouse_click(x: int, y: int, button: str = "left", double: bool = False) -> str:
    """Move the mouse cursor and click at screen coordinates.

    Coordinates are in screen pixels (0,0 is top-left on most displays).
    Requires xdotool or a similar X11 automation tool.

    Args:
        x: X coordinate in pixels from the left.
        y: Y coordinate in pixels from the top.
        button: Mouse button to click ('left', 'right', 'middle', '1', '2', '3').
        double: If True, perform a double-click.

    Returns:
        A confirmation message.

    Raises:
        ToolError: If the click cannot be performed.
    """
    button_num = {"left": "1", "right": "3", "middle": "2"}.get(button, button)

    cmd_parts = ["xdotool", "mousemove", str(x), str(y)]
    if double:
        cmd_parts.extend(["doubleclick", button_num])
    else:
        cmd_parts.extend(["click", button_num])

    try:
        subprocess.run(cmd_parts, capture_output=True, text=True, timeout=5)
        return f"Clicked at ({x}, {y}) with {button} button{' (double-click)' if double else ''}"
    except FileNotFoundError:
        raise ToolError(
            "xdotool is not installed or not in PATH. "
            "Install with: sudo apt install xdotool"
        )
    except subprocess.TimeoutExpired:
        raise ToolError("Mouse click command timed out.")
    except Exception as e:
        raise ToolError(f"Could not perform mouse click: {e}")


def mouse_drag(
    x1: int, y1: int, x2: int, y2: int, button: str = "left"
) -> str:
    """Drag from one point to another.

    Moves to (x1, y1), presses the button, moves to (x2, y2), releases.

    Args:
        x1: Start X coordinate.
        y1: Start Y coordinate.
        x2: End X coordinate.
        y2: End Y coordinate.
        button: Mouse button to hold ('left', 'right', 'middle', '1', '2', '3').

    Returns:
        A confirmation message.

    Raises:
        ToolError: If the drag cannot be performed.
    """
    button_num = {"left": "1", "right": "3", "middle": "2"}.get(button, button)

    try:
        subprocess.run(
            ["xdotool", "mousedown", button_num, "mousemove", str(x2), str(y2), "mouseup", button_num],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return f"Dragged from ({x1}, {y1}) to ({x2}, {y2}) with {button} button"
    except FileNotFoundError:
        raise ToolError(
            "xdotool is not installed or not in PATH. "
            "Install with: sudo apt install xdotool"
        )
    except subprocess.TimeoutExpired:
        raise ToolError("Mouse drag command timed out.")
    except Exception as e:
        raise ToolError(f"Could not perform mouse drag: {e}")


def type_text(text: str, delay_ms: int = 30) -> str:
    """Type text at the current cursor position.

    Uses xdotool to simulate keyboard input.
    Special keys can be included using xdotool syntax:
    - {CTRL}, {ALT}, {SHIFT} - modifier keys
    - {ENTER}, {TAB}, {SPACE} - special keys
    - {BACKSPACE}, {DELETE} - deletion keys

    Args:
        text: The text to type (may include special key placeholders).
        delay_ms: Delay in milliseconds between keystrokes (default 30ms).

    Returns:
        A confirmation message.

    Raises:
        ToolError: If typing cannot be performed.
    """
    try:
        subprocess.run(
            ["xdotool", "type", "--delay", str(delay_ms), text],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return f"Typed: {text!r}"
    except FileNotFoundError:
        raise ToolError(
            "xdotool is not installed or not in PATH. "
            "Install with: sudo apt install xdotool"
        )
    except subprocess.TimeoutExpired:
        raise ToolError("Typing command timed out.")
    except Exception as e:
        raise ToolError(f"Could not type text: {e}")


def key_press(key: str, modifiers: list[str] | None = None) -> str:
    """Press and release a keyboard key (optionally with modifiers).

    Args:
        key: The key to press. Can be a letter, number, or special key name.
            Special keys: ENTER, TAB, SPACE, ESC, F1-F12, HOME, END, etc.
        modifiers: List of modifier keys ['CTRL', 'ALT', 'SHIFT', 'META'].

    Returns:
        A confirmation message.

    Raises:
        ToolError: If the key press cannot be performed.
    """
    cmd = ["xdotool", "key"]

    if modifiers:
        # Group modifiers together
        mod_str = "+".join(modifiers)
        key = f"{mod_str}+{key}"

    cmd.append(key)

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return f"Pressed key: {key}"
    except FileNotFoundError:
        raise ToolError(
            "xdotool is not installed or not in PATH. "
            "Install with: sudo apt install xdotool"
        )
    except subprocess.TimeoutExpired:
        raise ToolError("Key press command timed out.")
    except Exception as e:
        raise ToolError(f"Could not press key: {e}")


# ── Tool registration ─────────────────────────────────────────────────────────


# Define parameter schemas first
_PARAMS_WINDOW_CLOSE = {
    "type": "OBJECT",
    "properties": {
        "window_title": {
            "type": "STRING",
            "description": "The window title or application name to close.",
        },
        "by_name": {
            "type": "BOOLEAN",
            "description": "If True, treat window_title as a process name to kill with pkill.",
            "default": False,
        },
    },
    "required": ["window_title"],
}

_PARAMS_COMMAND = {
    "type": "OBJECT",
    "properties": {
        "command": {
            "type": "STRING",
            "description": "The shell command to execute (e.g., 'ls -la', 'cat file.txt').",
        },
        "timeout": {
            "type": "INTEGER",
            "description": "Maximum seconds to wait (default 30).",
            "default": 30,
        },
    },
    "required": ["command"],
}

_PARAMS_FILE_READ = {
    "type": "OBJECT",
    "properties": {
        "path": {
            "type": "STRING",
            "description": "Absolute or ~-relative path to the file to read.",
        },
        "bytes_limit": {
            "type": "INTEGER",
            "description": "Maximum bytes to read (default 1MB).",
            "default": 1048576,
        },
    },
    "required": ["path"],
}

_PARAMS_FILE_WRITE = {
    "type": "OBJECT",
    "properties": {
        "path": {
            "type": "STRING",
            "description": "Absolute or ~-relative path for the file to write.",
        },
        "content": {
            "type": "STRING",
            "description": "The text content to write to the file.",
        },
        "append": {
            "type": "BOOLEAN",
            "description": "If True, append to the file instead of overwriting.",
            "default": False,
        },
    },
    "required": ["path", "content"],
}

_PARAMS_FILE_DELETE = {
    "type": "OBJECT",
    "properties": {
        "path": {
            "type": "STRING",
            "description": "Absolute or ~-relative path to the file to delete.",
        },
    },
    "required": ["path"],
}

_PARAMS_PATH_REMOVE = {
    "type": "OBJECT",
    "properties": {
        "path": {
            "type": "STRING",
            "description": "Absolute or ~-relative path to the file or directory to remove.",
        },
        "recursive": {
            "type": "BOOLEAN",
            "description": "If True (default), remove directories recursively.",
            "default": True,
        },
    },
    "required": ["path"],
}

_PARAMS_MOUSE_CLICK = {
    "type": "OBJECT",
    "properties": {
        "x": {"type": "INTEGER", "description": "X coordinate in screen pixels."},
        "y": {"type": "INTEGER", "description": "Y coordinate in screen pixels."},
        "button": {
            "type": "STRING",
            "description": "Mouse button: 'left', 'right', 'middle', or '1', '2', '3'.",
            "default": "left",
        },
        "double": {
            "type": "BOOLEAN",
            "description": "Perform a double-click.",
            "default": False,
        },
    },
    "required": ["x", "y"],
}

_PARAMS_MOUSE_DRAG = {
    "type": "OBJECT",
    "properties": {
        "x1": {"type": "INTEGER", "description": "Start X coordinate."},
        "y1": {"type": "INTEGER", "description": "Start Y coordinate."},
        "x2": {"type": "INTEGER", "description": "End X coordinate."},
        "y2": {"type": "INTEGER", "description": "End Y coordinate."},
        "button": {
            "type": "STRING",
            "description": "Mouse button to hold: 'left', 'right', 'middle'.",
            "default": "left",
        },
    },
    "required": ["x1", "y1", "x2", "y2"],
}

_PARAMS_TYPE_TEXT = {
    "type": "OBJECT",
    "properties": {
        "text": {
            "type": "STRING",
            "description": "The text to type (may include {ENTER}, {SPACE}, {CTRL}, etc.).",
        },
        "delay_ms": {
            "type": "INTEGER",
            "description": "Delay in milliseconds between keystrokes (default 30).",
            "default": 30,
        },
    },
    "required": ["text"],
}

_PARAMS_KEY_PRESS = {
    "type": "OBJECT",
    "properties": {
        "key": {
            "type": "STRING",
            "description": "The key to press (e.g., 'a', 'Enter', 'F1', 'Tab').",
        },
        "modifiers": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "Modifier keys: ['CTRL', 'ALT', 'SHIFT', 'META'].",
            "default": [],
        },
    },
    "required": ["key"],
}


def build() -> list[Tool]:
    """Register all external control tools."""
    return [
        Tool(
            name="close_app",
            description=(
                "Close a desktop application or window by title or name. "
                "Can close windows using wmctrl or kill processes using pkill. "
                "May fail if the app has unsaved work and doesn't handle SIGTERM gracefully. "
                "DANGEROUS: Can disrupt user workflow. Requires confirmation."
            ),
            parameters=_PARAMS_WINDOW_CLOSE,
            func=close_app,
            consequential=True,
            confirm_prompt=(
                "This will close a desktop application or window. "
                "If the app has unsaved work, it may be lost. "
                "Confirm to proceed?"
            ),
            category="external",
        ),
        Tool(
            name="run_command",
            description=(
                "Execute a shell command and capture the output. "
                "ARBITRARY CODE EXECUTION: Runs with your user permissions. "
                "Can read, write, delete files. Use only for trusted commands. "
                "DANGEROUS: This tool gives the assistant full shell access. Requires confirmation."
            ),
            parameters=_PARAMS_COMMAND,
            func=run_command,
            consequential=True,
            confirm_prompt=(
                "This will execute a shell command with your permissions. "
                "It can read, write, and delete any file you can access. "
                "Use only for commands you trust. Confirm to proceed?"
            ),
            category="external",
        ),
        Tool(
            name="read_file",
            description=(
                "Read the contents of any file on the system. "
                "Can read files outside the normal workspace restrictions. "
                "For binary files, returns a description instead of content. "
                "DANGEROUS: Can read sensitive files. Requires confirmation."
            ),
            parameters=_PARAMS_FILE_READ,
            func=read_file,
            consequential=True,  # Because it can read secrets, credentials, etc.
            confirm_prompt=(
                "This will read a file from anywhere on your system. "
                "It may expose sensitive information like passwords, API keys, or personal data. "
                "Confirm to proceed?"
            ),
            category="external",
        ),
        Tool(
            name="write_file",
            description=(
                "Write content to any file on the system. "
                "Creates parent directories if needed. Can overwrite existing files. "
                "DANGEROUS: Can overwrite important files, inject malicious code. Requires confirmation."
            ),
            parameters=_PARAMS_FILE_WRITE,
            func=write_file,
            consequential=True,
            confirm_prompt=(
                "This will write to a file on your system. "
                "It can overwrite existing files or create new ones. "
                "Be sure this is what you want before approving."
            ),
            category="external",
        ),
        Tool(
            name="delete_file",
            description=(
                "Delete a file from anywhere on the system. "
                "This action is irreversible. Only deletes files, not directories. "
                "DANGEROUS: Data loss is permanent. Requires confirmation."
            ),
            parameters=_PARAMS_FILE_DELETE,
            func=delete_file,
            consequential=True,
            confirm_prompt=(
                "This will permanently delete a file. "
                "The deletion cannot be undone. "
                "Confirm to proceed?"
            ),
            category="external",
        ),
        Tool(
            name="remove_path",
            description=(
                "Delete a file or directory (and all its contents) from anywhere on the system. "
                "This action is irreversible. USE WITH EXTREME CAUTION. "
                "DANGEROUS: Can destroy entire directory trees. Requires confirmation."
            ),
            parameters=_PARAMS_PATH_REMOVE,
            func=remove_path,
            consequential=True,
            confirm_prompt=(
                "This will permanently delete a file or directory and all its contents. "
                "This cannot be undone. "
                "Confirm to proceed?"
            ),
            category="external",
        ),
        Tool(
            name="mouse_click",
            description=(
                "Move the mouse cursor to screen coordinates (x, y) and click. "
                "Origin (0, 0) is typically the top-left of the primary monitor. "
                "DANGEROUS: Can click on unintended UI elements. Requires confirmation."
            ),
            parameters=_PARAMS_MOUSE_CLICK,
            func=mouse_click,
            consequential=True,
            confirm_prompt=(
                "This will move the mouse and click at a specific screen location. "
                "It might click on buttons or entries you didn't intend. "
                "Confirm to proceed?"
            ),
            category="external",
        ),
        Tool(
            name="mouse_drag",
            description=(
                "Drag from one screen coordinate to another. "
                "Useful for file operations, selecting text, or UI interactions. "
                "DANGEROUS: Can perform unintended drag operations. Requires confirmation."
            ),
            parameters=_PARAMS_MOUSE_DRAG,
            func=mouse_drag,
            consequential=True,
            confirm_prompt=(
                "This will perform a mouse drag operation. "
                "It might interact with UI elements unexpectedly. "
                "Confirm to proceed?"
            ),
            category="external",
        ),
        Tool(
            name="type_text",
            description=(
                "Type text at the current cursor position. "
                "Uses xdotool to simulate keyboard input. "
                "DANGEROUS: Can type into any focused window. Requires confirmation."
            ),
            parameters=_PARAMS_TYPE_TEXT,
            func=type_text,
            consequential=True,
            confirm_prompt=(
                "This will type text into whatever window currently has focus. "
                "It might type into an active form, chat window, or other UI. "
                "Confirm to proceed?"
            ),
            category="external",
        ),
        Tool(
            name="key_press",
            description=(
                "Press and release a keyboard key (optionally with modifiers like CTRL or SHIFT). "
                "DANGEROUS: Can trigger keyboard shortcuts or menu actions. Requires confirmation."
            ),
            parameters=_PARAMS_KEY_PRESS,
            func=key_press,
            consequential=True,
            confirm_prompt=(
                "This will press a keyboard key (possibly with modifiers). "
                "It might trigger shortcuts or menu items. "
                "Confirm to proceed?"
            ),
            category="external",
        ),
    ]