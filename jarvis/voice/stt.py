"""Speech-to-text.

One job: give me audio, get back text. Behind a seam so the transcriber can be
swapped without touching anything else — the same discipline the brain provider
follows.

Two implementations:

* `deepgram` — fast, accurate, streams. Needs DEEPGRAM_API_KEY.
* `whisper`  — runs entirely on this machine. No key, no network, no cost.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import httpx


class TranscriptionError(RuntimeError):
    """The audio could not be turned into text. Safe to show a human."""


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> str:  # pragma: no cover - protocol
        ...


class DeepgramTranscriber:
    """Cloud transcription via Deepgram's pre-recorded endpoint.

    Chosen over local whisper for one reason: latency. Whisper on CPU takes
    roughly ten seconds per utterance, which makes a spoken conversation feel
    like a walkie-talkie. Deepgram returns in about a second.

    Wire format is a single POST to /v1/listen with the audio as the body and
    the options as query parameters. Everything the user says in one push-to-talk
    turn is one pre-recorded request — streaming would only help for an open mic.
    """

    ENDPOINT = "https://api.deepgram.com/v1/listen"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "nova-3",
        language: str = "en",
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.language = language
        self.timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self.last_duration: float | None = None

    def transcribe(self, audio_path: Path) -> str:
        if not audio_path.exists():
            raise TranscriptionError(f"There is no recording at {audio_path}.")

        try:
            response = httpx.post(
                self.ENDPOINT,
                params={
                    "model": self.model,
                    "language": self.language,
                    "smart_format": "true",
                    "punctuate": "true",
                },
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": "audio/wav",
                },
                content=audio_path.read_bytes(),
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise TranscriptionError(
                "Deepgram did not respond in time. "
                "Set stt.provider: whisper in config.yaml to transcribe locally."
            ) from exc
        except httpx.HTTPError as exc:
            raise TranscriptionError(
                f"Could not reach Deepgram: {exc}. "
                "Set stt.provider: whisper in config.yaml to work offline."
            ) from exc

        if response.status_code in (401, 403):
            raise TranscriptionError(
                "Deepgram rejected the key. Check DEEPGRAM_API_KEY in .env "
                "(it must be the API key, not the project id)."
            )
        if response.status_code == 402:
            raise TranscriptionError(
                "Deepgram says the account has no credit left. "
                "Check usage in the Deepgram console, or set "
                "stt.provider: whisper in config.yaml to transcribe locally."
            )
        if response.status_code == 429:
            raise TranscriptionError(
                "Deepgram rate limit reached. Wait a moment, or set "
                "stt.provider: whisper in config.yaml."
            )
        if response.status_code == 400:
            raise TranscriptionError(
                f"Deepgram rejected the request ({response.text[:200]}). "
                f"The model '{self.model}' may not exist on this account — "
                "try 'nova-2' in config.yaml under stt.deepgram.model."
            )
        if response.status_code != 200:
            raise TranscriptionError(
                f"Deepgram returned {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()
            transcript = (
                data["results"]["channels"][0]["alternatives"][0]["transcript"]
            ).strip()
            # Duration of the audio, so latency can be reported against it.
            self.last_duration = (data.get("metadata") or {}).get("duration")
            return transcript
        except (KeyError, IndexError, ValueError) as exc:
            raise TranscriptionError(
                "Deepgram returned a response I could not read."
            ) from exc


class WhisperTranscriber:
    """Local transcription. Downloads the model once, then works offline.

    Audio is decoded here rather than by faster-whisper: our recorder always
    produces a plain 16-bit WAV, and handing the model a raw float array avoids
    its PyAV decode path entirely. That path is fragile — faster-whisper passes
    a kwarg that recent PyAV versions removed — and this is both more robust and
    faster, since the audio is never decoded twice.
    """

    def __init__(
        self,
        *,
        model_size: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "en",
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscriptionError(
                    "Local transcription needs faster-whisper.\n"
                    "  Install it with: .venv/bin/pip install faster-whisper\n"
                    "  Or set stt.provider: deepgram in config.yaml."
                ) from exc
            try:
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
            except Exception as exc:  # noqa: BLE001 - model download can fail many ways
                raise TranscriptionError(
                    f"Could not load the local speech model '{self.model_size}': {exc}"
                ) from exc
        return self._model

    @staticmethod
    def _read_wav(path: Path):
        """Decode a PCM WAV into a float32 mono array at 16 kHz.

        Returns (samples, sample_rate). Raises TranscriptionError with a clear
        message for anything it cannot read.
        """
        import wave

        import numpy as np

        try:
            with wave.open(str(path), "rb") as wav:
                channels = wav.getnchannels()
                width = wav.getsampwidth()
                rate = wav.getframerate()
                frames = wav.readframes(wav.getnframes())
        except wave.Error as exc:
            raise TranscriptionError(f"Could not read the recording: {exc}") from exc

        if width != 2:
            raise TranscriptionError(
                f"Expected 16-bit audio, got {width * 8}-bit."
            )

        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            # Mix down to mono so the model gets what it expects.
            samples = samples.reshape(-1, channels).mean(axis=1)
        return samples, rate

    def transcribe(self, audio_path: Path) -> str:
        if not audio_path.exists():
            raise TranscriptionError(f"There is no recording at {audio_path}.")

        model = self._load()
        try:
            samples, rate = self._read_wav(audio_path)
            if samples.size == 0:
                return ""
            segments, _info = model.transcribe(
                samples, beam_size=5, language=self.language
            )
            return "".join(segment.text for segment in segments).strip()
        except TranscriptionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"Local transcription failed: {exc}") from exc


def build_transcriber(cfg) -> Transcriber:
    """Construct the transcriber named in the config."""
    if cfg.provider == "deepgram":
        if not cfg.api_key:
            raise TranscriptionError(
                "stt.provider is 'deepgram' but no API key was found.\n"
                "  Fix: set DEEPGRAM_API_KEY in .env,\n"
                "  or set stt.provider: whisper in config.yaml to transcribe locally."
            )
        return DeepgramTranscriber(
            cfg.api_key,
            model=cfg.model,
            language=cfg.language,
            timeout_seconds=cfg.timeout_seconds,
        )

    if cfg.provider == "whisper":
        return WhisperTranscriber(
            model_size=cfg.model,
            device=cfg.device,
            compute_type=cfg.compute_type,
            language=cfg.language,
        )

    raise TranscriptionError(f"unknown stt.provider: {cfg.provider!r}")
