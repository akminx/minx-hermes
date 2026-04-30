"""Tests for production runner CLI/environment configuration."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "scripts" / "minx-investigate.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("minx_investigate_runner", RUNNER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_args_honors_investigation_routing_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_runner()
    monkeypatch.setattr(
        sys,
        "argv",
        ["minx-investigate.py", "--question", "hello"],
    )
    monkeypatch.setenv("MINX_INVESTIGATION_MODEL", "openrouter/free")
    monkeypatch.setenv("MINX_INVESTIGATION_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("MINX_INVESTIGATION_DATA_COLLECTION", "allow")
    monkeypatch.setenv("MINX_INVESTIGATION_REASONING_EFFORT", "off")
    monkeypatch.setenv("MINX_INVESTIGATION_QUANTIZATIONS", "")
    monkeypatch.setenv("MINX_INVESTIGATION_API_KEY_ENV", "OPENROUTER_API_KEY")

    args = runner.parse_args()

    assert args.model == "openrouter/free"
    assert args.base_url == "https://llm.example/v1"
    assert args.data_collection == "allow"
    assert args.reasoning_effort == "off"
    assert args.quantizations == ""
    assert args.api_key_env == "OPENROUTER_API_KEY"


def test_parse_args_keeps_configured_private_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = load_runner()
    monkeypatch.setattr(
        sys,
        "argv",
        ["minx-investigate.py", "--question", "hello"],
    )
    for name in (
        "MINX_INVESTIGATION_MODEL",
        "MINX_INVESTIGATION_DATA_COLLECTION",
        "MINX_INVESTIGATION_REASONING_EFFORT",
        "MINX_INVESTIGATION_QUANTIZATIONS",
        "MINX_INVESTIGATION_API_KEY_ENV",
    ):
        monkeypatch.delenv(name, raising=False)

    args = runner.parse_args()

    assert args.model == runner.DEFAULT_MODEL
    assert args.data_collection == "deny"
    assert args.reasoning_effort == "medium"
    assert args.quantizations == ""
    assert args.api_key_env == "OPENROUTER_API_KEY"


def test_print_config_does_not_require_question(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = load_runner()
    monkeypatch.setattr(sys, "argv", ["minx-investigate.py", "--print-config"])

    args = runner.parse_args()

    assert args.print_config is True
    assert args.question is None
