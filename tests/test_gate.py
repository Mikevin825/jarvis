"""The confirmation gate must fail closed, always.

These are the most important tests in the suite. Every one of them protects a
way the assistant could act without permission if the code regressed.
"""

from __future__ import annotations

import pytest

from jarvis.gate import (
    AutoApproveGate,
    CliGate,
    ConfirmationRequest,
    Decision,
    DenyAllGate,
    NoHumanGate,
)


def req(tool="send_message", args=None):
    return ConfirmationRequest(
        tool_name=tool,
        args=args or {"to": "mum", "body": "hi"},
        effect="sends a message to another person",
        detail=f"{tool}(to='mum', body='hi')",
    )


# -- the gates themselves ---------------------------------------------------


def test_default_gate_denies():
    """An unconfigured gate must never mean 'allowed'."""
    assert DenyAllGate().confirm(req()).approved is False


def test_no_human_gate_denies_and_leaves_a_note():
    deferred = []
    gate = NoHumanGate(on_defer=deferred.append)
    decision = gate.confirm(req())
    assert decision.approved is False
    assert len(deferred) == 1, "the user must be told something was deferred"


def test_cli_gate_non_interactive_denies_even_with_yes_available():
    """A piped 'y' on stdin must never stand in for a human."""
    gate = CliGate(input_fn=lambda prompt: "y", interactive=False)
    assert gate.confirm(req()).approved is False


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES"])
def test_cli_gate_accepts_affirmatives(answer):
    gate = CliGate(input_fn=lambda prompt: answer, interactive=True)
    assert gate.confirm(req()).approved is True


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe", "sure", "yesss"])
def test_cli_gate_treats_everything_else_as_no(answer):
    gate = CliGate(input_fn=lambda prompt: answer, interactive=True)
    assert gate.confirm(req()).approved is False


def test_cli_gate_cancelled_prompt_denies():
    def explode(prompt):
        raise KeyboardInterrupt

    gate = CliGate(input_fn=explode, interactive=True)
    assert gate.confirm(req()).approved is False


# -- the registry wiring ----------------------------------------------------


def test_consequential_tool_denied_by_default_registry(registry):
    result = registry.run("send_message", {"to": "mum", "body": "hi"})
    assert result.ok is False
    assert result.gated is True


def test_denied_action_does_not_run(registry, state_dir):
    """The real assertion: nothing happened."""
    registry.gate = DenyAllGate()
    registry.run("send_message", {"to": "mum", "body": "hi"})
    assert not (state_dir / "messages.json").exists()


def test_approved_action_does_run(registry, state_dir):
    import json

    registry.gate = AutoApproveGate()
    result = registry.run("send_message", {"to": "mum", "body": "hi"})
    assert result.ok is True
    store = json.loads((state_dir / "messages.json").read_text())
    assert len(store["outbox"]) == 1


def test_confirmation_is_per_action_not_generalised(registry):
    """Approving once must not pre-authorise the next action."""
    calls = {"n": 0}

    class CountingGate:
        def confirm(self, request):
            calls["n"] += 1
            return Decision(True, "yes")

    registry.gate = CountingGate()
    registry.run("send_message", {"to": "a", "body": "one"})
    registry.run("send_message", {"to": "b", "body": "two"})
    assert calls["n"] == 2, "each action must be confirmed separately"


def test_read_only_tools_never_consult_the_gate(registry):
    calls = {"n": 0}

    class SpyGate:
        def confirm(self, request):
            calls["n"] += 1
            return Decision(False, "should not be asked")

    registry.gate = SpyGate()
    registry.run("get_current_time", {})
    registry.run("list_notes", {})
    registry.run("list_facts", {})
    assert calls["n"] == 0, "read-only actions must flow freely"


def test_a_broken_gate_fails_closed(registry, state_dir):
    class ExplodingGate:
        def confirm(self, request):
            raise RuntimeError("gate is broken")

    registry.gate = ExplodingGate()
    result = registry.run("send_message", {"to": "mum", "body": "hi"})
    assert result.ok is False
    assert not (state_dir / "messages.json").exists()


def test_gate_error_is_audited(registry):
    logged = []
    registry.on_audit = lambda src, status, detail: logged.append(status)

    class ExplodingGate:
        def confirm(self, request):
            raise RuntimeError("nope")

    registry.gate = ExplodingGate()
    registry.run("send_message", {"to": "mum", "body": "hi"})
    assert "gate-error" in logged


def test_config_can_gate_an_otherwise_safe_tool(state_dir, memory_store):
    """Tightening the posture without a code change must work."""
    from jarvis.gate import DenyAllGate
    from jarvis.tools import build_registry

    reg = build_registry(memory_store, extra_gated=("get_current_time",))
    reg.gate = DenyAllGate()
    assert "get_current_time" in reg.consequential_names()
    assert reg.run("get_current_time", {}).gated is True


def test_config_can_ungate_a_consequential_tool(state_dir, memory_store):
    """Loosening must be possible, and deliberate."""
    from jarvis.tools import build_registry

    reg = build_registry(memory_store, ungated=("send_message",))
    assert "send_message" not in reg.consequential_names()


def test_every_gated_tool_states_its_effect(registry):
    """A gate prompt with no plain-language effect is not a real warning."""
    for name in registry.consequential_names():
        tool = registry.get(name)
        assert tool.confirm_prompt, f"{name} is gated but explains nothing"


def test_gated_result_tells_the_model_not_to_retry(registry):
    registry.gate = DenyAllGate()
    result = registry.run("delete_note", {"title": "x"})
    assert "not run" in result.content.lower()
    assert "do not retry" in result.content.lower()
