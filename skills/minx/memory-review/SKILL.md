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
3. Complete immediately after surfacing candidates with `result_json={"surfaced": N, "pending_ids": [...], "review_note_path": ...}`.
4. On skip (no pending candidates): `status='skipped'`, `conditions_met=False`.

## Data Sources
- `minx_core.get_pending_memory_candidates(scope?, limit=10)`
- `minx_core.memory_confirm(memory_id, actor='user_via_hermes')`
- `minx_core.memory_reject(memory_id, actor='user_via_hermes', reason?)`
- `minx_core.persist_note(relative_path, content, overwrite=true)`

## Workflow

### 1) Fetch pending candidates
- `get_pending_memory_candidates(limit=10)` — cap at 10 per run so user isn't spammed.
- If result is empty: complete with `status='skipped'`, exit silently.

### 2) Post confirmation prompt
Single post to `#journal` listing each candidate with both an index number and the durable `memory_id`. For each candidate include:
- `memory_type` + `scope` + `subject`
- Short payload summary (e.g., for `preference`: "prefers X over Y"; for `entity_fact`: "entity=X, value=Y"; for `pattern`: "X happens at Y")
- `confidence` score
- `source` (which detector proposed it)

End the post with exact reply instructions:
```
Reply with:
- `memory confirm 123,456` to confirm by memory_id
- `memory reject 789 reason=wrong` to reject by memory_id
- `memory skip 123` to leave a specific candidate pending
- `memory review status` to reprint the current pending set
```

### 3) Persist the surfaced set and complete immediately
- Write a durable note to `Minx/System/memory-review-pending.md` containing:
  - `reviewed_at`
  - the surfaced `memory_id` values
  - short summaries
  - the exact reply commands above
- Complete the playbook run right after the post/note write. Cron must not wait for a human reply.

### 4) Later replies are handled out-of-band
If the user replies later in `#journal`, Hermes handles that in a normal interactive turn by calling:
- `memory_confirm(memory_id=<id>, actor='user_via_hermes')`
- `memory_reject(memory_id=<id>, actor='user_via_hermes', reason=<text or null>)`

The cron playbook itself does not stay alive waiting for that reply.

### 5) Acknowledge only what cron actually did
Post a short confirmation line to `#journal`: `"Memory review: surfaced N pending candidates. Reply with memory IDs when you're ready."`

## Rules
1. **Never auto-confirm**. This playbook is confirmation-gated — no memory changes during the cron run.
2. **Cap per run**: 10 candidates max so the user can actually skim them. Backlog drains across runs.
3. **Actor must be `user_via_hermes`** so audit history distinguishes human decisions from vault sync or detector promotions.
4. **Surface stable IDs**. The post and durable note must include `memory_id` so later replies are not tied to ephemeral list ordering.
5. **Respect CONFLICT errors** on later confirm/reject: if a memory was auto-promoted or expired between surface and reply, skip it and note that in the follow-up acknowledgement.
6. **Idempotency**: if the user replies twice, the second pass finds fewer pending rows (already confirmed/rejected) and behaves normally. Do not error on "not found."
7. **Cron budget awareness**: do not block on a human. The playbook must finish well within Hermes' cron timeout / reconcile window.

## Failure Modes
- CONFLICT on `start_playbook_run`: silent exit.
- Empty backlog: `status='skipped'`, no post.
- `persist_note` fails after the Discord post: complete with `status='failed'` so the surfaced batch is not "lost" without a durable reference.
- Later `memory_confirm`/`memory_reject` CONFLICT (memory already terminal): log, skip that ID, continue; reflect in the follow-up acknowledgement.
- Malformed later user reply: ask for corrected `memory confirm|reject <ids>` syntax in the interactive turn. Do not reopen the original cron run.

## Bulletproof Audit Contract

These invariants are non-negotiable. A `running` row that never completes blocks the next cron tick via the unique-in-flight index until `playbook_reconcile_crashed` catches it.

1. **CONFLICT on `start_playbook_run` = hard stop.** Do not continue the workflow, do not read the vault, do not write notes, do not post to any channel, do not call any other tool. Emit `[SILENT]` immediately. Another worker already has the tick.
2. **If `start_playbook_run` returned a `run_id`, you MUST call `complete_playbook_run(run_id, status=...)` before your final response.** Every exit path ends with a completion call:
   - Normal success → `status='succeeded'`
   - Skip branch (empty day, empty backlog, nothing to do) → `status='skipped'`
   - Any tool error or malformed LLM output → `status='failed'`, `error_message=str(exc)`
3. **Never emit `[SILENT]` or any final response with an open `run_id`.** If you hit an unrecoverable error, first call `complete_playbook_run(run_id, status='failed', error_message='...')`, then emit your terminal response.
4. Uncatchable crashes (Hermes itself dies, LLM provider exhausts retries before you regain control) are swept by `playbook_reconcile_crashed` on a separate cron. Do not rely on it — always close your own run.
