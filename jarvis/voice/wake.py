"""Wake-word detection: "jarvis" heard, and he starts listening.

Push-to-talk is deliberately the first voice mode — the start and end of a turn
are never guessed at, so there is no "is it listening?" ambiguity. A wake word
gives that ambiguity back, which is why it comes after: it has to be built on a
turn mechanism that already works.

The shape is deliberately narrow. A wake listener is a *producer*: it hears the
wake word, records one turn, and hands the file to the existing voice loop. The
loop still owns transcription, thinking and speaking, so there is exactly one
agent path and no forked logic.

Detection is Porcupine, on-device and cheap enough to leave running. The keyword
`jarvis` ships with it, which is the name this project has always intended.
"""

from __future__ import annotations

import array
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit

# Porcupine consumes fixed-size frames; the listener matches whatever the
# engine reports rather than assuming 512.
DEFAULT_FRAME_LENGTH = 512


class WakeError(RuntimeError):
    """The wake listener could not start. Safe to show a human."""


class WakeDetector:
    """One method: feed PCM, get True when the wake word was heard."""

    def process(self, pcm: bytes) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def frame_length(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


class PorcupineDetector(WakeDetector):
    """On-device wake word detection via Picovoice Porcupine.

    The access key is read from `PORCUPINE_ACCESS_KEY` in the environment (or
    `.env`). Porcupine's free tier is per-developer and needs no card, but the
    key is still a secret: it never enters source or logs.
    """

    def __init__(
        self,
        *,
        access_key: str,
        keyword: str = "jarvis",
        sensitivity: float = 0.5,
        device_index: int = -1,
    ) -> None:
        try:
            import pvporcupine
        except ImportError as exc:
            raise WakeError(
                "wake word detection needs pvporcupine.\n"
                "  Install it with: .venv/bin/pip install pvporcupine"
            ) from exc

        if not access_key:
            raise WakeError(
                "no Porcupine access key.\n"
                "  Get a free one at https://console.picovoice.ai/, then set\n"
                "  PORCUPINE_ACCESS_KEY in .env."
            )

        if keyword not in pvporcupine.KEYWORDS:
            raise WakeError(
                f"{keyword!r} is not a built-in keyword. Available: "
                + ", ".join(sorted(pvporcupine.KEYWORDS))
            )

        try:
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keywords=[keyword],
                sensitivities=[sensitivity],
                input_device_index=device_index,
            )
        except pvporcupine.PorcupineActivationError as exc:
            raise WakeError(f"Porcupine refused the key: {exc}") from exc
        except pvporcupine.PorcupineActivationLimitError as exc:
            raise WakeError(f"Porcupine activation limit reached: {exc}") from exc
        except pvporcupine.PorcupineError as exc:
            raise WakeError(f"Porcupine could not start: {exc}") from exc

        self._keyword = keyword

    @property
    def frame_length(self) -> int:
        return int(self._porcupine.frame_length)

    def process(self, pcm: bytes) -> bool:
        """True when the wake word appears in this frame."""
        samples = array.array("h")
        samples.frombytes(pcm)
        index = self._porcupine.process(samples)
        return index == 0

    def close(self) -> None:
        try:
            self._porcupine.delete()
        except Exception:  # noqa: BLE001 - releasing a handle must not raise
            pass


class NullDetector(WakeDetector):
    """Never wakes. Used to test the listener without a microphone."""

    def __init__(self, frame_length: int = DEFAULT_FRAME_LENGTH) -> None:
        self._frame_length = frame_length

    @property
    def frame_length(self) -> int:
        return self._frame_length

    def process(self, pcm: bytes) -> bool:
        return False


# `wake_word` in config is written for Porcupine, whose keyword is "jarvis".
# openWakeWord ships the same word as "hey_jarvis", so translate when that
# engine is in use. Anything not listed is passed through unchanged, which also
# lets a raw openWakeWord model name be configured directly.
OPENWAKEWORD_KEYWORDS = {
    "jarvis": "hey_jarvis",
    "hey jarvis": "hey_jarvis",
    "mycroft": "hey_mycroft",
    "google": "ok_google",
}


