#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import date
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


DEFAULT_CORE_URL = "http://127.0.0.1:8001/mcp"
DEFAULT_FINANCE_URL = "http://127.0.0.1:8000/mcp"
DEFAULT_MEALS_URL = "http://127.0.0.1:8002/mcp"
DEFAULT_TRAINING_URL = "http://127.0.0.1:8003/mcp"


def canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def call_tool(url: str, name: str, arguments: dict[str, object]) -> dict[str, Any]:
    async with (
        httpx.AsyncClient(timeout=30.0) as http_client,
        streamable_http_client(url, http_client=http_client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(f"{name} returned MCP error")
        structured = getattr(result, "structuredContent", None)
        if structured is None:
            structured = getattr(result, "structured_content", None)
        if not isinstance(structured, dict):
            raise RuntimeError(f"{name} did not return structured content")
        if structured.get("success") is False:
            error = structured.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else None
            raise RuntimeError(message or f"{name} returned unsuccessful tool response")
        return structured


def data_payload(result: dict[str, Any], tool_name: str) -> dict[str, Any]:
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"{tool_name} response missing data object")
    return data


async def start_investigation(core_url: str, question: str, mode: str) -> int:
    result = await call_tool(
        core_url,
        "start_investigation",
        {
            "kind": "investigate",
            "question": question,
            "context_json": {"runner": "minx-investigate-once", "mode": mode},
            "harness": "hermes",
        },
    )
    data = data_payload(result, "start_investigation")
    if "investigation_id" in data:
        return int(data["investigation_id"])
    investigation = data.get("investigation")
    if isinstance(investigation, dict) and "id" in investigation:
        return int(investigation["id"])
    raise RuntimeError("start_investigation response missing investigation id")


async def append_step(
    core_url: str,
    investigation_id: int,
    *,
    step: int,
    tool: str,
    args: dict[str, object],
    result: dict[str, Any],
    latency_ms: int,
    summary: str,
    row_count: int | None = None,
) -> str:
    result_digest = canonical_digest(result)
    event_slots: dict[str, object] = {"summary": summary}
    if row_count is not None:
        event_slots["row_count"] = row_count
    await call_tool(
        core_url,
        "append_investigation_step",
        {
            "investigation_id": investigation_id,
            "step_json": {
                "step": step,
                "event_template": "investigation.step_logged",
                "event_slots": event_slots,
                "tool": tool,
                "args_digest": canonical_digest(args),
                "result_digest": result_digest,
                "latency_ms": latency_ms,
            },
        },
    )
    return result_digest


async def complete_investigation(
    core_url: str,
    investigation_id: int,
    *,
    answer_md: str,
    citation_refs: list[dict[str, object]],
    tool_call_count: int,
) -> None:
    await call_tool(
        core_url,
        "complete_investigation",
        {
            "investigation_id": investigation_id,
            "status": "succeeded",
            "answer_md": answer_md,
            "citation_refs": citation_refs,
            "tool_call_count": tool_call_count,
        },
    )


async def fail_investigation(
    core_url: str,
    investigation_id: int,
    *,
    error_message: str,
    tool_call_count: int,
) -> None:
    await call_tool(
        core_url,
        "complete_investigation",
        {
            "investigation_id": investigation_id,
            "status": "failed",
            "answer_md": "",
            "error_message": error_message[:500],
            "tool_call_count": tool_call_count,
        },
    )


def count_items(result: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
    return None


async def run_finance_summary(args: argparse.Namespace, investigation_id: int, state: dict[str, int]) -> int:
    tool_args: dict[str, object] = {}
    started = time.monotonic()
    result = await call_tool(args.finance_url, "safe_finance_summary", tool_args)
    state["tool_call_count"] = 1
    latency_ms = int((time.monotonic() - started) * 1000)
    digest = await append_step(
        args.core_url,
        investigation_id,
        step=1,
        tool="safe_finance_summary",
        args=tool_args,
        result=result,
        latency_ms=latency_ms,
        summary="safe_finance_summary returned the current aggregate finance overview",
        row_count=count_items(result, ("accounts", "categories", "summary")),
    )
    await complete_investigation(
        args.core_url,
        investigation_id,
        answer_md=(
            "Finance summary smoke completed. Hermes recorded the "
            "`safe_finance_summary` result by digest for audit."
        ),
        citation_refs=[{"type": "tool_result_digest", "tool": "safe_finance_summary", "digest": digest}],
        tool_call_count=1,
    )
    return 1


async def run_daily_snapshot(args: argparse.Namespace, investigation_id: int, state: dict[str, int]) -> int:
    review_date = args.review_date or date.today().isoformat()
    tool_args: dict[str, object] = {"review_date": review_date, "force": False}
    started = time.monotonic()
    result = await call_tool(args.core_url, "get_daily_snapshot", tool_args)
    state["tool_call_count"] = 1
    latency_ms = int((time.monotonic() - started) * 1000)
    digest = await append_step(
        args.core_url,
        investigation_id,
        step=1,
        tool="get_daily_snapshot",
        args=tool_args,
        result=result,
        latency_ms=latency_ms,
        summary=f"get_daily_snapshot returned the daily snapshot for {review_date}",
        row_count=None,
    )
    await complete_investigation(
        args.core_url,
        investigation_id,
        answer_md=(
            f"Daily snapshot smoke completed for {review_date}. Hermes recorded "
            "the `get_daily_snapshot` result by digest for audit."
        ),
        citation_refs=[{"type": "tool_result_digest", "tool": "get_daily_snapshot", "digest": digest}],
        tool_call_count=1,
    )
    return 1


async def amain(args: argparse.Namespace) -> None:
    investigation_id = await start_investigation(args.core_url, args.question, args.mode)
    state = {"tool_call_count": 0}
    try:
        if args.mode == "finance-summary":
            tool_call_count = await run_finance_summary(args, investigation_id, state)
        elif args.mode == "daily-snapshot":
            tool_call_count = await run_daily_snapshot(args, investigation_id, state)
        else:
            raise RuntimeError(f"unsupported mode: {args.mode}")
    except Exception as exc:
        await fail_investigation(
            args.core_url,
            investigation_id,
            error_message=str(exc),
            tool_call_count=state["tool_call_count"],
        )
        raise
    print(f"investigation_id={investigation_id} mode={args.mode} tool_call_count={tool_call_count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one deterministic Minx investigation smoke.")
    parser.add_argument("--question", required=True)
    parser.add_argument("--core-url", default=DEFAULT_CORE_URL)
    parser.add_argument("--finance-url", default=DEFAULT_FINANCE_URL)
    parser.add_argument("--meals-url", default=DEFAULT_MEALS_URL)
    parser.add_argument("--training-url", default=DEFAULT_TRAINING_URL)
    parser.add_argument("--mode", choices=("finance-summary", "daily-snapshot"), required=True)
    parser.add_argument("--review-date", help="YYYY-MM-DD for daily-snapshot mode")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(amain(parse_args()))
