---
name: weekly-review
description: Cross-domain Minx weekly review — owns the weekly_report playbook. Renders finance report, then synthesizes narrative across finance, training, meals, goals.
version: 4.0.0
author: Minx
metadata:
  hermes:
    tags: [report, weekly, review, goals, analytics, playbook, minx]
    playbook_id: weekly_report
---

# Weekly Review (Minx)

Consolidated weekly digest. Generates the deterministic finance report as a side artifact, then produces one LLM-synthesized narrative covering finance, training, meals, and goals.

This skill owns the `weekly_report` playbook in the Core registry. It wraps its work in `start_playbook_run`/`complete_playbook_run` so every run is audited in `playbook_runs` and crash-recoverable via `playbook_reconcile_crashed`.

## Data Sources
- `minx_core.get_daily_snapshot(review_date?, force?)`
- `minx_core.get_insight_history(days, insight_type?, goal_id?, end_date?)`
- `minx_core.get_goal_trajectory(goal_id, periods?, as_of_date?)`
- `minx_core.goal_list(status='active')`
- `minx_training.training_progress_summary(as_of?, lookback_days=7)`
- `minx_training.training_session_list(start_date?, end_date?, limit?)`
- `minx_finance.finance_generate_weekly_report(period_start, period_end)`

## Playbook Audit Pattern

Every run uses the two-phase pattern from Slice 8:

1. `run_id = minx_core.start_playbook_run(playbook_id='weekly_report', harness='hermes', trigger_type='cron', trigger_ref=<cron_name_or_manual_id>)`
   - On `CONFLICT` error: another worker claimed the tick; exit silently, do not retry.
2. Execute workflow below.
3. On success:
   `minx_core.complete_playbook_run(run_id=run_id, status='succeeded', conditions_met=True, action_taken=True, result_json={"finance_report_path": ..., "digest_path": ...})`
4. On skip (no data in period):
   `minx_core.complete_playbook_run(run_id=run_id, status='skipped', conditions_met=False, action_taken=False)`
5. On error:
   `minx_core.complete_playbook_run(run_id=run_id, status='failed', conditions_met=True, action_taken=<bool>, error_message=str(exc))`

## Workflow

### 1) Resolve window
Default: previous full ISO week (Mon–Sun) relative to run date.
Monthly/quarterly variants are ad-hoc only — if cadence=monthly or quarterly is in the trigger prompt, skip this workflow and instead invoke the relevant report tool directly (`finance_generate_monthly_report`), returning a plain digest without playbook-run wrapping.

### 2) Render finance report (deterministic)
- `minx_finance.finance_generate_weekly_report(period_start, period_end)` → returns `{vault_path, summary}`
- The report note is written to the vault by the tool; do not re-render or rewrite it.

### 3) Pull cross-domain data
- Core snapshot for `period_end`
- Active goals + trajectories for each
- Training progress summary (lookback_days=7)
- Insights from `get_insight_history(days=7)`

### 4) Synthesize digest
Compose one narrative with these sections:
- **Finance**: reference the rendered report path; pull top-line totals from the tool response summary — do not recompute.
- **Training**: volume, milestones, at-risk progress
- **Meals/Nutrition**: signals from snapshot
- **Goal progress**: on-track vs at-risk, cite trajectory
- **1–3 actionable insights** grounded in the data above

### 5) Deliver
- Post digest to `#reports` with markdown link to the finance report vault path.
- No vault write for the digest itself — Discord is the delivery surface. (If a persistent review record is needed later, route through `persist_note` under `Minx/Reviews/Weekly/`.)

## Rules
1. Minx DB is canonical. Vault notes are projection only.
2. Never recompute finance totals — use `finance_generate_weekly_report` output verbatim.
3. Always compare actuals against active goals.
4. If a domain has no data in the window, state "no data in period" explicitly; do not omit the section.
5. Keep output concise and decision-oriented. Max ~400 words.
6. On any tool error, stop and complete the playbook run with `status='failed'` and the real error message — never fabricate totals.

## Failure Modes
- `minx_core.start_playbook_run` returns CONFLICT: another worker has this tick, exit silently.
- `finance_generate_weekly_report` fails: complete run with `status='failed'`, surface error to `#reports`.
- No active goals: continue — "Goal progress" section says "no active goals in period."
- Empty period (no transactions, no sessions): complete with `status='skipped'`, conditions_met=False.

## Bulletproof Audit Contract

These invariants are non-negotiable. A `running` row that never completes blocks the next cron tick via the unique-in-flight index until `playbook_reconcile_crashed` catches it.

1. **CONFLICT on `start_playbook_run` = hard stop.** Do not continue the workflow, do not read the vault, do not write notes, do not post to any channel, do not call any other tool. Emit `[SILENT]` immediately. Another worker already has the tick.
2. **If `start_playbook_run` returned a `run_id`, you MUST call `complete_playbook_run(run_id, status=...)` before your final response.** Every exit path ends with a completion call:
   - Normal success → `status='succeeded'`
   - Skip branch (empty day, empty backlog, nothing to do) → `status='skipped'`
   - Any tool error or malformed LLM output → `status='failed'`, `error_message=str(exc)`
3. **Never emit `[SILENT]` or any final response with an open `run_id`.** If you hit an unrecoverable error, first call `complete_playbook_run(run_id, status='failed', error_message='...')`, then emit your terminal response.
4. Uncatchable crashes (Hermes itself dies, LLM provider exhausts retries before you regain control) are swept by `playbook_reconcile_crashed` on a separate cron. Do not rely on it — always close your own run.
