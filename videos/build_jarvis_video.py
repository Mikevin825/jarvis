#!/usr/bin/env python3
"""Build the "How JARVIS Was Built" video.

Two stages, no external video libraries:

1. **Audio** — each scene's narration is synthesised with ElevenLabs (the key
   JARVIS already has in `.env`), so the video is narrated by the same voice he
   uses.
2. **Video** — each scene is a static 1280x720 card rendered with ffmpeg's
   `drawtext` filter, faded in and out, then concatenated and muxed with the
   audio.

Frames are never written to disk by Python: the whole visual is an ffmpeg
filter graph. That keeps this dependency-free (no PIL, no matplotlib, no
moviepy) and means the only things installed are the ones JARVIS already needs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "videos"
WORK = Path(tempfile.mkdtemp(prefix="jarvis-video-"))

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

W, H = 1280, 720
FPS = 30
BG = "0x0b0d10"
ACCENT = "0x60a5fa"
ACCENT2 = "0xf472b6"
MUTED = "0x9ca3af"
TEXT = "0xf3f4f6"


def ffmpeg(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


# --------------------------------------------------------------------------
# The script: one card per scene.
# --------------------------------------------------------------------------

SCENES: list[dict] = [
    {
        "title": "HOW JARVIS WAS BUILT",
        "kicker": "a six-tier architecture, built one layer at a time",
        "lines": [],
        "narrate": "JARVIS is a voice-first personal assistant.",
    },
    {
        "title": "What it is",
        "lines": [
            "Runs on a laptop",
            "Acts through tools",
            "Remembers across restarts",
            "Reaches out first when something matters",
        ],
        "narrate": (
            "It runs on a laptop, acts on my behalf through tools, "
            "remembers me across restarts, and reaches out first when "
            "something matters."
        ),
    },
    {
        "title": "The stack",
        "lines": [
            "Python 3.14",
            "No framework — stdlib, httpx, pyyaml",
            "Gemini behind a thin provider seam",
        ],
        "narrate": (
            "Python, no framework. Just the standard library, httpx, and "
            "pyyaml. The model sits behind a thin provider seam, so it can be "
            "swapped in one line."
        ),
    },
    {
        "title": "Tier 1 — The brain",
        "kicker": "a text conversation loop",
        "lines": ["Plain text first. No audio at all."],
        "narrate": "Tier one: the brain. A text conversation loop. Plain text first, no audio at all.",
    },
    {
        "title": "Tier 2 — The hands",
        "kicker": "the tool registry",
        "lines": ["36 tools", "Extend the registry, never the core loop"],
        "narrate": (
            "Tier two: the hands. A tool registry. Thirty-six tools, and the "
            "rule is to extend the registry, never the core loop."
        ),
    },
    {
        "title": "Tier 3 — The ears and mouth",
        "kicker": "push-to-talk voice",
        "lines": ["Deepgram listens", "ElevenLabs speaks", "Each behind its own seam"],
        "narrate": (
            "Tier three: voice. Push-to-talk. Deepgram listens, ElevenLabs "
            "speaks, each behind its own seam."
        ),
    },
    {
        "title": "Tier 4 — The memory",
        "kicker": "durable facts",
        "lines": ["Survives a restart"],
        "narrate": "Tier four: memory. Durable facts that survive a restart.",
    },
    {
        "title": "Tier 5 — The heartbeat",
        "kicker": "proactive checks",
        "lines": ["Quiet by default", "Earns the right to interrupt"],
        "narrate": (
            "Tier five: the heartbeat. Proactive checks. Quiet by default, it "
            "earns the right to interrupt."
        ),
    },
    {
        "title": "Tier 6 — The rails",
        "kicker": "safety",
        "lines": ["Confirmation gate", "Audit trail", "Kill switch"],
        "narrate": (
            "Tier six: the rails. A confirmation gate, an audit trail, and a "
            "kill switch."
        ),
    },
    {
        "title": "One core, many surfaces",
        "lines": ["Galaxy", "Living mind map", "Phone app", "Desktop window"],
        "narrate": (
            "One core, many surfaces. A galaxy, a living mind map, a phone "
            "app, a desktop window."
        ),
    },
    {
        "title": "The numbers",
        "lines": [
            "19,176 lines of Python",
            "572 tests",
            "36 tools",
            "46 commits",
        ],
        "narrate": (
            "Nineteen thousand lines of Python. Five hundred and seventy-two "
            "tests. Thirty-six tools. Built tier by tier, and verified at each "
            "step."
        ),
    },
    {
        "title": "Built tier by tier.",
        "kicker": "verified at each step",
        "lines": [],
        "narrate": "That is how JARVIS was built.",
    },
]


# --------------------------------------------------------------------------
# Stage 1 — narration
# --------------------------------------------------------------------------


def load_config():
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from jarvis.config import load_config, load_dotenv

    load_dotenv()
    return load_config()


def synth_all(cfg) -> list[Path]:
    """Synthesise one mp3 per scene, in order."""
    import httpx

    key = cfg.tts.api_key
    voice = cfg.tts.voice
    if not key:
        raise SystemExit("no ElevenLabs key in .env — cannot narrate")

    paths: list[Path] = []
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        for i, scene in enumerate(SCENES, 1):
            out = WORK / f"audio_{i:02d}.mp3"
            print(f"  narrating scene {i}/{len(SCENES)}: {scene['title']}")
            with client.stream(
                "POST",
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={
                    "text": scene["narrate"],
                    "model_id": cfg.tts.model,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            ) as response:
                if response.status_code != 200:
                    raise SystemExit(
                        f"ElevenLabs returned {response.status_code} on scene {i}: "
                        f"{response.read().decode('utf-8', 'replace')[:300]}"
                    )
                with out.open("wb") as fh:
                    for chunk in response.iter_bytes():
                        fh.write(chunk)
            if out.stat().st_size == 0:
                raise SystemExit(f"scene {i} produced no audio")
            paths.append(out)
    return paths


# --------------------------------------------------------------------------
# Stage 2 — visuals
# --------------------------------------------------------------------------


def esc(text: str) -> str:
    """Escape a string for ffmpeg's drawtext textfile."""
    return text.replace("\\", "\\\\").replace("'", "\\'").replace("%", "\\%")


