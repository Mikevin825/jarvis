"""Listen to the mic and print what the wake-word detector hears.

The wake loop gives no feedback when it is working, so a silent failure is
indistinguishable from a broken one. This prints the live signal level and the
model's score per frame, which answers both questions at once:

  * is audio actually arriving?        -> the RMS level
  * is the model hearing the word?      -> the score

Run it, then say "jarvis" a few times.

    .venv/bin/python -m jarvis.tools.wake_debug --seconds 20
"""

from __future__ import annotations

import argparse
import array
import subprocess
import sys
import time

from jarvis.voice.wake import (
    OPENWAKEWORD_KEYWORDS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    WakeError,
    _rms,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--keyword", default="jarvis")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args(argv)

    try:
        from jarvis.voice.wake import OpenWakeWordDetector
    except Exception as exc:  # noqa: BLE001
        print(f"cannot import the detector: {exc}")
        return 2

    keyword = OPENWAKEWORD_KEYWORDS.get(args.keyword, args.keyword)
    try:
        detector = OpenWakeWordDetector(keyword=keyword, threshold=args.threshold)
    except WakeError as exc:
        print(f"cannot start the detector:\n{exc}")
        return 2

    frame_bytes = detector.frame_length * SAMPLE_WIDTH
    print(f"Listening for {args.seconds:.0f}s. Say \"{args.keyword}\" a few times.\n")
    print(f"{'time':>6}  {'level':>7}  {'score':>6}  state")
    print("-" * 40)

    proc = subprocess.Popen(
        ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
         "-c", "1", "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None

    started = time.time()
    best = 0.0
    hits = 0
    try:
        while time.time() - started < args.seconds:
            pcm = proc.stdout.read(frame_bytes)
            if not pcm:
                break
            level = _rms(pcm)
            score = max(detector._model.predict(
                __import__("numpy").frombuffer(pcm, dtype=__import__("numpy").int16)
            ).values())
            best = max(best, score)
            fired = score > args.threshold
            hits += fired
            state = "WAKE" if fired else ("listening" if level > 500 else "silent")
            if level > 500 or fired or int(time.time() - started) % 5 == 0:
                print(f"{time.time() - started:6.1f}  {level:7.0f}  {score:6.3f}  {state}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        detector.close()

    print("-" * 40)
    print(f"best score: {best:.3f}   (threshold {args.threshold})")
    print(f"wake events: {hits}")
    if best < 0.05:
        print("\nThe model barely reacted. Either the mic is not hearing you, or")
        print("the word is not being spoken clearly. Check the level column: if it")
        print("stays near 0 the mic is silent.")
    elif best < args.threshold:
        print(f"\nIt heard something (peak {best:.3f}) but not past the threshold.")
        print("Try lowering voice.wake_sensitivity in config.yaml.")
    else:
        print("\nIt is working. The wake loop should fire.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
