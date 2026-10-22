"""Sweep VAD and wake thresholds against the real acoustic path.

Synthetic testing of a wake word is unreliable on its own: openWakeWord zeroes
its first 5 frames and its streaming melspectrogram needs warm-up, so scores
from a cold detector say nothing about real use.

This warms the detector up first (feeding it speech it should NOT wake on),
then measures the phrase of interest, for each combination. Warm-up matters —
it is the difference between a working detector and a dead one.

    .venv/bin/python -m jarvis.tools.threshold_sweep
"""

from __future__ import annotations

import argparse
import subprocess
import wave
from pathlib import Path

import numpy as np

SAMPLES = Path("/tmp")
WARMUP = SAMPLES / "tts_what_time_is_it.wav"
TARGET = SAMPLES / "tts_jarvis.wav"


def read(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        return w.readframes(w.getnframes())


def score(detector, raw: bytes, step: int) -> list[float]:
    return [
        float(max(detector._model.predict(
            np.frombuffer(raw[i:i + step], dtype=np.int16)
        ).values()))
        for i in range(0, len(raw) - step + 1, step)
    ]


def acoustic(detector, path: Path, seconds: float = 6.0) -> bytes:
    proc = subprocess.Popen(
        ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1",
         "-t", "raw", "-d", str(int(seconds))],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    player = subprocess.Popen(["aplay", "-q", str(path)])
    raw = proc.stdout.read()
    proc.wait()
    player.wait()
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=TARGET.name)
    args = parser.parse_args(argv)

    from jarvis.voice.wake import OpenWakeWordDetector

    target = SAMPLES / args.target
    if not target.exists() or not WARMUP.exists():
        print("need the TTS samples in /tmp first")
        return 2

    print(f"target: {target.name}\n")
    print(f"{'vad':>5} {'wake':>6} {'max':>7} {'frames':>7}")
    print("-" * 30)

    best = None
    for vad in (0.0, 0.3, 0.5):
        for wake in (0.5, 0.35, 0.25, 0.15):
            d = OpenWakeWordDetector(
                keyword="hey_jarvis", threshold=wake, vad_threshold=vad
            )
            try:
                # Warm up on speech that must NOT wake.
                score(d, read(WARMUP), d.frame_length * 2)
                # Then measure the phrase through the real acoustic path.
                raw = acoustic(d, target)
                scores = score(d, raw, d.frame_length * 2)
            finally:
                d.close()

            top = max(scores) if scores else 0.0
            hits = sum(1 for s in scores if s > wake)
            print(f"{vad:5.1f} {wake:6.2f} {top:7.3f} {hits:7d}")
            if top > wake and (best is None or top > best[2]):
                best = (vad, wake, top)

    print("-" * 30)
    if best:
        print(f"best: vad={best[0]} wake={best[1]} (score {best[2]:.3f})")
    else:
        print("nothing cleared its own threshold through the room.")
        print("The mic is too far from the speaker — no threshold will fix that.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
