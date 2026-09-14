"""Smoke test for the property-conditioned demo script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np


def _run_demo_script(*args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_path) if not existing else f"{src_path}{os.pathsep}{existing}"
    return subprocess.run(
        [sys.executable, "scripts/demo_property_conditioned_spp.py", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=repo_root,
    )


def test_demo_script_smoke(tmp_path: Path) -> None:
    meta_csv = tmp_path / "meta.csv"
    meta_csv.write_text(
        "cif_name,property_label\n"
        "nacl.cif,B\n"
        "sic.cif,A\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "demo_out"
    name = "smoke"
    result = _run_demo_script(
        "--cif_dir",
        "tests/fixtures/cifs",
        "--meta_csv",
        str(meta_csv),
        "--property_filter",
        "A",
        "--out_dir",
        str(out_dir),
        "--name",
        name,
        "--max_eval",
        "2",
        "--bin_width",
        "0.2",
        "--r_cut",
        "3.5",
    )
    assert result.returncode == 0, result.stderr

    base = out_dir / name
    report_path = base / "report.json"
    summary_path = base / "summary.txt"
    assert report_path.exists()
    assert summary_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "metadata" in report
    assert "counts" in report
    assert "rows" in report
    assert "summary" in report
    assert "top_shifted" in report

    assert report["counts"]["num_eval"] <= 2
    deltas = np.asarray([row["delta"] for row in report["rows"]], dtype=float)
    assert np.all(np.isfinite(deltas))
