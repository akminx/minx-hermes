# minx-hermes

Personal version-controlled overlay for the Minx integration artifacts that
live inside the Hermes harness runtime (`~/.hermes/`). This repo captures the
bits of Minx that have to sit under the Hermes directory structure but that
don't belong in either of the upstream repos.

## Relationship to other repos

| Repo | Location | Remote | Role |
|---|---|---|---|
| **minx-mcp** | `~/Documents/minx-mcp` | `akminx/minx` | The Python MCP servers (minx-core, minx-finance, etc.). The server code that Hermes connects to. |
| **hermes-agent** | `~/.hermes/hermes-agent` | `NousResearch/hermes-agent` (upstream, read-only for us) | The Hermes harness itself. We do NOT push Minx-specific files here. |
| **minx-hermes** (this repo) | `~/Documents/minx-hermes` | local only | Minx playbook skills, smoke/ops scripts, cron snapshots, and handoff docs that must live under `~/.hermes/` at runtime. |

Separating this from `minx-mcp` keeps harness-framework concerns out of the
MCP server repo. Separating it from `hermes-agent` keeps our personal Minx
skills and scripts out of the NousResearch upstream (which we never push to).

## Layout

```
skills/minx/              Minx playbook skills, symlinked into ~/.hermes/skills/minx/
  daily-review/SKILL.md
  finance-import/SKILL.md
  investigate/SKILL.md
  wiki-update/SKILL.md
  memory-review/SKILL.md
  goal-nudge/SKILL.md
  weekly-review/SKILL.md
scripts/
  configure-finance-import-flow.sh  Bind #finances to the finance-import skill and sync the live symlink
  smoke-playbooks.sh      Queue a playbook and wait for terminal audit status
  smoke-investigations.sh Wrap a Hermes investigation command and wait for terminal audit status
  snapshot-cron-jobs.sh   Snapshot the 5 playbooks plus reconcile sweep from ~/.hermes/cron/jobs.json
cron/
  jobs.snapshot.json      Deterministic snapshot of the Minx cron jobs
docs/
  plans/                  Hermes infra plans
  slice8-handoff.md       Handoff for future Claude sessions
```

### Symlink contract

Each `skills/minx/<name>/` in this repo is symlinked from
`~/.hermes/skills/minx/<name>/`. Hermes loads skills from that path; the repo
owns the source of truth. Re-cloning on a new machine: clone this repo to
`~/Documents/minx-hermes`, then `ln -s ~/Documents/minx-hermes/skills/minx/<name> ~/.hermes/skills/minx/<name>` for each playbook.

## Common tasks

Refresh the cron snapshot after editing a playbook schedule:

```
./scripts/snapshot-cron-jobs.sh
git diff cron/jobs.snapshot.json
```

Install or re-apply the one-step Discord finance import flow:

```
./scripts/configure-finance-import-flow.sh
./scripts/configure-finance-import-flow.sh --check
```

Smoke-test a single playbook end-to-end:

```
./scripts/smoke-playbooks.sh --list            # see job IDs
./scripts/smoke-playbooks.sh daily-review
./scripts/smoke-playbooks.sh --history         # recent playbook_runs rows
```

`smoke-playbooks.sh` now waits for a new terminal `playbook_runs` row instead of
reporting success right after `hermes cron tick`. Override the wait budget with
`SMOKE_WAIT_SECONDS=<seconds>` if a playbook needs a longer window.

Smoke-test an investigation flow after triggering Hermes:

```
./scripts/smoke-investigations.sh --check-schema
./scripts/smoke-investigations.sh --history
./scripts/smoke-investigations.sh -- <command that triggers minx_investigate>
```

The investigation smoke script snapshots the current max `investigations.id`,
runs the supplied command without `eval`, then waits for a new terminal
`investigations` row (`succeeded`, `budget_exhausted`, `failed`, or
`cancelled`). Override the wait budget with `SMOKE_WAIT_SECONDS=<seconds>`.

Both scripts assume the Minx MCP stack is up (ports 8000-8003); start it with
`~/Documents/minx-mcp/scripts/start_hermes_stack.sh`.
