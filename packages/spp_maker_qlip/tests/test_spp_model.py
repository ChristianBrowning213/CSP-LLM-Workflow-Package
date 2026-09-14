"""Tests for loading exported SPP roots into an in-memory model."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from spp_maker.spp_model import load_spp_model


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


def test_load_spp_model_from_fit_output(tmp_path: Path) -> None:
    out_root = tmp_path / "spp_out"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
    )
    assert fit_result.returncode == 0, fit_result.stderr

    model = load_spp_model(out_root)
    assert model.binning is not None
    assert len(model.pairs) > 0

    key = model.pairs[0]
    r_vals = model.r[key]
    mid_d = float(r_vals[len(r_vals) // 2])
    penalty = model.penalty(key[0], key[1], mid_d)
    assert np.isfinite(penalty)
