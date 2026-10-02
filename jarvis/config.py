"""Configuration loading.

Reads `config.yaml` and a git-ignored `.env` from the project root. Nothing in
the harness hardcodes a model name, a threshold, or a key — it all comes from
here, so tuning is an edit, not a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or malformed."""


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE lines from `.env` into the environment.

    Deliberately tiny and dependency-free. Real environment variables always
    win, so `FOO=bar python -m jarvis` overrides the file.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class AssistantConfig:
    name: str
    purpose: str
    tone: str


@dataclass(frozen=True)
class BrainConfig:
    provider: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: float
    # The active provider's settings, already resolved from the block matching
    # `provider`. The rest of the harness never has to know which one it got.
    model: str
    base_url: str
    api_key: str | None


@dataclass(frozen=True)
class SttConfig:
    provider: str
    model: str
    language: str
    timeout_seconds: float
    # Local whisper options
    device: str
    compute_type: str
    api_key: str | None


@dataclass(frozen=True)
class TtsConfig:
    provider: str
    model: str
    voice: str
    rate: float
    timeout_seconds: float
    api_key: str | None
    # edge-tts uses string modifiers like "+10%" and "+0Hz"
    rate_str: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    # piper
    voices_dir: str | None = None
    length_scale: float = 1.0


@dataclass(frozen=True)
class VoiceConfig:
    ptt_key: str
    interrupt_key: str
    speak_replies: bool
    show_transcript: bool
    thinking_cue: bool
    min_sentence_chars: int


@dataclass(frozen=True)
class Config:
    assistant: AssistantConfig
    brain: BrainConfig
    stt: SttConfig
    tts: TtsConfig
    voice: VoiceConfig


def _require(mapping: dict, key: str, where: str):
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"missing required config value: {where}.{key}")
    return mapping[key]


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    assistant_raw = raw.get("assistant") or {}
    brain_raw = raw.get("brain") or {}
    stt_raw = raw.get("stt") or {}
    tts_raw = raw.get("tts") or {}
    voice_raw = raw.get("voice") or {}

    provider = _require(brain_raw, "provider", "brain")
    provider_block = (brain_raw.get(provider) or {})
    if not provider_block:
        raise ConfigError(
            f"brain.provider is '{provider}' but there is no brain.{provider} block"
        )

    # API keys are read from the environment at load time, never stored in the
    # config file and never written to source.
    api_key = None
    key_env = provider_block.get("api_key_env")
    if key_env:
        api_key = os.environ.get(key_env)

    stt_provider = stt_raw.get("provider", "whisper")
    stt_block = stt_raw.get(stt_provider) or {}
    stt_key = None
    if stt_block.get("api_key_env"):
        stt_key = os.environ.get(stt_block["api_key_env"])

    tts_provider = tts_raw.get("provider", "espeak")
    tts_block = tts_raw.get(tts_provider) or {}
    tts_key = None
    if tts_block.get("api_key_env"):
        tts_key = os.environ.get(tts_block["api_key_env"])

    return Config(
        assistant=AssistantConfig(
            name=_require(assistant_raw, "name", "assistant"),
            purpose=_require(assistant_raw, "purpose", "assistant"),
            tone=_require(assistant_raw, "tone", "assistant"),
        ),
        brain=BrainConfig(
            provider=provider,
            temperature=float(brain_raw.get("temperature", 0.7)),
            max_output_tokens=int(brain_raw.get("max_output_tokens", 2048)),
            timeout_seconds=float(brain_raw.get("timeout_seconds", 60)),
            model=_require(provider_block, "model", f"brain.{provider}"),
            base_url=_require(provider_block, "base_url", f"brain.{provider}"),
            api_key=api_key,
        ),
        stt=SttConfig(
            provider=stt_provider,
            model=stt_block.get("model", "base.en"),
            language=stt_block.get("language", "en"),
            timeout_seconds=float(stt_block.get("timeout_seconds", 60)),
            device=stt_block.get("device", "cpu"),
            compute_type=stt_block.get("compute_type", "int8"),
            api_key=stt_key,
        ),
        tts=TtsConfig(
            provider=tts_provider,
            model=tts_block.get("model", "eleven_turbo_v2_5"),
            voice=tts_block.get("voice", "en-gb"),
            rate=float(tts_block.get("rate", 165)),
            timeout_seconds=float(tts_block.get("timeout_seconds", 60)),
            api_key=tts_key,
            rate_str=str(tts_block.get("rate_str", "+0%")),
            volume=str(tts_block.get("volume", "+0%")),
            pitch=str(tts_block.get("pitch", "+0Hz")),
            voices_dir=tts_block.get("voices_dir"),
            length_scale=float(tts_block.get("length_scale", 1.0)),
        ),
        voice=VoiceConfig(
            ptt_key=str(voice_raw.get("ptt_key", "space")).lower(),
            interrupt_key=str(voice_raw.get("interrupt_key", "esc")).lower(),
            speak_replies=bool(voice_raw.get("speak_replies", True)),
            show_transcript=bool(voice_raw.get("show_transcript", True)),
            thinking_cue=bool(voice_raw.get("thinking_cue", True)),
            min_sentence_chars=int(voice_raw.get("min_sentence_chars", 2)),
        ),
    )
