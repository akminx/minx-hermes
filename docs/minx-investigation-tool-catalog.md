# Minx Investigation Tool Catalog

This catalog defines the default tool policy for `minx_investigate`. Investigations are read-first. Hermes may call read tools freely within budget, but mutation tools require explicit user confirmation and an `investigation.needs_confirmation` step before any state change.

## Core Read Tools

- `get_daily_snapshot(review_date?, force=false)`: read daily finance, nutrition, training, goal, and insight summary state.
- `get_insight_history(days?, insight_type?, goal_id?, end_date?)`: read historical insights.
- `get_goal_trajectory(goal_id, periods?, as_of_date?)`: read trajectory for a known goal.
- `goal_list(status?)`, `goal_get(goal_id, review_date?)`: read goal state.
- `memory_list(status?, memory_type?, scope?, limit?, include_cited_investigations?)`: browse memory records; pass `include_cited_investigations=true` when prior investigation references would help.
- `memory_get(memory_id)`: fetch one memory.
- `memory_search(query, scope?, memory_type?, status?, limit?)`: deterministic FTS search.
- `memory_hybrid_search(query, scope?, memory_type?, status?, limit?)`: FTS plus embedding rerank when configured.
- `memory_edge_list(memory_id, direction?, predicate?, limit?)`: traverse memory graph relationships.
- `investigation_history(kind?, harness?, status?, since?, days?, limit?)`: find prior investigations.
- `investigation_get(investigation_id)`: inspect one prior investigation.

## Finance Read Tools

- `safe_finance_summary()`: safe aggregate overview.
- `safe_finance_accounts()`: account overview without sensitive transaction rows.
- `finance_query(message?, review_date?, session_ref?, limit?, intent?, filters?, natural_query?)`: natural-language or structured finance query with Core render/slot contract.
- `finance_anomalies()`: anomaly summary.
- `finance_monitoring(period_start, period_end)`: monitoring summary for a bounded period.
- `finance_job_status(job_id)`: read import/report job status.

## Meals Read Tools

- `pantry_list()`: current pantry rows.
- `recommend_recipes(include_needs_shopping?, apply_nutrition_filter?)`: recipe recommendations.
- `nutrition_profile_get()`: current nutrition profile.
- `recipe_template()`: recipe note scaffold.

## Training Read Tools

- `training_exercise_list()`: current exercise catalog.
- `training_program_get(program_id)`: one program.
- `training_session_list(start_date?, end_date?, limit?)`: sessions in a bounded date range.
- `training_progress_summary(as_of?, lookback_days?)`: progress summary.

## Mutation Tools Requiring Confirmation

- Core: `memory_create`, `memory_capture`, `memory_confirm`, `memory_reject`, `memory_expire`, `memory_embedding_enqueue`, `memory_edge_create`, `memory_edge_delete`, `vault_replace_section`, `vault_replace_frontmatter`, `vault_scan`, `vault_reconcile_memories`, `persist_note`, `goal_create`, `goal_update`, `goal_archive`, `goal_parse`, `enrichment_sweep`, `enrichment_retry_dead_letter`.
- Finance: `finance_import`, `finance_import_preview` when it stages files, `finance_categorize`, `finance_add_category_rule`, `finance_generate_weekly_report`, `finance_generate_monthly_report`.
- Meals: `meal_log`, `pantry_add`, `pantry_update`, `pantry_remove`, `recipe_index`, `recipe_scan`, `recipes_reconcile`, `nutrition_profile_set`.
- Training: `training_exercise_upsert`, `training_program_upsert`, `training_program_activate`, `training_session_log`.

## Default Budgets

- `max_tool_calls`: 12 total MCP calls after `start_investigation`.
- `wall_clock_s`: 120 seconds.
- `max_large_output_bytes`: 64 KiB inspected by Hermes; digest the full result but summarize only counts/labels in Core.
- `max_steps`: 12 appended trajectory steps.

When a budget is exhausted, complete the investigation with `status="budget_exhausted"` and a partial answer.