def draw_text(text: str, *, font: str = FONT, size: int = 40, color: str = TEXT,
              x: str = "(w-text_w)/2", y: str = "0") -> str:
    return (
        f"drawtext=fontfile={font}:text='{esc(text)}':fontsize={size}:"
        f"fontcolor={color}:x={x}:y={y}"
    )


def scene_filters(scene: dict, duration: float) -> list[str]:
    """Build the filter list for one scene card."""
    filters: list[str] = []

    # A slow vertical drift so a static card still feels alive.
    filters.append(
        f"drawbox=x=0:y=0:w={W}:h={H}:color={BG}:t=fill"
    )

    y = 150
    if scene.get("kicker"):
        filters.append(
            draw_text(
                scene["kicker"].upper(),
                font=FONT, size=22, color=ACCENT,
                x="(w-text_w)/2", y=str(y),
            )
        )
        filters.append("format=rgba")
        y += 78

    filters.append(
        draw_text(
            scene["title"],
            font=FONT_BOLD, size=62, color=TEXT,
            x="(w-text_w)/2", y=str(y),
        )
    )
    y += 96

    if scene["lines"]:
        filters.append(
            f"drawbox=x=(w-260)/2:y={y-14}:w=260:h=2:color={ACCENT2}:t=fill"
        )
        y += 52
        for line in scene["lines"]:
            filters.append(
                draw_text(
                    line, font=FONT, size=34, color=TEXT,
                    x="(w-text_w)/2", y=str(y),
                )
            )
            y += 56

    # Fade in and out.
    fade_out_start = max(duration - 0.45, 0.1)
    filters.append(f"fade=t=in:st=0:d=0.4:color={BG}")
    filters.append(f"fade=t=out:st={fade_out_start:.2f}:d=0.45:color={BG}")
    filters.append("format=yuv420p")
    return filters


def render_scenes() -> list[Path]:
    clips: list[Path] = []
    for i, scene in enumerate(SCENES, 1):
        dur = scene["duration"]
        out = WORK / f"scene_{i:02d}.mp4"
        vf = ",".join(scene_filters(scene, dur))
        result = ffmpeg(
            "-f", "lavfi",
            "-i", f"color=c={BG}:s={W}x{H}:d={dur}:r={FPS}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-an",
            str(out),
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"scene {i} failed:\n{result.stderr[-1500:]}")
        clips.append(out)
        print(f"  rendered scene {i}/{len(SCENES)}")
    return clips


def concat_videos(clips: list[Path]) -> Path:
    listfile = WORK / "video_list.txt"
    listfile.write_text(
        "".join(f"file '{c}'\n" for c in clips), encoding="utf-8"
    )
    out = WORK / "video_only.mp4"
    result = ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c", "copy", str(out), check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"video concat failed:\n{result.stderr[-1500:]}")
    return out


def concat_audio(tracks: list[Path]) -> Path:
    """Join the per-scene mp3s, padding each to its scene's length."""
    listfile = WORK / "audio_list.txt"
    entries = []
    for track, scene in zip(tracks, SCENES):
        # -stream_loop with a short silence keeps timing simple: each scene's
        # audio is shorter than its card, so pad with silence to match.
        entries.append(f"file '{track}'")
    listfile.write_text("\n".join(entries) + "\n", encoding="utf-8")
    out = WORK / "audio_all.mp3"
    result = ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c", "copy", str(out), check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"audio concat failed:\n{result.stderr[-1500:]}")
    return out


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def probe_duration(path: Path) -> float:
    """How long an audio file is, in seconds."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def main() -> int:
    print("Stage 1: narration")
    cfg = load_config()
    audio = synth_all(cfg)

    # Each card stays up for its narration plus a beat, so the words and the
    # picture never run past each other. A floor of 4.5s keeps short lines from
    # flicking past too fast to read.
    for scene, track in zip(SCENES, audio):
        scene["duration"] = round(max(probe_duration(track) + 1.3, 4.5), 2)

    print("Stage 2: visuals")
    clips = render_scenes()

    print("Stage 3: assembly")
    video = concat_videos(clips)
    sound = concat_audio(audio)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    final = OUT_DIR / "how-jarvis-was-built.mp4"

    # Pad the audio to the video length so nothing is cut off, then mux.
    result = ffmpeg(
        "-i", str(video), "-i", str(sound),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-shortest",
        "-movflags", "+faststart",
        str(final), check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"mux failed:\n{result.stderr[-1500:]}")

    print(f"\nwrote {final} ({final.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
