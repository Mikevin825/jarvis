"""Speech-to-text: the Deepgram path and the local fallback.

The point of Deepgram here is latency — whisper on CPU takes ~10s per utterance,
which makes a spoken conversation feel like a walkie-talkie. These tests cover
the wire format and the failure messages, since a cloud dependency failing badly
is the thing most likely to leave the assistant mysteriously mute.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from jarvis.voice.stt import (
    DeepgramTranscriber,
    TranscriptionError,
    WhisperTranscriber,
    build_transcriber,
)


class FakeConfig:
    def __init__(self, **kw):
        self.provider = kw.get("provider", "deepgram")
        self.model = kw.get("model", "nova-3")
        self.language = kw.get("language", "en")
        self.timeout_seconds = kw.get("timeout_seconds", 30)
        self.device = kw.get("device", "cpu")
        self.compute_type = kw.get("compute_type", "int8")
        self.api_key = kw.get("api_key", "test-key")


@pytest.fixture()
def wav(tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


def _response(status=200, payload=None):
    return httpx.Response(
        status_code=status,
        json=payload if payload is not None else {},
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )


def good_payload(transcript="What is the weather in Paris?"):
    return {
        "metadata": {"duration": 2.4},
        "results": {
            "channels": [{"alternatives": [{"transcript": transcript}]}]
        },
    }


# -- the happy path ---------------------------------------------------------


def test_transcript_is_extracted(monkeypatch, wav):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(200, good_payload()))
    t = DeepgramTranscriber("key")
    assert t.transcribe(wav) == "What is the weather in Paris?"


def test_audio_duration_is_recorded(monkeypatch, wav):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(200, good_payload()))
    t = DeepgramTranscriber("key")
    t.transcribe(wav)
    assert t.last_duration == 2.4


def test_request_uses_the_right_wire_format(monkeypatch, wav):
    """Audio as the body, options as query params, token in the header."""
    seen = {}

    def capture(url, **kwargs):
        seen["url"] = url
        seen["params"] = kwargs.get("params", {})
        seen["headers"] = kwargs.get("headers", {})
        seen["content"] = kwargs.get("content")
        return _response(200, good_payload())

    monkeypatch.setattr(httpx, "post", capture)
    DeepgramTranscriber("my-key", model="nova-3").transcribe(wav)

    assert seen["url"] == "https://api.deepgram.com/v1/listen"
    assert seen["params"]["model"] == "nova-3"
    assert seen["params"]["smart_format"] == "true"
    assert seen["headers"]["Authorization"] == "Token my-key"
    assert seen["headers"]["Content-Type"] == "audio/wav"
    assert seen["content"] == wav.read_bytes()


def test_empty_transcript_is_returned_not_raised(monkeypatch, wav):
    """Silence is not an error — the caller reports 'heard nothing'."""
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(200, good_payload("")))
    assert DeepgramTranscriber("key").transcribe(wav) == ""


# -- failures must be legible -------------------------------------------------


def test_bad_key_says_so(monkeypatch, wav):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(401))
    with pytest.raises(TranscriptionError, match="rejected the key"):
        DeepgramTranscriber("bad").transcribe(wav)


def test_no_credit_says_so_and_offers_the_local_path(monkeypatch, wav):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(402))
    with pytest.raises(TranscriptionError) as exc:
        DeepgramTranscriber("key").transcribe(wav)
    assert "credit" in str(exc.value)
    assert "whisper" in str(exc.value), "the fallback must be offered"


def test_rate_limit_says_so(monkeypatch, wav):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(429))
    with pytest.raises(TranscriptionError, match="rate limit"):
        DeepgramTranscriber("key").transcribe(wav)


def test_unknown_model_points_at_the_model_setting(monkeypatch, wav):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(400))
    with pytest.raises(TranscriptionError) as exc:
        DeepgramTranscriber("key", model="nova-9").transcribe(wav)
    assert "nova-9" in str(exc.value)
    assert "config.yaml" in str(exc.value)


def test_network_failure_offers_the_offline_path(monkeypatch, wav):
    def boom(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(TranscriptionError) as exc:
        DeepgramTranscriber("key").transcribe(wav)
    assert "whisper" in str(exc.value)


def test_timeout_is_reported_clearly(monkeypatch, wav):
    def slow(*a, **k):
        raise httpx.TimeoutException("too slow")

    monkeypatch.setattr(httpx, "post", slow)
    with pytest.raises(TranscriptionError, match="did not respond in time"):
        DeepgramTranscriber("key").transcribe(wav)


def test_unreadable_response_is_reported(monkeypatch, wav):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _response(200, {"weird": True}))
    with pytest.raises(TranscriptionError, match="could not read"):
        DeepgramTranscriber("key").transcribe(wav)


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(TranscriptionError, match="no recording"):
        DeepgramTranscriber("key").transcribe(tmp_path / "nope.wav")


# -- construction ------------------------------------------------------------


def test_build_selects_deepgram():
    t = build_transcriber(FakeConfig(provider="deepgram", api_key="k"))
    assert isinstance(t, DeepgramTranscriber)
    assert t.model == "nova-3"


def test_build_selects_whisper():
    t = build_transcriber(FakeConfig(provider="whisper", model="base.en"))
    assert isinstance(t, WhisperTranscriber)


def test_deepgram_without_a_key_explains_the_fix():
    with pytest.raises(TranscriptionError) as exc:
        build_transcriber(FakeConfig(provider="deepgram", api_key=None))
    assert "DEEPGRAM_API_KEY" in str(exc.value)
    assert "whisper" in str(exc.value)


def test_unknown_provider_is_rejected():
    with pytest.raises(TranscriptionError, match="unknown stt.provider"):
        build_transcriber(FakeConfig(provider="telepathy"))


def test_whisper_is_still_available_as_the_offline_path():
    """Swapping to the cloud must not remove the ability to work offline."""
    t = build_transcriber(FakeConfig(provider="whisper", model="base.en"))
    assert isinstance(t, WhisperTranscriber)
    assert t.model_size == "base.en"
