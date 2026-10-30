"""The voice layer.

Two seams (`stt`, `tts`) and one loop that wires them to the *existing* brain.

Nothing here re-implements the agent. A spoken turn is transcribed to text and
handed to `Brain.ask` — the exact entry point a typed turn uses. If you ever
find yourself writing agent logic in this package, that is the wrong turn.
"""

from .audio import CaptureError, Recorder
from .stt import Transcriber, TranscriptionError, build_transcriber
from .tts import Speaker, SpeechError, build_speaker, build_speaker_with_fallback

__all__ = [
    "CaptureError",
    "Recorder",
    "SpeechError",
    "Speaker",
    "Transcriber",
    "TranscriptionError",
    "build_speaker",
    "build_speaker_with_fallback",
    "build_transcriber",
]
