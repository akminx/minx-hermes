---
name: minx-retro
description: Run a bounded Minx retrospective over a recent period using durable investigation audit rows.
version: 0.1.0
author: Minx
metadata:
  hermes:
    tags: [retrospective, review, agentic, minx, slice9]
    surface: minx_retro
---

# Retro (Minx)

Answer retrospective questions like "what changed this week?" or "why did that plan drift?" using the Slice 9 investigation lifecycle. Use `kind='retro'`.

## Audit Pattern

1. `investigation_id = minx_core.start_investigation(kind='retro', question=<retro request>, context_json=<period and scope>, harness='hermes')`
2. Read the relevant finance, training, meals, goal, memory, and prior-investigation context.
3. Append one digest-only investigation step after each domain tool call.
4. Complete with `status='succeeded'`, a Hermes-authored retrospective, and typed citations.
5. Complete as `budget_exhausted` for partial retrospectives when caps are hit.
6. Complete as `failed` after any unrecoverable error that happens after start.

Never persist raw tool output in Core investigation fields.

## Budget

- `max_tool_calls`: 12 total MCP tool calls after `start_investigation`
- `wall_clock_s`: 120 seconds
- `max_steps`: 12 appended trajectory steps

## Tool Policy

Use read tools from `docs/minx-investigation-tool-catalog.md`. Prefer:

- Core: `get_daily_snapshot`, `get_insight_history`, `goal_list`, `get_goal_trajectory`, `memory_list(include_cited_investigations=true)`, `memory_search`, `investigation_history`, `investigation_get`
- Finance: `safe_finance_summary`, `finance_query`, `finance_anomalies`, `finance_monitoring`
- Meals: `nutrition_profile_get`, `pantry_list`
- Training: `training_progress_summary`, `training_session_list`

Mutation tools require explicit user confirmation and an `investigation.needs_confirmation` step before any state change.

## Output

Return:

- What happened.
- Why it likely happened.
- What signals are strong vs weak.
- What to carry forward or adjust next.

Use citations for any durable memories, prior investigations, vault paths, and tool result digests.

## Running

Invoke the production runner with `kind=retro`:

```bash
uv run scripts/minx-investigate.py --kind retro \
  --question "<the retro question>" \
  --max-tool-calls 10 --wall-clock-s 90
```

Same agentic loop as `/minx-investigate`; only the `kind` differs. Hermes config in `~/.hermes/config.yaml` already routes the four Minx MCP servers; the runner drives Nemotron-3-Super on OpenRouter with no-logging routing and prints a JSON result.
