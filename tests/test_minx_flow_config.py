"""Tests for Minx Discord flow configuration helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "minx_flow_config.py"


def load_flow_config():
    spec = importlib.util.spec_from_file_location("minx_flow_config", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_normalize_channel_directory_renames_legacy_keys() -> None:
    flow = load_flow_config()
    config = {
        "discord": {
            "channel_directory": {
                "home": "1",
                "finances": "2",
                "health": "3",
                "journal": "4",
                "reports": "5",
                "meals": "6",
            },
            "channel_prompts": {},
        }
    }

    changed = flow.normalize_minx_discord_config(config)

    assert changed is True
    assert config["discord"]["channel_directory"] == {
        "ask_minx": "1",
        "finance": "2",
        "training": "3",
        "capture": "4",
        "reports": "5",
        "meals": "6",
    }


def test_normalize_channel_prompts_match_new_flow() -> None:
    flow = load_flow_config()
    config = {
        "discord": {
            "channel_directory": {
                "ask_minx": "1",
                "finance": "2",
                "training": "3",
                "capture": "4",
                "reports": "5",
                "meals": "6",
                "minx_ops": "7",
            },
            "channel_prompts": {"1": "old"},
        }
    }

    changed = flow.normalize_minx_discord_config(config)

    assert changed is True
    prompts = config["discord"]["channel_prompts"]
    assert "broad Minx questions" in prompts["1"]
    assert "CSV/PDF attachment" in prompts["2"]
    assert "workout" in prompts["3"]
    assert "stable preferences" in prompts["4"]
    assert "scheduled summaries" in prompts["5"]
    assert "meal logs" in prompts["6"]
    assert "stack status" in prompts["7"]
    assert config["discord"]["free_response_channels"] == "1,2,3,4,5,6,7"


def test_validate_reports_missing_minx_ops_as_warning() -> None:
    flow = load_flow_config()
    config = {
        "skills": {"external_dirs": [flow.DEFAULT_SKILLS_DIR]},
        "provider_routing": {"data_collection": "deny"},
        "discord": {
            "channel_directory": {
                "ask_minx": "1",
                "finance": "2",
                "training": "3",
                "capture": "4",
                "reports": "5",
                "meals": "6",
            },
            "channel_prompts": {
                "1": flow.CHANNEL_PROMPTS["ask_minx"],
                "2": flow.CHANNEL_PROMPTS["finance"],
                "3": flow.CHANNEL_PROMPTS["training"],
                "4": flow.CHANNEL_PROMPTS["capture"],
                "5": flow.CHANNEL_PROMPTS["reports"],
                "6": flow.CHANNEL_PROMPTS["meals"],
            },
        },
        "quick_commands": {
            "minx_investigate": {"type": "alias", "target": "/minx-investigate"},
            "minx_plan": {"type": "alias", "target": "/minx-plan"},
            "minx_retro": {"type": "alias", "target": "/minx-retro"},
            "minx_onboard_entity": {"type": "alias", "target": "/minx-onboard-entity"},
        },
    }

    issues = flow.validate_minx_flow_config(config)

    assert issues.errors == []
    assert "discord.channel_directory.minx_ops is not configured" in issues.warnings
