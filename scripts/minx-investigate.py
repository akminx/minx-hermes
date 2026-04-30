#!/usr/bin/env python3
"""Production Minx investigation runner.

Drives the Hermes investigation loop end-to-end with:

- OpenAIToolCallingPolicy on top of an OpenAI-compatible chat endpoint
  (default: OpenRouter at https://openrouter.ai/api/v1)
- MCPToolDispatcher that fans out to the running Minx Core / Finance /
  Meals / Training MCP servers
- MCPCoreClient that wraps Core's start/append/complete tools
- Hard budget caps (max_tool_calls, wall_clock_s) enforced by the loop

This is the actual command behind the live `/minx-investigate`,
`/minx-plan`, `/minx-retro`, and `/minx-onboard-entity` slash commands.
Endpoint flags or `MINX_*_URL` environment variables point at the four MCP
servers; this script stitches them together for the agentic loop.

Usage:
    OPENROUTER_API_KEY=sk-or-v1-... \
    MINX_INVESTIGATION_MODEL=google/gemini-2.5-flash \
    uv run scripts/minx-investigate.py \
      --kind investigate \
      --question "why did dining spend rise last month?" \
      --max-tool-calls 8 \
      --wall-clock-s 90

    # Plan / retro / onboard variants:
    minx-investigate --kind plan --question "weekly meal plan with 100g protein/day"
    minx-investigate --kind retro --question "what changed this week vs last?"
    minx-investigate --kind onboard --question "tell me about merchant 'Sweetgreen'"

Environment variables consumed:
    OPENROUTER_API_KEY (required for live LLM calls)
    MINX_INVESTIGATION_MODEL, MINX_INVESTIGATION_BASE_URL,
    MINX_INVESTIGATION_DATA_COLLECTION, MINX_INVESTIGATION_REASONING_EFFORT,
    MINX_INVESTIGATION_QUANTIZATIONS, MINX_INVESTIGATION_API_KEY_ENV
    MINX_CORE_URL, MINX_FINANCE_URL, MINX_MEALS_URL, MINX_TRAINING_URL
        (override default localhost MCP URLs)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Allow running against an editable minx checkout for local dev. This is
# intentionally opt-in so the script is portable across machines.
_MINX_MCP_DEV = os.environ.get("MINX_MCP_CHECKOUT")
_MINX_MCP_DEV_PATH = Path(_MINX_MCP_DEV).expanduser() if _MINX_MCP_DEV else None
if (
    _MINX_MCP_DEV_PATH
    and _MINX_MCP_DEV_PATH.exists()
    and str(_MINX_MCP_DEV_PATH) not in sys.path
):
    sys.path.insert(0, str(_MINX_MCP_DEV_PATH))

from hermes_loop import (  # noqa: E402
    Budget,
    OpenAIToolCallingPolicy,
    run_investigation,
)
from hermes_loop.mcp_clients import (  # noqa: E402
    MCPCoreClient,
    MCPEndpoints,
    MCPToolDispatcher,
)


DEFAULT_MODEL = "google/gemini-2.5-flash"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--kind",
        choices=("investigate", "plan", "retro", "onboard", "other"),
        default="investigate",
    )
    parser.add_argument("--question")
    parser.add_argument("--context-json", default="{}", help="JSON dict of extra context.")
    parser.add_argument("--max-tool-calls", type=int, default=8)
    parser.add_argument("--wall-clock-s", type=float, default=90.0)
    parser.add_argument(
        "--model",
        default=os.environ.get("MINX_INVESTIGATION_MODEL", DEFAULT_MODEL),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MINX_INVESTIGATION_BASE_URL", "https://openrouter.ai/api/v1"),
    )
    parser.add_argument(
        "--api-key-env",
        default=os.environ.get("MINX_INVESTIGATION_API_KEY_ENV", "OPENROUTER_API_KEY"),
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "off"),
        default=os.environ.get("MINX_INVESTIGATION_REASONING_EFFORT", "medium"),
    )
    parser.add_argument(
        "--data-collection",
        choices=("deny", "allow"),
        default=os.environ.get("MINX_INVESTIGATION_DATA_COLLECTION", "deny"),
        help="OpenRouter routing: deny = no-logging providers only.",
    )
    parser.add_argument(
        "--quantizations",
        default=os.environ.get("MINX_INVESTIGATION_QUANTIZATIONS", ""),
    )
    parser.add_argument(
        "--core-url",
        default=os.environ.get("MINX_CORE_URL", "http://127.0.0.1:8001/mcp"),
    )
    parser.add_argument(
        "--finance-url",
        default=os.environ.get("MINX_FINANCE_URL", "http://127.0.0.1:8000/mcp"),
    )
    parser.add_argument(
        "--meals-url",
        default=os.environ.get("MINX_MEALS_URL", "http://127.0.0.1:8002/mcp"),
    )
    parser.add_argument(
        "--training-url",
        default=os.environ.get("MINX_TRAINING_URL", "http://127.0.0.1:8003/mcp"),
    )
    parser.add_argument("--mcp-timeout-s", type=float, default=30.0)
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print resolved config and exit without making LLM/MCP calls.",
    )
    return parser.parse_args()


def build_policy(args: argparse.Namespace) -> OpenAIToolCallingPolicy:
    from minx_mcp.core.llm_openai import OpenAICompatibleLLM

    quantizations = (
        [q.strip() for q in args.quantizations.split(",") if q.strip()]
        if args.quantizations
        else None
    )
    provider_preferences: dict[str, object] = {
        "data_collection": args.data_collection,
        "zdr": True,
        "require_parameters": True,
        "allow_fallbacks": True,
    }
    if quantizations:
        provider_preferences["quantizations"] = quantizations

    reasoning = None
    if args.reasoning_effort != "off":
        reasoning = {"effort": args.reasoning_effort}

    adapter = OpenAICompatibleLLM(
        base_url=args.base_url,
        model=args.model,
        api_key_env=args.api_key_env,
        timeout_seconds=max(args.wall_clock_s, 60.0),
        provider_preferences=provider_preferences,
        reasoning=reasoning,
    )
    policy = OpenAIToolCallingPolicy(adapter=adapter)
    policy.configure_budget(max_tool_calls=args.max_tool_calls)
    return policy


def main() -> int:
    args = parse_args()
    if not args.print_config and not args.question:
        print("--question is required unless --print-config is used", file=sys.stderr)
        return 2
    try:
        context = json.loads(args.context_json)
    except json.JSONDecodeError as exc:
        print(f"--context-json is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(context, dict):
        print("--context-json must encode a JSON object", file=sys.stderr)
        return 2

    endpoints = MCPEndpoints(
        core=args.core_url,
        finance=args.finance_url,
        meals=args.meals_url,
        training=args.training_url,
        timeout_s=args.mcp_timeout_s,
    )

    if args.print_config:
        print(
            json.dumps(
                {
                    "kind": args.kind,
                    "question": args.question,
                    "context": context,
                    "model": args.model,
                    "base_url": args.base_url,
                    "api_key_env": args.api_key_env,
                    "reasoning_effort": args.reasoning_effort,
                    "data_collection": args.data_collection,
                    "zdr": True,
                    "max_tool_calls": args.max_tool_calls,
                    "wall_clock_s": args.wall_clock_s,
                    "endpoints": endpoints.__dict__,
                },
                indent=2,
            )
        )
        return 0

    if not os.environ.get(args.api_key_env):
        print(
            f"ERROR: {args.api_key_env} is not set; cannot drive the LLM.",
            file=sys.stderr,
        )
        return 3

    policy = build_policy(args)
    dispatcher = MCPToolDispatcher(endpoints=endpoints)
    core = MCPCoreClient(endpoints=endpoints)

    result = run_investigation(
        kind=args.kind,
        question=args.question,
        context=context,
        policy=policy,
        dispatcher=dispatcher,
        core=core,
        budget=Budget(
            max_tool_calls=args.max_tool_calls,
            max_wall_clock_s=args.wall_clock_s,
        ),
    )

    payload = {
        "investigation_id": result.investigation_id,
        "status": result.status,
        "tool_call_count": result.tool_call_count,
        "elapsed_s": round(result.elapsed_s, 2),
    }
    if result.answer_md:
        payload["answer_md"] = result.answer_md
    if result.citation_refs:
        payload["citation_refs"] = result.citation_refs
    if result.error_message:
        payload["error_message"] = result.error_message

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if result.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
