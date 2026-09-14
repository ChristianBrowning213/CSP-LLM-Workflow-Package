"""CLI calibration supercell score_method tests."""

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


def test_cli_calibrate_supercell_method_records_and_ignores_neighbor_args(tmp_path: Path) -> None:
    spp_root = tmp_path / "spp_out"
    fit_result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(spp_root),
        "--fit_method",
        "supercell_gr",
    )
    assert fit_result.returncode == 0, fit_result.stderr

    out_json = tmp_path / "calibration_supercell.json"
    result = _run_module_cli(
        "calibrate",
        "--spp_root",
        str(spp_root),
        "--cif_dir",
        "tests/fixtures/cifs",
        "--score_method",
        "supercell_gr",
        "--r_cut",
        "4.0",
        "--target",
        "5.0",
        "--out_json",
        str(out_json),
    )
    assert result.returncode == 0, result.stderr

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["score_method"] == "supercell_gr"
    assert payload["neighbor"] is None
    assert payload["supercell"]["r_max"] == 10.0
    assert payload["supercell"]["bin_width"] == 0.05
    assert payload["supercell"]["sigma"] == 0.1
