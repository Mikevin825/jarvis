"""Push-to-talk audio capture.

Hold a key, speak, release. Push-to-talk is deliberately the first voice mode:
it removes a whole class of "is it listening?" bugs, because the start and end of
a turn are never guessed at.

`arecord` does the capturing — it is present on essentially every Linux desktop
and needs no Python audio stack.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_FORMAT = "S16_LE"


class CaptureError(RuntimeError):
    """Audio could not be captured. Safe to show a human."""


class Recorder:
    """Start and stop a recording session."""

    def __init__(
        self,
        *,
        device: str | None = None,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self._proc: subprocess.Popen | None = None
        self._path: Path | None = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        return shutil.which("arecord") is not None

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if not self.available():
            raise CaptureError(
                "arecord is not installed.\n"
                "  Install it with: sudo apt install alsa-utils"
            )
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return  # already recording; ignore a repeated key-down

            handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            handle.close()
            self._path = Path(handle.name)

            cmd = [
                "arecord",
                "-q",
                "-f", SAMPLE_FORMAT,
                "-r", str(self.sample_rate),
                "-c", str(self.channels),
            ]
            if self.device:
                cmd += ["-D", self.device]
            cmd.append(str(self._path))

            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            except OSError as exc:
                raise CaptureError(f"Could not start recording: {exc}") from exc

    def stop(self) -> Path | None:
        """Stop recording and return the file. None if nothing was captured."""
        with self._lock:
            proc, path = self._proc, self._path
            self._proc = None
            self._path = None

        if proc is None or path is None:
            return None

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

        if not path.exists():
            return None

        # A recording of near-zero length means the key was tapped, not held.
        # Treating it as speech would send silence to the transcriber.
        if path.stat().st_size < 2048:
            path.unlink(missing_ok=True)
            return None

        return path

    def cancel(self) -> None:
        """Throw away the current recording without transcribing it."""
        path = self.stop()
        if path is not None:
            path.unlink(missing_ok=True)
