"""Project packaging metadata for local runner execution."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_declares_runtime_dependencies() -> None:
    metadata_path = ROOT / "pyproject.toml"
    metadata = tomllib.loads(metadata_path.read_text())

    project = metadata["project"]
    dependencies = set(project["dependencies"])

    assert project["requires-python"] == ">=3.12"
    assert "httpx>=0.27.0" in dependencies
    assert "mcp[cli]>=1.13.0" in dependencies
    assert "PyYAML>=6.0.0" in dependencies


def test_pytest_can_import_repo_without_manual_pythonpath() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert metadata["tool"]["setuptools"]["packages"]["find"]["include"] == ["hermes_loop*"]
    assert metadata["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
