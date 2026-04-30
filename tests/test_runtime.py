"""Tests for the Hermes investigation runtime loop.

Covers the contract Core deliberately doesn't enforce: hard budget caps,
tool allowlist, terminal-status guarantee, digest-only audit trail.
"""

from __future__ import annotations

from typing import Any

import pytest

from hermes_loop.runtime import (
    DEFAULT_TOOL_ALLOWLIST,
    Budget,
    FinalAnswer,
    PolicyDecision,
    canonical_digest,
    run_investigation,
)


class FakeCore:
    """In-memory Core stand-in. Records every call so tests can assert on it."""

    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []
        self._next_id = 100

    def start_investigation(self, **kwargs: Any) -> int:
        self.started.append(kwargs)
        inv_id = self._next_id
        self._next_id += 1
        return inv_id

    def append_investigation_step(self, **kwargs: Any) -> None:
        self.steps.append(kwargs)

    def complete_investigation(self, **kwargs: Any) -> None:
        self.completed.append(kwargs)


class ScriptedPolicy:
    """Policy that emits a fixed list of decisions in order."""

    def __init__(self, decisions: list[PolicyDecision]) -> None:
        self._decisions = list(decisions)
        self.history_lengths: list[int] = []

    def decide(self, *, question: str, kind: str, context: dict[str, Any], history: list) -> PolicyDecision:
        self.history_lengths.append(len(history))
        if not self._decisions:
            raise RuntimeError("ScriptedPolicy ran out of decisions")
        return self._decisions.pop(0)


