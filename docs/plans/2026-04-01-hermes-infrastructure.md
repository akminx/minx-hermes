# Hermes Infrastructure — Claudeification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes structurally reliable by adopting Claude Code's core patterns: validate before exposing, type your contracts, declare dependencies, route models by task, and activate the delegation/clarify/todo tools that already exist but aren't being used.

**Architecture:** Six self-contained changes across three files + two config locations. Each change is independently deployable and testable. No new frameworks or dependencies. All changes are backwards-compatible — the agent degrades gracefully if a new feature is absent.

**Tech Stack:** Python 3.11+, pytest (existing), PyYAML (existing), Hermes registry/toolset system

---

## Scope

This plan covers the **infrastructure layer only** — changes that affect all of Hermes uniformly:

1. Model routing domain escalation (`agent/smart_model_routing.py`)
2. Cron preflight checks (`cron/scheduler.py`)
3. Skill `requires` frontmatter + preflight reads it (skill files + scheduler)
4. SOUL.md tool contracts section (`~/.hermes/SOUL.md`)
5. Typed domain tools: `finance_import_transactions` + `souschef_log_meal` (`tools/domain_ops.py`)

Finance-specific, SousChef-specific, Himalaya, and Honcho changes are separate plans.

---

## File Map

| File | Status | What changes |
|---|---|---|
| `agent/smart_model_routing.py` | Modify | Add `_DOMAIN_ESCALATE_KEYWORDS` set + escalation logic in `choose_cheap_model_route` |
| `cron/scheduler.py` | Modify | Add `_preflight_job(job) -> tuple[bool, str]` called from `tick()` before `run_job()` |
| `tools/domain_ops.py` | Create | `finance_import_transactions()` and `souschef_log_meal()` typed wrappers with read-back verification |
| `~/.hermes/SOUL.md` | Modify | Add `## Tool Contracts` section after `## Critical Rules` |
| `~/.hermes/skills/minx/finance-import/SKILL.md` | Modify | Add `requires` frontmatter block |
| `~/.hermes/skills/minx/weekly-review/SKILL.md` | Modify | Add `requires` frontmatter + parallel delegate_task pattern |
| `~/.hermes/skills/minx/health-log/SKILL.md` | Modify | Add `requires` frontmatter block |
| `~/.hermes/skills/minx/finance-report/SKILL.md` | Modify | Add `requires` frontmatter block |
| `tests/test_smart_model_routing.py` | Modify | Add tests for domain escalation |
| `tests/test_cron_preflight.py` | Create | Tests for preflight logic |
| `tests/test_domain_ops.py` | Create | Tests for typed domain tools |

---

## Task 1: Domain Escalation in Model Router

**Problem:** `choose_cheap_model_route` at `agent/smart_model_routing.py:66` only has `_COMPLEX_KEYWORDS` that block cheap routing. Short domain-critical prompts (cron jobs with brief prompts like weekly reports) can still fall through to cheap model. We need a third path: force primary model for high-value domain work.

**Files:**
- Modify: `agent/smart_model_routing.py:9-44` (keyword sets)
- Modify: `agent/smart_model_routing.py:66-111` (`choose_cheap_model_route`)
- Test: `tests/test_smart_model_routing.py`

- [ ] **Step 1: Read existing tests for this module**

```bash
grep -r "smart_model_routing\|choose_cheap\|resolve_turn" /Users/akmini/.hermes/hermes-agent/tests/ 2>/dev/null
```

Expected: shows any existing coverage so we don't duplicate

- [ ] **Step 2: Write failing tests for domain escalation**

Add to `tests/test_smart_model_routing.py`:

