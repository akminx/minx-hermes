"""Concrete MCP-backed CoreClient and ToolDispatcher implementations.

Wires the agentic runtime loop to the real Minx MCP servers (Core,
Finance, Meals, Training). One short-lived MCP session per call keeps the
code simple and composable; the loop's wall-clock budget already caps how
often this happens. For higher-throughput callers a pooled session can
slot in behind the same Protocol with no other changes to the loop.

Routing: each tool name maps to the MCP server that owns it. The loop's
allowlist is enforced before we get here, so unknown tools should never
reach this dispatcher in production. We refuse them anyway for defense
in depth.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@dataclass(frozen=True)
class MCPEndpoints:
    core: str = "http://127.0.0.1:8001/mcp"
    finance: str = "http://127.0.0.1:8000/mcp"
    meals: str = "http://127.0.0.1:8002/mcp"
    training: str = "http://127.0.0.1:8003/mcp"
    timeout_s: float = 30.0


# Tool -> server-name routing. Keys must mirror tool_schemas.known_tool_names()
# and runtime.DEFAULT_TOOL_ALLOWLIST. Adding a new tool means updating both.
_TOOL_ROUTING: dict[str, str] = {
    # Core
    "memory_search": "core",
    "memory_hybrid_search": "core",
    "memory_list": "core",
    "memory_get": "core",
    "memory_edge_list": "core",
    "investigation_history": "core",
    "investigation_get": "core",
    "get_daily_snapshot": "core",
    "list_goals": "core",
    "goal_progress_summary": "core",
    "start_investigation": "core",
    "append_investigation_step": "core",
    "complete_investigation": "core",
    # Finance
    "finance_query": "finance",
    "safe_finance_summary": "finance",
    "list_accounts": "finance",
    "list_categories": "finance",
    "list_merchants": "finance",
    # Meals
    "pantry_list": "meals",
    "recommend_recipes": "meals",
    "nutrition_profile_get": "meals",
    # Training
    "training_exercise_list": "training",
    "training_session_list": "training",
    "training_progress_summary": "training",
}


def _run_async(coro: Any) -> Any:
    """Drive an async coroutine from sync code regardless of outer loop state."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    holder: dict[str, Any] = {}

    def _runner() -> None:
        try:
            holder["result"] = asyncio.run(coro)
        except BaseException as exc:
            holder["exc"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "exc" in holder:
        raise holder["exc"]
    return holder["result"]


async def _call_tool_async(url: str, name: str, arguments: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    async with (
        streamablehttp_client(url, timeout=timeout_s) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(f"MCP tool {name} returned an error envelope")
        structured = getattr(result, "structuredContent", None) or getattr(
            result, "structured_content", None
        )
        if not isinstance(structured, dict):
            raise RuntimeError(f"MCP tool {name} did not return structured content")
        return structured


@dataclass
class MCPToolDispatcher:
    """ToolDispatcher that routes the runtime loop's tool calls to MCP servers.

    Refuses unknown tools (returns a structured error). The loop's allowlist
    catches this earlier; we still defend at the boundary so a stray dev
    invocation can't reach the network.
    """

    endpoints: MCPEndpoints = field(default_factory=MCPEndpoints)
    routing: dict[str, str] = field(default_factory=lambda: dict(_TOOL_ROUTING))

    def __call__(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        server_name = self.routing.get(tool)
        if server_name is None:
            raise RuntimeError(f"no MCP route configured for tool: {tool}")
        url = self._url_for(server_name)
        return _run_async(_call_tool_async(url, tool, args, self.endpoints.timeout_s))

    def _url_for(self, server_name: str) -> str:
        if server_name == "core":
            return self.endpoints.core
        if server_name == "finance":
            return self.endpoints.finance
        if server_name == "meals":
            return self.endpoints.meals
        if server_name == "training":
            return self.endpoints.training
        raise RuntimeError(f"unknown MCP server name: {server_name}")


@dataclass
class MCPCoreClient:
    """CoreClient implementation that calls the Core MCP server's investigation tools.

    Uses `start_investigation`, `append_investigation_step`, and
    `complete_investigation`. Result extraction unwraps `data.investigation_id`.
    """

    endpoints: MCPEndpoints = field(default_factory=MCPEndpoints)

    def start_investigation(
        self,
        *,
        kind: str,
        question: str,
        context_json: dict[str, Any],
        harness: str,
    ) -> int:
        result = _run_async(
            _call_tool_async(
                self.endpoints.core,
                "start_investigation",
                {
                    "kind": kind,
                    "question": question,
                    "context_json": context_json,
                    "harness": harness,
                },
                self.endpoints.timeout_s,
            )
        )
        if result.get("success") is False:
            raise RuntimeError(self._error(result, "start_investigation"))
        data = result.get("data") or {}
        if "investigation_id" in data:
            return int(data["investigation_id"])
        investigation = data.get("investigation")
        if isinstance(investigation, dict) and "id" in investigation:
            return int(investigation["id"])
        raise RuntimeError("start_investigation did not return an investigation id")

    def append_investigation_step(
        self, *, investigation_id: int, step_json: dict[str, Any]
    ) -> None:
        result = _run_async(
            _call_tool_async(
                self.endpoints.core,
                "append_investigation_step",
                {"investigation_id": investigation_id, "step_json": step_json},
                self.endpoints.timeout_s,
            )
        )
        if result.get("success") is False:
            raise RuntimeError(self._error(result, "append_investigation_step"))

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
        args: dict[str, Any] = {
            "investigation_id": investigation_id,
            "status": status,
            "answer_md": answer_md or "",
            "citation_refs": citation_refs,
            "tool_call_count": tool_call_count,
        }
        if token_input is not None:
            args["token_input"] = token_input
        if token_output is not None:
            args["token_output"] = token_output
        if cost_usd is not None:
            args["cost_usd"] = cost_usd
        if error_message is not None:
            args["error_message"] = error_message
        result = _run_async(
            _call_tool_async(
                self.endpoints.core,
                "complete_investigation",
                args,
                self.endpoints.timeout_s,
            )
        )
        if result.get("success") is False:
            raise RuntimeError(self._error(result, "complete_investigation"))

    @staticmethod
    def _error(result: dict[str, Any], tool: str) -> str:
        err = result.get("error") or {}
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str) and msg:
                return f"{tool}: {msg}"
        return f"{tool}: failed (no message)"
