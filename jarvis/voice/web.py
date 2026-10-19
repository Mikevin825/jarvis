"""Voice over the web — speech in, speech out, for the mobile app.

The desktop voice loop plays audio through the machine's speakers. A phone
cannot use that, so this module does the two halves separately:

  * `transcribe_bytes` — accept whatever the phone recorded (webm/opus, m4a,
    ogg…) and hand it to the same transcriber the terminal uses.
  * `synthesize_bytes` — return spoken audio as bytes for the phone to play,
    instead of playing it here.

Both reuse the configured providers, so switching stt/tts in config.yaml
changes the phone too. Nothing about the providers is duplicated.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import httpx

from ..config import load_config, load_dotenv
from .stt import TranscriptionError, build_transcriber
from .tts import SpeechError

# Phone recordings are usually compressed and at 48 kHz stereo. Deepgram and
# Whisper both do best with a plain 16 kHz mono WAV, and normalising here means
# every provider sees the same shape regardless of which phone recorded it.
TARGET_RATE = 16000


def _ffmpeg() -> str | None:
    """Find ffmpeg. The desktop loop never needed it; the web path does."""
    for candidate in ("ffmpeg", "/usr/bin/ffmpeg"):
        try:
            subprocess.run(
                [candidate, "-version"],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return candidate
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    return None


def to_wav16(raw: bytes, suffix: str = ".webm") -> bytes:
    """Convert arbitrary recorded audio to 16 kHz mono WAV bytes."""
    ffmpeg = _ffmpeg()
    if ffmpeg is None:
        raise TranscriptionError(
            "ffmpeg is needed to read phone recordings but was not found. "
            "Install it with: sudo apt install ffmpeg"
        )

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        dst = Path(tmp) / "out.wav"
        src.write_bytes(raw)

        try:
            subprocess.run(
                [
                    ffmpeg, "-y", "-loglevel", "error",
                    "-i", str(src),
                    "-ar", str(TARGET_RATE),
                    "-ac", "1",
                    "-f", "wav",
                    str(dst),
                ],
                capture_output=True,
                timeout=60,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            # ffmpeg's stderr is multi-line and full of internals; the model
            # and the user only need the first meaningful line.
            detail = ""
            for line in exc.stderr.decode("utf-8", "replace").splitlines():
                line = line.strip()
                if line and not line.startswith(("[in#", "Error opening input file")):
                    detail = line
                    break
            raise TranscriptionError(
                "That recording could not be read as audio"
                + (f" ({detail[:120]})" if detail else "")
                + ". Try again and speak clearly into the microphone."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TranscriptionError("Converting the recording timed out.") from exc

        return dst.read_bytes()


def transcribe_bytes(raw: bytes, suffix: str = ".webm") -> str:
    """Turn recorded audio bytes into text, using the configured transcriber."""
    if not raw:
        raise TranscriptionError("The recording was empty.")

    wav = to_wav16(raw, suffix=suffix)
    load_dotenv()
    cfg = load_config()
    transcriber = build_transcriber(cfg.stt)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "speech.wav"
        path.write_bytes(wav)
        return transcriber.transcribe(path)


def synthesize_bytes(text: str) -> tuple[bytes, str]:
    """Render `text` to audio for the phone to play.

    Returns (audio_bytes, mime_type). Only the providers that can stream over
    HTTP are supported here — espeak/piper are local-playback engines and have
    no useful web form, so they fall back to ElevenLabs/edge when configured.
    """
    text = (text or "").strip()
    if not text:
        return b"", "audio/mpeg"

    load_dotenv()
    cfg = load_config()
    provider = cfg.tts.provider

    if provider == "elevenlabs":
        return _elevenlabs(text, cfg)

    if provider == "edge":
        return _edge(text, cfg)

    # espeak / piper: no cloud endpoint. Try edge as a sensible stand-in, and
    # say so plainly rather than returning silence.
    try:
        return _edge(text, cfg)
    except SpeechError:
        raise SpeechError(
            f"tts.provider is '{provider}', which cannot render audio for the "
            "web. Set tts.provider to 'elevenlabs' or 'edge' in config.yaml."
        )


def _elevenlabs(text: str, cfg) -> tuple[bytes, str]:
    key = cfg.tts.api_keys.get("elevenlabs")
    if not key:
        raise SpeechError("No ELEVENLABS_API_KEY, so I cannot speak.")

    model = cfg.tts.model or "eleven_flash_v2_5"
    voice = cfg.tts.voice

    try:
        response = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": model,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
    except httpx.HTTPError as exc:
        raise SpeechError(f"Could not reach ElevenLabs: {exc}") from exc

    if response.status_code == 402:
        raise SpeechError(
            "ElevenLabs needs a paid plan for this voice. Pick one from your "
            "own account: jarvis --voices"
        )
    if response.status_code in (401, 403):
        raise SpeechError("ElevenLabs rejected the key.")
    if response.status_code == 429:
        raise SpeechError("ElevenLabs character quota reached.")
    if response.status_code != 200:
        raise SpeechError(
            f"ElevenLabs returned {response.status_code}: "
            f"{response.text[:160]}"
        )

    return response.content, "audio/mpeg"


def _edge(text: str, cfg) -> tuple[bytes, str]:
    """Microsoft Edge voices via edge-tts — free, no key, needs network."""
    import asyncio

    try:
        import edge_tts
    except ImportError as exc:
        raise SpeechError(
            "edge-tts is not installed. Add it with: "
            ".venv/bin/pip install edge-tts"
        ) from exc

    voice = cfg.tts.voice or "en-GB-RyanNeural"
    rate = cfg.tts.rate_str or "+0%"

    async def render() -> bytes:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and "data" in chunk:
                chunks.append(chunk["data"])
        return b"".join(chunks)

    try:
        audio = asyncio.run(render())
    except Exception as exc:  # noqa: BLE001 - surface any edge-tts failure plainly
        raise SpeechError(f"edge-tts failed: {exc}") from exc

    if not audio:
        raise SpeechError("edge-tts returned no audio.")
    return audio, "audio/mpeg"