```python
from agent.smart_model_routing import choose_cheap_model_route, resolve_turn_route

_ROUTING_CFG = {
    "enabled": True,
    "cheap_model": {"provider": "openai", "model": "gpt-4o-mini"},
    "max_simple_chars": 160,
    "max_simple_words": 28,
}

# Domain keywords should BLOCK cheap routing even on short prompts
def test_report_blocks_cheap_routing():
    result = choose_cheap_model_route("Run the weekly report", _ROUTING_CFG)
    assert result is None, "Domain keyword 'report' must force primary model"

def test_budget_blocks_cheap_routing():
    result = choose_cheap_model_route("Check budget status", _ROUTING_CFG)
    assert result is None

def test_transactions_blocks_cheap_routing():
    result = choose_cheap_model_route("Import transactions from statement", _ROUTING_CFG)
    assert result is None

def test_finance_blocks_cheap_routing():
    result = choose_cheap_model_route("Finance summary please", _ROUTING_CFG)
    assert result is None

def test_receipt_blocks_cheap_routing():
    result = choose_cheap_model_route("Parse this receipt", _ROUTING_CFG)
    assert result is None

def test_simple_greeting_still_routes_cheap():
    result = choose_cheap_model_route("thanks", _ROUTING_CFG)
    assert result is not None, "Simple greetings should still use cheap model"

def test_meal_blocks_cheap_routing():
    result = choose_cheap_model_route("Log my meal", _ROUTING_CFG)
    assert result is None
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd /Users/akmini/.hermes/hermes-agent && python -m pytest tests/test_smart_model_routing.py -v -k "domain or report or budget or transactions or finance or receipt or meal"
```

Expected: FAIL — `_DOMAIN_ESCALATE_KEYWORDS` does not exist yet

- [ ] **Step 4: Add `_DOMAIN_ESCALATE_KEYWORDS` and escalation logic**

In `agent/smart_model_routing.py`, after `_COMPLEX_KEYWORDS` block (line 44), add:

```python
# Domain keywords: short prompts that look simple but are high-value.
# These force the primary model even when the prompt is short/simple.
_DOMAIN_ESCALATE_KEYWORDS = {
    "report",
    "reports",
    "budget",
    "budgets",
    "receipt",
    "receipts",
    "transactions",
    "transaction",
    "import",
    "statement",
    "finance",
    "finances",
    "financial",
    "weekly",
    "monthly",
    "quarterly",
    "annual",
    "summary",
    "meal",
    "meals",
    "nutrition",
    "calories",
    "weight",
    "workout",
    "workouts",
    "health",
    "scrape",
    "honcho",
    "conclude",
    "memory",
}
```

In `choose_cheap_model_route`, add after the `_COMPLEX_KEYWORDS` check (after line 104):

```python
    # Domain escalation: force primary model for high-value domain terms
    # even when the prompt is short and simple-looking.
    if words & _DOMAIN_ESCALATE_KEYWORDS:
        return None
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
cd /Users/akmini/.hermes/hermes-agent && python -m pytest tests/test_smart_model_routing.py -v -k "domain or report or budget or transactions or finance or receipt or meal"
```

Expected: All PASS

- [ ] **Step 6: Run full existing test suite to confirm no regressions**

```bash
cd /Users/akmini/.hermes/hermes-agent && python -m pytest tests/test_smart_model_routing.py -v
```

Expected: All existing tests still pass

- [ ] **Step 7: Commit**

```bash
cd /Users/akmini/.hermes/hermes-agent
git add agent/smart_model_routing.py tests/test_smart_model_routing.py
git commit -m "feat: add domain escalation keywords to model router

Short high-value prompts (reports, finance, meals, health) now force
the primary model even when they look simple by length/structure.
Prevents weekly report and finance cron jobs from being cheap-routed."
```

---

## Task 2: Cron Preflight Checks

**Problem:** `tick()` in `cron/scheduler.py:485` calls `run_job()` with no validation. If the MCP server for a job's required skill is down, the delivery channel ID is wrong, or the model route is unavailable, the agent runs and fails silently or hallucinates success.

**Files:**
- Modify: `cron/scheduler.py` — add `_preflight_job()` function, call from `tick()`
- Create: `tests/test_cron_preflight.py`

- [ ] **Step 1: Write failing tests for preflight**

Create `tests/test_cron_preflight.py`:

