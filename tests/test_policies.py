"""Tests for OpenAIToolCallingPolicy and tool_schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from hermes_loop.policies import OpenAIToolCallingPolicy
from hermes_loop.runtime import (
    Budget,
    FinalAnswer,
    PolicyDecision,
    StepRecord,
    run_investigation,
)
from hermes_loop.tool_schemas import all_schemas, known_tool_names, schemas_for


@dataclass
class _FakeToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class _FakeTurn:
    tool_calls: list[_FakeToolCall]
    content: str | None
    reasoning_details: list[Any] | None
    raw_assistant_message: dict[str, Any]


class FakeChatAdapter:
    """Returns scripted `run_tool_calling_turn` responses in order.

    Records every call so tests can assert on messages, tools, tool_choice.
    """

    def __init__(self, scripted: list[_FakeTurn]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    async def run_tool_calling_turn(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> _FakeTurn:
        self.calls.append(
            {
                "messages": [dict(m) for m in messages],
                "tools": list(tools),
                "tool_choice": tool_choice,
            }
        )
        if not self._scripted:
            raise RuntimeError("FakeChatAdapter ran out of scripted turns")
        return self._scripted.pop(0)


# --- tool_schemas ----------------------------------------------------------


def test_known_tool_names_covers_default_allowlist_subset() -> None:
    from hermes_loop.runtime import DEFAULT_TOOL_ALLOWLIST

    # Schemas should at least cover every entry in the runtime's default
    # allowlist, otherwise the LLM never gets to use them.
    missing = DEFAULT_TOOL_ALLOWLIST - known_tool_names()
    assert missing == set(), f"missing schemas for: {sorted(missing)}"


def test_tool_catalog_uses_current_minx_tool_names() -> None:
    from hermes_loop.runtime import DEFAULT_TOOL_ALLOWLIST

    stale_names = {
        "list_goals",
        "goal_progress_summary",
        "list_accounts",
        "list_categories",
        "list_merchants",
    }

    assert stale_names.isdisjoint(DEFAULT_TOOL_ALLOWLIST)
    assert stale_names.isdisjoint(known_tool_names())
    assert {"goal_list", "goal_get", "get_goal_trajectory", "safe_finance_accounts"} <= known_tool_names()


def test_tool_schemas_match_current_minx_arguments() -> None:
    schemas = {schema["function"]["name"]: schema["function"]["parameters"] for schema in all_schemas()}

    finance_query = schemas["finance_query"]["properties"]
    assert "message" in finance_query
    assert "natural_query" in finance_query
    assert "query" not in finance_query

    assert "harness" in schemas["investigation_history"]["properties"]
    assert "since" in schemas["investigation_history"]["properties"]
    assert "days" in schemas["investigation_history"]["properties"]
    assert "review_date" in schemas["goal_get"]["properties"]
    assert "periods" in schemas["get_goal_trajectory"]["properties"]
    assert "include_needs_shopping" in schemas["recommend_recipes"]["properties"]
    assert "start_date" in schemas["training_session_list"]["properties"]
    assert "lookback_days" in schemas["training_progress_summary"]["properties"]


def test_all_schemas_have_well_formed_function_objects() -> None:
    for schema in all_schemas():
        assert schema["type"] == "function"
        fn = schema["function"]
        assert isinstance(fn["name"], str) and fn["name"]
        assert isinstance(fn["description"], str) and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params
        assert params["additionalProperties"] is False


def test_schemas_for_filters_unknown_names_silently() -> None:
    out = schemas_for(["memory_search", "totally_made_up_tool"])
    assert [s["function"]["name"] for s in out] == ["memory_search"]


# --- OpenAIToolCallingPolicy ----------------------------------------------


def test_policy_emits_tool_call_then_final_answer() -> None:
    adapter = FakeChatAdapter(
        [
            _FakeTurn(
                tool_calls=[_FakeToolCall(id="c1", name="memory_search", arguments={"query": "x"})],
                content=None,
                reasoning_details=[{"type": "reasoning.text", "text": "look up first"}],
                raw_assistant_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "memory_search", "arguments": '{"query": "x"}'},
                        }
                    ],
                    "reasoning_details": [{"type": "reasoning.text", "text": "look up first"}],
                },
            ),
            _FakeTurn(
                tool_calls=[],
                content="Final answer.",
                reasoning_details=None,
                raw_assistant_message={"role": "assistant", "content": "Final answer."},
            ),
        ]
    )
    policy = OpenAIToolCallingPolicy(adapter=adapter)

    decision1 = policy.decide(question="why", kind="investigate", context={}, history=[])
    assert decision1.tool_call == ("memory_search", {"query": "x"})

    fake_step = StepRecord(
        step=1,
        tool="memory_search",
        args_digest="a" * 64,
        result_digest="b" * 64,
        summary="ok",
        latency_ms=12,
        raw_result={"data": {"rows": [{"id": 1}]}},
    )
    decision2 = policy.decide(
        question="why", kind="investigate", context={}, history=[fake_step]
    )
    assert decision2.final_answer == FinalAnswer(answer_md="Final answer.")

    # Second call should have included a `tool` message echoing the prior
    # tool_call_id, plus the assistant message verbatim (with reasoning_details).
    second_messages = adapter.calls[1]["messages"]
    assert any(
        m.get("role") == "tool" and m.get("tool_call_id") == "c1" for m in second_messages
    )
    assert any(
        m.get("role") == "assistant" and m.get("reasoning_details") for m in second_messages
    )


def test_policy_treats_empty_response_as_needs_confirmation() -> None:
    adapter = FakeChatAdapter(
        [
            _FakeTurn(
                tool_calls=[],
                content="   ",
                reasoning_details=None,
                raw_assistant_message={"role": "assistant", "content": "   "},
            )
        ]
    )
    policy = OpenAIToolCallingPolicy(adapter=adapter)
    decision = policy.decide(question="x", kind="investigate", context={}, history=[])
    assert decision.needs_confirmation is not None


def test_policy_drops_tools_on_last_turn_when_budget_configured() -> None:
    adapter = FakeChatAdapter(
        [
            _FakeTurn(
                tool_calls=[_FakeToolCall(id="c1", name="memory_search", arguments={})],
                content=None,
                reasoning_details=None,
                raw_assistant_message={"role": "assistant", "tool_calls": []},
            ),
            _FakeTurn(
                tool_calls=[],
                content="forced final",
                reasoning_details=None,
                raw_assistant_message={"role": "assistant", "content": "forced final"},
            ),
        ]
    )
    policy = OpenAIToolCallingPolicy(adapter=adapter, force_finalize_on_last_turn=True)
    policy.configure_budget(max_tool_calls=1)

    policy.decide(question="x", kind="investigate", context={}, history=[])
    fake_step = StepRecord(
        step=1, tool="memory_search", args_digest="a" * 64, result_digest="b" * 64,
        summary="ok", latency_ms=1, raw_result={},
    )
    policy.decide(question="x", kind="investigate", context={}, history=[fake_step])

    # On the second (final) turn the policy should send no tools and force tool_choice.
    assert adapter.calls[1]["tools"] == []
    assert adapter.calls[1]["tool_choice"] == "none"


def test_policy_drives_runtime_loop_to_succeeded() -> None:
    """Smoke test: runtime + policy + scripted adapter wire up correctly."""

    adapter = FakeChatAdapter(
        [
            _FakeTurn(
                tool_calls=[_FakeToolCall(id="c1", name="memory_search", arguments={"query": "q"})],
                content=None,
                reasoning_details=None,
                raw_assistant_message={"role": "assistant"},
            ),
            _FakeTurn(
                tool_calls=[],
                content="all done",
                reasoning_details=None,
                raw_assistant_message={"role": "assistant", "content": "all done"},
            ),
        ]
    )
    policy = OpenAIToolCallingPolicy(adapter=adapter)
    policy.configure_budget(max_tool_calls=5)

    class _FakeCore:
        def __init__(self) -> None:
            self.completed: list[dict[str, Any]] = []

        def start_investigation(self, **_: Any) -> int:
            return 1

        def append_investigation_step(self, **_: Any) -> None: ...

        def complete_investigation(self, **kwargs: Any) -> None:
            self.completed.append(kwargs)

    core = _FakeCore()
    result = run_investigation(
        kind="investigate",
        question="why",
        context={},
        policy=policy,
        dispatcher=lambda tool, args: {"data": {"rows": [{"x": 1}]}},
        core=core,
        budget=Budget(max_tool_calls=5, max_wall_clock_s=30.0),
    )
    assert result.status == "succeeded"
    assert result.answer_md == "all done"
    assert core.completed[0]["status"] == "succeeded"
