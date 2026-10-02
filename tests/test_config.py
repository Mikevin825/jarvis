"""Configuration must be the single source of truth, and keys must resolve."""

from __future__ import annotations

import os

import pytest
import yaml


def write_config(tmp_path, data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


BASE = {
    "assistant": {"name": "JARVIS", "purpose": "help", "tone": "crisp"},
    "brain": {
        "provider": "gemini",
        "gemini": {
            "model": "gemini-3.5-flash",
            "base_url": "https://example.invalid",
            "api_key_env": "TEST_GEMINI_KEY",
        },
    },
}


def test_missing_config_is_a_clear_error(tmp_path):
    from jarvis.config import ConfigError, load_config

    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_missing_required_value_is_reported(tmp_path):
    from jarvis.config import ConfigError, load_config

    data = {"assistant": {"purpose": "x", "tone": "y"}, "brain": BASE["brain"]}
    with pytest.raises(ConfigError) as exc:
        load_config(write_config(tmp_path, data))
    assert "name" in str(exc.value)


def test_unknown_provider_block_is_reported(tmp_path):
    from jarvis.config import ConfigError, load_config

    data = dict(BASE)
    data["brain"] = {"provider": "gemini"}  # no gemini block
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


def test_defaults_apply_for_optional_sections(tmp_path):
    """A minimal config must still produce a complete, usable object."""
    from jarvis.config import load_config

    cfg = load_config(write_config(tmp_path, BASE))
    assert cfg.voice.ptt_key == "f9"
    assert cfg.rails.confirm_consequential is True
    assert cfg.heartbeat.enabled is True
    assert cfg.stt.provider == "whisper"
    assert cfg.tts.provider in ("espeak", "edge", "piper", "elevenlabs")


def test_ungated_tools_defaults_to_empty(tmp_path):
    """Loosening a safety rule must never be a default."""
    from jarvis.config import load_config

    cfg = load_config(write_config(tmp_path, BASE))
    assert cfg.rails.ungated_tools == ()
    assert cfg.rails.extra_gated_tools == ()


def test_keys_resolve_for_every_provider_not_just_the_active_one(tmp_path, monkeypatch):
    """The bug that made a pasted ElevenLabs key invisible.

    A key present in the environment must stay usable even when another
    provider is the active one.
    """
    from jarvis.config import load_config

    monkeypatch.setenv("TEST_GEMINI_KEY", "gemini-value")
    monkeypatch.setenv("TEST_ELEVEN_KEY", "eleven-value")

    data = dict(BASE)
    data["tts"] = {
        "provider": "espeak",  # NOT elevenlabs
        "elevenlabs": {"api_key_env": "TEST_ELEVEN_KEY", "voice": "v"},
    }
    cfg = load_config(write_config(tmp_path, data))

    assert cfg.tts.provider == "espeak"
    assert cfg.tts.api_key is None, "the active provider has no key"
    assert cfg.tts.api_keys.get("elevenlabs") == "eleven-value", (
        "an inactive provider's key must still be visible"
    )


def test_environment_wins_over_dotenv(tmp_path, monkeypatch):
    from jarvis.config import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("JARVIS_TEST_KEY=from_file\n")
    monkeypatch.setenv("JARVIS_TEST_KEY", "from_env")
    load_dotenv(env_file)
    assert os.environ["JARVIS_TEST_KEY"] == "from_env"


def test_dotenv_handles_quotes_and_comments(tmp_path, monkeypatch):
    from jarvis.config import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text(
        '# a comment\nQUOTED_KEY="a value"\nSINGLE_KEY=\'b value\'\n\nIGNORED\n'
    )
    monkeypatch.delenv("QUOTED_KEY", raising=False)
    monkeypatch.delenv("SINGLE_KEY", raising=False)
    load_dotenv(env_file)
    assert os.environ["QUOTED_KEY"] == "a value"
    assert os.environ["SINGLE_KEY"] == "b value"
