"""Presence tools — let JARVIS read the business's website and YouTube channel.

These wrap `jarvis.presence`, so the report the model sees is the same report
the CLI prints. The URLs come from config (`presence:`), which means JARVIS
knows what to check without being told each time — but either tool accepts an
explicit URL, so a one-off look at some other site still works.
"""

from __future__ import annotations

from ..tools.base import Tool, ToolError
from ..config import load_config, load_dotenv
from . import (
    YouTubeError,
    channel_summary,
    generate_status_report,
    site_summary,
)


def _settings() -> dict:
    """Read the configured presence targets, falling back to empty.

    Read per call so editing config.yaml takes effect without a restart.
    """
    try:
        load_dotenv()
        cfg = load_config()
        return {
            "website_url": cfg.presence.website_url,
            "youtube_channel": cfg.presence.youtube_channel,
        }
    except Exception:  # noqa: BLE001 - a config problem must not kill the tool
        return {"website_url": "", "youtube_channel": ""}


def check_website(url: str = "") -> str:
    """Fetch the business website and report what is on it and whether it works."""
    target = (url or "").strip() or _settings()["website_url"]
    if not target:
        raise ToolError(
            "No website is configured. Add `presence.website_url` to config.yaml, "
            "or give me a URL to check."
        )
    return site_summary(target)


def check_youtube_channel(channel: str = "") -> str:
    """Read a YouTube channel's recent uploads and cadence from its RSS feed."""
    target = (channel or "").strip() or _settings()["youtube_channel"]
    if not target:
        raise ToolError(
            "No YouTube channel is configured. Add `presence.youtube_channel` "
            "to config.yaml, or give me a channel to check."
        )
    try:
        return channel_summary(target)
    except YouTubeError as exc:
        raise ToolError(str(exc)) from exc


def business_status_report() -> str:
    """A full status report across the configured website and YouTube channel."""
    settings = _settings()
    if not settings["website_url"] and not settings["youtube_channel"]:
        raise ToolError(
            "Nothing is configured to report on. Add `presence.website_url` "
            "and/or `presence.youtube_channel` to config.yaml."
        )
    return generate_status_report(
        website_url=settings["website_url"],
        channel=settings["youtube_channel"],
    )


def build() -> list[Tool]:
    return [
        Tool(
            name="check_website",
            description=(
                "Use this to read the business website: what it offers, how it "
                "presents itself, and whether it is up. Also probes common "
                "pages like /pricing and /contact for broken links. Call it "
                "when the user asks about their site, their online presence, "
                "or whether their website is working."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "url": {
                        "type": "STRING",
                        "description": (
                            "Optional. A specific URL to check instead of the "
                            "configured business website."
                        ),
                    }
                },
            },
            func=check_website,
        ),
        Tool(
            name="check_youtube_channel",
            description=(
                "Use this to read a YouTube channel: its recent uploads, how "
                "often it posts, and how those videos are performing. Call it "
                "when the user asks about their channel, their uploads, or "
                "their content cadence."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "channel": {
                        "type": "STRING",
                        "description": (
                            "Optional. A channel (@handle or URL) to check "
                            "instead of the configured one."
                        ),
                    }
                },
            },
            func=check_youtube_channel,
        ),
        Tool(
            name="business_status_report",
            description=(
                "Use this for a full status report across the business's online "
                "presence — the website and the YouTube channel together, with "
                "anything wrong called out first. Call it when the user asks "
                "for a status check, a health check, or 'how is the business "
                "looking online'."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {},
                "required": [],
            },
            func=business_status_report,
        ),
    ]
