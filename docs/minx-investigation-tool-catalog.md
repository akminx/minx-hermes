# Minx Investigation Tool Catalog

This catalog documents the shipped programmatic allowlist for `scripts/minx-investigate.py` and `hermes_loop/runtime.py`. Investigations are read-first. The runner refuses any tool outside `DEFAULT_TOOL_ALLOWLIST`; mutation tools require a future explicit confirmation path and are not part of the default runner.

## Core Read Tools

- `get_daily_snapshot(review_date?, force=false)`: read daily finance, nutrition, training, goal, and insight summary state.
- `goal_list(status?)`: read goal state.
- `goal_get(goal_id, review_date?)`: fetch one goal plus current progress.
- `get_goal_trajectory(goal_id, periods?, as_of_date?)`: read recent trajectory periods for one goal.
- `memory_list(status?, memory_type?, scope?, limit?, include_cited_investigations?)`: browse memory records; pass `include_cited_investigations=true` when prior investigation references would help.
- `memory_get(memory_id)`: fetch one memory.
- `memory_search(query, scope?, memory_type?, status?, limit?)`: deterministic FTS search.
- `memory_hybrid_search(query, scope?, memory_type?, status?, limit?)`: FTS plus embedding rerank when configured.
- `memory_edge_list(memory_id, direction?, predicate?, limit?)`: traverse memory graph relationships.
- `investigation_history(kind?, harness?, status?, since?, days?, limit?)`: find prior investigations.
- `investigation_get(investigation_id)`: inspect one prior investigation.

## Finance Read Tools

- `safe_finance_summary()`: safe aggregate overview.
- `finance_query(message?, review_date?, session_ref?, limit?, intent?, filters?, natural_query?)`: natural-language or structured finance query with Core render/slot contract.
- `safe_finance_accounts()`: account overview through the safe finance read surface.

## Meals Read Tools

- `pantry_list()`: current pantry rows.
- `recommend_recipes(include_needs_shopping?, apply_nutrition_filter?)`: recipe recommendations.
- `nutrition_profile_get()`: current nutrition profile.

## Training Read Tools

- `training_exercise_list()`: current exercise catalog.
- `training_session_list(start_date?, end_date?, limit?)`: sessions in a bounded date range.
- `training_progress_summary(as_of?, lookback_days?)`: progress summary.

## Tools Outside The Default Runner

Many Minx MCP tools exist outside the runner's default read-only policy, including imports, report generation, memory confirmation/rejection, goal mutation, vault writes, meal logging, recipe indexing, nutrition updates, and training writes. Do not document those as freely callable by `minx_investigate`.

If a future workflow needs a mutation, it should append an `investigation.needs_confirmation` step, ask the user, and perform the mutation through a separate explicit command path.

## Default Budgets

- `max_tool_calls`: runtime default 12 total MCP calls after `start_investigation`; CLI defaults may be smaller.
- `wall_clock_s`: runtime default 120 seconds; CLI defaults may be smaller.
- Model-facing tool summaries are truncated by `OpenAIToolCallingPolicy`; Core stores only digests and small slots.
- There is no separate `max_steps` knob; appended trajectory steps are bounded by `max_tool_calls`.

When a budget is exhausted, complete the investigation with `status="budget_exhausted"`. The runner should return the best available answer when it has one, but the durable row may have `answer_md=null` if no final answer was produced before the cap.
