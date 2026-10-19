"""Regression tests for two failures seen in real use.

Both came from the Gemini streaming path and neither was covered:

1. `UnicodeEncodeError: surrogates not allowed`. Gemini splits an emoji across
   SSE frames, leaving one frame with a lone surrogate escape. It accumulates
   in the conversation history and kills the *next* request — so the turn
   that caused the crash looked fine, and the failure appeared a turn later.

2. Board reasoning cut mid-sentence. Every seat call was capped at the brain's
   2048-token budget, which is far too small for the six-field structure a seat
   is asked to produce.
"""

from __future__ import annotations

import json

from jarvis.board.chair import run_chair
from jarvis.board.dossier import DoctrineEntry, Dossier
from jarvis.board.meeting import MeetingResult, SeatOpinion, run_meeting
from jarvis.config import load_config, load_dotenv
from jarvis.providers.base import Message, TextDelta, ToolOutput, TurnEnd, sanitize_text


class RecordingProvider:
    """Captures (system, messages, max_tokens) for every call it receives."""

    supports_tools = True

    def __init__(self, response: str = ""):
        self.response = response
        self.calls: list[tuple[str, list[Message], int | None]] = []

    def stream(self, system, messages, tools=None, max_tokens=None):
        self.calls.append((system, messages, max_tokens))
        yield TextDelta(text=self.response)
        yield TurnEnd(text=self.response, calls=[], usage={})


def _dossier() -> Dossier:
    return Dossier(
        id="t1",
        name="Test Seat",
        seat_title="Testing",
        domains=["testing"],
        doctrine=[
            DoctrineEntry(id="d1", text="A fact.", source="src", verification="user")
        ],
    )


# -- surrogate repair -------------------------------------------------------


class TestSanitizeText:
    def test_lone_high_surrogate_is_repaired(self):
        fixed = sanitize_text("cut off \ud83d")
        assert "\ud83d" not in fixed
        fixed.encode("utf-8")  # the whole point: this used to raise

    def test_lone_low_surrogate_is_repaired(self):
        fixed = sanitize_text("x \ude00 y")
        assert "\ude00" not in fixed
        fixed.encode("utf-8")

    def test_valid_pair_recombines_into_real_emoji(self):
        assert sanitize_text("hi \ud83d\ude00") == "hi \U0001f600"

    def test_normal_text_is_untouched(self):
        text = "The board is in session."
        assert sanitize_text(text) == text
        assert sanitize_text("") == ""

    def test_position_is_preserved_not_collapsed(self):
        # Replacing rather than deleting keeps the text from shifting.
        assert sanitize_text("a\ud83db") == "a\ufffdb"


# -- the crash, end to end -------------------------------------------------


class TestPoisonedHistoryDoesNotCrash:
    def test_lone_surrogate_in_replayed_raw_is_repaired(self):
        """The exact history shape that broke in the terminal.

        A prior assistant turn is replayed verbatim from `message.raw`, and
        that replay is where the lone surrogate was hiding.
        """
        poisoned = Message(
            role="assistant", content="", raw=[{"text": "reasoning \ud83d"}]
        )
        parts = poisoned.raw

        # Reproduce the old failure to prove the test is meaningful. httpx
        # encodes JSON with ensure_ascii=False, so a lone surrogate goes into
        # the string literally and .encode("utf-8") is what raises.
        try:
            json.dumps(parts, ensure_ascii=False).encode("utf-8")
            raised = False
        except UnicodeEncodeError:
            raised = True
        assert raised, "test fixture is not actually poisoned"

        # Now the repaired path.
        from jarvis.providers.gemini import _scrub_parts

        scrubbed = _scrub_parts(parts)
        json.dumps(scrubbed, ensure_ascii=False).encode("utf-8")
        assert "\ud83d" not in json.dumps(scrubbed, ensure_ascii=False)

    def test_lone_surrogate_in_tool_output_is_repaired(self):
        from jarvis.providers.gemini import GeminiProvider

        provider = GeminiProvider(
            api_key="test",
            model="gemini-3.5-flash-lite",
            max_output_tokens=2048,
            temperature=0.7,
            timeout_seconds=10,
            max_retries=1,
            base_url="https://example.invalid",
        )
        message = Message(
            role="assistant",
            content="",
            outputs=[ToolOutput(name="list_files", content="see \ud83d", ok=True)],
        )

        payload = provider._payload("system", [message], None)
        json.dumps(payload).encode("utf-8")

    def test_lone_surrogate_in_system_prompt_is_repaired(self):
        from jarvis.providers.gemini import GeminiProvider

        provider = GeminiProvider(
            api_key="test",
            model="gemini-3.5-flash-lite",
            max_output_tokens=2048,
            temperature=0.7,
            timeout_seconds=10,
            max_retries=1,
            base_url="https://example.invalid",
        )

        payload = provider._payload("system with \ud83d in it", [], None)
        json.dumps(payload).encode("utf-8")


# -- board token budgets ----------------------------------------------------


