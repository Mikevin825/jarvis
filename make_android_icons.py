to?
"""Generate the Android launcher icons — pure stdlib, same orb as the PWA.

Android needs mipmap-*/ic_launcher.png at several densities. The shape is a
radial gradient, so it is cheap to compute per pixel.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ANDROID = Path(__file__).resolve().parent / "android"
BG = (10, 10, 18)
GOLD = (255, 194, 71)
GOLD_LIGHT = (255, 224, 138)
GOLD_DARK = (122, 74, 30)

# density bucket -> icon size in px
DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * max(0.0, min(1.0, t)))


def _pixel(x: int, y: int, size: int) -> tuple[int, int, int]:
    cx = cy = size / 2.0
    dx = (x + 0.5 - cx) / (size / 2.0)
    dy = (y + 0.5 - cy) / (size / 2.0)
    r = (dx * dx + dy * dy) ** 0.5

    # Android masks the icon, so keep the orb well inside the safe zone.
    if r > 0.62:
        return BG

    shade = ((dx + 0.35) ** 2 + (dy + 0.35) ** 2) ** 0.5 / 1.1
    if shade < 0.5:
        t = shade / 0.5
        return (_lerp(GOLD_LIGHT[0], GOLD[0], t),
                _lerp(GOLD_LIGHT[1], GOLD[1], t),
                _lerp(GOLD_LIGHT[2], GOLD[2], t))
    t = (shade - 0.5) / 0.5
    return (_lerp(GOLD[0], GOLD_DARK[0], t),
            _lerp(GOLD[1], GOLD_DARK[1], t),
            _lerp(GOLD[2], GOLD_DARK[2], t))


def write_png(path: Path, size: int) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(_pixel(x, y, size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> int:
    for bucket, size in DENSITIES.items():
        d = ANDROID / "res" / bucket
        d.mkdir(parents=True, exist_ok=True)
        target = d / "ic_launcher.png"
        write_png(target, size)
        print(f"wrote {target} ({size}x{size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
