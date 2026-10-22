"""Fetch the openWakeWord models, which are not in the pip package.

openWakeWord ships its Python package but not its weights — those live in the
GitHub releases, because they are large and because the package is meant to
track them loosely. A first run would otherwise fail with a confusing
`File doesn't exist` from deep inside onnxruntime.

Models are ~1 MB each and land in openWakeWord's own resources directory, which
is where its own loader looks for them. Nothing is cached elsewhere and nothing
is re-downloaded once present.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"

# What an inference-only install needs: the melspec/embedding front end and the
# one keyword. openWakeWord also supports onnxruntime for the feature model,
# which is why these are .onnx and not .tflite.
DEFAULT_MODELS = {
    "melspectrogram.onnx": "melspectrogram.onnx",
    "embedding_model.onnx": "embedding_model.onnx",
    "hey_jarvis_v0.1.onnx": "hey_jarvis_v0.1.onnx",
}

# Useful extras, fetched only when asked.
EXTRA_MODELS = {
    "alexa_v0.1.onnx",
    "hey_mycroft_v0.1.onnx",
    "hey_rhasspy_v0.1.onnx",
    "timer_v0.1.onnx",
    "weather_v0.1.onnx",
}


def models_dir() -> Path:
    """Where openWakeWord keeps its weights.

    Found with `find_spec` rather than `import` on purpose: importing the
    package runs its `__init__`, which pulls in scikit-learn through the custom
    verifier. This tool does not need that, and neither does inference.
    """
    import importlib.util

    spec = importlib.util.find_spec("openwakeword")
    if spec is None or spec.origin is None:
        raise SystemExit(
            "openWakeWord is not installed.\n"
            "  Install it with: .venv/bin/pip install --no-deps openwakeword"
        )

    return Path(spec.origin).parent / "resources" / "models"


def fetch(names: list[str], *, force: bool = False) -> list[Path]:
    """Download each model into openWakeWord's resources directory.

    Returns the paths written. Skips anything already present unless `force`.
    """
    import httpx

    target_dir = models_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for name in names:
        path = target_dir / name
        if path.exists() and not force:
            print(f"  {name} already present ({path.stat().st_size:,} bytes)")
            written.append(path)
            continue

        url = f"{BASE}/{name}"
        print(f"  {name} ...", end=" ", flush=True)
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
                r.raise_for_status()
                with path.open("wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
        except Exception as exc:  # noqa: BLE001 - a failed download is not fatal
            path.unlink(missing_ok=True)
            print(f"failed ({type(exc).__name__})")
            raise SystemExit(
                f"could not download {name}: {exc}\n"
                f"  from {url}\n"
                "  Check the network and try again; the models can also be "
                "placed by hand in " + str(target_dir)
            ) from exc

        print(f"{path.stat().st_size:,} bytes")
        written.append(path)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all", action="store_true", help="also fetch the extra keywords"
    )
    parser.add_argument(
        "--force", action="store_true", help="re-download even if present"
    )
    args = parser.parse_args(argv)

    names = list(DEFAULT_MODELS.values())
    if args.all:
        names += sorted(EXTRA_MODELS)

    print(f"Downloading {len(names)} model(s) into {models_dir()}")
    fetch(names, force=args.force)
    print("\nDone. Start him with: ./jarvis-wake")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
