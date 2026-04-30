# Slice 8 Handoff — Proactive Autonomy

> Historical handoff: this records the April 2026 Slice 8 state and should not be used as current architecture or operations guidance. Current behavior lives in `../README.md`, `hermes-investigation-runtime-contract.md`, `minx-investigation-tool-catalog.md`, and `discord-flow-smoke-runbook.md`.

**Date**: 2026-04-22

## Summary

Slice 8 (Proactive Autonomy) is validated end-to-end. All 5 playbooks now have
successful terminal smoke evidence, the reconcile sweep cron is installed and
has executed successfully, and no `playbook_runs` rows remain stuck in
`status='running'`. Core MCP surfaces shipped in `minx-mcp` on `main` and the
dict-payload fix is present at commit **`bab7c92`**. All harness-side artifacts (skills, smoke
scripts, cron snapshot) now live in this repo (`~/Documents/minx-hermes`)
rather than scattered across `~/.hermes/`.

## Session findings (read this before touching anything)

- **DB migration jump.** The production Minx DB (`~/.minx/data/minx.db`) was
  at migration 012 before today. Bringing the stack up via
  `~/Documents/minx-mcp/scripts/start_hermes_stack.sh` auto-applied migrations
  013 through 019 (memory, snapshot archives, vault_index, playbook_runs).
  Pre-upgrade backup is at
  `~/.minx/data/minx.db.pre-slice8.20260422T011159`. If anything looks wrong
  with the DB schema, compare against that backup first.

- **First smoke run silent-failed.** The initial `daily-review` smoke
  silent-exited with `[SILENT]` because `start_playbook_run` got
  connection-refused — the MCP servers were not running. Always verify
  `curl http://127.0.0.1:8001/mcp` responds before smoke-testing.

- **Second smoke run orphaned.** One row landed in `playbook_runs`
  (`id=1, status=running`). The then-active LLM provider
  (`nvidia/nemotron-3-super-120b-a12b:free` via OpenRouter) flaked through 3
  retries; the model eventually produced
  output and the skill posted to Discord, but never called
  `complete_playbook_run`. The row was reconciled via the
  `playbook_reconcile_crashed` MCP tool with `stale_after_minutes=1`, which
  flipped it to `status=failed, error_message='harness crash suspected'`.

- **Root cause of the orphan.** The skill's `[SILENT]` path on LLM failure
  did not call `complete_playbook_run`. Today we patched all 5 SKILL.md files
  with a **"Bulletproof Audit Contract"** section requiring the skill to
  complete the run (with `ok | failed | skipped`) before any terminal
  response, including silent exits. That patch is now tracked in this repo
  under `skills/minx/*/SKILL.md`.

## Current Slice 8 status

Done:
- Core MCP tools shipped (minx-mcp `main` @ `bab7c92`):
  `start_playbook_run`, `complete_playbook_run`, `log_playbook_run`,
  `playbook_history`, `playbook_reconcile_crashed`, `playbook://registry`,
  migration `019_playbook_runs.sql`.
- Cron wiring: 6 Minx jobs in `~/.hermes/cron/jobs.json` (5 playbooks +
  `playbook-reconcile-sweep`, snapshotted here at
  `cron/jobs.snapshot.json`).
- 5 Minx playbook skills in `skills/minx/` with the Bulletproof Audit
  Contract applied.
- `memory-review` rewritten to a non-blocking “surface now, resolve later”
  cron flow so it no longer conflicts with Hermes' inactivity timeout / the
  reconcile sweep window.
- All Minx cron jobs pinned to `nvidia/nemotron-3-super-120b-a12b` on
  OpenRouter, with Hermes provider routing locked to `deepinfra` +
  `bf16`, instead of inheriting the flaky free default model.
- Hermes main model and auxiliary text-model slots are aligned to the same
  OpenRouter `deepinfra` + `bf16` route.
- `#finances` now has a dedicated Discord-triggered import path:
  `discord.channel_skill_bindings` auto-loads `minx/finance-import` there,
  and a channel prompt tells Hermes to treat supported CSV/PDF uploads as
  import requests by default.
- The `finance-import` skill is now tracked in this repo and can be
  re-synced into `~/.hermes/skills/minx/finance-import` with
  `scripts/configure-finance-import-flow.sh`.