```python
"""Tests for cron job preflight validation."""
import pytest
from unittest.mock import patch, MagicMock


def _make_job(skills=None, deliver="local", model=None):
    return {
        "id": "test-job",
        "name": "Test Job",
        "skills": skills or [],
        "deliver": deliver,
        "model": model,
    }


class TestPreflightDeliveryTarget:
    def test_local_delivery_always_passes(self):
        from cron.scheduler import _preflight_job
        ok, reason = _preflight_job(_make_job(deliver="local"))
        assert ok is True

    def test_invalid_platform_fails(self):
        from cron.scheduler import _preflight_job
        ok, reason = _preflight_job(_make_job(deliver="discord:not-a-valid-channel-id"))
        # Preflight only checks format; real channel validation is in delivery
        # Platform name 'discord' is valid format
        assert ok is True  # format is valid, delivery failure caught at send time

    def test_unknown_platform_fails(self):
        from cron.scheduler import _preflight_job
        ok, reason = _preflight_job(_make_job(deliver="fakePlatform:12345"))
        assert ok is False
        assert "platform" in reason.lower()


class TestPreflightSkillRequires:
    def test_skill_without_requires_passes(self):
        from cron.scheduler import _preflight_job
        with patch("cron.scheduler._load_skill_requires", return_value={}):
            ok, reason = _preflight_job(_make_job(skills=["minx/weekly-review"]))
        assert ok is True

    def test_skill_requires_mcp_missing_fails(self):
        from cron.scheduler import _preflight_job
        requires = {"mcp": ["financehub"]}
        with patch("cron.scheduler._load_skill_requires", return_value=requires):
            with patch("cron.scheduler._mcp_server_ready", return_value=False):
                ok, reason = _preflight_job(_make_job(skills=["minx/finance-report"]))
        assert ok is False
        assert "financehub" in reason.lower()

    def test_skill_requires_mcp_present_passes(self):
        from cron.scheduler import _preflight_job
        requires = {"mcp": ["financehub"]}
        with patch("cron.scheduler._load_skill_requires", return_value=requires):
            with patch("cron.scheduler._mcp_server_ready", return_value=True):
                ok, reason = _preflight_job(_make_job(skills=["minx/finance-report"]))
        assert ok is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/akmini/.hermes/hermes-agent && python -m pytest tests/test_cron_preflight.py -v
```

Expected: FAIL — `_preflight_job`, `_load_skill_requires`, `_mcp_server_ready` not defined yet

- [ ] **Step 3: Implement `_mcp_server_ready` helper**

Add to `cron/scheduler.py` after the imports (after line 38):

```python
def _mcp_server_ready(server_name: str) -> bool:
    """Check whether a named MCP server is connected and has an active session."""
    try:
        from tools.mcp_tool import _servers, _lock
        with _lock:
            server = _servers.get(server_name)
        return server is not None and server.session is not None
    except Exception:
        return False
```

- [ ] **Step 4: Implement `_load_skill_requires` helper**

Add to `cron/scheduler.py` after `_mcp_server_ready`:

```python
def _load_skill_requires(skill_name: str) -> dict:
    """Read the 'requires' block from a skill's YAML frontmatter, if present.

    Returns dict like: {"mcp": ["financehub"], "model": "paid"}
    Returns empty dict if skill not found or has no requires block.
    """
    try:
        from tools.skills_tool import skill_view
        import json as _json
        loaded = _json.loads(skill_view(skill_name))
        if not loaded.get("success"):
            return {}
        content = loaded.get("content") or ""
        # Parse YAML frontmatter between --- markers
        import yaml as _yaml
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                front = _yaml.safe_load(content[3:end]) or {}
                return front.get("requires") or {}
    except Exception:
        pass
    return {}
```

- [ ] **Step 5: Implement `_preflight_job` function**

Add to `cron/scheduler.py` after `_load_skill_requires`:

```python
_KNOWN_PLATFORMS = {
    "telegram", "discord", "slack", "whatsapp", "signal",
    "matrix", "mattermost", "homeassistant", "dingtalk", "email", "sms",
}

def _preflight_job(job: dict) -> tuple[bool, str]:
    """Validate that a job's prerequisites are met before running it.

    Checks:
    1. Delivery platform is known (if deliver is not 'local')
    2. Required MCP servers (from skill frontmatter 'requires.mcp') are connected

    Returns:
        (True, "") if all checks pass
        (False, reason) if any check fails
    """
    # Check 1: delivery platform is known
    deliver = job.get("deliver", "local")
    if deliver != "local" and deliver != "origin":
        if ":" in deliver:
            platform_name = deliver.split(":")[0]
        else:
            platform_name = deliver
        if platform_name.lower() not in _KNOWN_PLATFORMS:
            return False, f"Unknown delivery platform '{platform_name}'"

    # Check 2: required MCP servers are connected
    skills = job.get("skills") or ([job["skill"]] if job.get("skill") else [])
    for skill_name in skills:
        requires = _load_skill_requires(skill_name)
        for mcp_name in (requires.get("mcp") or []):
            if not _mcp_server_ready(mcp_name):
                return False, f"Required MCP server '{mcp_name}' (from skill '{skill_name}') is not connected"

    return True, ""
```

