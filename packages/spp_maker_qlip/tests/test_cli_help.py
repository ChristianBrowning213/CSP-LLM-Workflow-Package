"""CLI help smoke tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_module_cli(*args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(src_path)
        if not existing
        else f"{src_path}{os.pathsep}{existing}"
    )
    return subprocess.run(
        [sys.executable, "-m", "spp_maker.cli", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=repo_root,
    )


@pytest.mark.parametrize(
    "args",
    [
        ("--help",),
        ("fit", "--help"),
        ("score", "--help"),
        ("calibrate", "--help"),
        ("run", "--help"),
    ],
)
def test_cli_help_exits_zero(args: tuple[str, ...]) -> None:
    result = _run_module_cli(*args)
    assert result.returncode == 0, result.stderr
