"""Hermes investigation runtime loop.

This is the harness-side counterpart to Core's Slice 9 investigation storage.
Core owns durable lifecycle, history, and digest-only audit rows. This module
owns the things Core deliberately does not:

- programmatic enforcement of `max_tool_calls`, `max_wall_clock_s`, and a
  read-only tool allowlist
- computing canonical digests for tool args and results
- dispatching tools through a pluggable client (real MCP, fake for tests)
- choosing which tool to call next via a pluggable policy (real LLM, fake
  scripted policy for tests)
- always closing the investigation with a terminal status — no orphans

The contract intentionally separates `Policy` from `ToolDispatcher` from
`CoreClient`. Tests substitute fakes for all three; production wires real MCP
clients and an LLM-driven policy. Core's storage rules (digest-only steps, no
raw tool output in slots) are enforced before we hand anything to Core.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


# Core's investigation kinds. Mirrored here so policies can validate without
# importing Core. Keep in sync with minx_mcp/core/investigations.py:KIND_VALUES.
CORE_KIND_VALUES = frozenset({"investigate", "plan", "retro", "onboard", "other"})

# Keys Core forbids in event_slots because they would store raw tool output.
RAW_OUTPUT_KEYS = frozenset(
    {"raw_output", "tool_output", "result_json", "result_rows", "transcript", "messages"}
)


def canonical_digest(value: Any) -> str:
    """SHA-256 of canonical JSON. Matches Core's canonical_json_digest."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Budget:
    max_tool_calls: int = 12
    max_wall_clock_s: float = 120.0
    # Optional informational caps — Core stores token usage but does not enforce.
    max_token_input: int | None = None
    max_token_output: int | None = None

    def __post_init__(self) -> None:
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be >= 1")
        if self.max_wall_clock_s <= 0:
            raise ValueError("max_wall_clock_s must be positive")


# Default read-only allowlist. The runtime refuses any tool not in the active
# allowlist; the caller can override per-invocation but cannot escape the gate.
DEFAULT_TOOL_ALLOWLIST = frozenset(
    {
        # Core read tools
        "memory_search",
        "memory_hybrid_search",
        "memory_list",
        "memory_get",
        "memory_edge_list",
        "investigation_history",
        "investigation_get",
        "get_daily_snapshot",
        "goal_list",
        "goal_get",
        "get_goal_trajectory",
        # Finance read tools
        "finance_query",
        "safe_finance_summary",
        "safe_finance_accounts",
        # Meals read tools
        "pantry_list",
        "recommend_recipes",
        "nutrition_profile_get",
        # Training read tools
        "training_exercise_list",
        "training_session_list",
        "training_progress_summary",
    }
)


class CoreClient(Protocol):
    """Subset of Core MCP needed by the loop."""

    def start_investigation(
        self,
        *,
        kind: str,
        question: str,
        context_json: dict[str, Any],
        harness: str,
    ) -> int: ...

    def append_investigation_step(
        self, *, investigation_id: int, step_json: dict[str, Any]
    ) -> None: ...

    def complete_investigation(
        self,
        *,
        investigation_id: int,
        status: str,
        answer_md: str | None,
        citation_refs: list[dict[str, Any]],
        tool_call_count: int,
        token_input: int | None = None,
        token_output: int | None = None,
        cost_usd: float | None = None,
        error_message: str | None = None,
    ) -> None: ...


