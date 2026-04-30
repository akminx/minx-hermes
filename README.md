# minx-hermes

Personal version-controlled overlay for the Minx integration artifacts that
live inside the Hermes harness runtime (`~/.hermes/`). This repo holds the
Minx skills, the agentic investigation loop, and the production runner that
ties them to the Minx MCP servers.

> **Setting up the system?** Start at the canonical runbook in the minx-mcp
> repo: [`docs/RUNBOOK.md`](https://github.com/akminx/minx/blob/main/docs/RUNBOOK.md).
> This README only covers Hermes-overlay specifics.

## Repo layout

```
hermes_loop/                 Agentic investigation loop (budget caps, tool
                             allowlist, terminal-status guarantee)
  runtime.py                 Pluggable Policy / Dispatcher / CoreClient + run_investigation
  policies.py                OpenAIToolCallingPolicy (drives any OpenAI-shaped chat endpoint)
  tool_schemas.py            JSON Schemas for the read-only tool allowlist
  mcp_clients.py             MCPToolDispatcher + MCPCoreClient over streamablehttp_client
scripts/
  minx-investigate.py        Production runner — the actual command behind /minx-investigate
  minx-investigate-once.py   Deterministic mode-driven smoke runner (predates the agentic loop)
  smoke-investigations.sh    Wraps a Hermes investigation command and waits for terminal audit
  smoke-playbooks.sh         Queues a playbook and waits for terminal audit
  configure-finance-import-flow.sh  Bind #finances to the finance-import skill
  snapshot-cron-jobs.sh      Snapshot the Minx cron jobs
skills/minx/                 Minx playbook skills, symlinked into ~/.hermes/skills/minx/
  investigate/SKILL.md       Slice 9 — /minx-investigate
  plan/SKILL.md              Slice 9 — /minx-plan
  retro/SKILL.md             Slice 9 — /minx-retro
  onboard-entity/SKILL.md    Slice 9 — /minx-onboard-entity
  daily-review/, finance-import/, weekly-review/, ...
cron/jobs.snapshot.json      Deterministic snapshot of the Minx cron jobs
docs/
  hermes-investigation-runtime-contract.md  Slice 9 contract for any LLM-driven harness
  minx-investigation-tool-catalog.md        Read-only tool catalog
  archive/                                  Historical handoffs
tests/                       30 tests covering loop, policy, MCP clients, end-to-end
```

## Repo relationships

| Repo | Path | Remote | Role |
|---|---|---|---|
| **minx-mcp** | `~/Documents/minx-mcp` | `akminx/minx` | The four Python MCP servers + durable storage + schema |
| **minx-hermes** (this repo) | `~/Documents/minx-hermes` | `akminx/minx-hermes` | Harness overlay: skills, scripts, agentic loop, production runner |
| **hermes-agent** | `~/.hermes/hermes-agent` | `NousResearch/hermes-agent` (read-only for us) | The Hermes harness itself; we never push there |

## Symlink contract

Each `skills/minx/<name>/` in this repo is symlinked from
`~/.hermes/skills/minx/<name>/`. Hermes loads skills from that path; the repo
owns the source of truth. To re-clone on a new machine:

```bash
git clone git@github.com:akminx/minx-hermes.git ~/Documents/minx-hermes
for skill in ~/Documents/minx-hermes/skills/minx/*/; do
  ln -sfn "$skill" "$HOME/.hermes/skills/minx/$(basename "$skill")"
done
```

Latest Hermes derives slash commands from SKILL frontmatter names. The Slice 9
interactive surfaces are:

- `/minx-investigate` (alias `/minx_investigate`)
- `/minx-plan` (alias `/minx_plan`)
- `/minx-retro` (alias `/minx_retro`)
- `/minx-onboard-entity` (alias `/minx_onboard_entity`)

All four invoke `scripts/minx-investigate.py` with a different `--kind`.

## Common tasks

Run the test suite:

```bash
PYTHONPATH=$PWD uv run pytest tests/ -x -q
```

Drive an investigation against the running stack (assumes the four Minx MCP
servers are up on 8000–8003 — see the runbook):

```bash
OPENROUTER_API_KEY=sk-or-v1-... \
uv run scripts/minx-investigate.py --kind investigate \
  --question "what merchants did I spend the most at last month?" \
  --max-tool-calls 6 --wall-clock-s 60
```

Refresh the cron snapshot after editing a playbook schedule:

```bash
./scripts/snapshot-cron-jobs.sh
git diff cron/jobs.snapshot.json
```

Install or re-apply the one-step Discord finance import flow:

```bash
./scripts/configure-finance-import-flow.sh
./scripts/configure-finance-import-flow.sh --check
```

Smoke-test a single playbook end-to-end:

```bash
./scripts/smoke-playbooks.sh --list             # see job IDs
./scripts/smoke-playbooks.sh daily-review
./scripts/smoke-playbooks.sh --history          # recent playbook_runs rows
```

`smoke-playbooks.sh` waits for a new terminal `playbook_runs` row instead of
reporting success right after `hermes cron tick`. Override the wait budget
with `SMOKE_WAIT_SECONDS=<seconds>`.

Smoke-test an investigation flow:

```bash
./scripts/smoke-investigations.sh --check-schema
./scripts/smoke-investigations.sh --history
./scripts/smoke-investigations.sh -- <command that triggers minx_investigate>
```

The investigation smoke script snapshots the current max `investigations.id`,
runs the supplied command without `eval`, then waits for a new terminal row
(`succeeded`, `budget_exhausted`, `failed`, or `cancelled`).

Run the deterministic smoke runner (no LLM, fixed mode):

```bash
~/Documents/minx-mcp/scripts/start_hermes_stack.sh
./scripts/smoke-investigations.sh -- \
  python3 scripts/minx-investigate-once.py \
    --question "Summarize my current finance state" \
    --mode finance-summary
```

All smoke scripts assume the Minx MCP stack is up; start it with
`~/Documents/minx-mcp/scripts/start_hermes_stack.sh`.

## Where to go next

- End-to-end setup, troubleshooting, observability: [`minx-mcp/docs/RUNBOOK.md`](https://github.com/akminx/minx/blob/main/docs/RUNBOOK.md)
- Agent orientation (Claude / Codex / Hermes): [`minx-mcp/docs/AGENT_GUIDE.md`](https://github.com/akminx/minx/blob/main/docs/AGENT_GUIDE.md)
- Slice 9 contract: [`docs/hermes-investigation-runtime-contract.md`](docs/hermes-investigation-runtime-contract.md)
- Tool catalog: [`docs/minx-investigation-tool-catalog.md`](docs/minx-investigation-tool-catalog.md)
