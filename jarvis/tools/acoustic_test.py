"""Measure how much the acoustic path costs the wake word.

Plays a known phrase through the speakers and captures it with the mic, so the
same audio can be scored two ways:

    direct   -> the model's ceiling for that phrase
    acoustic -> what actually arrives at the mic

The gap between them is the cost of the room. If the gap is large, no
threshold will help and the answer is to get closer to the mic.

    .venv/bin/python -m jarvis.tools.acoustic_test
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SAMPLES = Path("/tmp")


def direct_score(detector, path: Path) -> tuple[float, int]:
    """Score a file straight off disk — the ceiling."""
    with wave.open(str(path)) as w:
        raw = w.readframes(w.getnframes())
    return _score_frames(detector, raw)


def acoustic_score(detector, path: Path, seconds: float = 6.0) -> tuple[float, int]:
    """Play a file out loud and capture it back through the mic."""
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
    return _score_frames(detector, raw)


def _score_frames(detector, raw: bytes) -> tuple[float, int]:
    step = detector.frame_length * 2
    scores = []
    for i in range(0, len(raw) - step + 1, step):
        samples = np.frombuffer(raw[i:i + step], dtype=np.int16)
        scores.append(float(max(detector._model.predict(samples).values())))
    return (max(scores) if scores else 0.0), sum(
        1 for s in scores if s > detector._threshold
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default="tts_jarvis.wav")
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--vad", type=float, default=0.5)
    parser.add_argument("--no-vad", action="store_true")
    args = parser.parse_args(argv)

    sample = SAMPLES / args.sample
    if not sample.exists():
        print(f"no sample at {sample}")
        return 2

    from jarvis.voice.wake import OpenWakeWordDetector

    vad = 0.0 if args.no_vad else args.vad
    detector = OpenWakeWordDetector(
        keyword="hey_jarvis", threshold=args.threshold, vad_threshold=vad
    )
    try:
        direct, direct_hits = direct_score(detector, sample)
        acoustic, acoustic_hits = acoustic_score(detector, sample)
    finally:
        detector.close()

    print(f"sample:  {args.sample}")
    print(f"vad:     {'off' if args.no_vad else args.vad}")
    print(f"direct:   {direct:.3f}  ({direct_hits} frames over {args.threshold})")
    print(f"acoustic: {acoustic:.3f}  ({acoustic_hits} frames over {args.threshold})")
    print()

    if acoustic > 0.5:
        print("Works through the room. Wake mode should fire.")
    elif direct > 0.5 and acoustic < 0.2:
        print("The phrase scores well direct but badly through the mic.")
        print("That is a distance/acoustics problem, not a model one — get")
        print("closer to the mic, or use a headset.")
    elif direct < 0.5:
        print("The phrase does not score well even direct. Try another sample")
        print("or another keyword.")
    else:
        print("Marginal. Lowering the threshold may help, but watch for false wakes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
