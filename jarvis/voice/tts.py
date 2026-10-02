"""Text-to-speech.

One job: give me text, speak it aloud. Behind a seam so the voice or the provider
can change in one place — the same discipline the brain provider follows.

Two implementations:

* `elevenlabs` — natural voices, streams. Needs ELEVENLABS_API_KEY.
* `espeak`     — local, instant, robotic. No key, no network. Good enough to
  build and verify the whole voice loop before spending anything.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

import httpx


class SpeechError(RuntimeError):
    """The text could not be spoken. Safe to show a human."""


class Speaker(Protocol):
    def speak(self, text: str) -> None:  # pragma: no cover - protocol
        ...

    def stop(self) -> None:  # pragma: no cover - protocol
        ...


def _player() -> list[str] | None:
    """The command that plays an audio file, best first."""
    for name, args in (
        ("paplay", []),
        ("aplay", ["-q"]),
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ):
        if shutil.which(name):
            return [name, *args]
    return None


class _SubprocessSpeaker:
    """Shared plumbing: run a player, and be able to cut it off mid-sentence.

    Interrupting matters. An assistant that will not let you cut it off feels
    broken fast, so `stop()` kills playback immediately.
    """

    def __init__(self) -> None:
        self._current: subprocess.Popen | None = None

    def _play(self, path: Path) -> None:
        player = _player()
        if player is None:
            raise SpeechError(
                "No audio player found. Install one of: paplay, aplay, ffplay."
            )
        self._current = subprocess.Popen(
            [*player, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._current.wait()
        self._current = None

    def stop(self) -> None:
        proc = self._current
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._current = None


class EspeakSpeaker(_SubprocessSpeaker):
    """Local, offline speech. Robotic, but instant and free."""

    def __init__(self, *, voice: str = "en-gb", speed: int = 165) -> None:
        super().__init__()
        self.voice = voice
        self.speed = speed
        if shutil.which("espeak-ng") is None:
            raise SpeechError(
                "espeak-ng is not installed.\n"
                "  Install it with: sudo apt install espeak-ng"
            )

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            result = subprocess.run(
                [
                    "espeak-ng",
                    "-v", self.voice,
                    "-s", str(self.speed),
                    "-w", str(path),
                    text,
                ],
                capture_output=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise SpeechError(
                    f"espeak-ng failed: {result.stderr.decode('utf-8', 'replace')[:200]}"
                )
            self._play(path)
        finally:
            path.unlink(missing_ok=True)


class EdgeTtsSpeaker(_SubprocessSpeaker):
    """Free neural voices from Microsoft Edge's read-aloud service.

    No API key and no account. Voices are markedly more natural than espeak, and
    synthesis is fast enough for a spoken turn. It does need the network, and it
    is an undocumented service, so it can change without notice — which is why
    the local piper option exists as well.
    """

    def __init__(
        self,
        *,
        voice: str = "en-GB-RyanNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> None:
        super().__init__()
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        try:
            import edge_tts
        except ImportError as exc:
            raise SpeechError(
                "edge-tts is not installed.\n"
                "  Install it with: .venv/bin/pip install edge-tts"
            ) from exc

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            communicate = edge_tts.Communicate(
                text,
                self.voice,
                rate=self.rate,
                volume=self.volume,
                pitch=self.pitch,
            )
            # save_sync does the async work internally, so the voice loop stays
            # synchronous like every other speaker.
            communicate.save_sync(str(path))
            if not path.exists() or path.stat().st_size == 0:
                raise SpeechError("edge-tts returned no audio.")
            self._play(path)
        except SpeechError:
            raise
        except Exception as exc:  # noqa: BLE001 - network + service can fail many ways
            raise SpeechError(
                f"edge-tts failed: {type(exc).__name__}: {exc}. "
                "It needs a network connection; set tts.provider: piper for "
                "fully offline speech."
            ) from exc
        finally:
            path.unlink(missing_ok=True)


class PiperSpeaker(_SubprocessSpeaker):
    """Fully offline neural speech.

    The model is loaded once and kept in memory, so subsequent sentences are
    fast. Voices are downloaded ahead of time — see AGENT.md for the command.
    """

    def __init__(
        self,
        *,
        voice: str = "en_GB-alan-medium",
        voices_dir: str | None = None,
        length_scale: float = 1.0,
    ) -> None:
        super().__init__()
        self.voice = voice
        self.length_scale = length_scale
        self.voices_dir = Path(
            voices_dir or Path.home() / ".local" / "share" / "piper-voices"
        ).expanduser()
        self._model = None

    def _model_path(self) -> Path:
        return self.voices_dir / f"{self.voice}.onnx"

    def _load(self):
        if self._model is None:
            try:
                from piper import PiperVoice
            except ImportError as exc:
                raise SpeechError(
                    "piper is not installed.\n"
                    "  Install it with: .venv/bin/pip install piper-tts"
                ) from exc

            path = self._model_path()
            if not path.exists():
                raise SpeechError(
                    f"The piper voice '{self.voice}' is not downloaded.\n"
                    f"  Expected at: {path}\n"
                    "  Download it with:\n"
                    "    .venv/bin/python -c \"from pathlib import Path; "
                    "from piper.download_voices import download_voice; "
                    f"download_voice('{self.voice}', "
                    "Path.home()/'.local/share/piper-voices')\""
                )
            try:
                self._model = PiperVoice.load(str(path))
            except Exception as exc:  # noqa: BLE001
                raise SpeechError(
                    f"Could not load the piper voice '{self.voice}': {exc}"
                ) from exc
        return self._model

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        import wave

        model = self._load()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            from piper.config import SynthesisConfig

            config = SynthesisConfig(length_scale=self.length_scale)
            with wave.open(str(path), "wb") as wav:
                model.synthesize_wav(text, wav, syn_config=config)
            self._play(path)
        except SpeechError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpeechError(f"piper synthesis failed: {exc}") from exc
        finally:
            path.unlink(missing_ok=True)


class ElevenLabsSpeaker(_SubprocessSpeaker):
    """Cloud speech via ElevenLabs. Streams, so playback starts before the
    sentence is fully synthesised."""

    BASE = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(
        self,
        api_key: str,
        *,
        voice_id: str,
        model: str = "eleven_turbo_v2_5",
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.timeout = httpx.Timeout(timeout_seconds, connect=10.0)

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = Path(tmp.name)

        try:
            with httpx.stream(
                "POST",
                f"{self.BASE}/{self.voice_id}",
                params={"output_format": "mp3_44100_128"},
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": self.model,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
                timeout=self.timeout,
            ) as response:
                if response.status_code in (401, 403):
                    raise SpeechError(
                        "ElevenLabs rejected the key. Check ELEVENLABS_API_KEY in .env."
                    )
                if response.status_code != 200:
                    raise SpeechError(
                        f"ElevenLabs returned {response.status_code}: "
                        f"{response.read().decode('utf-8', 'replace')[:200]}"
                    )
                with path.open("wb") as fh:
                    for chunk in response.iter_bytes():
                        fh.write(chunk)

            self._play(path)
        except httpx.TimeoutException as exc:
            raise SpeechError("ElevenLabs did not respond in time.") from exc
        except httpx.HTTPError as exc:
            raise SpeechError(f"Could not reach ElevenLabs: {exc}") from exc
        finally:
            path.unlink(missing_ok=True)


def build_speaker(cfg) -> Speaker:
    """Construct the speaker named in the config."""
    if cfg.provider == "elevenlabs":
        if not cfg.api_key:
            raise SpeechError(
                "tts.provider is 'elevenlabs' but no API key was found.\n"
                "  Fix: set ELEVENLABS_API_KEY in .env,\n"
                "  or set tts.provider: edge in config.yaml for a free neural voice."
            )
        return ElevenLabsSpeaker(
            cfg.api_key,
            voice_id=cfg.voice,
            model=cfg.model,
            timeout_seconds=cfg.timeout_seconds,
        )

    if cfg.provider == "edge":
        return EdgeTtsSpeaker(
            voice=cfg.voice,
            rate=cfg.rate_str,
            volume=cfg.volume,
            pitch=cfg.pitch,
        )

    if cfg.provider == "piper":
        return PiperSpeaker(
            voice=cfg.voice,
            voices_dir=cfg.voices_dir,
            length_scale=cfg.length_scale,
        )

    if cfg.provider == "espeak":
        return EspeakSpeaker(voice=cfg.voice, speed=int(cfg.rate))

    raise SpeechError(f"unknown tts.provider: {cfg.provider!r}")