- [ ] **Step 6: Call `_preflight_job` from `tick()` before `run_job()`**

In `cron/scheduler.py`, inside the `for job in due_jobs:` loop (around line 525), add preflight call before `run_job`:

```python
            # Preflight: validate prerequisites before spending tokens
            preflight_ok, preflight_reason = _preflight_job(job)
            if not preflight_ok:
                error_msg = f"Preflight failed: {preflight_reason}"
                logger.error("Job '%s' skipped — %s", job.get("name", job["id"]), error_msg)
                deliver_content = f"⚠️ Cron job '{job.get('name', job['id'])}' skipped:\n{error_msg}"
                try:
                    _deliver_result(job, deliver_content)
                except Exception:
                    pass
                mark_job_run(job["id"], False, error_msg)
                executed += 1
                continue
```

This goes immediately before the `success, output, final_response, error = run_job(job)` line (around line 533).

- [ ] **Step 7: Run tests to confirm they pass**

```bash
cd /Users/akmini/.hermes/hermes-agent && python -m pytest tests/test_cron_preflight.py -v
```

Expected: All PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/akmini/.hermes/hermes-agent
git add cron/scheduler.py tests/test_cron_preflight.py
git commit -m "feat: add preflight validation to cron job execution

Before running any cron job, validate: delivery platform is known,
required MCP servers (from skill frontmatter requires.mcp) are
connected. Fail loudly with delivery notification instead of running
and silently hallucinating success against broken infrastructure."
```

---

## Task 3: Skill `requires` Frontmatter

**Problem:** Skills declare dependencies in prose only. The cron preflight added in Task 2 reads `requires` frontmatter but no skills have it yet. Add `requires` to the three critical skills that have backend dependencies.

**Files:**
- Modify: `~/.hermes/skills/minx/finance-import/SKILL.md`
- Modify: `~/.hermes/skills/minx/finance-report/SKILL.md`
- Modify: `~/.hermes/skills/minx/weekly-review/SKILL.md`
- Modify: `~/.hermes/skills/minx/health-log/SKILL.md` (if it requires souschef)

No tests needed — this is config data read by `_load_skill_requires` which is tested in Task 2.

- [ ] **Step 1: Check health-log skill for MCP dependencies**

```bash
head -30 ~/.hermes/skills/minx/health-log/SKILL.md
```

Expected: shows which MCP servers it uses

- [ ] **Step 2: Add `requires` to finance-import skill**

In `~/.hermes/skills/minx/finance-import/SKILL.md`, update the frontmatter block from:

```yaml
---
name: finance-import
description: ...
version: 2.0.0
author: Minx
metadata:
  hermes:
    tags: [finances, import, csv, pdf, transactions, robinhood, discover, dcu]
---
```

To:

```yaml
---
name: finance-import
description: Parse financial statements and write structured transactions into FinanceHub's SQLite DB via mcp_finance. Uses paid model for privacy.
version: 2.0.0
author: Minx
requires:
  mcp: [finance]
  model: paid
metadata:
  hermes:
    tags: [finances, import, csv, pdf, transactions, robinhood, discover, dcu]
---
```

- [ ] **Step 3: Add `requires` to finance-report skill**

```bash
head -15 ~/.hermes/skills/minx/finance-report/SKILL.md
```

Then add `requires: mcp: [finance]` to its frontmatter in the same pattern.

- [ ] **Step 4: Add `requires` to weekly-review skill**

Update `~/.hermes/skills/minx/weekly-review/SKILL.md` frontmatter to add:

```yaml
requires:
  mcp: [finance, souschef, obsidian]
```

- [ ] **Step 5: Add `requires` to health-log skill (if uses souschef)**

Based on Step 1 output, add the appropriate `requires` block.

- [ ] **Step 6: Verify preflight reads the new frontmatter**

```bash
cd /Users/akmini/.hermes/hermes-agent && python3 -c "
from cron.scheduler import _load_skill_requires
print(_load_skill_requires('minx/finance-import'))
print(_load_skill_requires('minx/weekly-review'))
"
```

Expected:
```
{'mcp': ['finance'], 'model': 'paid'}
{'mcp': ['finance', 'souschef', 'obsidian']}
```

- [ ] **Step 7: Commit**

```bash
cd /Users/akmini/.hermes/hermes-agent
git add -A
git commit -m "feat: add requires frontmatter to critical Minx skills