def _load_model_class():
    """Import openWakeWord's Model without dragging in its training deps.

    `openwakeword/__init__.py` eagerly imports `custom_verifier_model`, which
    needs scikit-learn. That is a dependency for *training* a custom wake word,
    not for running a pretrained one — and it is a 9 MB download on a slow
    network for code this never calls. Stub it out before the package import
    so an inference-only install works.
    """
    import sys
    import types

    if "openwakeword.custom_verifier_model" not in sys.modules:
        stub = types.ModuleType("openwakeword.custom_verifier_model")

        def train_custom_verifier(*args, **kwargs):
            raise WakeError(
                "training custom wake words needs scikit-learn, which is not "
                "installed. Using a pretrained keyword needs nothing extra."
            )

        stub.train_custom_verifier = train_custom_verifier
        sys.modules["openwakeword.custom_verifier_model"] = stub

    from openwakeword.model import Model

    return Model


class OpenWakeWordDetector(WakeDetector):
    """Offline wake word detection via openWakeWord.

    No key, no account, no network at runtime — the models are downloaded once
    and run on CPU through onnxruntime. That is the whole reason this exists
    alongside Porcupine: Picovoice's free key asks for a company email, which
    rules it out for a lot of people.

    Models ship inside the package. `hey_jarvis` is the closest match for this
    project; anything openWakeWord provides works.
    """

    # openWakeWord's own melspec wants 16 kHz, 16-bit mono — the same PCM the
    # listener already produces.
    CHUNK = 1280  # 80 ms at 16 kHz; the model's native hop

    def __init__(
        self,
        *,
        keyword: str = "hey_jarvis",
        threshold: float = 0.4,
        vad_threshold: float = 0.5,
        model_path: str | None = None,
    ) -> None:
        try:
            import numpy as np
        except ImportError as exc:
            raise WakeError(
                "openWakeWord needs numpy, which is not installed."
            ) from exc

        self._np = np
        self._keyword = keyword
        self._threshold = threshold

        try:
            Model = _load_model_class()
            self._model = Model(
                wakeword_models=[model_path] if model_path else [keyword],
                inference_framework="onnx",
                # VAD gates predictions on speech actually being present. That is
                # what makes a low threshold safe: background noise and fan hum
                # no longer count, so the word can be matched more loosely.
                vad_threshold=vad_threshold,
            )
        except WakeError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaces missing models, bad names
            raise WakeError(
                f"openWakeWord could not load {keyword!r}: {exc}\n"
                "  Models ship with the package — try one of:\n"
                "  hey_jarvis, hey_mycroft, alexa, computer, ok_google"
            ) from exc

    @property
    def frame_length(self) -> int:
        # openWakeWord consumes whatever it is given; the listener must feed it
        # a fixed size, so report its native hop.
        return self.CHUNK

    def process(self, pcm: bytes) -> bool:
        """True when the wake word scores above the threshold this frame.

        `predict` returns a score per model, 0 to 1. Only one model is loaded
        here, so any score over threshold is our keyword.
        """
        samples = self._np.frombuffer(pcm, dtype=self._np.int16)
        scores = self._model.predict(samples)
        return any(score > self._threshold for score in scores.values())

    def close(self) -> None:
        self._model = None


def _rms(pcm: bytes) -> float:
    """Root-mean-square of a 16-bit mono frame.

    Used for end-of-speech detection. Computed by hand rather than with
    `audioop`, which is deprecated and on its way out.
    """
    if not pcm:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm)
    total = 0
    for value in samples:
        total += value * value
    return (total / len(samples)) ** 0.5


