"""Shared fixtures for MCP server tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_module_cli(*args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "src"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_path) if not existing else f"{src_path}{os.pathsep}{existing}"
    return subprocess.run(
        [sys.executable, "-m", "spp_maker.cli", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=repo_root,
    )


@pytest.fixture
def spp_root(tmp_path: Path) -> Path:
    """Build a minimal valid SPP root from fixture CIFs."""
    out_root = tmp_path / "spp_root"
    result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
        "--fit_method",
        "neighbors",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out_root

