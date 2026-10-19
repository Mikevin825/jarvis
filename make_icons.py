"""Generate the PWA icons with pure stdlib — no PIL, no dependencies.

Writes a gold orb on a dark background as a PNG. Straightforward because
the shape is a radial gradient, which is cheap to compute per pixel.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "mobile"

BG = (10, 10, 18)
GOLD = (255, 194, 71)
GOLD_LIGHT = (255, 224, 138)
GOLD_DARK = (122, 74, 30)


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * max(0.0, min(1.0, t)))


def _pixel(x: int, y: int, size: int) -> tuple[int, int, int]:
    """One pixel of the orb, or the background."""
    cx = cy = size / 2.0
    dx = (x + 0.5 - cx) / (size / 2.0)
    dy = (y + 0.5 - cy) / (size / 2.0)
    r = (dx * dx + dy * dy) ** 0.5

    orb_r = 0.68  # the orb occupies most of the icon
    if r > orb_r:
        return BG

    # Radial gradient: light at the upper-left, dark at the lower-right.
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
    """Write an RGB PNG, one filter byte per row, zlib-compressed."""
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type 0 (None)
        for x in range(size):
            raw.extend(_pixel(x, y, size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        target = OUT_DIR / f"icon-{size}.png"
        write_png(target, size)
        print(f"wrote {target} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