class ToolDispatcher(Protocol):
    """Calls a domain MCP tool. Returns the raw structured result.

    The loop never stores this result in Core; it only digests it. Raw output
    is the policy's input for the next decision and is dropped after the run.
    """

    def __call__(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PolicyDecision:
    """Policy's next move.

    Exactly one of `tool_call` or `final_answer` must be set.
    """

    tool_call: tuple[str, dict[str, Any]] | None = None
    final_answer: "FinalAnswer | None" = None
    needs_confirmation: str | None = None  # human prompt; the loop will stop


@dataclass(frozen=True)
class FinalAnswer:
    answer_md: str
    citation_refs: list[dict[str, Any]] = field(default_factory=list)


class Policy(Protocol):
    """Decides the next action.

    Real implementations call an LLM with the tool catalog, the question, and
    a redacted history of digested results. Tests substitute scripted
    policies that emit deterministic decisions.
    """

    def decide(
        self,
        *,
        question: str,
        kind: str,
        context: dict[str, Any],
        history: list["StepRecord"],
    ) -> PolicyDecision: ...


@dataclass(frozen=True)
class StepRecord:
    """In-memory record of a step the loop appended to Core.

    Stored locally so the policy can reason about prior calls without us
    re-reading from Core. The actual durable copy lives in Core's trajectory.
    """

    step: int
    tool: str
    args_digest: str
    result_digest: str
    summary: str
    latency_ms: int
    raw_result: dict[str, Any]


@dataclass(frozen=True)
class InvestigationResult:
    investigation_id: int
    status: str
    answer_md: str | None
    citation_refs: list[dict[str, Any]]
    tool_call_count: int
    elapsed_s: float
    error_message: str | None = None


class BudgetExhausted(Exception):
    """Raised inside the loop when a hard cap trips. Caller should not see this."""


def _validate_event_slots(slots: dict[str, Any]) -> None:
    overlap = RAW_OUTPUT_KEYS.intersection(slots.keys())
    if overlap:
        raise ValueError(
            f"event_slots contains raw-output keys forbidden by Core: {sorted(overlap)}"
        )


def run_investigation(
    *,
    kind: str,
    question: str,
    context: dict[str, Any] | None,
    policy: Policy,
    dispatcher: ToolDispatcher,
    core: CoreClient,
    budget: Budget = Budget(),
    tool_allowlist: frozenset[str] = DEFAULT_TOOL_ALLOWLIST,
    harness: str = "hermes",
    clock: Callable[[], float] = time.monotonic,
) -> InvestigationResult:
    """Run an agentic investigation under a hard budget.

    Always terminates with a Core-recorded terminal status: ``succeeded``,
    ``failed``, ``cancelled``, or ``budget_exhausted``. Never leaves an
    investigation in ``running``.
    """

    if kind not in CORE_KIND_VALUES:
        raise ValueError(
            f"kind={kind!r} not in Core's accepted set {sorted(CORE_KIND_VALUES)}"
        )

    started = clock()
    deadline = started + budget.max_wall_clock_s
    investigation_id = core.start_investigation(
        kind=kind,
        question=question,
        context_json=context or {},
        harness=harness,
    )

    history: list[StepRecord] = []
    tool_call_count = 0
    needs_confirmation: str | None = None
    final: FinalAnswer | None = None

    try:
        while True:
            if clock() >= deadline:
                raise BudgetExhausted("wall clock exceeded")
            decision = policy.decide(
                question=question,
                kind=kind,
                context=context or {},
                history=history,
            )
            if sum(
                1
                for x in (decision.tool_call, decision.final_answer, decision.needs_confirmation)
                if x is not None
            ) != 1:
                raise ValueError(
                    "Policy.decide must return exactly one of tool_call, "
                    "final_answer, or needs_confirmation"
                )

            if decision.needs_confirmation is not None:
                needs_confirmation = decision.needs_confirmation
                step_index = len(history) + 1
                event_slots = {"prompt": decision.needs_confirmation[:200]}
                _validate_event_slots(event_slots)
                core.append_investigation_step(
                    investigation_id=investigation_id,
                    step_json={
                        "step": step_index,
                        "event_template": "investigation.needs_confirmation",
                        "event_slots": event_slots,
                        "tool": "policy.needs_confirmation",
                        "args_digest": canonical_digest({}),
                        "result_digest": canonical_digest({"prompt": decision.needs_confirmation}),
                        "latency_ms": 0,
                    },
                )
                core.complete_investigation(
                    investigation_id=investigation_id,
                    status="cancelled",
                    answer_md=None,
                    citation_refs=[],
                    tool_call_count=tool_call_count,
                    error_message=f"awaiting user confirmation: {decision.needs_confirmation[:200]}",
                )
                elapsed = clock() - started
                return InvestigationResult(
                    investigation_id=investigation_id,
                    status="cancelled",
                    answer_md=None,
                    citation_refs=[],
                    tool_call_count=tool_call_count,
                    elapsed_s=elapsed,
                    error_message=f"needs_confirmation: {needs_confirmation}",
                )

            if decision.final_answer is not None:
                final = decision.final_answer
                break

            assert decision.tool_call is not None
            tool, args = decision.tool_call

            if tool not in tool_allowlist:
                raise ValueError(
                    f"tool={tool!r} not in allowlist; refusing to dispatch. "
                    f"allowlist size={len(tool_allowlist)}"
                )

            if tool_call_count >= budget.max_tool_calls:
                raise BudgetExhausted(
                    f"reached max_tool_calls={budget.max_tool_calls}"
                )
            if clock() >= deadline:
                raise BudgetExhausted("wall clock exceeded")

            call_started = clock()
            raw_result = dispatcher(tool, args)
            latency_ms = int((clock() - call_started) * 1000)
            tool_call_count += 1

            args_digest = canonical_digest(args)
            result_digest = canonical_digest(raw_result)
            row_count = _row_count(raw_result)
            summary = f"{tool} returned {row_count if row_count is not None else 'a result'}"
            event_slots: dict[str, Any] = {"summary": summary[:200]}
            if row_count is not None:
                event_slots["row_count"] = row_count
            _validate_event_slots(event_slots)

            step_index = len(history) + 1
            core.append_investigation_step(
                investigation_id=investigation_id,
                step_json={
                    "step": step_index,
                    "event_template": "investigation.step_logged",
                    "event_slots": event_slots,
                    "tool": tool,
                    "args_digest": args_digest,
                    "result_digest": result_digest,
                    "latency_ms": latency_ms,
                },
            )
            history.append(
                StepRecord(
                    step=step_index,
                    tool=tool,
                    args_digest=args_digest,
                    result_digest=result_digest,
                    summary=summary,
                    latency_ms=latency_ms,
                    raw_result=raw_result,
                )
            )
    except BudgetExhausted as exc:
        core.complete_investigation(
            investigation_id=investigation_id,
            status="budget_exhausted",
            answer_md=None,
            citation_refs=[],
            tool_call_count=tool_call_count,
            error_message=str(exc)[:500],
        )
        elapsed = clock() - started
        return InvestigationResult(
            investigation_id=investigation_id,
            status="budget_exhausted",
            answer_md=None,
            citation_refs=[],
            tool_call_count=tool_call_count,
            elapsed_s=elapsed,
            error_message=str(exc),
        )
    except Exception as exc:
        core.complete_investigation(
            investigation_id=investigation_id,
            status="failed",
            answer_md=None,
            citation_refs=[],
            tool_call_count=tool_call_count,
            error_message=f"{type(exc).__name__}: {exc}"[:500],
        )
        elapsed = clock() - started
        return InvestigationResult(
            investigation_id=investigation_id,
            status="failed",
            answer_md=None,
            citation_refs=[],
            tool_call_count=tool_call_count,
            elapsed_s=elapsed,
            error_message=f"{type(exc).__name__}: {exc}",
        )

    assert final is not None
    core.complete_investigation(
        investigation_id=investigation_id,
        status="succeeded",
        answer_md=final.answer_md,
        citation_refs=list(final.citation_refs),
        tool_call_count=tool_call_count,
    )
    elapsed = clock() - started
    return InvestigationResult(
        investigation_id=investigation_id,
        status="succeeded",
        answer_md=final.answer_md,
        citation_refs=list(final.citation_refs),
        tool_call_count=tool_call_count,
        elapsed_s=elapsed,
    )


def _row_count(result: dict[str, Any]) -> int | None:
    """Best-effort row count for the step summary. Never raises."""
    if not isinstance(result, dict):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    for key in ("rows", "memories", "investigations", "items", "results"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, list):
            return len(value)
    return None