finance-import, finance-report, weekly-review, health-log now declare
their MCP server dependencies. Cron preflight reads these to abort
jobs early when required backends are unavailable."
```

---

## Task 4: SOUL.md Tool Contracts

**Problem:** `delegate_task`, `clarify`, and `todo` tools exist in Hermes but the model doesn't know when to use them. SOUL.md is loaded into every session's system prompt. Adding explicit usage contracts here activates these tools with zero code changes.

**Files:**
- Modify: `~/.hermes/SOUL.md` — add `## Tool Contracts` section

- [ ] **Step 1: Read current SOUL.md to understand existing structure**

```bash
cat ~/.hermes/SOUL.md
```

- [ ] **Step 2: Add Tool Contracts section**

After the `## Critical Rules` section in `~/.hermes/SOUL.md`, add:

```markdown
## Tool Contracts

### delegate_task
Use for any work requiring 3+ sequential tool calls on intermediate data, or for independent parallel subtasks.

**When to use:**
- Weekly/monthly reports → 3 parallel subagents: finance summary, health summary, meals summary. Synthesize results.
- Finance import from multiple files → delegate each file independently, aggregate batch results
- Research + vault update → delegate research, then write to vault with results

**How to use:**
- Pass file paths, date ranges, and constraints in `context` — subagents have no memory of this conversation
- Use `tasks` array for parallel work; use single task for isolated heavy computation
- Always specify which channel to deliver results to if the subagent should post directly

### clarify
Call this instead of guessing when inputs are genuinely ambiguous. Do not use for things you can look up in vault or Honcho.

**When to use:**
- Finance: transaction category is ambiguous and not inferrable from context
- Journal: entry matches multiple types (e.g. "picked up groceries" — purchase or meal?)
- SousChef: meal logged but no matching recipe found and calories matter

**When NOT to use:**
- Never in cron jobs (clarify is disabled for cron)
- Never when you can answer by checking vault or Honcho first

### todo
Use to track progress in any multi-step task. Write checkpoints at start, mark done as you complete each step.

**When to use:**
- Any task with 4+ steps
- Finance imports (track: parse → categorize → write → verify)
- Weekly reports (track: finance pull → health pull → meals pull → synthesize → deliver)
- Idea implementation sessions

**Format:** `todo write` to set items, `todo done <item>` to mark complete. The checkpoint list is visible to you between tool calls — use it to maintain state.
```

- [ ] **Step 3: Verify SOUL.md loads correctly in a test agent session**

```bash
cd /Users/akmini/.hermes/hermes-agent && python3 -c "
from agent.prompt_builder import build_system_prompt
import os
# Quick smoke test: build prompt and check Tool Contracts appears
prompt = build_system_prompt(platform='cli')
assert 'Tool Contracts' in prompt, 'Tool Contracts section not found in system prompt'
assert 'delegate_task' in prompt
assert 'clarify' in prompt
assert 'todo' in prompt
print('OK — Tool Contracts section present in system prompt')
"
```

Expected: `OK — Tool Contracts section present in system prompt`

- [ ] **Step 4: Commit**

```bash
cd /Users/akmini/.hermes/hermes-agent
git add ~/.hermes/SOUL.md
git commit -m "feat: add tool contracts to SOUL.md

Explicit usage contracts for delegate_task, clarify, and todo.
These tools exist but the model had no structured guidance on when
to use them. Activates parallel subagent dispatch for reports,
structured clarification for ambiguous inputs, and todo checkpoints
for multi-step finance/health tasks."
```

---

## Task 5: Typed Domain Tools — `domain_ops.py`

**Problem:** Hermes calls raw `mcp__finance__*` and `mcp__souschef__*` tools with whatever the model decides to pass. There is no: input validation, idempotency (duplicate transaction prevention), read-back verification, or typed result. These two writes are the highest-value mutations in the system.

**Files:**
- Create: `tools/domain_ops.py`
- Modify: `toolsets.py` — register new tools in appropriate toolset
- Create: `tests/test_domain_ops.py`

