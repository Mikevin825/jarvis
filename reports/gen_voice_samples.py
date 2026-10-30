"""Generate TTS samples from Gemini voices and save them as mp3."""
import base64, json, struct, subprocess, sys, wave
from pathlib import Path

import httpx

from jarvis.config import load_config, load_dotenv

SENTENCE = ("Good afternoon. All systems are nominal. Shall I run the diagnostics, "
            "or is there something else you need?")

OUT = Path.home() / "jarvis" / "reports" / "gemini-tts-samples"
OUT.mkdir(parents=True, exist_ok=True)


def rms(path: Path) -> float:
    with wave.open(str(path)) as w:
        frames = w.readframes(w.getnframes())
    n = len(frames) // 2
    if not n:
        return 0.0
    vals = struct.unpack(f"<{n}h", frames[: n * 2])
    return (sum(v * v for v in vals) / n) ** 0.5


def synth(voice: str, label: str) -> str:
    body = {
        "contents": [{"parts": [{"text": SENTENCE}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    r = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent",
        headers={"x-goog-api-key": KEY, "Content-Type": "application/json"},
        json=body, timeout=120,
    )
    if r.status_code != 200:
        return f"{label}: {r.status_code} {(r.json().get('error') or {}).get('message','')[:100]}"
    raw = base64.b64decode(
        r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    )
    wav = OUT / f"{label}.wav"
    wav.write_bytes(raw)
    mp3 = OUT / f"{label}.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", str(wav), str(mp3)], check=True)
    return f"{label:20s} rms={rms(wav):7.1f}  {mp3.name}"


load_dotenv()
KEY = load_config().brain.api_key

targets = json.loads(Path(sys.argv[1]).read_text())
for label, voice in targets.items():
    print(synth(voice, label))