class TestBoardTokenBudgets:
    def test_seat_calls_receive_the_board_budget(self):
        """The regression: `run_meeting`'s budget never reached the provider.

        Every seat was silently capped at the brain's 2048 tokens, so the
        reasoning was cut mid-sentence.
        """
        provider = RecordingProvider(
            '{"position":"Yes","reasoning":"Because","citations":["d1"],'
            '"confidence":4,"would_change_mind":"No","abstains":false}'
        )

        run_meeting(
            question="Q?",
            dossiers=[_dossier()],
            seat_ids=["t1"],
            provider=provider,
            max_output_tokens=8192,
        )

        assert provider.calls, "no seat call was made"
        assert provider.calls[0][2] == 8192

    def test_chair_call_receives_the_board_budget(self):
        opinion = SeatOpinion(
            seat_id="t1",
            seat_name="Test Seat",
            position="Yes",
            reasoning="Because",
            citations=[],
            confidence=4,
            would_change_mind="No",
            abstains=False,
            cost_usd=0.0,
            wall_clock_s=0.1,
        )
        meeting = MeetingResult(question="Q?", opinions=[opinion])
        provider = RecordingProvider("The board says yes.")

        run_chair(
            meeting=meeting,
            dossiers=[_dossier()],
            provider=provider,
            max_output_tokens=4096,
        )

        assert provider.calls, "no chair call was made"
        assert provider.calls[0][2] == 4096

    def test_provider_default_applies_when_no_override(self):
        from jarvis.providers.gemini import GeminiProvider

        provider = GeminiProvider(
            api_key="test",
            model="gemini-3.5-flash-lite",
            max_output_tokens=2048,
            temperature=0.7,
            timeout_seconds=10,
            max_retries=1,
            base_url="https://example.invalid",
        )

        default = provider._payload("s", [], None)
        assert default["generationConfig"]["maxOutputTokens"] == 2048

        override = provider._payload("s", [], None, max_tokens=8192)
        assert override["generationConfig"]["maxOutputTokens"] == 8192

    def test_board_budget_is_configurable_and_generous(self):
        load_dotenv()
        cfg = load_config()

        assert cfg.board.max_output_tokens >= 4096, (
            "the seat budget must be large enough for a full structured answer"
        )
        assert cfg.board.max_output_tokens > cfg.brain.max_output_tokens
        assert cfg.board.chair_max_output_tokens >= 2048
        assert cfg.board.max_cost_usd > 0


# -- seat response parsing --------------------------------------------------
#
# The bug the user actually saw: advisors answer in Markdown, never the JSON
# the schema requests. The old fallback took only the first line after a
# label, so `**Reasoning:**\n\nAre you trying…` yielded "" and the inbox showed
# a blank or two-character reasoning. Sections must span paragraphs.


class TestSeatResponseParsing:
    BOLD = (
        "**Position:** Stop chasing them and look in the mirror.\n"
        "\n"
        "**Reasoning:**\n"
        "First paragraph of the argument.\n"
        "\n"
        "Second paragraph, which the old parser threw away entirely.\n"
        "\n"
        "**Citations:**\n"
        "- *Linchpin* (Chapter 3) — on replaceable cogs.\n"
        "- *Purple Cow* (Chapter 1) — on fitting in.\n"
        "\n"
        "**Confidence:**\n"
        "5/5\n"
        "\n"
        "**What would change your mind:**\n"
        "Evidence of a personal reason."
    )

    HASH = (
        "### Position\n"
        "Treat it as a brand gap, not an HR issue.\n"
        "\n"
        "### Reasoning\n"
        "The communication gap is the distance between intent and experience.\n"
        "\n"
        "### Confidence\n"
        "4/5"
    )

    def test_markdown_reasoning_survives_multiple_paragraphs(self):
        from jarvis.board.meeting import _parse_seat_response

        r = _parse_seat_response(self.BOLD)
        assert r is not None

        assert "First paragraph" in r["reasoning"]
        assert "Second paragraph" in r["reasoning"], (
            "a multi-paragraph reasoning must not be cut at the first line"
        )
        assert len(r["reasoning"]) > 80

    def test_markdown_position_is_not_the_raw_heading(self):
        from jarvis.board.meeting import _parse_seat_response

        r = _parse_seat_response(self.BOLD)
        assert r is not None

        assert r["position"].startswith("Stop chasing them")
        assert "**Position:**" not in r["position"]

    def test_hash_headings_are_parsed(self):
        from jarvis.board.meeting import _parse_seat_response

        r = _parse_seat_response(self.HASH)
        assert r is not None

        assert r["position"].startswith("Treat it as a brand gap")
        assert "communication gap" in r["reasoning"]
        assert r["confidence"] == "4" or r["confidence"] == 4

    def test_citations_are_extracted_from_bullets(self):
        from jarvis.board.meeting import _parse_seat_response

        r = _parse_seat_response(self.BOLD)
        assert r is not None

        assert len(r["citations"]) == 2
        assert any("Linchpin" in c for c in r["citations"])

    def test_json_still_parses_first(self):
        from jarvis.board.meeting import _parse_seat_response

        r = _parse_seat_response(
            '{"position":"Yes","reasoning":"Because.","citations":["d1"],'
            '"confidence":4,"would_change_mind":"Nothing","abstains":false}'
        )
        assert r is not None

        assert r["position"] == "Yes"
        assert r["reasoning"] == "Because."
        assert r["confidence"] == 4

    def test_abstention_is_read(self):
        from jarvis.board.meeting import _parse_seat_response

        r = _parse_seat_response(
            "**Position:**\nPass.\n\n**Reasoning:**\nOutside my domain.\n\n"
            "**Abstains:**\nYes"
        )
        assert r is not None

        assert r["abstains"] is True