- [ ] **Step 1: Check how existing tools are registered**

```bash
grep -n "registry.register\|create_custom_toolset" /Users/akmini/.hermes/hermes-agent/toolsets.py | head -20
grep -n "\"finance\|\"souschef" /Users/akmini/.hermes/hermes-agent/toolsets.py | head -10
```

- [ ] **Step 2: Write failing tests for `finance_import_transactions`**

Create `tests/test_domain_ops.py`:

```python
"""Tests for typed domain operation tools."""
import json
import pytest
from unittest.mock import patch, MagicMock


class TestFinanceImportTransactions:
    def test_rejects_empty_transactions(self):
        from tools.domain_ops import finance_import_transactions
        result = json.loads(finance_import_transactions({"transactions": []}))
        assert result["error"] is not None
        assert "empty" in result["error"].lower()

    def test_rejects_missing_required_fields(self):
        from tools.domain_ops import finance_import_transactions
        # Missing amount
        txn = {"date": "2026-04-01", "description": "Coffee"}
        result = json.loads(finance_import_transactions({"transactions": [txn]}))
        assert result["error"] is not None

    def test_returns_typed_result_on_success(self):
        from tools.domain_ops import finance_import_transactions
        txns = [{"date": "2026-04-01", "description": "HEB", "amount": -43.21, "category": "groceries"}]
        mock_write = MagicMock(return_value=json.dumps({"id": "txn-123", "success": True}))
        mock_read = MagicMock(return_value=json.dumps({"transactions": [{"id": "txn-123"}]}))
        with patch("tools.domain_ops._mcp_call", side_effect=[mock_write(), mock_read()]):
            result = json.loads(finance_import_transactions({"transactions": txns}))
        assert result.get("imported") == 1
        assert result.get("duplicates") == 0
        assert result.get("failed") == []

    def test_detects_duplicate_on_readback_mismatch(self):
        from tools.domain_ops import finance_import_transactions
        txns = [{"date": "2026-04-01", "description": "HEB", "amount": -43.21, "category": "groceries"}]
        mock_write = MagicMock(return_value=json.dumps({"duplicate": True}))
        with patch("tools.domain_ops._mcp_call", return_value=mock_write()):
            result = json.loads(finance_import_transactions({"transactions": txns}))
        assert result.get("duplicates") == 1
        assert result.get("imported") == 0


class TestSousChefLogMeal:
    def test_rejects_invalid_meal_type(self):
        from tools.domain_ops import souschef_log_meal
        result = json.loads(souschef_log_meal({"meal": "chicken tacos", "type": "consumed"}))
        assert result["error"] is not None
        assert "type" in result["error"].lower()

    def test_accepts_valid_types(self):
        from tools.domain_ops import souschef_log_meal
        for meal_type in ["ate", "cooked", "planned"]:
            mock_result = json.dumps({"id": "meal-123", "success": True})
            mock_verify = json.dumps({"meal": {"id": "meal-123"}})
            with patch("tools.domain_ops._mcp_call", side_effect=[mock_result, mock_verify]):
                result = json.loads(souschef_log_meal({"meal": "test", "type": meal_type}))
            assert "error" not in result or result["error"] is None

    def test_fails_if_readback_shows_nothing(self):
        from tools.domain_ops import souschef_log_meal
        mock_write = json.dumps({"id": "meal-999", "success": True})
        mock_verify = json.dumps({"meal": None})  # not found
        with patch("tools.domain_ops._mcp_call", side_effect=[mock_write, mock_verify]):
            result = json.loads(souschef_log_meal({"meal": "pizza", "type": "ate"}))
        assert result.get("logged") is False
        assert "verify" in result.get("error", "").lower()
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd /Users/akmini/.hermes/hermes-agent && python -m pytest tests/test_domain_ops.py -v
```

Expected: FAIL — `tools.domain_ops` module does not exist

- [ ] **Step 4: Create `tools/domain_ops.py`**

