---
name: wiki-update
description: Maintain the Minx wiki — refresh Obsidian wiki pages for active memories using the LLM Wiki pattern. Owns the wiki_update playbook.
version: 1.0.0
author: Minx
metadata:
  hermes:
    tags: [wiki, vault, memory, obsidian, playbook, minx]
    playbook_id: wiki_update
---

# Wiki Update (Minx)

Karpathy LLM Wiki pattern: the vault is the codebase, Minx is the programmer. Each cron tick, refresh wiki pages that are stale relative to current active memories + snapshot data.

Owns the `wiki_update` playbook. Runs after `daily_review` so today's snapshot is fresh.

## Playbook Audit Pattern

1. `run_id = minx_core.start_playbook_run(playbook_id='wiki_update', harness='hermes', trigger_type='cron', trigger_ref=<cron_name>)` — silent exit on CONFLICT.
2. Execute workflow.
3. Complete with counts in `result_json`: `{"pages_written": N, "pages_skipped": M}`.
4. On failure: complete with `status='failed'`, `error_message=str(exc)`, and surface to `#reports` only if N > 0 pages were partially written (partial failures matter; clean "nothing to do" failures stay silent).

## Data Sources
- `minx_core.get_daily_snapshot(review_date=<today>)`
- `minx_core.memory_list(status='active')`
- `minx_core.memory_events(memory_id, limit=10)` — only if needed to check "significant changes since last wiki update"
- `wiki-templates://entity`, `wiki-templates://pattern`, `wiki-templates://goal` — MCP resources, scaffolds with `${llm_body}` regions

## Workflow

### 1) Fetch active memories + snapshot
- `memory_list(status='active')` → list of active memories
- `get_daily_snapshot(review_date=<today>)` → context

### 2) Decide which pages to refresh
For each active memory:
- Compute target vault path based on `memory_type` and `subject`:
  - `entity_fact` → `Minx/Entities/<subject>.md`
  - `pattern` → `Minx/Patterns/<subject>.md`
  - `preference`, `constraint` → do NOT generate a wiki page (these stay in SQLite only)
- Consider "significant changes" = memory `updated_at` newer than the existing page's frontmatter `last_wiki_update`, or page does not exist.
- Bound work: max 10 page refreshes per run. If more are stale, pick the 10 oldest and defer the rest to tomorrow's run.

### 3) For each page to refresh
a. Fetch the correct scaffold via `wiki-templates://{entity|pattern|goal}`.
b. Read the existing page (if any) via `minx_core.vault_read_note` or fall through if not present.
c. Build LLM context:
   - The memory's structured payload (from SQLite)
   - Recent insights related to this memory's subject (from `get_insight_history`)
   - Existing page body (for incremental updates)
   - Candidate wikilinks: other active memories in the same scope
d. LLM fills `${llm_body}` regions ONLY. Do not modify frontmatter keys or section headings.
e. Ensure frontmatter has:
   - `type: minx-wiki`
   - `wiki_type: entity|pattern|goal`
   - `memory_id: <id>` (link back to SQLite source)
   - `last_wiki_update: <today_iso>`
f. Write:
   - New page: `minx_core.persist_note(relative_path, content, overwrite=false)`
   - Existing page: `minx_core.vault_replace_section(relative_path, section_heading, new_body)` — update by section, not full rewrite, so user edits to other sections survive.

### 4) Do NOT trigger vault_reconcile_memories
Per Slice 8 spec §7, the reconciler holds the writer lock. Let the nightly reconcile sweep catch changes instead.

### 5) Log and complete
- Count `pages_written`, `pages_skipped_unchanged`, `pages_skipped_non_wiki_type`.
- Complete playbook run.
- Only post to `#reports` if `pages_written > 0`: short line with count + 2–3 page links. Silent otherwise.

## Rules
1. **Frontmatter contract**: every page MUST have `type: minx-wiki` and `wiki_type: entity|pattern|goal`. Memory-reconciler ignores these. Violation collides with Slice 6.
2. **Bounded work**: max 10 pages per run. Defer rest.
3. **Scaffolds are canonical structure**: LLM fills body regions, never invents frontmatter or section headings.
4. **No synchronous reconciler calls** — let nightly sweep handle drift.
5. **Preserve user edits**: use `vault_replace_section` for existing pages, not full-file rewrite.
6. **Path safety**: only write under `Minx/`. `persist_note` enforces this.
7. **preference / constraint memory types**: SQL-only, no wiki page generated.

## Failure Modes
- CONFLICT on `start_playbook_run`: silent exit.
- `wiki-templates://` fetch fails: abort run, `status='failed'`, `error_message`.
- Individual page write fails: log, increment failure counter, continue with next page. Complete playbook with `status='succeeded'` if at least one page written; else `status='failed'`.
- LLM produces malformed fill: skip that page, log warning, continue.

## Bulletproof Audit Contract

These invariants are non-negotiable. A `running` row that never completes blocks the next cron tick via the unique-in-flight index until `playbook_reconcile_crashed` catches it.

1. **CONFLICT on `start_playbook_run` = hard stop.** Do not continue the workflow, do not read the vault, do not write notes, do not post to any channel, do not call any other tool. Emit `[SILENT]` immediately. Another worker already has the tick.
2. **If `start_playbook_run` returned a `run_id`, you MUST call `complete_playbook_run(run_id, status=...)` before your final response.** Every exit path ends with a completion call:
   - Normal success → `status='succeeded'`
   - Skip branch (empty day, empty backlog, nothing to do) → `status='skipped'`
   - Any tool error or malformed LLM output → `status='failed'`, `error_message=str(exc)`
3. **Never emit `[SILENT]` or any final response with an open `run_id`.** If you hit an unrecoverable error, first call `complete_playbook_run(run_id, status='failed', error_message='...')`, then emit your terminal response.
4. Uncatchable crashes (Hermes itself dies, LLM provider exhausts retries before you regain control) are swept by `playbook_reconcile_crashed` on a separate cron. Do not rely on it — always close your own run.
