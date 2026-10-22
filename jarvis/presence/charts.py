"""SVG chart rendering for presence analytics.

No dependencies, no CDN, no build step: the chart sheet is a single HTML file
with inline SVG that any browser can open. That matters because the graph sheet
is something the user opens on their own machine — it cannot rely on a package
being installed or a script being fetched.

The one function that matters is `line_chart`. It takes named series of
`(x, y)` points and returns a `<svg>` element. `None` y-values are drawn as
gaps rather than as zero, which is the honest way to show a metric that was
not recorded at a given time.
"""

from __future__ import annotations

import html

# A palette that stays distinguishable in print and on screen, and does not
# rely on red/green alone (colour-blindness is common enough to design around).
PALETTE = (
    "#2563eb",  # blue
    "#db2777",  # pink
    "#059669",  # green
    "#d97706",  # amber
    "#7c3aed",  # violet
    "#0891b2",  # cyan
)

GRID = "#e5e7eb"
AXIS = "#9ca3af"
TEXT = "#374151"
BACKGROUND = "#ffffff"

# Margins leave room for axis labels and a legend.
PAD_LEFT = 64
PAD_RIGHT = 20
PAD_TOP = 40
PAD_BOTTOM = 44


def _nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round tick values between low and high.

    A linear sweep from the raw min/max produces labels like 17.3, 34.6, 51.9.
    Rounding to 1/2/5×10ⁿ gives 20, 40, 60 — which is what a person reads.
    """
    if high <= low:
        return [low]
    span = high - low
    step = span / max(count - 1, 1)
    magnitude = 10 ** _floor_log10(step)
    for multiplier in (1, 2, 2.5, 5, 10):
        candidate = multiplier * magnitude
        if candidate >= step:
            step = candidate
            break

    start = _ceil_to(low, step)
    ticks = []
    value = start
    while value <= high + step * 0.001:
        ticks.append(round(value, 10))
        value += step
    return ticks or [low]


def _floor_log10(value: float) -> int:
    import math

    if value <= 0:
        return 0
    return int(math.floor(math.log10(value)))


def _ceil_to(value: float, step: float) -> float:
    import math

    return math.ceil(value / step) * step


def _format_tick(value: float) -> str:
    """Compact axis labels: 1.2k, 3.4M, plain integers where they fit."""
    if value == int(value):
        return f"{int(value):,}"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:g}"


def line_chart(
    series: list,
    *,
    title: str = "",
    y_label: str = "",
    x_label: str = "",
    width: int = 720,
    height: int = 280,
    x_formatter=None,
) -> str:
    """Render one line chart as an SVG string.

    `series` is a list of `(name, points)` where points are `(x, y)` tuples.
    `x` values must be comparable across series (use a timestamp or an index,
    not a mix). `y` may be `None`, which draws a gap.

    Returns a complete `<svg>` element, ready to drop into an HTML page.
    """
    inner_w = width - PAD_LEFT - PAD_RIGHT
    inner_h = height - PAD_TOP - PAD_BOTTOM

    # -- bounds -------------------------------------------------------------
    xs: list[float] = []
    ys: list[float] = []
    for _name, points in series:
        for x, y in points:
            xs.append(float(x))
            if y is not None:
                ys.append(float(y))

    if not xs:
        return _empty_svg(title, width, height)

    x_low, x_high = min(xs), max(xs)
    y_low = min(ys) if ys else 0.0
    y_high = max(ys) if ys else 1.0
    if y_high <= y_low:
        y_high = y_low + 1.0
    # Headroom so a line sitting at the top is not clipped.
    y_high += (y_high - y_low) * 0.08
    # When every value is the same, a 1-unit axis puts the line hard against
    # the top edge and the chart reads as blank. Pad a flat series by 10% of
    # its own value so the line sits in a readable band.
    if y_low == y_high or (y_high - y_low) <= 1.0:
        centre = (y_low + y_high) / 2
        span = max(abs(centre) * 0.2, 1.0)
        y_low = centre - span / 2
        y_high = centre + span / 2

    def sx(x: float) -> float:
        if x_high == x_low:
            return PAD_LEFT + inner_w / 2
        return PAD_LEFT + (x - x_low) / (x_high - x_low) * inner_w

    def sy(y: float) -> float:
        return PAD_TOP + (y_high - y) / (y_high - y_low) * inner_h

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{html.escape(title or "chart")}">',
        f'<rect width="{width}" height="{height}" fill="{BACKGROUND}"/>',
    ]

    if title:
        parts.append(
            f'<text x="{width / 2}" y="22" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="15" '
            f'font-weight="600" fill="{TEXT}">{html.escape(title)}</text>'
        )

    # -- grid + y ticks -----------------------------------------------------
    for tick in _nice_ticks(y_low, y_high):
        y = sy(tick)
        parts.append(
            f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{PAD_LEFT + inner_w}" '
            f'y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{PAD_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-family="system-ui,sans-serif" font-size="11" '
            f'fill="{AXIS}">{_format_tick(tick)}</text>'
        )

    # -- axes ---------------------------------------------------------------
    parts.append(
        f'<line x1="{PAD_LEFT}" y1="{PAD_TOP}" x2="{PAD_LEFT}" '
        f'y2="{PAD_TOP + inner_h}" stroke="{AXIS}" stroke-width="1.5"/>'
    )
    parts.append(
        f'<line x1="{PAD_LEFT}" y1="{PAD_TOP + inner_h}" '
        f'x2="{PAD_LEFT + inner_w}" y2="{PAD_TOP + inner_h}" '
        f'stroke="{AXIS}" stroke-width="1.5"/>'
    )

    # -- x ticks ------------------------------------------------------------
    x_ticks = _nice_ticks(x_low, x_high, count=6)
    for tick in x_ticks:
        x = sx(tick)
        parts.append(
            f'<line x1="{x:.1f}" y1="{PAD_TOP + inner_h}" '
            f'x2="{x:.1f}" y2="{PAD_TOP + inner_h + 5}" '
            f'stroke="{AXIS}" stroke-width="1.5"/>'
        )
        label = x_formatter(tick) if x_formatter else _format_tick(tick)
        parts.append(
            f'<text x="{x:.1f}" y="{PAD_TOP + inner_h + 18}" '
            f'text-anchor="middle" font-family="system-ui,sans-serif" '
            f'font-size="11" fill="{AXIS}">{html.escape(str(label))}</text>'
        )

    if x_label:
        parts.append(
            f'<text x="{PAD_LEFT + inner_w / 2}" y="{height - 4}" '
            f'text-anchor="middle" font-family="system-ui,sans-serif" '
            f'font-size="11" fill="{AXIS}">{html.escape(x_label)}</text>'
        )
    if y_label:
        parts.append(
            f'<text x="14" y="{PAD_TOP + inner_h / 2}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="11" '
            f'fill="{AXIS}" '
            f'transform="rotate(-90 14 {PAD_TOP + inner_h / 2})">'
            f"{html.escape(y_label)}</text>"
        )

    # -- series -------------------------------------------------------------
    legend_y = PAD_TOP + 12
    for index, (name, points) in enumerate(series):
        colour = PALETTE[index % len(PALETTE)]
        segments: list[str] = []
        for x, y in points:
            if y is None:
                if segments:
                    segments.append(" ")
                continue
            segments.append(f"{sx(x):.1f},{sy(y):.1f}")
        if segments:
            parts.append(
                f'<polyline points="{" ".join(segments)}" fill="none" '
                f'stroke="{colour}" stroke-width="2" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )
        for x, y in points:
            if y is None:
                continue
            parts.append(
                f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="2.6" '
                f'fill="{colour}"><title>{html.escape(name)}: '
                f"{_format_tick(y)}</title></circle>"
            )

        # Legend, in the top-right corner.
        lx = PAD_LEFT + inner_w - 8
        ly = legend_y + index * 18
        parts.append(
            f'<line x1="{lx - 26}" y1="{ly}" x2="{lx - 6}" y2="{ly}" '
            f'stroke="{colour}" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{lx}" y="{ly + 4}" text-anchor="end" '
            f'font-family="system-ui,sans-serif" font-size="11" '
            f'fill="{TEXT}">{html.escape(name)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _empty_svg(title: str, width: int, height: int) -> str:
    """A chart-shaped placeholder for when there is no data to draw."""
    label = title or "No data"
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="{width}" height="{height}" fill="{BACKGROUND}"/>'
        f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" '
        f'font-family="system-ui,sans-serif" font-size="13" '
        f'fill="{AXIS}">{html.escape(label)}</text>'
        f"</svg>"
    )
