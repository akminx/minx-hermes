# Hermes Investigation Runtime Contract

The live Hermes runtime must expose Slice 9 agentic Minx surfaces with the same lifecycle used by `scripts/minx-investigate-once.py`.

Surfaces:

- `minx_investigate(question, context?)` / `/minx-investigate`: `kind="investigate"`
- `minx_plan(request, context?)` / `/minx-plan`: `kind="plan"`
- `minx_retro(request, context?)` / `/minx-retro`: `kind="retro"`
- `minx_onboard_entity(entity, context?)` / `/minx-onboard-entity`: `kind="onboard"` (Core's enum is `{investigate, plan, retro, onboard, other}`; entity-specific context goes in `context_json`)

Required behavior:

1. Call `minx_core.start_investigation(kind=<surface kind>, harness="hermes", question=..., context_json=...)` before any domain tool call.
2. Choose read tools from `docs/minx-investigation-tool-catalog.md`.
3. For each tool call, hash canonical JSON arguments and full structured result with lowercase SHA-256 hex.
4. Call `minx_core.append_investigation_step` with only digests, tool name, latency, and small summary slots.
5. Stop at 12 domain tool calls or 120 seconds unless the user explicitly gives a smaller budget.
6. Complete terminally with `status="succeeded"`, `status="failed"`, `status="cancelled"`, or `status="budget_exhausted"`.
7. Include typed `citation_refs` for durable memories, prior investigations, vault paths, and ephemeral tool result digests.
8. Never persist raw domain tool outputs, transcripts, rows, or messages in Core investigation fields.

The deterministic runner is the executable reference for lifecycle and digest behavior. `hermes_loop/runtime.py` is the executable reference for the agentic shape with hard budget enforcement, a programmatic tool allowlist, and a terminal-status guarantee. The real LLM loop may choose tools dynamically, but it must preserve this storage contract and budget discipline.

Hard caps live here (the harness), not in Core. Core enforces a soft sanity cap (`MINX_MAX_TOOL_CALLS_PER_INVESTIGATION`, default 1000) that exists only as defense in depth against a buggy harness; production budgets must be smaller and enforced before reaching Core.