- Smoke test: `scripts/smoke-playbooks.sh [job-name]`.
- Hardened smoke harness: `scripts/smoke-playbooks.sh` now waits for a new
  terminal `playbook_runs` row instead of reporting success immediately after
  `hermes cron tick`.
- `daily-review` validated end-to-end to Discord.
- Remaining 4 playbooks also smoke-validated:
  - `wiki-update` → `playbook_runs.id=4`, `status=skipped`
  - `memory-review` → `playbook_runs.id=5`, `status=skipped`
  - `goal-nudge` → `playbook_runs.id=6`, `status=skipped`
  - `weekly-review` → `playbook_runs.id=7`, `status=succeeded`
- Reconcile sweep cron added: `playbook-reconcile-sweep` runs every 15 minutes
  and calls `playbook_reconcile_crashed(stale_after_minutes=15)`.
- Reconcile sweep validated live: Hermes job `playbook-reconcile-sweep`
  (`id=bbb726daf813`) ran at `2026-04-22T03:04:16-05:00` with
  `last_status=ok`.

Not yet done:
- Commit the current `minx-hermes` overlay changes (tracked files are modified
  locally as of this handoff update).
- Add overlay/runtime drift prevention tooling:
  - `sync-hermes-overlay.sh` (or equivalent) to copy/symlink the repo state
    into `~/.hermes/`
  - cron-config validation for required Minx job fields
  - optional dedicated skill for `playbook-reconcile-sweep`
- Start Slice 9 harness work after the Core surface lands.

## Recommended Next Work (Slice 9 + Ops)

1. **Core first: Slice 9a + 9b**
   - add the `investigations` table / MCP tools from the Slice 9 spec
   - implement trajectory digests + redaction before any Hermes loop work
2. **Ops hardening in parallel**
   - add overlay sync tooling so the repo and `~/.hermes/` cannot silently drift
   - add cron validation so future jobs cannot land with missing `model`,
     `provider`, or `next_run_at`
   - normalize `trigger_ref` naming across playbooks for cleaner audit/history
   - add a lightweight “playbook health” report job
3. **Hermes Slice 9d after Core lands**
   - build a budgeted `minx_investigate` loop that starts / appends /
     completes investigation rows in Core
   - re-use the same explicit audit discipline that now works for Slice 8

## How to resume Slice 8 work

```
cd ~/Documents/minx-mcp && ./scripts/start_hermes_stack.sh
curl http://127.0.0.1:8001/mcp    # should respond; if not: tail /tmp/minx-stack.log
```

Then, from this repo:

```
~/Documents/minx-hermes/scripts/smoke-playbooks.sh --list        # list the 5 playbook job IDs
~/Documents/minx-hermes/scripts/smoke-playbooks.sh <name>        # queue + tick one
~/Documents/minx-hermes/scripts/smoke-playbooks.sh --history     # recent playbook_runs
~/Documents/minx-hermes/scripts/configure-finance-import-flow.sh --check
```

For the maintenance cron:

```
hermes cron run bbb726daf813 && hermes cron tick
```

Then inspect `~/.hermes/cron/jobs.json` for `playbook-reconcile-sweep.last_status`
or check `playbook_runs` for any newly reconciled rows.

If a run orphans at `status=running` for more than 15 minutes, the
`playbook-reconcile-sweep` cron should catch it automatically; you can still
call `playbook_reconcile_crashed` manually via an MCP client for an immediate
repair.

## Key file paths

| Path | Role |
|---|---|
| `~/Documents/minx-mcp/` | Minx MCP server code (remote: `akminx/minx`) |
| `~/.hermes/hermes-agent/` | Hermes upstream checkout (remote: NousResearch, read-only for us) |
| `~/.minx/data/minx.db` | Minx SQLite DB |
| `~/.hermes/cron/jobs.json` | Cron runtime state |
| `~/.hermes/config.yaml` | Hermes config (declares MCP server URLs) |
| `~/.hermes/skills/minx/` | Symlinks into `~/Documents/minx-hermes/skills/minx/` |

## References

- Slice 8 spec: `~/Documents/minx-mcp/docs/superpowers/specs/2026-04-15-slice8-proactive-autonomy.md`
- Slice 9 spec: `~/Documents/minx-mcp/docs/superpowers/specs/2026-04-19-slice9-agentic-investigations.md`
- minx-mcp handoff: `~/Documents/minx-mcp/HANDOFF.md`
