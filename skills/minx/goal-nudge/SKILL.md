---
name: goal-nudge
description: Daily check on active goals — post nudges to #journal when trajectories are at risk. Owns the goal_nudge playbook.
version: 1.0.0
author: Minx
metadata:
  hermes:
    tags: [goals, nudge, cron, playbook, minx]
    playbook_id: goal_nudge
---

# Goal Nudge (Minx)

Daily scan of active goals. If a goal's trajectory is at risk, post a targeted, concrete nudge in `#journal` so the user can react the same day.

Owns the `goal_nudge` playbook. `requires_confirmation=True` — user acknowledges/snoozes; the skill does not silently log anything beyond the playbook audit row.

## Playbook Audit Pattern

1. `run_id = minx_core.start_playbook_run(playbook_id='goal_nudge', harness='hermes', trigger_type='cron', trigger_ref=<cron_name>)` — silent exit on CONFLICT.
2. Execute workflow.
3. Complete with `result_json={"goals_checked": N, "nudges_sent": M, "at_risk_ids": [...]}`.
4. On skip (no at-risk goals): `status='skipped'`, `conditions_met=False`.

## Data Sources
- `minx_core.goal_list(status='active')`
- `minx_core.get_goal_trajectory(goal_id, periods=4, as_of_date=<today>)`

## Workflow

### 1) Fetch active goals
- `goal_list(status='active')`
- If empty: complete with `status='skipped'`, no post.

### 2) Evaluate trajectory for each goal
For each goal, call `get_goal_trajectory(goal_id, periods=4, as_of_date=<today>)`.

Classify as at-risk if any of:
- Current pace projects a miss by > 10% of target
- Most recent period is below trend AND below target
- Detector flagged drift (check goal's `at_risk` field if present)

Bound to top 3 at-risk goals per run — user can't act on more in one day.

### 3) Compose nudge
One Discord post per at-risk goal (or one combined post if ≤3). Each nudge includes:
- Goal name + target
- Current actual vs target (with period)
- Projected end-of-period outcome
- One concrete action the user could take today
- Link to the goal trajectory view (if dashboard exists; otherwise goal_id)

Tone: concrete and actionable, not preachy. Cite numbers. No fabricated stats.

End each post with reply instructions:
```
Reply: `ack` to acknowledge, `snooze 7d` to silence this goal for 7 days, `done` if already handled.
```

### 4) (Optional) Handle reply
If user replies within 15 min, log the ack/snooze/done in a short `persist_note` under `Minx/Goals/nudge_log.md` (append-only) for traceability. Non-blocking — if no reply, playbook still completes.

### 5) Complete playbook
Record counts in `result_json`. Do NOT log per-goal nudges as separate playbook runs — one `goal_nudge` run covers all nudges sent this tick.

## Rules
1. **Never auto-modify goals**. This skill reads and nudges. `goal_update` / `goal_archive` are user-initiated only.
2. **At most 3 nudges per run**. Budget is attention, not just time.
3. **Skip terminal or expired goals**: `goal_list(status='active')` already filters, but double-check `end_date` if trajectory projects past it — no point nudging a goal whose window closed.
4. **Numbers must come from tool responses**, never LLM-estimated. If trajectory is missing data, state "not enough data for trajectory" rather than inventing one.
5. **Respect snooze**: before posting a nudge, check if the goal has a recent snooze entry in `Minx/Goals/nudge_log.md` — skip if snoozed.

## Failure Modes
- CONFLICT on `start_playbook_run`: silent exit.
- No active goals: `status='skipped'`.
- All goals on-track: `status='skipped'`, `conditions_met=True`, `action_taken=False`.
- Trajectory tool fails for one goal: log warning, skip that goal, continue.
- All trajectory calls fail: `status='failed'`, `error_message`.

## Bulletproof Audit Contract

These invariants are non-negotiable. A `running` row that never completes blocks the next cron tick via the unique-in-flight index until `playbook_reconcile_crashed` catches it.

1. **CONFLICT on `start_playbook_run` = hard stop.** Do not continue the workflow, do not read the vault, do not write notes, do not post to any channel, do not call any other tool. Emit `[SILENT]` immediately. Another worker already has the tick.
2. **If `start_playbook_run` returned a `run_id`, you MUST call `complete_playbook_run(run_id, status=...)` before your final response.** Every exit path ends with a completion call:
   - Normal success → `status='succeeded'`
   - Skip branch (empty day, empty backlog, nothing to do) → `status='skipped'`
   - Any tool error or malformed LLM output → `status='failed'`, `error_message=str(exc)`
3. **Never emit `[SILENT]` or any final response with an open `run_id`.** If you hit an unrecoverable error, first call `complete_playbook_run(run_id, status='failed', error_message='...')`, then emit your terminal response.
4. Uncatchable crashes (Hermes itself dies, LLM provider exhausts retries before you regain control) are swept by `playbook_reconcile_crashed` on a separate cron. Do not rely on it — always close your own run.
