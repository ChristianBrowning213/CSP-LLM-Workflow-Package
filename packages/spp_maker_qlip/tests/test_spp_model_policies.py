"""Tests for SPPModel missing-pair and out-of-range policy behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

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


def test_missing_pair_policies_and_oob_policies(tmp_path: Path) -> None:
    spp_root = tmp_path / "spp_out"
    fit_res = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(spp_root),
        "--r_cut",
        "8.0",
    )
    assert fit_res.returncode == 0, fit_res.stderr

    model_safe = load_spp_model(spp_root, missing_pair_policy="max_global", oob_policy="max")
    assert model_safe.pairs

    missing_penalty = model_safe.penalty("Xx", "Xx", 2.0)
    assert np.isclose(missing_penalty, model_safe.global_max_phi)

    model_error = load_spp_model(spp_root, missing_pair_policy="error", oob_policy="max")
    with pytest.raises(KeyError):
        model_error.penalty("Xx", "Xx", 2.0)

    key = model_safe.pairs[0]
    d_lo = float(model_safe.binning.edges[0]) - 0.1 if model_safe.binning is not None else 0.0
    d_hi = float(model_safe.binning.edges[-1]) + 0.1 if model_safe.binning is not None else 99.0

    model_max = load_spp_model(spp_root, oob_policy="max")
    expected_max = float(np.max(model_max.phi[key]))
    assert np.isclose(model_max.penalty(key[0], key[1], d_lo), expected_max)
    assert np.isclose(model_max.penalty(key[0], key[1], d_hi), expected_max)

    model_clamp = load_spp_model(spp_root, oob_policy="clamp")
    assert np.isclose(model_clamp.penalty(key[0], key[1], d_lo), float(model_clamp.phi[key][0]))
    assert np.isclose(model_clamp.penalty(key[0], key[1], d_hi), float(model_clamp.phi[key][-1]))

    model_zero = load_spp_model(spp_root, oob_policy="zero")
    assert np.isclose(model_zero.penalty(key[0], key[1], d_lo), 0.0)
    assert np.isclose(model_zero.penalty(key[0], key[1], d_hi), 0.0)