class WakeListener:
    """Always listening for the wake word, then recording one turn.

    After the wake word it records until the user stops talking. Silence is
    detected by energy, which is crude compared to a real voice-activity
    detector but needs nothing extra and behaves the way a person expects: talk,
    pause, and the turn ends.
    """

    def __init__(
        self,
        detector: WakeDetector,
        *,
        submit,
        on_state=None,
        device: str | None = None,
        silence_threshold: float = 400.0,
        silence_frames: int = 45,
        max_seconds: float = 60.0,
        pre_roll_frames: int = 8,
        output_dir: Path | None = None,
    ) -> None:
        """
        `submit(path)` is called with the finished recording — the listener does
        not know what a turn is *for*, only how to capture one.

        `silence_threshold` is in RMS units for 16-bit audio: 0 is a perfect
        silence, ~1000 is a normal speaking voice. 400 is below normal speech
        but well above the noise floor of a quiet room.

        `silence_frames` is how long that quiet must last before the turn ends.
        At 32ms a frame, 45 is about 1.4 seconds.
        """
        self._detector = detector
        self._submit = submit
        self._on_state = on_state
        self._device = device
        self._silence_threshold = silence_threshold
        self._silence_frames = silence_frames
        self._max_frames = int(max_seconds * SAMPLE_RATE / detector.frame_length)
        self._pre_roll = pre_roll_frames
        self._output_dir = output_dir

        self._quit = threading.Event()
        self._thread: threading.Thread | None = None
        self._recording = False
        self._frames: list[bytes] = []
        self._quiet = 0

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if shutil.which("arecord") is None:
            raise WakeError(
                "arecord is not installed.\n"
                "  Install it with: sudo apt install alsa-utils"
            )
        self._quit.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._quit.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _say(self, state: str, detail: str = "") -> None:
        if self._on_state is not None:
            self._on_state(state, detail)

    # -- the loop -----------------------------------------------------------

    def _run(self) -> None:
        frame_bytes = self._detector.frame_length * SAMPLE_WIDTH
        pre_roll: list[bytes] = []

        try:
            proc = subprocess.Popen(
                [
                    "arecord", "-q",
                    "-f", "S16_LE",
                    "-r", str(SAMPLE_RATE),
                    "-c", str(CHANNELS),
                    "-t", "raw",
                    *( ["-D", self._device] if self._device else [] ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._say("error", f"could not open the microphone: {exc}")
            return

        assert proc.stdout is not None
        try:
            while not self._quit.is_set():
                pcm = proc.stdout.read(frame_bytes)
                if not pcm:
                    break
                self._handle(pcm, pre_roll)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            self._finalize()

    def _handle(self, pcm: bytes, pre_roll: list[bytes]) -> None:
        if self._recording:
            self._frames.append(pcm)
            if _rms(pcm) < self._silence_threshold:
                self._quiet += 1
            else:
                self._quiet = 0

            if self._quiet >= self._silence_frames:
                self._finalize()
            elif len(self._frames) >= self._max_frames:
                self._finalize()
            return

        # Listening for the wake word.
        pre_roll.append(pcm)
        if len(pre_roll) > self._pre_roll:
            pre_roll.pop(0)

        if self._detector.process(pcm):
            self._start_recording(pre_roll)

    def _start_recording(self, pre_roll: list[bytes]) -> None:
        self._recording = True
        self._frames = list(pre_roll)
        self._quiet = 0
        self._say("wake", "heard — listening")

    def _finalize(self) -> None:
        if not self._recording:
            return
        self._recording = False
        frames, self._frames = self._frames, []

        path = self._write_wav(frames)
        if path is None:
            self._say("error", "recording was too short to keep")
            return

        self._say("recording", str(path))
        try:
            self._submit(path)
        except Exception as exc:  # noqa: BLE001 - a consumer must not kill the listener
            self._say("error", f"could not hand off the recording: {exc}")

    def _write_wav(self, frames: list[bytes]) -> Path | None:
        """Write the frames as a 16kHz mono wav, or None if there is too little."""
        payload = b"".join(frames)
        # A turn that is only pre-roll silence is not a turn.
        if len(payload) < SAMPLE_RATE * SAMPLE_WIDTH // 4:
            return None

        directory = self._output_dir
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            suffix=".wav", dir=directory, delete=False
        )
        path = Path(handle.name)
        try:
            with wave.open(handle, "wb") as wav:
                wav.setnchannels(CHANNELS)
                wav.setsampwidth(SAMPLE_WIDTH)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(payload)
        finally:
            handle.close()
        return path
