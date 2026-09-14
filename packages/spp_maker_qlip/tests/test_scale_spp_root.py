"""Tests for scaling exported SPP roots by lambda."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from spp_maker.calibration import scale_spp_root
from spp_maker.pot_compat import check_pot_root
from spp_maker.pot_io import read_pot_like_qlip


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


def test_scale_spp_root_multiplies_u_and_updates_manifest(tmp_path: Path) -> None:
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

    scaled_root = tmp_path / "spp_scaled"
    scale_spp_root(
        spp_root,
        scaled_root,
        2.0,
        convention="penalty",
        source_calibration_json="calibration.json",
        min_lambda=0.0,
        max_lambda=1e9,
    )

    orig_pot = sorted(spp_root.rglob("*.POT"), key=lambda p: str(p.relative_to(spp_root)))[0]
    scaled_pot = scaled_root / orig_pot.relative_to(spp_root)
    assert scaled_pot.is_file()

    r_orig, u_orig = read_pot_like_qlip(orig_pot)
    r_scaled, u_scaled = read_pot_like_qlip(scaled_pot)
    assert np.allclose(r_scaled, r_orig)
    assert np.allclose(u_scaled, 2.0 * u_orig)

    manifest = json.loads((scaled_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["lambda"] == 2.0
    assert "scaled_from" in manifest
    assert manifest["scaling"]["lambda_used"] == 2.0
    assert manifest["scaling"]["convention"] == "penalty"
    assert manifest["scaling"]["source_calibration_json"] == "calibration.json"

    header_lines = [line.strip() for line in scaled_pot.read_text(encoding="utf-8").splitlines() if line.startswith("#")]
    assert "# scaled_lambda_used: 2.0" in header_lines
    assert "# convention: penalty" in header_lines

    compat = check_pot_root(scaled_root, strict=True)
    assert compat.ok