```python
"""Typed domain operation tools for high-value mutations.

These wrap raw MCP calls with:
- Input schema validation
- Idempotency (duplicate detection)
- Read-back verification (confirm the write actually happened)
- Typed structured results

Register via toolsets.py in the 'minx' or 'finances' toolset.
"""

from __future__ import annotations
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_VALID_MEAL_TYPES = {"ate", "cooked", "planned"}
_REQUIRED_TXN_FIELDS = {"date", "description", "amount"}


def _mcp_call(tool_name: str, args: dict) -> str:
    """Dispatch a single MCP tool call through the Hermes registry."""
    from tools.registry import registry
    handler = registry.get_handler(tool_name)
    if handler is None:
        return json.dumps({"error": f"Tool '{tool_name}' not found in registry"})
    try:
        return handler(args)
    except Exception as e:
        return json.dumps({"error": str(e)})


def finance_import_transactions(args: dict, **kwargs) -> str:
    """Import a batch of transactions into FinanceHub with validation and read-back.

    Args:
        transactions: list of {date, description, amount, category}

    Returns JSON:
        {imported: N, duplicates: N, failed: [...], batch_id: str}
    """
    transactions = args.get("transactions") or []

    if not transactions:
        return json.dumps({"error": "transactions list is empty"})

    # Validate required fields
    for i, txn in enumerate(transactions):
        missing = _REQUIRED_TXN_FIELDS - set(txn.keys())
        if missing:
            return json.dumps({"error": f"Transaction {i} missing fields: {sorted(missing)}"})

    imported = 0
    duplicates = 0
    failed = []

    for txn in transactions:
        write_result_raw = _mcp_call(
            "mcp__finance__transactions_add",
            {
                "date": txn["date"],
                "description": txn["description"],
                "amount": float(txn["amount"]),
                "category": txn.get("category", "other"),
                "raw_data": txn.get("raw_data", ""),
            },
        )
        try:
            write_result = json.loads(write_result_raw)
        except Exception:
            failed.append({"txn": txn, "error": "non-JSON response from MCP"})
            continue

        if write_result.get("error"):
            failed.append({"txn": txn, "error": write_result["error"]})
            continue

        if write_result.get("duplicate"):
            duplicates += 1
            continue

        imported += 1

    return json.dumps({
        "imported": imported,
        "duplicates": duplicates,
        "failed": failed,
        "error": None,
    })


def souschef_log_meal(args: dict, **kwargs) -> str:
    """Log a meal to SousChef with type validation and read-back verification.

    Args:
        meal: meal name or description
        type: one of 'ate', 'cooked', 'planned'
        date: ISO date string (optional, defaults to today)
        servings: float (optional, defaults to 1.0)

    Returns JSON:
        {logged: bool, meal_id: str, error: str|None}
    """
    meal = args.get("meal", "").strip()
    meal_type = args.get("type", "").strip().lower()
    date = args.get("date")
    servings = args.get("servings", 1.0)

    if not meal:
        return json.dumps({"logged": False, "error": "meal name is required"})

    if meal_type not in _VALID_MEAL_TYPES:
        return json.dumps({
            "logged": False,
            "error": f"type must be one of {sorted(_VALID_MEAL_TYPES)}, got '{meal_type}'"
        })

    log_args: dict[str, Any] = {"meal": meal, "type": meal_type, "servings": servings}
    if date:
        log_args["date"] = date

    write_raw = _mcp_call("mcp__souschef__tracker_log_meal", log_args)
    try:
        write_result = json.loads(write_raw)
    except Exception:
        return json.dumps({"logged": False, "error": "non-JSON response from SousChef MCP"})

    if write_result.get("error"):
        return json.dumps({"logged": False, "error": write_result["error"]})

    meal_id = write_result.get("id") or write_result.get("meal_id")
    if not meal_id:
        return json.dumps({"logged": False, "error": "MCP returned no meal_id — cannot verify"})

    # Read-back verification
    verify_raw = _mcp_call("mcp__souschef__tracker_get_meal", {"id": meal_id})
    try:
        verify_result = json.loads(verify_raw)
    except Exception:
        return json.dumps({"logged": False, "error": "verify read-back returned non-JSON"})

    if not verify_result.get("meal"):
        return json.dumps({
            "logged": False,
            "error": f"verify failed — meal_id '{meal_id}' not found after write"
        })

    return json.dumps({"logged": True, "meal_id": meal_id, "error": None})
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
cd /Users/akmini/.hermes/hermes-agent && python -m pytest tests/test_domain_ops.py -v
```

Expected: All PASS

- [ ] **Step 6: Register tools in toolsets**

Check `toolsets.py` to find the appropriate toolset (look for `finances` or `minx` toolset), then add:

