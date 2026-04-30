"""Deterministic replay regressions for the Hermes investigation loop.

These tests pin the model-facing contract with scripted adapter turns. They are
small by design: when a model/provider swap changes tool-calling behavior, these
fixtures should make the Minx-visible regression obvious without touching a
real model or MCP server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hermes_loop.policies import OpenAIToolCallingPolicy
from hermes_loop.runtime import Budget, canonical_digest, run_investigation


@dataclass(frozen=True)
class FakeToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class FakeTurn:
    tool_calls: list[FakeToolCall]
    content: str | None
    reasoning_details: list[Any] | None
    raw_assistant_message: dict[str, Any]


class ReplayAdapter:
    """Scripted chat adapter that records the exact policy requests."""

    def __init__(self, turns: list[FakeTurn]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def run_tool_calling_turn(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> FakeTurn:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": list(tools),
                "tool_choice": tool_choice,
            }
        )
        if not self._turns:
            raise RuntimeError("ReplayAdapter ran out of scripted turns")
        return self._turns.pop(0)


class RecordingCore:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []

    def start_investigation(self, **kwargs: Any) -> int:
        self.started.append(kwargs)
        return 4242

    def append_investigation_step(self, **kwargs: Any) -> None:
        self.steps.append(kwargs)

    def complete_investigation(self, **kwargs: Any) -> None:
        self.completed.append(kwargs)


class RecordingDispatcher:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.result = result or {"data": {"rows": [{"id": 1}]}}

    def __call__(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, dict(args)))
        return self.result


def _assistant_tool_turn(call_id: str, name: str, args: dict[str, Any]) -> FakeTurn:
    return FakeTurn(
        tool_calls=[FakeToolCall(id=call_id, name=name, arguments=args)],
        content=None,
        reasoning_details=[{"type": "reasoning.text", "text": f"call {name}"}],
        raw_assistant_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, sort_keys=True),
                    },
                }
            ],
            "reasoning_details": [{"type": "reasoning.text", "text": f"call {name}"}],
        },
    )


def _assistant_final_turn(content: str) -> FakeTurn:
    return FakeTurn(
        tool_calls=[],
        content=content,
        reasoning_details=None,
        raw_assistant_message={"role": "assistant", "content": content},
    )


def test_replay_happy_path_records_tool_dispatch_and_digest_only_steps() -> None:
    adapter = ReplayAdapter(
        [
            _assistant_tool_turn("call-1", "memory_search", {"query": "budget patterns"}),
            _assistant_final_turn("Found a stable answer."),
        ]
    )
    policy = OpenAIToolCallingPolicy(adapter=adapter)
    policy.configure_budget(max_tool_calls=4)
    core = RecordingCore()
    dispatcher_result = {
        "data": {
            "rows": [
                {"id": 7, "text": "Relevant memory"},
                {"id": 9, "text": "Another memory"},
            ]
        }
    }
    dispatcher = RecordingDispatcher(dispatcher_result)

    result = run_investigation(
        kind="investigate",
        question="What changed in my budget behavior?",
        context={"source": "eval-replay"},
        policy=policy,
        dispatcher=dispatcher,
        core=core,
        budget=Budget(max_tool_calls=4, max_wall_clock_s=30.0),
    )

    assert result.status == "succeeded"
    assert result.answer_md == "Found a stable answer."
    assert dispatcher.calls == [("memory_search", {"query": "budget patterns"})]
    assert core.started == [
        {
            "kind": "investigate",
            "question": "What changed in my budget behavior?",
            "context_json": {"source": "eval-replay"},
            "harness": "hermes",
        }
    ]
    assert core.completed == [
        {
            "investigation_id": 4242,
            "status": "succeeded",
            "answer_md": "Found a stable answer.",
            "citation_refs": [],
            "tool_call_count": 1,
        }
    ]

    first_request = adapter.calls[0]
    assert first_request["tool_choice"] == "auto"
    assert any(
        schema["function"]["name"] == "memory_search"
        for schema in first_request["tools"]
    )
    assert all(
        schema["function"]["name"] != "memory_create"
        for schema in first_request["tools"]
    )
    assert "Never propose mutating actions" in first_request["messages"][0]["content"]
    assert json.loads(first_request["messages"][1]["content"]) == {
        "question": "What changed in my budget behavior?",
        "kind": "investigate",
        "context": {"source": "eval-replay"},
    }

    second_request = adapter.calls[1]
    assert any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == "call-1"
        and "Relevant memory" in message.get("content", "")
        for message in second_request["messages"]
    )

    assert len(core.steps) == 1
    step = core.steps[0]["step_json"]
    assert step["event_template"] == "investigation.step_logged"
    assert step["event_slots"] == {
        "summary": "memory_search returned 2",
        "row_count": 2,
    }
    assert step["tool"] == "memory_search"
    assert step["args_digest"] == canonical_digest({"query": "budget patterns"})
    assert step["result_digest"] == canonical_digest(dispatcher_result)
    assert "raw_output" not in step["event_slots"]


def test_replay_budget_exhaustion_blocks_extra_model_tool_calls_cleanly() -> None:
    adapter = ReplayAdapter(
        [
            _assistant_tool_turn("call-1", "memory_search", {"query": "one"}),
            _assistant_tool_turn("call-2", "finance_query", {"message": "two"}),
            _assistant_tool_turn("call-3", "memory_search", {"query": "three"}),
        ]
    )
    policy = OpenAIToolCallingPolicy(adapter=adapter)
    policy.configure_budget(max_tool_calls=2)
    core = RecordingCore()
    dispatcher = RecordingDispatcher()

    result = run_investigation(
        kind="investigate",
        question="Keep searching forever",
        context={},
        policy=policy,
        dispatcher=dispatcher,
        core=core,
        budget=Budget(max_tool_calls=2, max_wall_clock_s=30.0),
    )

    assert result.status == "budget_exhausted"
    assert result.tool_call_count == 2
    assert "max_tool_calls=2" in (result.error_message or "")
    assert dispatcher.calls == [
        ("memory_search", {"query": "one"}),
        ("finance_query", {"message": "two"}),
    ]
    assert len(core.steps) == 2
    assert core.completed == [
        {
            "investigation_id": 4242,
            "status": "budget_exhausted",
            "answer_md": None,
            "citation_refs": [],
            "tool_call_count": 2,
            "error_message": "reached max_tool_calls=2",
        }
    ]
    assert adapter.calls[1]["tools"] == []
    assert adapter.calls[1]["tool_choice"] == "none"
    assert adapter.calls[2]["tools"] == []
    assert adapter.calls[2]["tool_choice"] == "none"


def test_replay_mutating_tool_request_is_not_dispatched() -> None:
    adapter = ReplayAdapter(
        [
            _assistant_tool_turn(
                "call-1",
                "memory_create",
                {"text": "Write this without asking"},
            )
        ]
    )
    policy = OpenAIToolCallingPolicy(adapter=adapter)
    policy.configure_budget(max_tool_calls=3)
    core = RecordingCore()
    dispatcher = RecordingDispatcher()

    result = run_investigation(
        kind="investigate",
        question="Please remember this automatically",
        context={},
        policy=policy,
        dispatcher=dispatcher,
        core=core,
        budget=Budget(max_tool_calls=3, max_wall_clock_s=30.0),
    )

    assert result.status == "failed"
    assert "memory_create" in (result.error_message or "")
    assert dispatcher.calls == []
    assert core.steps == []
    assert len(core.completed) == 1
    assert core.completed[0]["status"] == "failed"
    assert core.completed[0]["tool_call_count"] == 0
    assert "memory_create" in (core.completed[0]["error_message"] or "")
