"""OpenAI-style tool schemas for the read-only investigation allowlist.

The Hermes loop hands these to the LLM via the `tools` array. Schemas mirror
the actual MCP tool surfaces in Core / Finance / Meals / Training and stay
minimal: enough for the model to fill arguments correctly, no aspirational
fields. Add a new schema here when you add a tool to DEFAULT_TOOL_ALLOWLIST.

Each entry is the OpenAI tool object format:
    {"type": "function", "function": {"name", "description", "parameters"}}

Schemas are intentionally permissive on optional integer/limit fields so
OpenAI-compatible providers do not fail strict JSON validation when they omit
optional arguments.
"""

from __future__ import annotations

from typing import Any


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


# Core memory tools
_MEMORY_SEARCH = _fn(
    "memory_search",
    "Full-text search durable memories. Returns matching rows with id, subject, scope, type, status, payload.",
    {
        "query": {"type": "string", "description": "Search query (BM25 / FTS5)."},
        "scope": {"type": "string", "description": "Optional scope filter."},
        "memory_type": {"type": "string", "description": "Optional type filter."},
        "status": {
            "type": "string",
            "description": "active | candidate | expired. Defaults to active.",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
    },
    ["query"],
)

_MEMORY_HYBRID_SEARCH = _fn(
    "memory_hybrid_search",
    "Hybrid lexical + embedding search over memories. Use when keyword search alone misses paraphrases.",
    {
        "query": {"type": "string"},
        "scope": {"type": "string"},
        "memory_type": {"type": "string"},
        "status": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
    },
    ["query"],
)

_MEMORY_LIST = _fn(
    "memory_list",
    "List durable memories with optional filters. Set include_cited_investigations=true to also return prior investigations that cited each memory.",
    {
        "status": {"type": "string"},
        "memory_type": {"type": "string"},
        "scope": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
        "include_cited_investigations": {"type": "boolean", "default": False},
    },
    [],
)

_MEMORY_GET = _fn(
    "memory_get",
    "Fetch a single memory row by id.",
    {"memory_id": {"type": "integer", "minimum": 1}},
    ["memory_id"],
)

_MEMORY_EDGE_LIST = _fn(
    "memory_edge_list",
    "List edges connecting a memory to other memories.",
    {
        "memory_id": {"type": "integer", "minimum": 1},
        "direction": {"type": "string", "description": "in | out | both"},
        "predicate": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
    },
    ["memory_id"],
)

_INVESTIGATION_HISTORY = _fn(
    "investigation_history",
    "List recent investigation runs (for retro/onboard context). Read-only.",
    {
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        "kind": {"type": "string"},
        "harness": {"type": "string"},
        "status": {"type": "string"},
        "since": {"type": "string", "description": "Optional ISO timestamp lower bound."},
        "days": {"type": "integer", "minimum": 1, "maximum": 365},
    },
    [],
)

_INVESTIGATION_GET = _fn(
    "investigation_get",
    "Fetch one investigation run by id, including trajectory digests and citations.",
    {"investigation_id": {"type": "integer", "minimum": 1}},
    ["investigation_id"],
)

_GET_DAILY_SNAPSHOT = _fn(
    "get_daily_snapshot",
    "Get the daily review snapshot for a date. Read-only; force=false reuses existing.",
    {
        "review_date": {
            "type": "string",
            "description": "ISO date YYYY-MM-DD. Defaults to today.",
        },
        "force": {"type": "boolean", "default": False},
    },
    [],
)

_GOAL_LIST = _fn(
    "goal_list",
    "List goals with optional status filter.",
    {"status": {"type": "string"}},
    [],
)

_GOAL_GET = _fn(
    "goal_get",
    "Fetch one goal plus current progress for the requested review date.",
    {
        "goal_id": {"type": "integer", "minimum": 1},
        "review_date": {"type": "string", "description": "ISO date YYYY-MM-DD. Defaults to today."},
    },
    ["goal_id"],
)

_GET_GOAL_TRAJECTORY = _fn(
    "get_goal_trajectory",
    "Fetch recent trajectory periods for a goal.",
    {
        "goal_id": {"type": "integer", "minimum": 1},
        "periods": {"type": "integer", "minimum": 1, "maximum": 24, "default": 4},
        "as_of_date": {"type": "string", "description": "ISO date YYYY-MM-DD. Defaults to today."},
    },
    ["goal_id"],
)

# Finance read tools
_FINANCE_QUERY = _fn(
    "finance_query",
    "Run a structured natural-language finance query. Returns rows aggregated by the inferred filters.",
    {
        "message": {"type": "string", "description": "Plain-language finance question."},
        "natural_query": {"type": "string", "description": "Alias for message."},
        "review_date": {"type": "string", "description": "ISO date YYYY-MM-DD. Defaults to today."},
        "session_ref": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
        "intent": {"type": "string", "description": "Structured intent such as list_transactions."},
        "filters": {"type": "object", "additionalProperties": True},
    },
    [],
)

_SAFE_FINANCE_SUMMARY = _fn(
    "safe_finance_summary",
    "Aggregate finance overview (accounts, categories, balances). Audit-envelope wrapped.",
    {},
    [],
)

_SAFE_FINANCE_ACCOUNTS = _fn(
    "safe_finance_accounts",
    "List finance accounts through the safe finance read surface.",
    {},
    [],
)

# Meals read tools
_PANTRY_LIST = _fn(
    "pantry_list",
    "List pantry items.",
    {},
    [],
)

_RECOMMEND_RECIPES = _fn(
    "recommend_recipes",
    "Recommend recipes given current pantry and nutrition profile.",
    {
        "include_needs_shopping": {"type": "boolean", "default": False},
        "apply_nutrition_filter": {"type": "boolean", "default": False},
    },
    [],
)

_NUTRITION_PROFILE_GET = _fn(
    "nutrition_profile_get",
    "Get the active nutrition profile.",
    {},
    [],
)

# Training read tools
_TRAINING_EXERCISE_LIST = _fn(
    "training_exercise_list",
    "List training exercises.",
    {},
    [],
)

_TRAINING_SESSION_LIST = _fn(
    "training_session_list",
    "List recent training sessions.",
    {
        "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD."},
        "end_date": {"type": "string", "description": "ISO date YYYY-MM-DD."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
    },
    [],
)

_TRAINING_PROGRESS_SUMMARY = _fn(
    "training_progress_summary",
    "Summary of training progress over recent weeks.",
    {
        "as_of": {"type": "string", "description": "ISO date YYYY-MM-DD. Defaults to today."},
        "lookback_days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 7},
    },
    [],
)


_BY_NAME: dict[str, dict[str, Any]] = {
    schema["function"]["name"]: schema
    for schema in [
        _MEMORY_SEARCH,
        _MEMORY_HYBRID_SEARCH,
        _MEMORY_LIST,
        _MEMORY_GET,
        _MEMORY_EDGE_LIST,
        _INVESTIGATION_HISTORY,
        _INVESTIGATION_GET,
        _GET_DAILY_SNAPSHOT,
        _GOAL_LIST,
        _GOAL_GET,
        _GET_GOAL_TRAJECTORY,
        _FINANCE_QUERY,
        _SAFE_FINANCE_SUMMARY,
        _SAFE_FINANCE_ACCOUNTS,
        _PANTRY_LIST,
        _RECOMMEND_RECIPES,
        _NUTRITION_PROFILE_GET,
        _TRAINING_EXERCISE_LIST,
        _TRAINING_SESSION_LIST,
        _TRAINING_PROGRESS_SUMMARY,
    ]
}


def schemas_for(tool_names: list[str] | frozenset[str]) -> list[dict[str, Any]]:
    """Return tool schemas for the given names. Unknown names are skipped silently.

    Use this to feed the LLM a tool list that exactly matches the runtime
    allowlist. The Hermes loop already refuses to dispatch tools outside the
    allowlist, so omitting a schema for a tool the LLM might want simply
    means the LLM won't see it as an option.
    """

    return [_BY_NAME[name] for name in tool_names if name in _BY_NAME]


def all_schemas() -> list[dict[str, Any]]:
    return list(_BY_NAME.values())


def known_tool_names() -> frozenset[str]:
    return frozenset(_BY_NAME)
