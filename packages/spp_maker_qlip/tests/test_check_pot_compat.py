"""Smoke test for scripts/check_pot_compat.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_cmd(*args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_path) if not existing else f"{src_path}{os.pathsep}{existing}"
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=repo_root,
    )


def test_check_pot_compat_on_generated_spp_root(tmp_path: Path) -> None:
    spp_root = tmp_path / "spp_out"
    fit_res = _run_cmd(
        "-m",
        "spp_maker.cli",
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(spp_root),
    )
    assert fit_res.returncode == 0, fit_res.stderr

    check_res = _run_cmd("scripts/check_pot_compat.py", "--spp_root", str(spp_root))
    assert check_res.returncode == 0, check_res.stdout + check_res.stderr
    assert "POT files checked" in check_res.stdout
