"""Smoke tests for the `spp-maker fit` CLI workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def test_cli_fit_smoke_exports_tree(tmp_path: Path) -> None:
    out_root = tmp_path / "spp_out"
    result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
    )

    assert result.returncode == 0, result.stderr
    assert "CIFs loaded:" in result.stdout
    assert "Pairs exported:" in result.stdout

    manifest_path = out_root / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    pot_files = sorted(out_root.rglob("*.POT"))
    assert pot_files
    assert len(pot_files) == len(manifest["pairs"])

    r, u = read_pot_like_qlip(pot_files[0])
    assert r.shape == (manifest["nbins"],)
    assert u.shape == (manifest["nbins"],)


def test_cli_fit_smoke_with_weights_csv(tmp_path: Path) -> None:
    out_root = tmp_path / "spp_weighted"
    weights_csv = tmp_path / "weights.csv"
    weights_csv.write_text(
        "cif_name,weight\n"
        "nacl.cif,2.0\n"
        "sic.cif,2.0\n",
        encoding="utf-8",
    )

    result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
        "--weights_csv",
        str(weights_csv),
    )

    assert result.returncode == 0, result.stderr

    manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["weights_csv"] == str(weights_csv.resolve())
    assert manifest["total_pairs_seen"] > 0
    assert manifest["total_weighted_pairs_seen"] >= manifest["total_pairs_seen"]


def test_cli_fit_accepts_short_distance_guardrail_args(tmp_path: Path) -> None:
    out_root = tmp_path / "spp_guarded"
    result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
        "--r_cut",
        "8.0",
        "--short_distance_floor",
        "2.5",
        "--short_distance_bins",
        "2",
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["short_distance_floor"] == 2.5
    assert manifest["short_distance_bins"] == 2


def test_cli_fit_supercell_gr_smoke(tmp_path: Path) -> None:
    out_root = tmp_path / "spp_supercell"
    dump_dir = tmp_path / "gr_dump"
    result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
        "--fit_method",
        "supercell_gr",
        "--dump_gr_csv",
        str(dump_dir),
        "--dump_gr_pair",
        "Na-Cl",
    )

    assert result.returncode == 0, result.stderr
    assert "fit_method: supercell_gr" in result.stdout

    manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fit_method"] == "supercell_gr"
    assert manifest["supercell_target_len"] == 20.0
    assert manifest["r_max"] == 10.0
    assert manifest["bin_width"] == 0.05
    assert manifest["sigma"] == 0.1
    assert manifest["truncate_sigma"] == 3.0
    assert manifest["gr_eps"] == 1e-12
    assert manifest["max_pairs"] is None
    assert manifest["gr_support_ok"] is True
    assert manifest["supercell_min_half_extent"] is not None
    assert isinstance(manifest["supercell_repeats"], list)
    assert "normalization_convention" in manifest
    assert manifest["shifted"] is False
    assert manifest["excluded_structure_count"] == 0
    assert manifest["excluded_by_rule"] == {}
    assert manifest["sample_exclusions"] == []
    assert manifest["pair_count_total_est"] >= manifest["pair_count_used"] >= 1

    pot_files = sorted(out_root.rglob("*.POT"))
    assert pot_files
    csv_files = sorted(dump_dir.glob("*.csv"))
    assert csv_files
    assert [item.name for item in csv_files] == ["Cl-Na.csv"]
