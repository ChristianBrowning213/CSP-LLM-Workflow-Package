"""Tests for calibration statistics collection and lambda recommendations."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

from spp_maker.calibration import (
    collect_scores_for_corpus,
    recommend_lambda_by_edge_median,
    recommend_lambda_by_structure_median,
    recommend_lambda_quantile,
)


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


def test_collect_scores_and_recommend_lambda(tmp_path: Path) -> None:
    spp_root = tmp_path / "spp_out"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(spp_root),
        "--r_cut",
        "8.0",
    )
    assert fit_result.returncode == 0, fit_result.stderr

    stats = collect_scores_for_corpus(
        spp_root=spp_root,
        cif_dir=Path("tests/fixtures/cifs"),
        max_n=2,
        r_cut=4.0,
    )
    assert stats.num_structures == 2
    assert stats.num_edges_total >= 0
    assert stats.score_structures.shape == (2,)
    assert stats.score_edges.shape == (2,)

    median_structure = stats.summary["structure_scores"]["median"]
    median_edge = stats.summary["edge_scores"]["median"]
    assert math.isfinite(median_structure)
    assert math.isfinite(median_edge)

    lam_structure = recommend_lambda_by_structure_median(
        stats,
        target_structure_median=5.0,
        convention="reward",
        min_lambda=0.0,
        max_lambda=1e9,
    )
    lam_edge = recommend_lambda_by_edge_median(
        stats,
        target_edge_median=0.1,
        convention="reward",
        min_lambda=0.0,
        max_lambda=1e9,
    )
    lam_quantile = recommend_lambda_quantile(
        stats,
        q=0.5,
        target=5.0,
        convention="reward",
        min_lambda=0.0,
        max_lambda=1e9,
    )
    assert math.isfinite(lam_structure.lambda_used) and lam_structure.lambda_used >= 0.0
    assert math.isfinite(lam_edge.lambda_used) and lam_edge.lambda_used >= 0.0
    assert math.isfinite(lam_quantile.lambda_used) and lam_quantile.lambda_used >= 0.0
    assert hasattr(lam_structure, "lambda_raw_signed")
    assert hasattr(lam_edge, "lambda_positive")
    assert hasattr(lam_quantile, "lambda_clipped")
