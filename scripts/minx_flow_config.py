#!/usr/bin/env python3
"""Configure and validate the Minx Discord/Hermes flow."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


REQUIRED_CHANNELS = ("ask_minx", "finance", "training", "capture", "reports", "meals")
OPTIONAL_CHANNELS = ("minx_ops",)
LEGACY_CHANNEL_KEYS = {
    "home": "ask_minx",
    "finances": "finance",
    "health": "training",
    "journal": "capture",
}

CHANNEL_PROMPTS = {
    "ask_minx": (
        "This is #ask-minx, the broad Minx control plane. Route broad Minx questions "
        "through /minx-investigate, planning requests through /minx-plan, retrospectives "
        "through /minx-retro, and entity lookups through /minx-onboard-entity. Use domain "
        "tools for clear read-only questions. Ask one short clarification question when "
        "intent or scope is ambiguous."
    ),
    "finance": (
        "This is #finance. When a user uploads a supported finance CSV/PDF attachment, "
        "treat it as an import request by default and use the minx/finance-import skill. "
        "Supported one-step imports are Robinhood CSV, Discover PDF, and DCU CSV/PDF. "
        "Prefer cached local attachment paths from Discord, stage them under "
        "~/.minx/data/imports/discord/YYYY-MM-DD/, always run finance_import_preview "
        "before finance_import, and import only when account/source kind are clear. "
        "Ask one short clarification question instead of guessing."
    ),
    "training": (
        "This is #training. Use Minx training and goals tools for workout, adherence, "
        "fitness, and training progress questions. Log workouts through minx_training "
        "tools only when the user clearly asks to log them. Do not write workout notes "
        "directly to Obsidian as canonical data."
    ),
    "capture": (
        "This is #capture for Minx memory, goals, preferences, constraints, and reflection "
        "intake. Capture stable preferences, routines, constraints, and goals through "
        "Minx memory and goal tools. Ask before saving sensitive or uncertain facts. "
        "Do not treat Obsidian journal notes as canonical state."
    ),
    "reports": (
        "This is #reports. Prefer concise scheduled summaries, anomaly alerts, and links "
        "to Minx projection notes. Avoid casual chatter. If a report suggests a follow-up "
        "investigation or plan, point the user to #ask-minx or the matching /minx-* command."
    ),
    "meals": (
        "This is #meals. Use Minx meals tools for meal logs, nutrition profiles, pantry, "
        "recipes, and meal planning. Log meals or edit pantry only when the user clearly "
        "asks. Do not reference old SousChef vault recipes unless the user explicitly "
        "re-imports them."
    ),
}


class ValidationIssues:
    def __init__(self, *, errors: list[str], warnings: list[str]) -> None:
        self.errors = errors
        self.warnings = warnings


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_minx_discord_config(config: dict[str, Any]) -> bool:
    """Apply the approved logical channel names and prompts in-place."""

    changed = False
    discord = config.setdefault("discord", {})
    if not isinstance(discord, dict):
        raise ValueError("discord must be a mapping")

    raw_directory = discord.get("channel_directory")
    directory = dict(_mapping(raw_directory))
    normalized_directory: dict[str, Any] = {}

    for key, value in directory.items():
        normalized_key = LEGACY_CHANNEL_KEYS.get(str(key), str(key))
        normalized_directory[normalized_key] = value

    for legacy_key in LEGACY_CHANNEL_KEYS:
        normalized_directory.pop(legacy_key, None)

    if normalized_directory != raw_directory:
        discord["channel_directory"] = normalized_directory
        changed = True

    prompts = dict(_mapping(discord.get("channel_prompts")))
    for channel_key, prompt in CHANNEL_PROMPTS.items():
        channel_id = normalized_directory.get(channel_key)
        if not channel_id:
            continue
        prompt_key = str(channel_id)
        if prompts.get(prompt_key) != prompt:
            prompts[prompt_key] = prompt
            changed = True

    if prompts != discord.get("channel_prompts"):
        discord["channel_prompts"] = prompts
        changed = True

    return changed


def validate_minx_flow_config(config: dict[str, Any]) -> ValidationIssues:
    errors: list[str] = []
    warnings: list[str] = []
    discord = _mapping(config.get("discord"))
    directory = _mapping(discord.get("channel_directory"))
    prompts = _mapping(discord.get("channel_prompts"))

    for key in REQUIRED_CHANNELS:
        channel_id = directory.get(key)
        if not channel_id:
            errors.append(f"discord.channel_directory.{key} is not configured")
            continue
        expected_prompt = CHANNEL_PROMPTS[key]
        if prompts.get(str(channel_id)) != expected_prompt:
            errors.append(f"discord.channel_prompts.{channel_id} does not match {key}")

    for key in LEGACY_CHANNEL_KEYS:
        if key in directory:
            errors.append(f"legacy discord.channel_directory.{key} is still configured")

    for key in OPTIONAL_CHANNELS:
        if not directory.get(key):
            warnings.append(f"discord.channel_directory.{key} is not configured")

    external_dirs = _mapping(config.get("skills")).get("external_dirs")
    if "/Users/akmini/Documents/minx-hermes/skills" not in (external_dirs or []):
        errors.append("skills.external_dirs must include /Users/akmini/Documents/minx-hermes/skills")

    provider_routing = _mapping(config.get("provider_routing"))
    if provider_routing.get("data_collection") != "deny":
        errors.append("provider_routing.data_collection must be deny")

    quick_commands = _mapping(config.get("quick_commands"))
    expected_aliases = {
        "minx_investigate": "/minx-investigate",
        "minx_plan": "/minx-plan",
        "minx_retro": "/minx-retro",
        "minx_onboard_entity": "/minx-onboard-entity",
    }
    for name, target in expected_aliases.items():
        value = _mapping(quick_commands.get(name))
        if value.get("target") != target:
            errors.append(f"quick_commands.{name}.target must be {target}")

    return ValidationIssues(errors=errors, warnings=warnings)


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text()) or {}
    if not isinstance(config, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path.home() / ".hermes" / "config.yaml")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    changed = normalize_minx_discord_config(config)
    issues = validate_minx_flow_config(config)

    for warning in issues.warnings:
        print(f"WARNING: {warning}")
    for error in issues.errors:
        print(f"ERROR: {error}")

    if issues.errors:
        return 1

    if not args.check and changed:
        args.config.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
        print(f"updated {args.config}")
    elif args.check:
        print("minx flow config OK")
    else:
        print("minx flow config already OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
