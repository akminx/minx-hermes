---
name: daily-review
description: Nightly Minx daily review — synthesize snapshot + insights into the review note at Minx/Reviews/YYYY-MM-DD.md. Owns the daily_review playbook.
version: 1.0.0
author: Minx
metadata:
  hermes:
    tags: [daily, review, cron, playbook, minx]
    playbook_id: daily_review
---

# Daily Review (Minx)

Generate the nightly review note summarizing the day's activity, open loops, and attention items.

Owns the `daily_review` playbook in the Core registry. Writes to `Minx/Reviews/YYYY-MM-DD.md` using the `wiki-templates://review` scaffold, then posts a short digest to `#reports`.

## Playbook Audit Pattern

1. `run_id = minx_core.start_playbook_run(playbook_id='daily_review', harness='hermes', trigger_type='cron', trigger_ref=<cron_name>)`
   - On CONFLICT: another worker has the tick; exit silently.
2. Execute workflow.
3. On success: `complete_playbook_run(run_id, status='succeeded', conditions_met=True, action_taken=True, result_json={"review_path": ...})`
4. On skip (empty day, nothing to report): `complete_playbook_run(run_id, status='skipped', conditions_met=False, action_taken=False)`
5. On error: `complete_playbook_run(run_id, status='failed', conditions_met=True, action_taken=<bool>, error_message=str(exc))`

## Data Sources
- `minx_core.get_daily_snapshot(review_date=<today>, force=false)`
- `minx_core.get_insight_history(days=1, end_date=<today>)`
- `wiki-templates://review` (MCP resource — scaffold the note body)

## Workflow

### 1) Resolve review date
Default: `today` (run date, local). If `trigger_ref` carries a specific date, use it.

### 2) Fetch snapshot + insights
- `get_daily_snapshot(review_date=<today>)` → includes `attention_items`, `memory_context`, cross-domain facts
- `get_insight_history(days=1, end_date=<today>)` → today's detector signals

### 3) Check conditions
If snapshot is empty AND no insights today AND no pending attention items:
- Skip — complete playbook run with `status='skipped'`, do not write a note, do not post.

### 4) Fetch the review scaffold
- Read MCP resource `wiki-templates://review` → contains frontmatter + section skeleton with `${llm_body}` regions.
- Fill `${llm_body}` regions only; do not alter frontmatter keys or section headings.
- Ensure frontmatter includes `type: minx-wiki` and `wiki_type: review` (the scaffold already does — don't remove).

### 5) Synthesize review body
Sections:
- **Summary**: 2–3 sentences capturing the day's shape.
- **Finance signals**: from snapshot + insights (spending anomalies, goal drift).
- **Training signals**: sessions logged, progress, at-risk streaks.
- **Meals/Nutrition signals**: day totals vs target if available.
- **Open loops / attention**: list items from `attention_items` + anything the user should act on.
- **Memory context**: pending candidate count (do NOT confirm/reject here — that's the `memory_review` playbook).

Keep under ~400 words. No fabricated data — if a section is empty, say "no signals."

### 6) Persist review note
- `minx_core.persist_note(relative_path='Minx/Reviews/YYYY-MM-DD.md', content=<filled_scaffold>, overwrite=true)`
- Overwrite is intentional: re-running today's review replaces the note.

### 7) Deliver
- Post a 3–5 line digest to `#reports` with a markdown link to the vault path.
- Do NOT paste the full review body.

## Rules
1. Frontmatter contract: `type: minx-wiki`, `wiki_type: review`. The memory reconciler ignores these. Never write `type: minx-memory` here.
2. Write only to `Minx/Reviews/`. Never touch memory notes.
3. Deterministic paths — `YYYY-MM-DD.md` format.
4. One note per day. Re-runs overwrite.
5. Empty days exit via `status='skipped'` — no note, no channel post.

## Failure Modes
- CONFLICT on `start_playbook_run`: silent exit.
- Snapshot tool fails: `status='failed'`, surface to `#reports`.
- `persist_note` fails: `status='failed'`, action_taken=False, surface to `#reports`.
- LLM synthesis returns malformed fill: fallback to a minimal summary ("Snapshot captured, see raw tool output") rather than fabricating — still mark succeeded if note written.

## Bulletproof Audit Contract

These invariants are non-negotiable. A `running` row that never completes blocks the next cron tick via the unique-in-flight index until `playbook_reconcile_crashed` catches it.

1. **CONFLICT on `start_playbook_run` = hard stop.** Do not continue the workflow, do not read the vault, do not write notes, do not post to any channel, do not call any other tool. Emit `[SILENT]` immediately. Another worker already has the tick.
2. **If `start_playbook_run` returned a `run_id`, you MUST call `complete_playbook_run(run_id, status=...)` before your final response.** Every exit path ends with a completion call:
   - Normal success → `status='succeeded'`
   - Skip branch (empty day, empty backlog, nothing to do) → `status='skipped'`
   - Any tool error or malformed LLM output → `status='failed'`, `error_message=str(exc)`
3. **Never emit `[SILENT]` or any final response with an open `run_id`.** If you hit an unrecoverable error, first call `complete_playbook_run(run_id, status='failed', error_message='...')`, then emit your terminal response.
4. Uncatchable crashes (Hermes itself dies, LLM provider exhausts retries before you regain control) are swept by `playbook_reconcile_crashed` on a separate cron. Do not rely on it — always close your own run.
