---
name: minx-onboard-entity
description: Build a bounded Minx dossier for a person, merchant, place, habit, or project with durable investigation audit rows.
version: 0.1.0
author: Minx
metadata:
  hermes:
    tags: [entity, onboarding, agentic, minx, slice9]
    surface: minx_onboard_entity
---

# Onboard Entity (Minx)

Create a compact entity dossier from existing Minx data. This is the Slice 9f `minx_onboard_entity(...)` surface and uses `kind='onboard'` (Core's enum is `{investigate, plan, retro, onboard, other}`; the entity context goes in `context_json`).

## Audit Pattern

1. `investigation_id = minx_core.start_investigation(kind='onboard', question=<entity request>, context_json={"entity": <name>, "entity_type": <optional type>}, harness='hermes')`
2. Search memories, prior investigations, vault notes, and relevant domain summaries for the entity.
3. Append digest-only investigation steps after each tool call.
4. Complete with `status='succeeded'`, a Hermes-authored dossier, and typed citations.
5. Complete as `budget_exhausted` if the run reaches caps.
6. Complete as `failed` after any unrecoverable error that happens after start.

## Budget

- `max_tool_calls`: 12 total MCP tool calls after `start_investigation`
- `wall_clock_s`: 120 seconds
- `max_steps`: 12 appended trajectory steps

## Tool Policy

Use read tools from `docs/minx-investigation-tool-catalog.md`. Prefer:

- Core: `memory_search`, `memory_hybrid_search`, `memory_list(include_cited_investigations=true)`, `memory_get`, `memory_edge_list`, `investigation_history`, `investigation_get`, `get_daily_snapshot`
- Finance: `finance_query`, `safe_finance_summary` for merchants or accounts
- Meals: `pantry_list`, `recommend_recipes`, `nutrition_profile_get` for food entities
- Training: `training_exercise_list`, `training_session_list`, `training_progress_summary` for training entities

Do not create or update entity memories or vault pages unless the user explicitly confirms. If that action is useful, append `investigation.needs_confirmation`, ask, and stop.

## Output

Return:

- Known facts.
- Open questions.
- Relevant history and patterns.
- Suggested next action, if any.

Use structured citations for memories, prior investigations, vault paths, and tool result digests. Core stores the audit; Hermes writes the dossier.

## Running

Invoke the production runner with `kind=onboard`:

```bash
uv run scripts/minx-investigate.py --kind onboard \
  --question "<entity request>" \
  --context-json '{"entity": "Sweetgreen", "entity_type": "merchant"}' \
  --max-tool-calls 12 --wall-clock-s 120
```

Same agentic loop and budget enforcement as the other `/minx-*` surfaces; entity context goes in `--context-json`.
