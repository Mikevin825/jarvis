"""Text-to-speech.

One job: give me text, speak it aloud. Behind a seam so the voice or the provider
can change in one place — the same discipline the brain provider follows.

Providers:

* `elevenlabs` — natural voices, streams. Needs ELEVENLABS_API_KEY.
* `fish`       — high-quality free neural voices (s2.1-pro-free). Needs FISH_API_KEY.
* `edge`       — free Microsoft neural voices. No key, needs network.
* `piper`      — fully offline neural voices. No key, no network.
* `espeak`     — local, instant, robotic. No key, no network. Good enough to
  build and verify the whole voice loop before spending anything.

A configured provider is not the same as a working one: a key runs out of quota
and a free service changes its endpoint. `build_speaker_with_fallback` keeps a
turn speakable when that happens, and says which voice it settled on — a silent
substitution would leave the user thinking their chosen voice still works.
"""

from __future__ import annotations

import json as jsonlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

import httpx


class SpeechError(RuntimeError):
    """The text could not be spoken. Safe to show a human."""


def _elevenlabs_rejection(response) -> SpeechError:
    """Turn an ElevenLabs 401/403 into the complaint that fits.

    ElevenLabs answers 401 to more than a bad key: an exhausted character quota
    and a key missing a scope arrive the same way. Only the body's `detail.code`
    separates them, and telling a user their key is broken when it is their
    quota sends them to fix the wrong thing — verified here: a perfectly valid
    key returns 401 `quota_exceeded` once the free tier runs out.
    """
    code = None
    try:
        # A streaming response has not read its body yet, and `.json()` on one
        # raises rather than reading it — so read first, whatever the response.
        raw = response.read()
        code = (jsonlib.loads(raw).get("detail") or {}).get("code")
    except Exception:  # noqa: BLE001 - a body we cannot read is not worth failing over
        code = None

    if code == "quota_exceeded":
        return SpeechError(
            "ElevenLabs quota is used up — this request needs characters and "
            "none remain. Add credits or upgrade at elevenlabs.io, or set "
            "tts.provider in config.yaml: piper is free and works offline."
        )
    if code == "missing_permissions":
        return SpeechError(
            "The ElevenLabs key is missing a permission this call needs. "
            "Create a new key with the required scopes at elevenlabs.io."
        )
    return SpeechError(
        "ElevenLabs rejected the key. Check ELEVENLABS_API_KEY in .env."
    )


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

    BASE = "https://api.elevenlabs.io/v1"

    def __init__(
        self,
        api_key: str,
        *,
        voice_id: str,
        model: str = "eleven_flash_v2_5",
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.timeout = httpx.Timeout(timeout_seconds, connect=10.0)

    def list_voices(self) -> list[tuple[str, str]]:
        """The voices this key can actually use, as (voice_id, name).

        Worth checking before choosing a voice: on a free plan the public voice
        library is not available through the API, so a voice id copied from the
        website may be rejected even though it looks valid.
        """
        try:
            response = httpx.get(
                f"{self.BASE}/voices",
                headers={"xi-api-key": self._api_key},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise SpeechError(f"Could not reach ElevenLabs: {exc}") from exc

        if response.status_code in (401, 403):
            raise _elevenlabs_rejection(response)
        if response.status_code != 200:
            raise SpeechError(
                f"ElevenLabs returned {response.status_code}: {response.text[:200]}"
            )
        try:
            return [
                (v["voice_id"], v.get("name", v["voice_id"]))
                for v in response.json().get("voices", [])
            ]
        except (KeyError, ValueError) as exc:
            raise SpeechError("ElevenLabs returned a voice list I could not read.") from exc

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = Path(tmp.name)

        try:
            with httpx.stream(
                "POST",
                f"{self.BASE}/text-to-speech/{self.voice_id}",
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
                    raise _elevenlabs_rejection(response)
                if response.status_code == 422:
                    raise SpeechError(
                        f"ElevenLabs rejected the request for voice "
                        f"'{self.voice_id}'. On a free plan the public voice "
                        "library is not available through the API — use a voice "
                        "from your own account instead. List them with:\n"
                        "  .venv/bin/python -m jarvis --voices"
                    )
                if response.status_code == 429:
                    raise SpeechError(
                        "ElevenLabs rate limit or character quota reached. "
                        "Check your plan's usage."
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


class FishTtsSpeaker(_SubprocessSpeaker):
    """Fish Audio TTS via REST API.

    Free tier uses model `s2.1-pro-free` (no credit card needed).
    Quality is high, comparable to ElevenLabs. Requires FISH_API_KEY.

    The API returns raw MP3 bytes — no base64 wrapping needed.
    """

    BASE = "https://api.fish.audio/v1/tts"
    DEFAULT_MODEL = "s2.1-pro-free"

    def __init__(
        self,
        api_key: str,
        *,
        voice: str | None = None,
        model: str = DEFAULT_MODEL,
        speed: float = 1.0,
        volume: float = 0.0,
        normalize: bool = True,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self.voice = voice
        self.model = model
        self.speed = speed
        self.volume = volume
        self.normalize = normalize

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        body: dict = {"text": text, "format": "mp3"}
        if self.voice:
            body["reference_id"] = self.voice
        if self.speed != 1.0:
            body["prosody"] = {"speed": self.speed}
        if self.volume != 0.0:
            body["prosody"] = body.get("prosody", {})
            body["prosody"]["volume"] = self.volume
        if not self.normalize:
            body["normalize"] = False

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = Path(tmp.name)

        try:
            response = httpx.post(
                self.BASE,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "model": self.model,
                },
                json=body,
                timeout=120.0,
            )
            if response.status_code == 401:
                raise SpeechError("Fish Audio rejected the key. Check FISH_API_KEY in .env.")
            if response.status_code == 402:
                raise SpeechError("Fish Audio quota exhausted. Add credit at fish.audio.")
            if response.status_code == 429:
                raise SpeechError("Fish Audio rate limit reached. Retry later.")
            if response.status_code != 200:
                raise SpeechError(
                    f"Fish Audio returned {response.status_code}: {response.text[:200]}"
                )
            path.write_bytes(response.content)
            if not path.exists() or path.stat().st_size == 0:
                raise SpeechError("Fish Audio returned no audio.")
            self._play(path)
        except httpx.TimeoutException as exc:
            raise SpeechError("Fish Audio did not respond in time.") from exc
        except httpx.HTTPError as exc:
            raise SpeechError(f"Could not reach Fish Audio: {exc}") from exc
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

    if cfg.provider == "fish":
        if not cfg.api_key:
            raise SpeechError(
                "tts.provider is 'fish' but no API key was found.\n"
                "  Fix: set FISH_API_KEY in .env,\n"
                "  or set tts.provider: edge in config.yaml for a free neural voice."
            )
        return FishTtsSpeaker(
            cfg.api_key,
            voice=cfg.voice,
            model=cfg.model or FishTtsSpeaker.DEFAULT_MODEL,
            speed=cfg.speed,
            volume=cfg.volume_db,
            normalize=cfg.normalize,
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


# Order tried when the configured provider cannot speak. fish before edge:
# both are network-dependent, but fish is neural-quality (s2.1-pro-free); edge is
# also free but can break unpredictably. Both before piper since they are faster.
# espeak last: offline but robotic. When a provider is added to the fallback chain,
# it should be network-first if it requires no key; providers that require keys
# (fish, elevenlabs) are tried only when explicitly configured.
FALLBACK_ORDER = ("edge", "piper", "espeak")


def _build_named(cfg, provider: str) -> Speaker:
    """Build one specific provider, honouring the settings configured for it."""
    block = (cfg.providers or {}).get(provider) or {}

    if provider == "edge":
        return EdgeTtsSpeaker(
            voice=block.get("voice", "en-GB-RyanNeural"),
            rate=block.get("rate_str", "+0%"),
            volume=block.get("volume", "+0%"),
            pitch=block.get("pitch", "+0Hz"),
        )
    if provider == "piper":
        return PiperSpeaker(
            voice=block.get("voice", "en_GB-alan-medium"),
            voices_dir=block.get("voices_dir"),
            length_scale=float(block.get("length_scale", 1.0)),
        )
    if provider == "espeak":
        return EspeakSpeaker(
            voice=block.get("voice", "en-gb"),
            speed=int(block.get("rate", 165)),
        )
    if provider == "fish":
        return FishTtsSpeaker(
            block.get("api_key", ""),
            voice=block.get("voice"),
            model=block.get("model", FishTtsSpeaker.DEFAULT_MODEL),
            speed=block.get("speed", 1.0),
            volume=block.get("volume_db", 0.0),
            normalize=block.get("normalize", True),
        )
    raise SpeechError(f"unknown tts.provider: {provider!r}")


class FallbackSpeaker:
    """Speaks with the configured provider, and switches permanently on failure.

    A provider can be constructed and still fail on its first real sentence:
    the character quota runs out mid-month, a free service changes its endpoint
    without notice. Retrying the same provider every turn would fail every turn,
    so the first failure moves to the next provider for the rest of the session.

    Fallbacks are built lazily, only when one is actually needed — piper loads a
    model and edge-tts imports a dependency, and neither should be paid for on a
    session where the configured voice works.

    `on_switch` runs once, when a fallback takes over, so the caller can say so
    out loud. A silent substitution reads as a bug to the person listening.
    """

    def __init__(self, primary: Speaker, name: str, cfg, on_switch=None) -> None:
        self._speaker = primary
        self._name = name
        self._cfg = cfg
        self._on_switch = on_switch
        self._tried: set[str] = set()
        self.switched_to: str | None = None

    @property
    def provider(self) -> str:
        """The provider actually in use — which may no longer be the configured one."""
        return self._name

    def speak(self, text: str) -> None:
        try:
            self._speaker.speak(text)
            return
        except SpeechError:
            pass  # the configured voice failed; try the alternatives

        for provider in FALLBACK_ORDER:
            if provider in self._tried or provider == self._name:
                continue
            self._tried.add(provider)
            try:
                candidate = _build_named(self._cfg, provider)
                candidate.speak(text)
            except SpeechError:
                continue
            self._take_over(provider, candidate)
            return

        raise SpeechError(
            f"no text-to-speech provider could speak this reply "
            f"(tried {self._name} and {len(self._tried)} alternative(s))."
        )

    def stop(self) -> None:
        self._speaker.stop()

    def _take_over(self, provider: str, speaker: Speaker) -> None:
        self._speaker = speaker
        self._name = provider
        self.switched_to = provider
        if self._on_switch is not None:
            self._on_switch(provider)


def build_speaker_with_fallback(cfg, on_switch=None) -> Speaker:
    """A speaker that keeps working when the configured provider cannot.

    Construction is attempted first, so a missing key or an unknown provider
    falls back immediately. A provider that builds but fails at speak time is
    handled by `FallbackSpeaker` on the first real sentence.

    Returns the speaker; its `.provider` is the provider actually in use.
    """
    try:
        primary = build_speaker(cfg)
    except SpeechError as first_error:
        # Nothing configured works, so start from the first alternative.
        problems = [f"{cfg.provider}: {first_error}"]
        for provider in FALLBACK_ORDER:
            try:
                speaker = FallbackSpeaker(
                    _build_named(cfg, provider), provider, cfg, on_switch
                )
            except SpeechError as exc:
                problems.append(f"{provider}: {exc}")
                continue
            return speaker
        raise SpeechError(
            "No text-to-speech provider could be built.\n  " + "\n  ".join(problems)
        )

    return FallbackSpeaker(primary, cfg.provider, cfg, on_switch)
