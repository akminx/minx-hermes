"""Tests for MCPToolDispatcher and MCPCoreClient.

Patches the module-level `_call_tool_async` coroutine so we can verify
routing, request shape, and error envelope handling without spinning up
real MCP servers.
"""

from __future__ import annotations

from typing import Any

import pytest

from hermes_loop import mcp_clients
from hermes_loop.mcp_clients import (
    MCPCoreClient,
    MCPEndpoints,
    MCPToolDispatcher,
    _TOOL_ROUTING,
)


@pytest.fixture
def stub_calls(monkeypatch: pytest.MonkeyPatch):
    """Capture every (url, name, args) tuple and return scripted responses."""

    captured: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []

    async def fake(url: str, name: str, arguments: dict[str, Any], timeout_s: float):
        captured.append(
            {"url": url, "name": name, "arguments": dict(arguments), "timeout_s": timeout_s}
        )
        if not queue:
            return {"success": True, "data": {}}
        return queue.pop(0)

    monkeypatch.setattr(mcp_clients, "_call_tool_async", fake)
    return {"captured": captured, "queue": queue}


def test_dispatcher_routes_to_correct_server(stub_calls) -> None:
    dispatcher = MCPToolDispatcher()
    dispatcher("memory_search", {"query": "x"})
    dispatcher("finance_query", {"message": "dining last month"})
    dispatcher("pantry_list", {})
    dispatcher("training_session_list", {})

    urls = [c["url"] for c in stub_calls["captured"]]
    assert urls == [
        "http://127.0.0.1:8001/mcp",
        "http://127.0.0.1:8000/mcp",
        "http://127.0.0.1:8002/mcp",
        "http://127.0.0.1:8003/mcp",
    ]


def test_dispatcher_refuses_unknown_tools(stub_calls) -> None:
    dispatcher = MCPToolDispatcher()
    with pytest.raises(RuntimeError, match="no MCP route configured"):
        dispatcher("delete_everything", {})
    assert stub_calls["captured"] == []


def test_dispatcher_passes_arguments_through(stub_calls) -> None:
    dispatcher = MCPToolDispatcher()
    dispatcher("memory_search", {"query": "abc", "limit": 5})
    call = stub_calls["captured"][0]
    assert call["name"] == "memory_search"
    assert call["arguments"] == {"query": "abc", "limit": 5}


def test_routing_covers_default_allowlist() -> None:
    from hermes_loop.runtime import DEFAULT_TOOL_ALLOWLIST

    missing = DEFAULT_TOOL_ALLOWLIST - _TOOL_ROUTING.keys()
    assert missing == set(), f"missing route for: {sorted(missing)}"


def test_routing_uses_current_minx_tool_names() -> None:
    stale_names = {
        "list_goals",
        "goal_progress_summary",
        "list_accounts",
        "list_categories",
        "list_merchants",
    }

    assert stale_names.isdisjoint(_TOOL_ROUTING)
    assert _TOOL_ROUTING["goal_list"] == "core"
    assert _TOOL_ROUTING["goal_get"] == "core"
    assert _TOOL_ROUTING["get_goal_trajectory"] == "core"
    assert _TOOL_ROUTING["safe_finance_accounts"] == "finance"


def test_core_client_start_investigation_returns_id(stub_calls) -> None:
    stub_calls["queue"].append(
        {
            "success": True,
            "data": {"investigation_id": 7, "response_template": "investigation.started"},
        }
    )
    client = MCPCoreClient()
    inv_id = client.start_investigation(
        kind="investigate",
        question="why",
        context_json={"smoke": True},
        harness="hermes",
    )
    assert inv_id == 7
    call = stub_calls["captured"][0]
    assert call["name"] == "start_investigation"
    assert call["arguments"] == {
        "kind": "investigate",
        "question": "why",
        "context_json": {"smoke": True},
        "harness": "hermes",
    }
    assert call["url"] == "http://127.0.0.1:8001/mcp"


def test_core_client_propagates_error_envelope(stub_calls) -> None:
    stub_calls["queue"].append(
        {"success": False, "error": {"code": "INVALID_INPUT", "message": "bad kind"}}
    )
    client = MCPCoreClient()
    with pytest.raises(RuntimeError, match="bad kind"):
        client.start_investigation(
            kind="onboard_entity",  # would get rejected by Core
            question="x",
            context_json={},
            harness="hermes",
        )


def test_core_client_complete_investigation_uses_optional_fields(stub_calls) -> None:
    stub_calls["queue"].append({"success": True, "data": {}})
    client = MCPCoreClient()
    client.complete_investigation(
        investigation_id=1,
        status="succeeded",
        answer_md="done",
        citation_refs=[{"type": "memory", "id": 1}],
        tool_call_count=2,
        token_input=100,
        token_output=200,
        cost_usd=0.001,
    )
    args = stub_calls["captured"][0]["arguments"]
    assert args["token_input"] == 100
    assert args["token_output"] == 200
    assert args["cost_usd"] == 0.001
    assert args["status"] == "succeeded"


def test_core_client_complete_investigation_omits_unset_fields(stub_calls) -> None:
    stub_calls["queue"].append({"success": True, "data": {}})
    client = MCPCoreClient()
    client.complete_investigation(
        investigation_id=1,
        status="succeeded",
        answer_md="done",
        citation_refs=[],
        tool_call_count=0,
    )
    args = stub_calls["captured"][0]["arguments"]
    assert "token_input" not in args
    assert "token_output" not in args
    assert "cost_usd" not in args
    assert "error_message" not in args


def test_endpoints_can_be_overridden(stub_calls) -> None:
    custom = MCPEndpoints(
        core="http://core.test/mcp",
        finance="http://fin.test/mcp",
        meals="http://meals.test/mcp",
        training="http://train.test/mcp",
        timeout_s=15.0,
    )
    dispatcher = MCPToolDispatcher(endpoints=custom)
    dispatcher("memory_search", {})
    assert stub_calls["captured"][0]["url"] == "http://core.test/mcp"
    assert stub_calls["captured"][0]["timeout_s"] == 15.0
