#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"

if [[ "$MODE" != "apply" && "$MODE" != "--check" ]]; then
  echo "Usage: $0 [apply|--check]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

CONFIG_PATH="$HERMES_HOME/config.yaml"
REPO_SKILL_PATH="$REPO_ROOT/skills/minx/finance-import"
LIVE_SKILL_PATH="$HERMES_HOME/skills/minx/finance-import"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "ERROR: Hermes config not found: $CONFIG_PATH" >&2
  exit 1
fi

if [[ ! -d "$REPO_SKILL_PATH" ]]; then
  echo "ERROR: repo skill not found: $REPO_SKILL_PATH" >&2
  exit 1
fi

python3 - "$MODE" "$CONFIG_PATH" "$REPO_SKILL_PATH" "$LIVE_SKILL_PATH" <<'PY'
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import yaml

mode = sys.argv[1]
config_path = Path(sys.argv[2])
repo_skill_path = Path(sys.argv[3]).resolve()
live_skill_path = Path(sys.argv[4])

FINANCE_CHANNEL_PROMPT = """This is #finances. When a user uploads a supported finance CSV/PDF attachment here, treat it as an import request by default and use the minx/finance-import skill. Supported one-step imports are Robinhood CSV, Discover PDF, and DCU CSV/PDF. Prefer the cached local attachment paths from Discord, stage them under ~/.minx/data/imports/discord/YYYY-MM-DD/, always run finance_import_preview before finance_import, and import immediately when the account/source kind are clear. If there is no supported attachment, do not force an import. If the attachment or account is ambiguous, ask one short clarification question instead of guessing."""


def _normalize_bindings(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, object]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        normalized.append(dict(entry))
    return normalized


def _normalize_prompts(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            normalized[str(key)] = text
    return normalized


def _ensure_live_skill(apply: bool) -> tuple[bool, str]:
    if live_skill_path.is_symlink():
        target = live_skill_path.resolve()
        ok = target == repo_skill_path
        return ok, f"symlink -> {target}"

    if not live_skill_path.exists():
        if apply:
            live_skill_path.parent.mkdir(parents=True, exist_ok=True)
            live_skill_path.symlink_to(repo_skill_path, target_is_directory=True)
            return True, f"created symlink -> {repo_skill_path}"
        return False, "missing"

    if not apply:
        return False, "exists but is not a symlink"

    backup = live_skill_path.with_name(f"{live_skill_path.name}.backup.{time.strftime('%Y%m%dT%H%M%S')}")
    shutil.move(str(live_skill_path), str(backup))
    live_skill_path.symlink_to(repo_skill_path, target_is_directory=True)
    return True, f"moved existing skill to {backup.name} and linked -> {repo_skill_path}"


config = yaml.safe_load(config_path.read_text()) or {}
if not isinstance(config, dict):
    raise SystemExit(f"Unsupported config structure in {config_path}")

discord = config.setdefault("discord", {})
if not isinstance(discord, dict):
    raise SystemExit("Expected `discord` config block to be a mapping")

channel_directory = discord.get("channel_directory") or {}
if not isinstance(channel_directory, dict):
    raise SystemExit("Expected `discord.channel_directory` to be a mapping")

finance_channel_id = str(channel_directory.get("finances", "")).strip()
if not finance_channel_id:
    raise SystemExit("Could not resolve discord.channel_directory.finances from config.yaml")

bindings = _normalize_bindings(discord.get("channel_skill_bindings"))
binding_changed = False
desired_skills = ["minx/finance-import"]
found = False
for entry in bindings:
    if str(entry.get("id", "")).strip() != finance_channel_id:
        continue
    entry["id"] = finance_channel_id
    entry["skills"] = desired_skills
    entry.pop("skill", None)
    found = True
    binding_changed = True
    break
if not found:
    bindings.append({"id": finance_channel_id, "skills": desired_skills})
    binding_changed = True

prompts = _normalize_prompts(discord.get("channel_prompts"))
prompt_changed = prompts.get(finance_channel_id) != FINANCE_CHANNEL_PROMPT
prompts[finance_channel_id] = FINANCE_CHANNEL_PROMPT

skill_ok, skill_status = _ensure_live_skill(apply=mode != "--check")

bindings_ok = any(
    str(entry.get("id", "")).strip() == finance_channel_id
    and entry.get("skills") == desired_skills
    for entry in bindings
)
prompt_ok = prompts.get(finance_channel_id) == FINANCE_CHANNEL_PROMPT

if mode != "--check":
    discord["channel_skill_bindings"] = bindings
    discord["channel_prompts"] = prompts
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=False))

print(f"finance_channel_id={finance_channel_id}")
print(f"channel_skill_binding={'ok' if bindings_ok else 'missing'}")
print(f"channel_prompt={'ok' if prompt_ok else 'missing'}")
print(f"live_skill={skill_status}")

if mode == "--check" and not (bindings_ok and prompt_ok and skill_ok):
    raise SystemExit(1)
PY
