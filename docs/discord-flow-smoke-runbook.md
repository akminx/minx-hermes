# Discord Flow Smoke Runbook

Use this after Discord channel changes, Hermes upgrades, model swaps, or Minx MCP deploys.

## Preconditions

- Minx MCP stack is running:

```bash
~/Documents/minx-mcp/scripts/start_hermes_stack.sh
```

- Hermes config passes the Minx channel check:

```bash
python3 scripts/minx_flow_config.py --check --config ~/.hermes/config.yaml
```

- Expected Discord lanes exist and are mapped:

| Logical lane | Discord channel | Purpose |
|---|---|---|
| `ask_minx` | `#ask-minx` | General free-response questions and agent entrypoint |
| `finance` | `#finance` | Finance imports, summaries, and evidence review |
| `training` | `#training` | Training captures, summaries, and coaching |
| `capture` | `#capture` | Raw inbox material before routing |
| `reports` | `#reports` | Durable report outputs and retrospectives |
| `meals` | `#meals` | Meal captures and nutrition summaries |
| `minx_ops` | `#minx-ops` | Harness, deployment, and smoke-test operations |

## Smoke Checklist

Run these in order. Record the date, model, Hermes commit, and Minx MCP commit in `#minx-ops`.

1. Post a low-risk free-response prompt in `#ask-minx`.
   - Expected: Hermes responds in-channel without requiring a slash command.
   - Expected: no write action is taken unless explicitly requested.

2. Trigger a deterministic investigation:

```bash
./scripts/smoke-investigations.sh -- \
  python3 scripts/minx-investigate-once.py \
    --question "Summarize my current finance state" \
    --mode finance-summary
```

   - Expected: terminal `investigations` row with `succeeded` or `budget_exhausted`.
   - Expected: trajectory steps contain digests, not raw domain output.

3. Check recent investigation history:

```bash
./scripts/smoke-investigations.sh --history
```

   - Expected: the new row is visible, terminal, and has a sane `tool_call_count`.

4. Post lane-specific prompts:
   - `#finance`: ask for a read-only finance summary.
   - `#training`: ask for a read-only training recap.
   - `#meals`: ask for a read-only meal recap.
   - `#capture`: paste a short note and ask Minx where it belongs.
   - `#reports`: ask for the latest durable report pointers.
   - `#minx-ops`: ask for current stack health.

5. Confirm mutation guardrails.
   - Ask for a change that would alter data, such as creating or updating a memory.
   - Expected: Hermes asks for confirmation or redirects to an explicit command path.
   - Expected: no accidental domain write happens from a free-response lane.

## Pass Criteria

- All seven Discord lanes accept free-response Minx prompts.
- Read-only prompts stay read-only.
- Any mutation-like request requires explicit confirmation.
- Investigation rows always end terminally.
- Stored investigation trajectory contains hashes, small summaries, and citations only.

## If Something Fails

- Re-run `python3 scripts/minx_flow_config.py --check --config ~/.hermes/config.yaml`.
- Check whether the Minx MCP ports `8000-8003` are listening.
- Use `./scripts/smoke-investigations.sh --history` to find the newest terminal error.
- Keep failure notes in `#minx-ops` and link the relevant Obsidian note under `Minx/Ops/Smoke Tests`.
