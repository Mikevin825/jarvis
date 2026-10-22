"""Business website status.

Fetches the homepage for its content and probes a handful of common paths
(`/pricing`, `/contact`, `/about`) so a broken link is caught rather than
reported as fine. Text extraction reuses `jarvis.tools.web`, so the site is
read exactly the way `fetch_web` reads any other page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from ..htmltext import extract_text, extract_title

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Paths worth probing when the homepage links to them. Probing arbitrary paths
# would flag every single-page site, so only linked paths are checked.
COMMON_PATHS = ("/pricing", "/contact", "/about", "/services", "/blog", "/work")

MAX_TEXT_CHARS = 4000


@dataclass
class PageProbe:
    """The result of asking one URL."""

    path: str
    url: str
    ok: bool
    status: int | None
    content_type: str = ""
    error: str = ""


@dataclass
class SiteInfo:
    """What could be learned about the site.

    The metrics beyond `reachable` are what make website *analytics* possible
    rather than just an uptime check: response time and page size are the two
    numbers a site owner can actually act on, and both are trendable once
    history is being kept.
    """

    url: str
    reachable: bool
    title: str
    text: str
    probes: list[PageProbe] = field(default_factory=list)
    error: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # -- measurable metrics -------------------------------------------------
    response_time_ms: int | None = None
    page_size_bytes: int | None = None
    word_count: int | None = None
    ssl_expires: str | None = None

    @property
    def broken_paths(self) -> list[PageProbe]:
        """Probes that resolved but were not a page (404, redirect-to-404…)."""
        return [p for p in self.probes if not p.ok]


def _normalise(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value.rstrip("/")


def _ssl_expiry(host: str) -> str | None:
    """The TLS certificate expiry date, or None if it can't be determined.

    An expired certificate is the most common way a site silently breaks for
    visitors, and it fails days before the owner notices — so it is worth
    recording alongside the other metrics. Returns the raw `notAfter` string
    (e.g. "Nov  6 23:59:59 2026 GMT").
    """
    import socket
    import ssl

    if not host.startswith("https://"):
        return None
    hostname = host[len("https://"):].split("/")[0]
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    return None
                return str(cert.get("notAfter"))
    except Exception:  # noqa: BLE001 - cert problems are not fatal
        return None


def fetch_site(url: str, probe: bool = True) -> SiteInfo:
    """Fetch the site's homepage and, optionally, probe common paths."""
    base = _normalise(url)
    if not base:
        return SiteInfo(url="", reachable=False, title="", text="", error="No URL was given.")

    # -- homepage ---------------------------------------------------------
    try:
        started = datetime.now(timezone.utc)
        response = httpx.get(base, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    except httpx.TimeoutException:
        return SiteInfo(
            url=base, reachable=False, title="", text="",
            error=f"{base} did not respond within 20 seconds.",
        )
    except httpx.HTTPError as exc:
        return SiteInfo(
            url=base, reachable=False, title="", text="",
            error=f"Could not reach {base}: {exc}",
        )

    if response.status_code >= 400:
        return SiteInfo(
            url=base, reachable=False, title="", text="",
            error=f"{base} returned HTTP {response.status_code}.",
        )

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return SiteInfo(
            url=base, reachable=False, title="", text="",
            error=f"{base} returned {content_type or 'unknown content'}, not a web page.",
        )

    text = extract_text(response.text)
    title = extract_title(response.text) or base

    info = SiteInfo(
        url=base,
        reachable=True,
        title=title,
        text=text,
        response_time_ms=elapsed_ms,
        page_size_bytes=len(response.content),
        word_count=len(text.split()),
        ssl_expires=_ssl_expiry(base),
    )

    # -- probes ----------------------------------------------------------
    # Only probe paths the homepage actually links to. Probing a fixed list
    # would flag every single-page site (a landing page with no /pricing is
    # not broken), so the links are read out of the HTML first.
    if probe:
        linked = _linked_paths(response.text, base)
        info.probes.append(
            PageProbe(path="/", url=base, ok=True, status=response.status_code,
                      content_type=content_type)
        )
        for path in linked:
            info.probes.append(_probe(base + path))

    return info


def _linked_paths(html: str, base: str) -> list[str]:
    """Paths the homepage links to, narrowed to the ones worth probing.

    Absolute URLs on other hosts are dropped, as are asset and mailto links.
    """
    import re
    from urllib.parse import urljoin, urlparse

    paths: list[str] = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        resolved = urlparse(urljoin(base, href))
        if resolved.netloc and resolved.netloc != urlparse(base).netloc:
            continue
        path = resolved.path.split("#")[0]
        if not path or path == "/":
            continue
        if not path.startswith("/"):
            continue
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".css", ".js")):
            continue
        if path not in paths:
            paths.append(path)

    # Keep the list short: probing is a courtesy, not a crawl.
    interesting = [p for p in paths if any(p.startswith(c) for c in COMMON_PATHS)]
    return (interesting or paths)[:8]


def _probe(url: str) -> PageProbe:
    """Ask one URL whether it is a page, without downloading the body."""
    try:
        response = httpx.get(
            url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
        )
    except httpx.TimeoutException:
        return PageProbe(path="", url=url, ok=False, status=None, error="timed out")
    except httpx.HTTPError as exc:
        return PageProbe(path="", url=url, ok=False, status=None, error=str(exc))

    ok = response.status_code < 400 and (
        "text/html" in response.headers.get("content-type", "")
    )
    return PageProbe(
        path="",
        url=url,
        ok=ok,
        status=response.status_code,
        content_type=response.headers.get("content-type", ""),
    )




def site_summary(url: str) -> str:
    """A plain-text briefing on the site, for the model to reason over."""
    info = fetch_site(url)

    if not info.reachable:
        return (
            f"Website: {info.url or url}\n"
            f"NOT REACHABLE — {info.error}\n"
            "The site is down or the address is wrong."
        )

    lines = [f"Website: {info.url}", f"Title: {info.title}", ""]

    if info.broken_paths:
        lines.append("Broken pages:")
        for broken in info.broken_paths:
            status = broken.status or "no response"
            lines.append(f"- {broken.url} (HTTP {status})")
        lines.append("")

    lines.append("Page content:")
    body = " ".join(info.text.split())
    lines.append(body[:MAX_TEXT_CHARS])
    if len(body) > MAX_TEXT_CHARS:
        lines.append(f"…(truncated; {len(body):,} characters in total)")

    return "\n".join(lines)
