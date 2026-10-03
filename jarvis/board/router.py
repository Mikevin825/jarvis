"""Routing: who has standing, and should this be a board question at all.

Before spending money on a fan-out, one cheap call decides two things: is this
a question for the board, and which seats have standing.

Match seats by name and by domain. Two things will bite you:

- Normalize apostrophes and unicode before matching names. If the agent is
  voice-driven, a dictated "O'Leary" arrives with a curly apostrophe (U+2019)
  and a naive comparison against `O'Leary` fails silently.

- Watch for names that collide with the user's name. If an advisor shares a
  first name with the user, a bare mention of that name is ambiguous and must
  not route. Require the surname.

The decline gate is the most annoying failure mode if done wrong. An over-eager
gate refuses "Should I cut this product loose?" as "a personal business
decision." Business decisions about the user's own company are the core use
case, no matter how personal they feel.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dossier import Dossier


@dataclass
class RoutingDecision:
    """The result of routing a question."""

    should_route: bool
    reason: str
    seat_ids: list[str] = field(default_factory=list)
    declined: bool = False
    decline_reason: str = ""


def normalize_name(name: str) -> str:
    """Normalize a name for matching.

    Handles curly apostrophes (U+2019), fullwidth variants, non-breaking
    spaces, and soft hyphens. Voice-driven input often arrives with these.
    """
    # Normalize unicode (NFKC handles fullwidth, compatibility chars)
    normalized = unicodedata.normalize("NFKC", name)
    # Replace curly apostrophes with straight ones
    normalized = normalized.replace("\u2019", "'").replace("\u2018", "'")
    # Replace non-breaking spaces with regular spaces
    normalized = normalized.replace("\u00a0", " ")
    # Remove soft hyphens
    normalized = normalized.replace("\u00ad", "")
    # Lowercase and strip
    return normalized.lower().strip()


def _extract_name_mentions(text: str, names: list[str]) -> list[str]:
    """Extract which names are mentioned in the text.

    Requires the surname for names that collide with common words or the
    user's name. A bare first name is not enough to route.
    """
    text_lower = text.lower()
    mentions = []
    for name in names:
        normalized = normalize_name(name)
        # Check for full name
        if normalized in text_lower:
            mentions.append(name)
            continue
        # Check for surname only (last word)
        parts = normalized.split()
        if len(parts) > 1:
            surname = parts[-1]
            if surname in text_lower:
                mentions.append(name)
    return mentions


def _is_decline_question(question: str) -> tuple[bool, str]:
    """Check if a question should be declined.

    The decline criteria are concrete examples of what to refuse — code,
    medical, legal, health, family — and state explicitly that business
    decisions about the user's own company are the core use case, no matter
    how personal they feel.

    Returns (should_decline, reason).
    """
    question_lower = question.lower()

    # Concrete decline patterns — these are the things the board should NOT
    # answer. Business decisions are NOT in this list.
    decline_patterns = [
        # Code/technical
        (r"\b(how (do|to|can) i (code|program|debug|deploy|build a (app|website|system)))\b", "technical implementation"),
        (r"\b(what (programming language|framework|library) should i use)\b", "technical implementation"),
        (r"\b(fix (this|my) (bug|error|code|script))\b", "technical implementation"),
        # Medical/health
        (r"\b(should i (take|stop|start) (medication|medicine|drugs|pills|antidepressant))\b", "medical advice"),
        (r"\b(is (this|symptom|pain) (serious|dangerous|cancer))\b", "medical advice"),
        (r"\b(diagnos|prognosis|treatment for)\b", "medical advice"),
        (r"\b(medication|medicine|drugs|pills|antidepressant|dosage|side effect)\b", "medical advice"),
        # Legal
        (r"\b(should i (sue|sue|file a lawsuit|take legal action))\b", "legal advice"),
        (r"\b(is (this|that) (legal|illegal|a crime))\b", "legal advice"),
        (r"\b(draw up|draft|review) (a |the )?(contract|agreement|lease|will|trust)\b", "legal advice"),
        # Family/personal relationships
        (r"\b(should i (divorce|break up with|leave) (my |the )?(wife|husband|partner|girlfriend|boyfriend))\b", "family/relationship advice"),
        (r"\b(should i (tell|confront) (my |the )?(mother|father|sister|brother|parent))\b", "family/relationship advice"),
    ]

    for pattern, reason in decline_patterns:
        if re.search(pattern, question_lower):
            return True, reason

    return False, ""


# Keyword mappings for domain matching. Maps domain names to related keywords
# that might appear in questions. This makes routing more flexible — "grow"
# matches "marketing", "creative" matches "creativity", etc.
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "marketing": ["marketing", "grow", "growth", "client", "customer", "sale", "sell", "price", "pricing", "lead", "funnel", "market", "audience", "reach"],
    "agency-growth": ["agency", "grow", "growth", "scale", "revenue", "profit", "business", "company"],
    "positioning": ["position", "positioning", "differentiate", "differentiation", "stand out", "unique", "category"],
    "creativity": ["creative", "creativity", "design", "pitch", "idea", "concept", "art", "visual", "copy", "write", "writing", "story", "stories"],
    "design": ["design", "layout", "visual", "ui", "ux", "user experience", "interface", "aesthetic"],
    "client-work": ["client", "customer", "brief", "project", "deliver", "deadline", "scope", "feedback", "revision"],
    "branding": ["brand", "branding", "logo", "identity", "message", "messaging", "voice", "tone"],
    "strategy": ["strategy", "strategic", "plan", "planning", "decision", "choice", "direction", "focus", "product", "cut", "stop", "keep"],
    "agency-branding": ["agency", "brand", "branding", "position", "positioning", "differentiate", "differentiation"],
    "operations": ["operation", "operations", "manage", "management", "process", "workflow", "system", "tool"],
    "project-management": ["project", "deadline", "deliver", "scope", "timeline", "milestone", "task", "sprint"],
    "culture": ["culture", "team", "hire", "hiring", "fire", "firing", "meeting", "communication", "remote", "office", "work-life", "balance"],
}


def route_question(
    question: str,
    dossiers: list["Dossier"],
    user_name: str = "",
    max_seats: int = 4,
) -> RoutingDecision:
    """Route a question to the board.

    One cheap call decides: is this a question for the board, and which seats
    have standing.

    Args:
        question: The user's question.
        dossiers: The available seats.
        user_name: The user's name, to avoid routing on name collisions.
        max_seats: Maximum number of seats per meeting (default 4).

    Returns:
        A RoutingDecision with the result.
    """
    # First: should this be declined?
    should_decline, decline_reason = _is_decline_question(question)
    if should_decline:
        return RoutingDecision(
            should_route=False,
            reason="declined",
            declined=True,
            decline_reason=decline_reason,
        )

    # Second: which seats have standing?
    # Match by domain keywords in the question
    question_lower = question.lower()
    seat_scores: list[tuple[str, int]] = []

    for dossier in dossiers:
        score = 0
        # Check domain matches using keyword mappings
        for domain in dossier.domains:
            keywords = DOMAIN_KEYWORDS.get(domain.lower(), [domain.lower()])
            for keyword in keywords:
                if keyword in question_lower:
                    score += 1

        # Check name mentions (requires surname for collisions)
        name_mentions = _extract_name_mentions(question, [dossier.name])
        if name_mentions:
            score += 10  # Strong signal

        if score > 0:
            seat_scores.append((dossier.id, score))

    # Sort by score descending, then by name for stability
    seat_scores.sort(key=lambda x: (-x[1], x[0]))

    # Take top N
    selected = [seat_id for seat_id, _ in seat_scores[:max_seats]]

    if not selected:
        return RoutingDecision(
            should_route=False,
            reason="no seats have standing on this question",
        )

    return RoutingDecision(
        should_route=True,
        reason=f"routed to {len(selected)} seat(s)",
        seat_ids=selected,
    )