def fake_dispatcher(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Default test dispatcher — returns a small structured result with rows."""
    return {"data": {"rows": [{"tool": tool, "args": args}]}}


def test_succeeds_after_two_tool_calls() -> None:
    core = FakeCore()
    policy = ScriptedPolicy(
        [
            PolicyDecision(tool_call=("memory_search", {"query": "x"})),
            PolicyDecision(tool_call=("finance_query", {"q": "y"})),
            PolicyDecision(
                final_answer=FinalAnswer(
                    answer_md="done",
                    citation_refs=[{"type": "memory", "id": 1}],
                )
            ),
        ]
    )
    result = run_investigation(
        kind="investigate",
        question="why",
        context=None,
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
    )
    assert result.status == "succeeded"
    assert result.tool_call_count == 2
    assert result.answer_md == "done"
    assert len(core.steps) == 2
    assert len(core.completed) == 1
    assert core.completed[0]["status"] == "succeeded"
    # Audit trail stored only digests, never raw tool output.
    for step in core.steps:
        assert "raw_output" not in step["step_json"]["event_slots"]
        assert len(step["step_json"]["args_digest"]) == 64
        assert len(step["step_json"]["result_digest"]) == 64


def test_budget_max_tool_calls_enforced() -> None:
    core = FakeCore()
    policy = ScriptedPolicy(
        [PolicyDecision(tool_call=("memory_search", {"i": i})) for i in range(20)]
    )
    result = run_investigation(
        kind="investigate",
        question="loop",
        context={},
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
        budget=Budget(max_tool_calls=3, max_wall_clock_s=120.0),
    )
    assert result.status == "budget_exhausted"
    assert result.tool_call_count == 3
    assert core.completed[0]["status"] == "budget_exhausted"
    assert "max_tool_calls" in (core.completed[0]["error_message"] or "")


def test_wall_clock_exhaustion() -> None:
    core = FakeCore()
    # Each clock read advances 50s. Deadline is 120s after start.
    counter = {"t": 0.0}

    def clock() -> float:
        t = counter["t"]
        counter["t"] = t + 50.0
        return t

    policy = ScriptedPolicy(
        [
            PolicyDecision(tool_call=("memory_search", {})),
            PolicyDecision(tool_call=("memory_search", {})),
            PolicyDecision(tool_call=("memory_search", {})),
        ]
    )
    result = run_investigation(
        kind="investigate",
        question="slow",
        context={},
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
        budget=Budget(max_tool_calls=10, max_wall_clock_s=120.0),
        clock=clock,
    )
    assert result.status == "budget_exhausted"
    assert "wall clock" in (core.completed[0]["error_message"] or "")


def test_tool_allowlist_blocks_unknown_tool() -> None:
    core = FakeCore()
    policy = ScriptedPolicy(
        [PolicyDecision(tool_call=("delete_everything", {}))]
    )
    result = run_investigation(
        kind="investigate",
        question="dangerous",
        context={},
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
    )
    assert result.status == "failed"
    assert "delete_everything" in (result.error_message or "")
    assert core.completed[0]["status"] == "failed"


def test_dispatcher_exception_results_in_failed_status() -> None:
    core = FakeCore()

    def boom(_tool: str, _args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("upstream MCP died")

    policy = ScriptedPolicy([PolicyDecision(tool_call=("memory_search", {}))])
    result = run_investigation(
        kind="investigate",
        question="brittle",
        context={},
        policy=policy,
        dispatcher=boom,
        core=core,
    )
    assert result.status == "failed"
    assert "upstream MCP died" in (result.error_message or "")


def test_invalid_kind_raises_before_starting() -> None:
    core = FakeCore()
    with pytest.raises(ValueError, match="not in Core"):
        run_investigation(
            kind="onboard_entity",  # the bug we just fixed in the skill
            question="x",
            context={},
            policy=ScriptedPolicy([]),
            dispatcher=fake_dispatcher,
            core=core,
        )
    assert core.started == []


def test_needs_confirmation_terminates_as_cancelled() -> None:
    core = FakeCore()
    policy = ScriptedPolicy(
        [
            PolicyDecision(tool_call=("memory_search", {})),
            PolicyDecision(needs_confirmation="May I write a vault note?"),
        ]
    )
    result = run_investigation(
        kind="investigate",
        question="soft halt",
        context={},
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
    )
    assert result.status == "cancelled"
    assert result.tool_call_count == 1
    assert any(
        s["step_json"]["event_template"] == "investigation.needs_confirmation"
        for s in core.steps
    )
    assert core.completed[0]["status"] == "cancelled"


def test_canonical_digest_is_order_independent() -> None:
    a = canonical_digest({"b": 2, "a": 1})
    b = canonical_digest({"a": 1, "b": 2})
    assert a == b
    assert len(a) == 64


def test_default_allowlist_excludes_writes() -> None:
    forbidden = {
        "memory_create",
        "memory_capture",
        "memory_confirm",
        "memory_reject",
        "vault_write",
        "goal_create",
        "goal_update",
        "delete_everything",
    }
    assert forbidden.isdisjoint(DEFAULT_TOOL_ALLOWLIST)


def test_history_grows_per_tool_call() -> None:
    core = FakeCore()
    policy = ScriptedPolicy(
        [
            PolicyDecision(tool_call=("memory_search", {})),
            PolicyDecision(tool_call=("memory_search", {})),
            PolicyDecision(final_answer=FinalAnswer(answer_md="ok")),
        ]
    )
    run_investigation(
        kind="investigate",
        question="q",
        context={},
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
    )
    # Decision 1 sees 0 prior steps, decision 2 sees 1, decision 3 sees 2.
    assert policy.history_lengths == [0, 1, 2]


def test_terminal_status_always_recorded_on_success() -> None:
    core = FakeCore()
    policy = ScriptedPolicy([PolicyDecision(final_answer=FinalAnswer(answer_md="hi"))])
    run_investigation(
        kind="plan",
        question="plan x",
        context={"scope": "week"},
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
    )
    assert len(core.completed) == 1
    assert core.completed[0]["status"] == "succeeded"


def test_event_slots_reject_raw_output_keys() -> None:
    """If a future change tries to stuff raw output into slots, we refuse early."""
    from hermes_loop.runtime import _validate_event_slots

    _validate_event_slots({"summary": "ok"})
    with pytest.raises(ValueError, match="raw-output"):
        _validate_event_slots({"raw_output": [1, 2, 3]})
    with pytest.raises(ValueError, match="raw-output"):
        _validate_event_slots({"transcript": "..."})
