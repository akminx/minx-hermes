"""Policy implementations for the Hermes investigation loop.

`OpenAIToolCallingPolicy` drives an OpenAI-compatible chat endpoint
(direct OpenAI, Azure, Together, or OpenRouter) through the loop. It:

- Manages an in-memory message history across turns.
- Carries `reasoning_details` from the assistant message back into the next
  request — Nemotron-3-Super requires this for multi-turn reasoning.
- Translates the chat-side `tool_calls` response into the loop's
  `PolicyDecision`. The first tool call in the response wins; the loop is
  one-tool-per-turn by design (sequential reasoning, not fan-out).
- Appends digested tool results as `role: "tool"` messages so the model can
  see what came back without us ever sending raw outputs to durable storage
  (Core only ever sees digests; this in-memory message history is
  ephemeral and bounded by the loop's wall clock).

Pluggable adapter: any object with a coroutine
``run_tool_calling_turn(messages, tools, tool_choice) -> ToolCallingTurn``
works. minx-mcp's ``OpenAICompatibleLLM`` is the canonical implementation.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from hermes_loop.runtime import (
    DEFAULT_TOOL_ALLOWLIST,
    FinalAnswer,
    PolicyDecision,
    StepRecord,
)
from hermes_loop.tool_schemas import schemas_for


@dataclass(frozen=True)
class _ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class _ToolCallingTurn:
    tool_calls: list[_ToolCall]
    content: str | None
    reasoning_details: list[Any] | None
    raw_assistant_message: dict[str, Any]


class ChatAdapter(Protocol):
    """The subset of OpenAICompatibleLLM the policy needs."""

    async def run_tool_calling_turn(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> Any: ...


_DEFAULT_SYSTEM = (
    "You are Minx, an investigation agent. You have read-only tools to query "
    "the user's durable memory, finance ledger, meal logs, and training logs. "
    "Use tools sparingly — favor a small number of high-signal calls. "
    "Stop and emit a final answer as soon as you have enough. "
    "Never propose mutating actions; if a write would be useful, describe it "
    "in the final answer and let the human run it. "
    "When the answer is ready, respond with a concise Markdown summary "
    "(no tool calls). Cite memory ids, investigation ids, or vault paths "
    "where relevant."
)


@dataclass
class OpenAIToolCallingPolicy:
    """Policy that drives an OpenAI-compatible chat model through the loop."""

    adapter: ChatAdapter
    tool_names: frozenset[str] = DEFAULT_TOOL_ALLOWLIST
    system_prompt: str = _DEFAULT_SYSTEM
    final_turn_tool_choice: str = "none"
    # If True, omits tools on the very last allowed turn so the model is
    # forced to emit a final answer. The loop also enforces hard caps; this
    # is a soft hint to the model.
    force_finalize_on_last_turn: bool = True

    _messages: list[dict[str, Any]] = field(default_factory=list, init=False)
    _initialized: bool = field(default=False, init=False)
    _last_tool_call_id: str | None = field(default=None, init=False)
    _budget_tool_calls: int | None = field(default=None, init=False)

    def configure_budget(self, *, max_tool_calls: int) -> None:
        """Optional hint so the policy knows when to suggest finalizing."""
        self._budget_tool_calls = max_tool_calls

    def decide(
        self,
        *,
        question: str,
        kind: str,
        context: dict[str, Any],
        history: list[StepRecord],
    ) -> PolicyDecision:
        if not self._initialized:
            self._messages.append({"role": "system", "content": self.system_prompt})
            user_payload = {"question": question, "kind": kind, "context": context}
            self._messages.append(
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
            )
            self._initialized = True
        else:
            # The previous turn must have been a tool call we dispatched.
            assert self._last_tool_call_id is not None, (
                "decide() called again without a recorded tool_call_id; "
                "the loop should only re-enter after dispatching a tool"
            )
            last_step = history[-1]
            tool_message = {
                "role": "tool",
                "tool_call_id": self._last_tool_call_id,
                "name": last_step.tool,
                "content": _summarize_for_model(last_step),
            }
            self._messages.append(tool_message)
            self._last_tool_call_id = None

        # Decide whether to push the model toward finalizing.
        on_last_turn = (
            self.force_finalize_on_last_turn
            and self._budget_tool_calls is not None
            and len(history) >= max(0, self._budget_tool_calls - 1)
        )
        tools = schemas_for(self.tool_names) if not on_last_turn else []
        tool_choice: str | dict[str, Any] = self.final_turn_tool_choice if on_last_turn else "auto"

        turn = _run_async(
            self.adapter.run_tool_calling_turn(
                messages=list(self._messages),
                tools=tools,
                tool_choice=tool_choice,
            )
        )
        # Echo the assistant message back into history verbatim so any
        # reasoning_details survive into the next request.
        self._messages.append(turn.raw_assistant_message)

        if turn.tool_calls:
            call = turn.tool_calls[0]
            self._last_tool_call_id = call.id
            return PolicyDecision(tool_call=(call.name, call.arguments))

        # No tool call → final answer (content can be None if the model
        # bails; treat empty as a needs_confirmation soft halt rather than
        # silently succeeding with empty prose).
        content = (turn.content or "").strip()
        if not content:
            return PolicyDecision(
                needs_confirmation=(
                    "Model returned no tool call and no answer text; "
                    "stopping for human review."
                )
            )
        return PolicyDecision(final_answer=FinalAnswer(answer_md=content))


def _run_async(coro: Any) -> Any:
    """Run an awaitable from sync code, working both inside and outside a running loop.

    The Policy protocol is synchronous; production harnesses may or may not
    already be inside an event loop. asyncio.run() works only outside one,
    so when a loop is already active we hand the coroutine to a fresh loop
    on a worker thread.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import threading

    holder: dict[str, Any] = {}

    def _runner() -> None:
        try:
            holder["result"] = asyncio.run(coro)
        except BaseException as exc:  # propagate to caller
            holder["exc"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "exc" in holder:
        raise holder["exc"]
    return holder["result"]


def _summarize_for_model(step: StepRecord) -> str:
    """Build the `tool` message content the model sees on the next turn.

    Includes the structured tool result so the model can reason on it. The
    Core audit trail only stores digests of this content; this string lives
    only in the in-process message history for the duration of the loop.
    """

    try:
        result_text = json.dumps(step.raw_result, ensure_ascii=False)
    except (TypeError, ValueError):
        result_text = str(step.raw_result)
    # Cap length — Nemotron's 262K window is generous but we don't need to
    # dump megabytes; truncate at 32 KB and let the model ask follow-ups.
    if len(result_text) > 32_000:
        result_text = result_text[:32_000] + "...[truncated]"
    return result_text
