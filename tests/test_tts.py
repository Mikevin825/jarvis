"""Tests for the text-to-speech layer.

No network and no audio: the providers are stubbed, so what is proven is the
decision-making — which voice is used, when a fallback engages, that a switch
is announced once, and that the user is told the right reason when the
configured provider cannot speak.
"""

from __future__ import annotations

import pytest

from jarvis.voice import tts as tts_mod
from jarvis.voice.tts import FallbackSpeaker, SpeechError, build_speaker_with_fallback


class _Cfg:
    """The slice of TtsConfig the tts layer reads.

    Provides enough attributes for all providers, with most defaulting to
    working values that don't require external services.
    """

    def __init__(
        self,
        provider: str = "edge",
        providers: dict | None = None,
        api_key: str | None = None,
        voice: str = "en-GB-RyanNeural",
        model: str = "",
        timeout_seconds: float = 60.0,
        speed: float = 1.0,
        volume_db: float = 0.0,
        normalize: bool = True,
    ):
        self.provider = provider
        self.providers = providers or {}
        self.api_key = api_key
        self.voice = voice
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.speed = speed
        self.volume_db = volume_db
        self.normalize = normalize
        # edge-tts needs these as strings
        self.rate_str = "+0%"
        self.volume = "+0%"
        self.pitch = "+0Hz"
        self.rate = 165  # espeak
        self.voices_dir = None
        self.length_scale = 1.0


class _FailingSpeaker:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.stopped = 0

    def speak(self, text: str) -> None:
        raise self._error

    def stop(self) -> None:
        self.stopped += 1


class _WorkingSpeaker:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.stopped = 0

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        self.stopped += 1


# -- the rejection message --------------------------------------------------


class TestRejectionMessage:
    def test_quota_exceeded_is_not_reported_as_a_bad_key(self):
        """ElevenLabs answers 401 to an exhausted quota as well as a bad key.

        Verified against a live key: 401 with detail.code "quota_exceeded" once
        the free tier ran out. Sending the user to check a working key is the
        wrong instruction.
        """

        class _Response:
            def read(self) -> bytes:
                return b'{"detail":{"code":"quota_exceeded","message":"0 credits"}}'

        message = str(tts_mod._elevenlabs_rejection(_Response()))
        assert "quota" in message.lower()
        assert "rejected the key" not in message

    def test_a_genuine_auth_failure_still_blames_the_key(self):
        class _Response:
            def read(self) -> bytes:
                return b'{"detail":{"code":"unauthorized"}}'

        assert "rejected the key" in str(tts_mod._elevenlabs_rejection(_Response()))

    def test_an_unreadable_body_does_not_crash_the_reader(self):
        class _Response:
            def read(self) -> bytes:
                raise RuntimeError("no body")

        assert "rejected the key" in str(tts_mod._elevenlabs_rejection(_Response()))


# -- the fallback chain -----------------------------------------------------


class TestFallbackSpeaker:
    def test_a_working_primary_is_used_and_nothing_else_is_built(self, monkeypatch):
        built: list[str] = []
        monkeypatch.setattr(
            tts_mod, "_build_named", lambda cfg, p: built.append(p) or _WorkingSpeaker()
        )
        primary = _WorkingSpeaker()

        speaker = FallbackSpeaker(primary, "elevenlabs", _Cfg())
        speaker.speak("hello")

        assert primary.spoken == ["hello"]
        assert built == [], "a working voice must not pay for the alternatives"

    def test_a_failing_primary_switches_and_announces_it(self, monkeypatch):
        primary = _FailingSpeaker(SpeechError("quota used up"))
        fallback = _WorkingSpeaker()
        monkeypatch.setattr(tts_mod, "_build_named", lambda cfg, p: fallback)
        announced: list[str] = []

        speaker = FallbackSpeaker(
            primary, "elevenlabs", _Cfg(), on_switch=announced.append
        )
        speaker.speak("hello")

        assert fallback.spoken == ["hello"]
        assert announced == [tts_mod.FALLBACK_ORDER[0]], "the switch must be announced"

    def test_the_switch_happens_once_not_on_every_turn(self, monkeypatch):
        """Retrying a broken provider every turn would fail every turn."""
        primary = _FailingSpeaker(SpeechError("quota used up"))
        fallback = _WorkingSpeaker()
        monkeypatch.setattr(tts_mod, "_build_named", lambda cfg, p: fallback)
        announced: list[str] = []

        speaker = FallbackSpeaker(
            primary, "elevenlabs", _Cfg(), on_switch=announced.append
        )
        speaker.speak("first")
        speaker.speak("second")

        assert fallback.spoken == ["first", "second"]
        assert announced == [tts_mod.FALLBACK_ORDER[0]]

    def test_stop_reaches_the_provider_in_use(self, monkeypatch):
        primary = _FailingSpeaker(SpeechError("quota used up"))
        fallback = _WorkingSpeaker()
        monkeypatch.setattr(tts_mod, "_build_named", lambda cfg, p: fallback)

        speaker = FallbackSpeaker(primary, "elevenlabs", _Cfg())
        speaker.speak("hello")
        speaker.stop()

        assert fallback.stopped == 1

    def test_a_non_speech_failure_is_not_swallowed(self, monkeypatch):
        """A crash in the speaker is not a provider problem and must propagate."""
        primary = _FailingSpeaker(RuntimeError("bug in the player"))
        fallback = _WorkingSpeaker()
        monkeypatch.setattr(tts_mod, "_build_named", lambda cfg, p: fallback)

        speaker = FallbackSpeaker(primary, "elevenlabs", _Cfg())
        with pytest.raises(RuntimeError):
            speaker.speak("hello")
        assert fallback.spoken == []


class TestBuildWithFallback:
    def test_an_unbuildable_configured_provider_falls_back(self, monkeypatch):
        """No key configured: construction fails, so start from an alternative."""

        def refuse(cfg):
            raise SpeechError("no key")

        monkeypatch.setattr(tts_mod, "build_speaker", refuse)
        monkeypatch.setattr(
            tts_mod, "_build_named", lambda cfg, p: _WorkingSpeaker()
        )

        # Explicitly use a provider that requires an API key
        speaker = build_speaker_with_fallback(_Cfg(provider="elevenlabs", api_key=None))
        assert speaker.provider == tts_mod.FALLBACK_ORDER[0]

    def test_nothing_available_at_all_is_reported(self, monkeypatch):
        monkeypatch.setattr(
            tts_mod, "build_speaker", lambda cfg: (_ for _ in ()).throw(SpeechError("no key"))
        )

        def refuse(cfg, provider):
            raise SpeechError("not installed")

        monkeypatch.setattr(tts_mod, "_build_named", refuse)

        with pytest.raises(SpeechError, match="No text-to-speech provider"):
            build_speaker_with_fallback(_Cfg())
