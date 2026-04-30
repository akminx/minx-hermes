---
name: minx-investigate
description: Run a bounded Minx investigation with durable Core audit rows. Owns the interactive minx_investigate surface.
version: 0.1.0
author: Minx
metadata:
  hermes:
    tags: [investigation, agentic, minx, slice9]
    surface: minx_investigate
---

# Investigate (Minx)

Answer one open-ended Minx question by running a bounded, read-first tool loop and recording every step in Core investigations.

This skill owns the first Slice 9 interactive surface: `minx_investigate(question)`. Core stores lifecycle state, structured render events, step digests, and citations. Hermes owns the LLM loop, budget, user interaction, and final answer prose.

## Audit Pattern

1. `investigation_id = minx_core.start_investigation(kind='investigate', question=<user question>, context_json=<structured context>, harness='hermes')`
2. Run a bounded read-only investigation loop.
3. After each domain tool call, compute digest-only step metadata and call `minx_core.append_investigation_step(investigation_id, step_json=<digest step>)`.
4. On success, call `minx_core.complete_investigation(..., status='succeeded', answer_md=<Hermes-authored answer>, citation_refs=<typed refs>, ...)`.
5. On budget exhaustion, call `complete_investigation(..., status='budget_exhausted', answer_md=<partial answer>, ...)`.
6. On any unrecoverable tool or reasoning error after start, call `complete_investigation(..., status='failed', error_message=<short error>)` before responding.

Never leave an investigation in `running` status if Hermes regains control after an error.

## Budget

Default caps unless the user explicitly narrows them:

- `max_tool_calls`: 12 total MCP tool calls after `start_investigation`
- `wall_clock_s`: 120 seconds
- `max_output_review`: inspect summaries and counts, not full raw rows, when a tool returns large data

Stop early when the answer is clear. If a cap is hit, produce the best partial answer and mark the run `budget_exhausted`.

## Tool Allowlist

Use the concrete catalog in `docs/minx-investigation-tool-catalog.md`.

Default read tools:

- Core: `get_daily_snapshot`, `get_insight_history`, `get_goal_trajectory`, `goal_list`, `goal_get`, `memory_list`, `memory_get`, `memory_search`, `memory_hybrid_search`, `memory_edge_list`, `investigation_history`, `investigation_get`
- Finance: `safe_finance_summary`, `safe_finance_accounts`, `finance_query`, `finance_anomalies`, `finance_monitoring`, `finance_job_status`
- Meals: `pantry_list`, `recommend_recipes`, `nutrition_profile_get`, `recipe_template`
- Training: `training_exercise_list`, `training_program_get`, `training_session_list`, `training_progress_summary`

Do not call destructive or confirming tools (`memory_confirm`, `memory_reject`, vault writes, imports, or mutation tools) during an investigation unless the user explicitly asked for that action. If a risky mutation looks useful, append a step with `event_template='investigation.needs_confirmation'`, ask the user, and stop the investigation loop until they decide.

## Step Digest Contract

For every domain tool call, append a step shaped like:

```json
{
  "step": 1,
  "event_template": "investigation.step_logged",
  "event_slots": {
    "summary": "finance_query returned 12 matching dining transactions",
    "row_count": 12
  },
  "tool": "finance_query",
  "args_digest": "<64 lowercase sha256 hex>",
  "result_digest": "<64 lowercase sha256 hex>",
  "latency_ms": 182
}
```

Digest rules:

- Canonicalize arguments/results as JSON with sorted keys and compact separators before SHA-256 hashing.
- Store only raw lowercase hex digests, never `sha256:<hex>`.
- Do not store raw tool outputs, row payloads, transcripts, or messages in `step_json` or `event_slots`.
- Use counts, byte counts, ids, short labels, and digest values for `event_slots`.

## Citations

Complete the investigation with structured `citation_refs` whenever the answer depends on durable objects:

- `{"type": "memory", "id": <memory_id>}`
- `{"type": "investigation", "id": <investigation_id>}`
- `{"type": "vault_path", "path": "Minx/..."}`
- `{"type": "tool_result_digest", "tool": "<tool_name>", "digest": "<64 lowercase sha256 hex>"}`

Prefer memory/investigation/vault citations over prose-only references. Tool result digests are acceptable for ephemeral read-only tool outputs.

## Final Answer

Hermes authors `answer_md`; Core must not write the final prose. The response to the user should be concise and cite the durable facts used. Mention if the answer is partial because the investigation hit its budget.

## Failure Modes

- `start_investigation` fails: do not run domain tools. Report the Core error.
- Domain tool returns clarification/error: append a digest step for the attempt, then either ask a narrow follow-up question or complete as `failed`.
- Budget exhausted: append the last observed step if possible, complete as `budget_exhausted`, and return the partial answer.
- Confirmation needed: append `investigation.needs_confirmation`, ask the user, and do not mutate state until the user explicitly confirms.

## Runtime Contract

The live Hermes implementation must follow `docs/hermes-investigation-runtime-contract.md`. Two reference implementations live in this repo:

- `hermes_loop/runtime.py` — agentic loop with hard budget enforcement (`max_tool_calls`, wall-clock), a programmatic tool allowlist, terminal-status guarantee, and pluggable Policy/Dispatcher/Core seams. Tested by `tests/test_runtime.py`. This is what production Hermes must adopt or reimplement.
- `scripts/minx-investigate-once.py` — deterministic mode-driven runner used by smoke. Predates the agentic loop and is kept for the smoke harness.
