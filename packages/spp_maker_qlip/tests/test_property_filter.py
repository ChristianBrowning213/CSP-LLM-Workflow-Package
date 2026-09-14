"""Tests for metadata-driven property filtering in `spp-maker fit`."""

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


def _read_manifest(out_root: Path) -> dict:
    return json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))


def test_property_filter_include_and_exclude(tmp_path: Path) -> None:
    meta_csv = tmp_path / "meta.csv"
    meta_csv.write_text(
        "cif_name,property_label\n"
        "nacl.cif,A\n"
        "sic.cif,B\n",
        encoding="utf-8",
    )

    out_a = tmp_path / "out_a"
    result_a = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_a),
        "--meta_csv",
        str(meta_csv),
        "--property_filter",
        "A",
        "--property_mode",
        "include",
    )
    assert result_a.returncode == 0, result_a.stderr
    manifest_a = _read_manifest(out_a)
    assert manifest_a["num_structures_total"] == 2
    assert manifest_a["num_structures_selected"] == 1
    assert manifest_a["property_filter"] == "A"
    assert manifest_a["property_mode"] == "include"
    assert manifest_a["missing_meta_for_cifs"] == 0
    assert manifest_a["unmatched_meta_rows"] == 0

    out_b = tmp_path / "out_b"
    result_b = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_b),
        "--meta_csv",
        str(meta_csv),
        "--property_filter",
        "B",
        "--property_mode",
        "include",
    )
    assert result_b.returncode == 0, result_b.stderr
    manifest_b = _read_manifest(out_b)
    assert manifest_b["num_structures_selected"] == 1
    assert manifest_b["property_filter"] == "B"
    assert manifest_b["property_mode"] == "include"
    assert manifest_b["missing_meta_for_cifs"] == 0

    out_excl = tmp_path / "out_excl"
    result_excl = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_excl),
        "--meta_csv",
        str(meta_csv),
        "--property_filter",
        "A",
        "--property_mode",
        "exclude",
    )
    assert result_excl.returncode == 0, result_excl.stderr
    manifest_excl = _read_manifest(out_excl)
    assert manifest_excl["num_structures_selected"] == 1
    assert manifest_excl["property_filter"] == "A"
    assert manifest_excl["property_mode"] == "exclude"
    assert manifest_excl["missing_meta_for_cifs"] == 0


def test_meta_csv_weight_is_used_when_weights_csv_missing(tmp_path: Path) -> None:
    meta_csv = tmp_path / "meta_weights.csv"
    meta_csv.write_text(
        "cif_name,property_label,weight\n"
        "nacl.cif,A,2.0\n"
        "sic.cif,B,2.0\n",
        encoding="utf-8",
    )

    out_root = tmp_path / "out_meta_weight"
    result = _run_module_cli(
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(out_root),
        "--meta_csv",
        str(meta_csv),
        "--r_cut",
        "8.0",
    )
    assert result.returncode == 0, result.stderr

    manifest = _read_manifest(out_root)
    assert manifest["weights_source"] == "meta_csv"
    assert manifest["meta_csv"] == str(meta_csv.resolve())
    assert manifest["total_pairs_seen"] > 0
    assert manifest["total_weighted_pairs_seen"] >= manifest["total_pairs_seen"]
