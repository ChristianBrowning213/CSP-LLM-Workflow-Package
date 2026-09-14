"""Smoke tests for `spp-maker score` CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_module_cli(*args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
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


def test_score_cli_single_cif_smoke(tmp_path: Path) -> None:
    out_root = tmp_path / "spp_out"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
    )
    assert fit_result.returncode == 0, fit_result.stderr

    result = _run_module_cli(
        "score",
        "--spp_root",
        str(out_root),
        "--cif",
        "tests/fixtures/cifs/nacl.cif",
    )
    assert result.returncode == 0, result.stderr
    assert "total:" in result.stdout


def test_score_cli_json_output_smoke(tmp_path: Path) -> None:
    out_root = tmp_path / "spp_out_json"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
    )
    assert fit_result.returncode == 0, fit_result.stderr

    result = _run_module_cli(
        "score",
        "--spp_root",
        str(out_root),
        "--cif",
        "tests/fixtures/cifs/nacl.cif",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert "total" in payload


def test_score_cli_accepts_policy_flags(tmp_path: Path) -> None:
    out_root = tmp_path / "spp_out_policies"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
        "--r_cut",
        "8.0",
    )
    assert fit_result.returncode == 0, fit_result.stderr

    result = _run_module_cli(
        "score",
        "--spp_root",
        str(out_root),
        "--cif",
        "tests/fixtures/cifs/nacl.cif",
        "--oob_policy",
        "clamp",
        "--missing_pair_policy",
        "max_global",
    )
    assert result.returncode == 0, result.stderr
