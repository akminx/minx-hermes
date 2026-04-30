---
name: minx-plan
description: Build an actionable Minx plan from current goals, memories, finance, meals, and training context with durable investigation audit rows.
version: 0.1.0
author: Minx
metadata:
  hermes:
    tags: [planning, agentic, minx, slice9]
    surface: minx_plan
---

# Plan (Minx)

Turn an open-ended planning request into a bounded, read-first Minx planning run. This is the Slice 9e surface `minx_plan(...)`, implemented as the same audit loop as `minx-investigate` with `kind='plan'`.

## Audit Pattern

1. `investigation_id = minx_core.start_investigation(kind='plan', question=<planning request>, context_json=<structured context>, harness='hermes')`
2. Read current state through the allowlisted tools in `docs/minx-investigation-tool-catalog.md`.
3. After each domain tool call, append a digest-only `minx_core.append_investigation_step` entry.
4. Complete with `minx_core.complete_investigation(..., status='succeeded', answer_md=<Hermes-authored plan>, citation_refs=<typed refs>, ...)`.
5. If a budget is exhausted, complete as `budget_exhausted` with a partial plan if one is available.
6. If an unrecoverable error happens after start, complete as `failed` before responding.

Never leave a started planning run in `running` status when Hermes regains control.

## Budget

- `max_tool_calls`: 12 total MCP tool calls after `start_investigation`
- `wall_clock_s`: 120 seconds
- `max_output_review`: summarize large tool output with counts, labels, ids, and digests

## Tool Policy

Use read tools from the runtime allowlist documented in `docs/minx-investigation-tool-catalog.md`. Prefer:

- Core: `get_daily_snapshot`, `goal_list`, `goal_get`, `get_goal_trajectory`, `memory_list(include_cited_investigations=true)`, `memory_search`, `memory_hybrid_search`, `investigation_history`, `investigation_get`
- Finance: `safe_finance_summary`, `safe_finance_accounts`, `finance_query`
- Meals: `pantry_list`, `recommend_recipes`, `nutrition_profile_get`
- Training: `training_progress_summary`, `training_session_list`, `training_exercise_list`

Do not mutate goals, memories, vault notes, meals, training logs, or finance data during planning unless the user explicitly confirms that mutation. If a mutation looks useful, append `event_template='investigation.needs_confirmation'`, ask the user, and stop.

## Output

Return a concise plan with:

- A short current-state readout.
- The recommended next actions.
- Constraints, tradeoffs, and any missing inputs.
- Typed citations for memories, prior investigations, vault paths, and tool result digests.

Core stores lifecycle data; Hermes authors the plan prose.

## Running

Invoke the production runner with `kind=plan`:

```bash
uv run scripts/minx-investigate.py --kind plan \
  --question "<the planning request>" \
  --max-tool-calls 12 --wall-clock-s 120
```

The runner enforces budget caps, calls the Core/Finance/Meals/Training MCP server URLs resolved from CLI flags or `MINX_*_URL` environment variables, drives a configured OpenAI-compatible model endpoint, and prints a JSON result with `investigation_id`, `status`, `answer_md`, and `citation_refs`. Use `MINX_INVESTIGATION_MODEL=google/gemini-2.5-flash` as the recommended OpenRouter example unless deployment config says otherwise.
