---
name: memory-review
description: Surface pending memory candidates for user confirmation via #journal. Owns the memory_review playbook.
version: 1.0.0
author: Minx
metadata:
  hermes:
    tags: [memory, confirmation, cron, playbook, minx]
    playbook_id: memory_review
---

# Memory Review (Minx)

Keeps the memory candidate backlog small and explicit. Each run surfaces pending candidates to the user in `#journal` and, on reply, confirms or rejects them in Core.

Owns the `memory_review` playbook. `requires_confirmation=True` in the registry — never auto-confirms.

## Playbook Audit Pattern

1. `run_id = minx_core.start_playbook_run(playbook_id='memory_review', harness='hermes', trigger_type='cron', trigger_ref=<cron_name>)` — silent exit on CONFLICT.
2. Execute workflow.
3. Complete with `result_json={"surfaced": N, "confirmed": C, "rejected": R, "deferred": D}`.
4. On skip (no pending candidates): `status='skipped'`, `conditions_met=False`.

## Data Sources
- `minx_core.get_pending_memory_candidates(scope?, limit=10)`
- `minx_core.memory_confirm(memory_id, actor='user_via_hermes')`
- `minx_core.memory_reject(memory_id, actor='user_via_hermes', reason?)`

## Workflow

### 1) Fetch pending candidates
- `get_pending_memory_candidates(limit=10)` — cap at 10 per run so user isn't spammed.
- If result is empty: complete with `status='skipped'`, exit silently.

### 2) Post confirmation prompt
Single post to `#journal` listing each candidate with an index number. For each candidate include:
- `memory_type` + `scope` + `subject`
- Short payload summary (e.g., for `preference`: "prefers X over Y"; for `entity_fact`: "entity=X, value=Y"; for `pattern`: "X happens at Y")
- `confidence` score
- `source` (which detector proposed it)

End the post with exact reply instructions:
```
Reply with:
- `confirm 1,3,5` to confirm candidates by index
- `reject 2,4` to reject (optional: add a reason, e.g. `reject 2 reason=wrong`)
- `skip` to leave them pending
- `skip 1,2` to defer specific ones
```

### 3) Wait for user reply
Listen for a message in `#journal` matching the reply pattern. Timeout: 30 minutes. If no reply, complete with `status='skipped'`, `action_taken=False`, reason="user did not respond".

### 4) Apply user decisions
For each confirmed index:
- `memory_confirm(memory_id=<id>, actor='user_via_hermes')`
For each rejected index:
- `memory_reject(memory_id=<id>, actor='user_via_hermes', reason=<text or null>)`
Skipped indices: leave alone (stay pending for the next run).

### 5) Acknowledge
Post a short confirmation line to `#journal`: `"Memory review: confirmed N, rejected M, deferred K."`

## Rules
1. **Never auto-confirm**. This playbook is confirmation-gated — no memory changes without explicit user reply.
2. **Cap per run**: 10 candidates max so the user can actually skim them. Backlog drains across runs.
3. **Actor must be `user_via_hermes`** so audit history distinguishes human decisions from vault sync or detector promotions.
4. **Respect CONFLICT errors** on confirm/reject: if a memory was auto-promoted or expired between surface and reply, skip it and note in the acknowledgement.
5. **Idempotency**: if the user replies twice, the second pass finds fewer pending rows (already confirmed/rejected) and behaves normally. Do not error on "not found."

## Failure Modes
- CONFLICT on `start_playbook_run`: silent exit.
- Empty backlog: `status='skipped'`, no post.
- User no-reply: `status='skipped'`, `action_taken=False`.
- `memory_confirm`/`memory_reject` CONFLICT (memory already terminal): log, skip that index, continue; reflect in acknowledgement.
- Malformed user reply: post clarification in `#journal`, wait up to 5 more minutes for corrected reply before giving up.

## Bulletproof Audit Contract

These invariants are non-negotiable. A `running` row that never completes blocks the next cron tick via the unique-in-flight index until `playbook_reconcile_crashed` catches it.

1. **CONFLICT on `start_playbook_run` = hard stop.** Do not continue the workflow, do not read the vault, do not write notes, do not post to any channel, do not call any other tool. Emit `[SILENT]` immediately. Another worker already has the tick.
2. **If `start_playbook_run` returned a `run_id`, you MUST call `complete_playbook_run(run_id, status=...)` before your final response.** Every exit path ends with a completion call:
   - Normal success → `status='succeeded'`
   - Skip branch (empty day, empty backlog, nothing to do) → `status='skipped'`
   - Any tool error or malformed LLM output → `status='failed'`, `error_message=str(exc)`
3. **Never emit `[SILENT]` or any final response with an open `run_id`.** If you hit an unrecoverable error, first call `complete_playbook_run(run_id, status='failed', error_message='...')`, then emit your terminal response.
4. Uncatchable crashes (Hermes itself dies, LLM provider exhausts retries before you regain control) are swept by `playbook_reconcile_crashed` on a separate cron. Do not rely on it — always close your own run.
