# Slice 8 Handoff — Proactive Autonomy

**Date**: 2026-04-22

## Summary

Slice 8 (Proactive Autonomy) is validated end-to-end. The `daily-review`
playbook cron fired on schedule, the skill called `start_playbook_run` on
minx-core, the LLM produced a review, posted it to Discord, and an audit-trail
row landed in `playbook_runs`. Core MCP surfaces shipped in `minx-mcp` on
`main` at commit **`e5371a3`**. All harness-side artifacts (skills, smoke
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
  (`id=1, status=running`). The LLM provider (`nvidia/nemotron-3-super-120b-a12b:free`
  via openrouter) flaked through 3 retries; the model eventually produced
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
- Core MCP tools shipped (minx-mcp `main` @ `e5371a3`):
  `start_playbook_run`, `complete_playbook_run`, `log_playbook_run`,
  `playbook_history`, `playbook_reconcile_crashed`, `playbook://registry`,
  migration `019_playbook_runs.sql`.
- Cron wiring: 5 jobs in `~/.hermes/cron/jobs.json` (snapshotted here at
  `cron/jobs.snapshot.json`).
- 5 Minx playbook skills in `skills/minx/` with the Bulletproof Audit
  Contract applied.
- Smoke test: `scripts/smoke-playbooks.sh [job-name]`.
- `daily-review` validated end-to-end to Discord.

Not yet done:
- Smoke tests pending for `wiki-update`, `memory-review`, `goal-nudge`,
  `weekly-review`.
- LLM provider (`nvidia/nemotron-3-super-120b-a12b:free` on openrouter) is
  flaky. Consider pinning a paid model for playbook runs.
- Recommended: add a Hermes cron that calls
  `playbook_reconcile_crashed(stale_after_minutes=15)` every 15 minutes as a
  belt-and-suspenders sweep for any orphaned `status=running` rows.

## How to resume Slice 8 work

```
cd ~/Documents/minx-mcp && ./scripts/start_hermes_stack.sh
curl http://127.0.0.1:8001/mcp    # should respond; if not: tail /tmp/minx-stack.log
```

Then, from this repo:

```
~/Documents/minx-hermes/scripts/smoke-playbooks.sh --list        # list all 5 job IDs
~/Documents/minx-hermes/scripts/smoke-playbooks.sh <name>        # queue + tick one
~/Documents/minx-hermes/scripts/smoke-playbooks.sh --history     # recent playbook_runs
```

If a run orphans at `status=running` for more than 15 minutes, call
`playbook_reconcile_crashed` via an MCP client (or wait for the recommended
sweep cron once it's set up).

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
- minx-mcp handoff: `~/Documents/minx-mcp/HANDOFF.md`
