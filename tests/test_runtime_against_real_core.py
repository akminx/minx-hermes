"""End-to-end smoke: drive the runtime loop against a real Core SQLite.

Exercises the cross-repo contract without spinning up an MCP transport. We
import Core directly, wrap its functions in a minimal CoreClient adapter,
and assert Core records what the loop says it did.

Skipped if minx_mcp isn't importable (e.g. running this repo in isolation).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

# Make an optional local minx checkout importable for in-tree smoke runs.
_MINX_MCP_CANDIDATE = Path.cwd().parent / "minx"
if _MINX_MCP_CANDIDATE.exists() and str(_MINX_MCP_CANDIDATE) not in sys.path:
    sys.path.insert(0, str(_MINX_MCP_CANDIDATE))

if importlib.util.find_spec("minx_mcp") is None:
    pytest.skip("minx_mcp not importable in this environment", allow_module_level=True)

from minx_mcp.core import investigations as core_inv  # noqa: E402
from minx_mcp.db import get_connection  # noqa: E402

from hermes_loop.runtime import (  # noqa: E402
    Budget,
    FinalAnswer,
    PolicyDecision,
    run_investigation,
)


class RealCoreAdapter:
    """Wraps Core's investigation helpers as a CoreClient."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _conn(self):
        return get_connection(self.db_path)

    def start_investigation(
        self, *, kind: str, question: str, context_json: dict[str, Any], harness: str
    ) -> int:
        with self._conn() as conn:
            result = core_inv.start_investigation(
                conn,
                kind=kind,
                question=question,
                context_json=context_json,
                harness=harness,
            )
        return int(result["investigation_id"])

    def append_investigation_step(
        self, *, investigation_id: int, step_json: dict[str, Any]
    ) -> None:
        with self._conn() as conn:
            core_inv.append_investigation_step(
                conn,
                investigation_id=investigation_id,
                step_json=step_json,
            )

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
    ) -> None:
        with self._conn() as conn:
            core_inv.complete_investigation(
                conn,
                investigation_id=investigation_id,
                status=status,
                answer_md=answer_md,
                citation_refs=citation_refs,
                tool_call_count=tool_call_count,
                token_input=token_input,
                token_output=token_output,
                cost_usd=cost_usd,
                error_message=error_message,
            )


class ScriptedPolicy:
    def __init__(self, decisions: list[PolicyDecision]) -> None:
        self._decisions = list(decisions)

    def decide(self, **_: Any) -> PolicyDecision:
        return self._decisions.pop(0)


def fake_dispatcher(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"rows": [{"tool": tool}]}}


def test_loop_drives_real_core_to_succeeded(tmp_path: Path) -> None:
    db_path = tmp_path / "minx.db"
    # Triggers schema bootstrap on first connect.
    get_connection(db_path).close()

    core = RealCoreAdapter(db_path)
    policy = ScriptedPolicy(
        [
            PolicyDecision(tool_call=("memory_search", {"query": "x"})),
            PolicyDecision(
                final_answer=FinalAnswer(
                    answer_md="all clear",
                    citation_refs=[
                        {
                            "type": "tool_result_digest",
                            "tool": "memory_search",
                            "digest": "a" * 64,
                        }
                    ],
                )
            ),
        ]
    )
    result = run_investigation(
        kind="investigate",
        question="cross-repo smoke",
        context={"smoke": True},
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
        budget=Budget(max_tool_calls=5, max_wall_clock_s=30.0),
    )
    assert result.status == "succeeded"
    assert result.tool_call_count == 1

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT status, kind, answer_md, tool_call_count FROM investigations WHERE id = ?",
            (result.investigation_id,),
        ).fetchone()
    assert row is not None
    assert row["status"] == "succeeded"
    assert row["kind"] == "investigate"
    assert row["answer_md"] == "all clear"
    assert int(row["tool_call_count"]) == 1


def test_loop_drives_real_core_to_budget_exhausted(tmp_path: Path) -> None:
    db_path = tmp_path / "minx.db"
    # Triggers schema bootstrap on first connect.
    get_connection(db_path).close()

    core = RealCoreAdapter(db_path)
    policy = ScriptedPolicy(
        [PolicyDecision(tool_call=("memory_search", {"i": i})) for i in range(10)]
    )
    result = run_investigation(
        kind="investigate",
        question="overrun",
        context={},
        policy=policy,
        dispatcher=fake_dispatcher,
        core=core,
        budget=Budget(max_tool_calls=2, max_wall_clock_s=30.0),
    )
    assert result.status == "budget_exhausted"
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT status, tool_call_count FROM investigations WHERE id = ?",
            (result.investigation_id,),
        ).fetchone()
    assert row["status"] == "budget_exhausted"
    assert int(row["tool_call_count"]) == 2
