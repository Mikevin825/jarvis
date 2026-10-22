"""Tests for the wake word listener.

No microphone and no Porcupine key are needed: the listener is driven with a
fake detector and silence is produced by real byte patterns. What these prove is
the state machine — listen, wake, record, end on silence, hand off — and that a
finished turn really becomes a wav the transcriber could read.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from jarvis.voice.wake import (
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    NullDetector,
    WakeError,
    WakeListener,
    _rms,
)

FRAME = 512  # samples per frame, matching Porcupine's default


def _pcm(samples: int, amplitude: int = 0) -> bytes:
    """Silent or loud mono 16-bit PCM of `samples` samples."""
    return struct.pack(f"<{samples}h", *([amplitude] * samples))


def _frame(amplitude: int = 0) -> bytes:
    return _pcm(FRAME, amplitude)


class ScriptedDetector:
    """Wakes on the Nth frame it is handed.

    `every=N` makes it wake on every Nth frame, which is what a test needs when
    it wants to prove the listener can take a second turn.
    """

    def __init__(self, wake_at: int, every: int | None = None) -> None:
        self.wake_at = wake_at
        self.every = every
        self.calls = 0

    @property
    def frame_length(self) -> int:
        return FRAME

    def process(self, pcm: bytes) -> bool:
        self.calls += 1
        if self.every is not None:
            return self.calls % self.every == 0
        return self.calls == self.wake_at


# -- silence measurement ---------------------------------------------------


class TestRms:
    def test_silence_is_zero(self):
        assert _rms(_frame(0)) == 0.0

    def test_loud_is_nonzero(self):
        assert _rms(_frame(2000)) > 0

    def test_louder_is_larger(self):
        assert _rms(_frame(3000)) > _rms(_frame(1000))

    def test_empty_is_zero(self):
        assert _rms(b"") == 0.0


# -- the turn state machine ------------------------------------------------


class TestTurnLifecycle:
    def _listener(self, tmp_path, detector, **kw):
        submitted: list[Path] = []
        listener = WakeListener(
            detector,
            submit=submitted.append,
            output_dir=tmp_path,
            **kw,
        )
        return listener, submitted

    def test_silence_alone_never_produces_a_turn(self, tmp_path):
        listener, submitted = self._listener(tmp_path, ScriptedDetector(wake_at=99))
        # Drive the state machine directly, with no microphone involved.
        listener._handle(_frame(0), [])
        listener._handle(_frame(0), [])
        assert submitted == []

    def test_a_wake_starts_a_recording(self, tmp_path):
        listener, submitted = self._listener(tmp_path, ScriptedDetector(wake_at=1))
        listener._handle(_frame(0), [])
        assert listener._recording is True

    def test_speech_then_silence_finishes_the_turn(self, tmp_path):
        detector = ScriptedDetector(wake_at=1)
        listener, submitted = self._listener(
            tmp_path, detector, silence_frames=3
        )

        listener._handle(_frame(0), [])          # wake
        for _ in range(5):
            listener._handle(_frame(3000), [])   # talking
        for _ in range(3):
            listener._handle(_frame(0), [])      # gone quiet

        assert len(submitted) == 1
        assert submitted[0].exists()

    def test_the_turn_is_a_readable_wav(self, tmp_path):
        listener, submitted = self._listener(
            tmp_path, ScriptedDetector(wake_at=1), silence_frames=3
        )
        listener._handle(_frame(0), [])
        for _ in range(6):
            listener._handle(_frame(3000), [])
        for _ in range(3):
            listener._handle(_frame(0), [])

        assert submitted, "a spoken turn should have been submitted"
        with wave.open(str(submitted[0]), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == SAMPLE_WIDTH
            assert wav.getframerate() == SAMPLE_RATE
            assert wav.getnframes() > 0

    def test_a_too_short_turn_is_dropped(self, tmp_path):
        """Wake plus one frame is not a request; it must not be submitted."""
        listener, submitted = self._listener(
            tmp_path, ScriptedDetector(wake_at=1), silence_frames=1
        )
        listener._handle(_frame(0), [])
        listener._handle(_frame(0), [])

        assert submitted == []

    def test_the_recording_flag_resets_after_a_turn(self, tmp_path):
        listener, submitted = self._listener(
            tmp_path, ScriptedDetector(wake_at=1), silence_frames=2
        )
        listener._handle(_frame(0), [])
        listener._handle(_frame(2000), [])
        listener._handle(_frame(0), [])
        listener._handle(_frame(0), [])

        assert listener._recording is False

    def test_a_broken_consumer_does_not_kill_the_listener(self, tmp_path):
        """If the voice loop rejects a recording, listening must continue."""

        def explode(path):
            raise RuntimeError("consumer is down")

        listener = WakeListener(
            ScriptedDetector(wake_at=1, every=1),
            submit=explode,
            output_dir=tmp_path,
            silence_frames=2,
        )
        listener._handle(_frame(0), [])
        for _ in range(4):
            listener._handle(_frame(3000), [])
        for _ in range(2):
            listener._handle(_frame(0), [])

        # Still listening: a second wake is still recognised.
        listener._handle(_frame(0), [])
        assert listener._recording is True

    def test_max_length_stops_a_never_ending_turn(self, tmp_path):
        listener, submitted = self._listener(
            tmp_path, ScriptedDetector(wake_at=1), silence_frames=10_000
        )
        listener._max_frames = 12
        listener._handle(_frame(0), [])
        for _ in range(12):
            listener._handle(_frame(3000), [])

        assert len(submitted) == 1


# -- lifecycle -------------------------------------------------------------


class TestLifecycle:
    def test_null_detector_never_wakes(self):
        assert NullDetector().process(_frame(9000)) is False

    def test_running_reflects_the_thread(self):
        listener = WakeListener(NullDetector(), submit=lambda p: None)
        assert listener.running is False
        listener._thread = None

    def test_stop_without_start_is_safe(self):
        WakeListener(NullDetector(), submit=lambda p: None).stop()


# -- detector construction -------------------------------------------------


class TestPorcupineDetector:
    def test_a_missing_key_is_an_actionable_error(self, monkeypatch):
        """No key must produce instructions, not a traceback."""
        pytest.importorskip("pvporcupine")
        from jarvis.voice.wake import PorcupineDetector

        with pytest.raises(WakeError) as exc:
            PorcupineDetector(access_key="", keyword="jarvis")
        assert "console.picovoice.ai" in str(exc.value)

    def test_an_unknown_keyword_is_refused(self, monkeypatch):
        pytest.importorskip("pvporcupine")
        import pvporcupine
        from jarvis.voice.wake import PorcupineDetector

        monkeypatch.setattr(pvporcupine, "create", lambda **kw: object())
        with pytest.raises(WakeError):
            PorcupineDetector(access_key="x", keyword="not-a-keyword")


def _models_present() -> bool:
    """Are openWakeWord's weights on disk?

    Checked via find_spec rather than an import: importing the package runs its
    `__init__`, which pulls in scikit-learn through the custom verifier. That is
    a training dependency, and `pytest.importorskip("openwakeword")` would
    wrongly skip a perfectly good inference install.
    """
    import importlib.util

    spec = importlib.util.find_spec("openwakeword")
    if spec is None or spec.origin is None:
        return False
    models = Path(spec.origin).parent / "resources" / "models"
    return (models / "hey_jarvis_v0.1.onnx").exists() and (
        models / "embedding_model.onnx"
    ).exists()


class TestOpenWakeWordDetector:
    def test_a_missing_package_is_an_actionable_error(self, monkeypatch):
        """No install must produce instructions, not a traceback."""
        monkeypatch.setitem(
            __import__("sys").modules, "openwakeword.model", None
        )
        import sys
        from jarvis.voice.wake import OpenWakeWordDetector

        with pytest.raises(WakeError) as exc:
            OpenWakeWordDetector(keyword="hey_jarvis")
        assert "openWakeWord" in str(exc.value) or "numpy" in str(exc.value)
        monkeypatch.setitem(sys.modules, "openwakeword.model", None)

    def test_keyword_translation(self):
        """config says "jarvis"; openWakeWord calls it "hey_jarvis"."""
        from jarvis.voice.wake import OPENWAKEWORD_KEYWORDS

        assert OPENWAKEWORD_KEYWORDS["jarvis"] == "hey_jarvis"
        assert OPENWAKEWORD_KEYWORDS["mycroft"] == "hey_mycroft"

    @pytest.mark.slow
    def test_silence_never_wakes(self):
        """A real, model-backed detector must stay quiet on silence.

        Marked slow: it loads onnxruntime and the model, which takes seconds.
        """
        if not _models_present():
            pytest.skip("openWakeWord models not fetched yet")

        from jarvis.voice.wake import OpenWakeWordDetector

        detector = OpenWakeWordDetector(keyword="hey_jarvis", threshold=0.5)
        try:
            for _ in range(20):
                assert detector.process(_frame(0)) is False
        finally:
            detector.close()

    @pytest.mark.slow
    def test_frame_length_matches_the_model_hop(self):
        """The listener feeds this many samples per call."""
        if not _models_present():
            pytest.skip("openWakeWord models not fetched yet")

        from jarvis.voice.wake import OpenWakeWordDetector

        detector = OpenWakeWordDetector(keyword="hey_jarvis")
        try:
            assert detector.frame_length > 0
            assert detector.frame_length % 160 == 0, "must be a whole number of 10 ms hops"
        finally:
            detector.close()
