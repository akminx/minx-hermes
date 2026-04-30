# minx-hermes

`minx-hermes` is the harness-side overlay for Minx: skills, smoke scripts,
cron snapshots, and the budgeted investigation runner that lets Hermes talk to
the Minx MCP servers without mixing harness concerns into the backend repo.

The companion backend repo is [akminx/minx](https://github.com/akminx/minx).
`minx` owns durable facts and deterministic logic. `minx-hermes` owns how an
agent chooses tools, asks the model for the next step, enforces budgets, and
turns structured facts into user-facing prose.

## Relationship to other repos

| Repo | Location | Remote | Role |
|---|---|---|---|
| **minx** | your `minx` checkout | `akminx/minx` | The Python MCP servers (minx-core, minx-finance, etc.). The server code that Hermes connects to. |
| **hermes-agent** | `~/.hermes/hermes-agent` | `NousResearch/hermes-agent` (upstream, read-only for us) | The Hermes harness itself. We do NOT push Minx-specific files here. |
| **minx-hermes** (this repo) | your `minx-hermes` checkout | `akminx/minx-hermes` | Minx playbook skills, smoke/ops scripts, cron snapshots, investigation runner, and operational docs. |

Separating this from `minx` keeps harness-framework concerns out of the
MCP server repo. Separating it from `hermes-agent` keeps our personal Minx
skills and scripts out of the NousResearch upstream (which we never push to).

## Layout

```
skills/minx/              Minx playbook skills, symlinked into ~/.hermes/skills/minx/
  daily-review/SKILL.md
  finance-import/SKILL.md
  investigate/SKILL.md
  plan/SKILL.md
  retro/SKILL.md
  onboard-entity/SKILL.md
  wiki-update/SKILL.md
  memory-review/SKILL.md
  goal-nudge/SKILL.md
  weekly-review/SKILL.md
scripts/
  configure-finance-import-flow.sh  Bind finance lane import flow and sync the live symlink
  smoke-playbooks.sh      Queue a playbook and wait for terminal audit status
  smoke-investigations.sh Wrap a Hermes investigation command and wait for terminal audit status
  snapshot-cron-jobs.sh   Snapshot the 5 playbooks plus reconcile sweep from ~/.hermes/cron/jobs.json
cron/
  jobs.snapshot.json      Deterministic snapshot of the Minx cron jobs
docs/
  plans/                  Hermes infra plans
  discord-flow-smoke-runbook.md  Discord lane and investigation smoke checklist
  slice8-handoff.md       Historical Slice 8 handoff
```

### Symlink contract

Each `skills/minx/<name>/` in this repo is symlinked from
`~/.hermes/skills/minx/<name>/`. Hermes loads skills from that path; the repo
owns the source of truth. Re-cloning on a new machine: clone this repo, then
symlink each `skills/minx/<name>` directory into `~/.hermes/skills/minx/<name>`.

Latest Hermes derives slash commands from SKILL frontmatter names. The Slice 9
interactive surfaces are:

- `/minx-investigate` with `/minx_investigate` alias
- `/minx-plan` with `/minx_plan` alias
- `/minx-retro` with `/minx_retro` alias
- `/minx-onboard-entity` with `/minx_onboard_entity` alias

## Common tasks

Start the Minx MCP stack from the backend checkout:

```
/path/to/minx/scripts/start_hermes_stack.sh
```

For local development, install the backend checkout into this environment or
point the runner at it:

```
uv pip install -e /path/to/minx
# or
export MINX_MCP_CHECKOUT=/path/to/minx
```

Run a live investigation with the recommended example model:

```
export OPENROUTER_API_KEY=sk-or-v1-...
export MINX_INVESTIGATION_MODEL=google/gemini-2.5-flash
export MINX_INVESTIGATION_BASE_URL=https://openrouter.ai/api/v1
uv run scripts/minx-investigate.py --kind investigate \
  --question "what changed in my spending last month?" \
  --max-tool-calls 8 --wall-clock-s 90
```

The model id is configuration. The runtime works through an OpenAI-compatible
endpoint and should be smoke-tested whenever the model changes.
Use `MINX_CORE_URL`, `MINX_FINANCE_URL`, `MINX_MEALS_URL`, and
`MINX_TRAINING_URL` to point the runner at non-default MCP endpoints. Smoke
scripts read `MINX_DB` when your SQLite database is not at
`~/.minx/data/minx.db`.

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

Smoke-test a deterministic investigation:

```
/path/to/minx/scripts/start_hermes_stack.sh
./scripts/smoke-investigations.sh -- \
  python3 scripts/minx-investigate-once.py \
    --question "Summarize my current finance state" \
    --mode finance-summary
```

Both scripts assume the Minx MCP stack is up (ports 8000-8003); start it with
`/path/to/minx/scripts/start_hermes_stack.sh`.

After Discord channel, Hermes, or model changes, run the full lane checklist in
`docs/discord-flow-smoke-runbook.md`.