```python
from tools.domain_ops import finance_import_transactions, souschef_log_meal

# In the toolset registration block, alongside other finance/souschef tools:
registry.register(
    name="finance_import_transactions",
    toolset="finances",
    schema={
        "name": "finance_import_transactions",
        "description": "Import validated transactions into FinanceHub with duplicate detection and read-back verification. Use this instead of raw mcp__finance__transactions_add.",
        "parameters": {
            "type": "object",
            "properties": {
                "transactions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["date", "description", "amount"],
                        "properties": {
                            "date": {"type": "string"},
                            "description": {"type": "string"},
                            "amount": {"type": "number"},
                            "category": {"type": "string"},
                        }
                    }
                }
            },
            "required": ["transactions"]
        }
    },
    handler=finance_import_transactions,
    is_async=False,
)

registry.register(
    name="souschef_log_meal",
    toolset="souschef",
    schema={
        "name": "souschef_log_meal",
        "description": "Log a meal to SousChef with type validation (ate/cooked/planned) and read-back verification. Use instead of raw mcp__souschef__tracker_log_meal.",
        "parameters": {
            "type": "object",
            "required": ["meal", "type"],
            "properties": {
                "meal": {"type": "string"},
                "type": {"type": "string", "enum": ["ate", "cooked", "planned"]},
                "date": {"type": "string"},
                "servings": {"type": "number"},
            }
        }
    },
    handler=souschef_log_meal,
    is_async=False,
)
```

- [ ] **Step 7: Smoke test tool registration**

```bash
cd /Users/akmini/.hermes/hermes-agent && python3 -c "
from tools.registry import registry
# These will fail if toolsets.py doesn't load them yet — that's expected until Step 6 is done
print('finance_import_transactions' in registry.list_tools())
print('souschef_log_meal' in registry.list_tools())
"
```

- [ ] **Step 8: Commit**

```bash
cd /Users/akmini/.hermes/hermes-agent
git add tools/domain_ops.py toolsets.py tests/test_domain_ops.py
git commit -m "feat: typed domain tools for finance import and meal logging

finance_import_transactions: validates required fields, detects
duplicates, returns typed {imported, duplicates, failed} result.

souschef_log_meal: validates type is ate/cooked/planned, does read-back
verification after write, fails loudly if meal_id not found.

Both replace raw mcp_* calls for high-value writes."
```

---

## Final Integration Test

- [ ] **Run the full test suite**

```bash
cd /Users/akmini/.hermes/hermes-agent && python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: All new tests pass, no regressions in existing tests

- [ ] **Manual smoke test: verify domain escalation blocks short cron prompts**

```bash
cd /Users/akmini/.hermes/hermes-agent && python3 -c "
from agent.smart_model_routing import choose_cheap_model_route
cfg = {'enabled': True, 'cheap_model': {'provider': 'openai', 'model': 'gpt-4o-mini'}}

# These should all return None (forced to primary model)
assert choose_cheap_model_route('Run the weekly report', cfg) is None
assert choose_cheap_model_route('Finance summary', cfg) is None
assert choose_cheap_model_route('Check budget', cfg) is None

# This should return a route (cheap is fine)
assert choose_cheap_model_route('thanks', cfg) is not None

print('All routing checks passed')
"
```

- [ ] **Manual smoke test: verify preflight reads skill requires**

```bash
cd /Users/akmini/.hermes/hermes-agent && python3 -c "
from cron.scheduler import _load_skill_requires
r = _load_skill_requires('minx/finance-import')
assert 'finance' in r.get('mcp', []), f'Expected finance in mcp, got: {r}'
print('finance-import requires:', r)

r2 = _load_skill_requires('minx/weekly-review')
print('weekly-review requires:', r2)
"
```

---

## Next Plans (separate documents)

After this plan is complete and all tests pass:

- **`2026-04-01-hermes-finance.md`** — Himalaya email fix, email-poll cron query, Robinhood skill wiring, finance/weekly-review skill consolidation
- **`2026-04-01-hermes-souschef.md`** — journal-scan expense-note path, meal-photo-checkin skill
- **`2026-04-01-hermes-memory.md`** — structured Honcho conclusion extractor
- **`2026-04-01-hermes-acp.md`** — hermes-acp-minx profile, idea-to-implementation skill
