"""Tests for scripts/publish_qlip_outputs.py."""

from __future__ import annotations

import json
import os
import re
import shutil
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


def _extract_run_id(stdout: str) -> str:
    match = re.search(r"Published run_id:\s+([^\r\n]+)", stdout)
    if not match:
        raise AssertionError(f"Could not parse run_id from output:\n{stdout}")
    return match.group(1).strip()


def _break_one_pot_file(spp_root: Path) -> None:
    pot_file = next(iter(sorted(spp_root.rglob("*.POT"))), None)
    if pot_file is None:
        raise AssertionError("Expected at least one POT file to break.")
    lines = pot_file.read_text(encoding="utf-8").splitlines()

    numeric_indices = []
    for idx, line in enumerate(lines):
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            float(parts[0])
            float(parts[1])
        except ValueError:
            continue
        numeric_indices.append(idx)
    if len(numeric_indices) < 2:
        raise AssertionError("POT file must have at least two numeric lines.")

    i0 = numeric_indices[0]
    i1 = numeric_indices[1]
    r0 = lines[i0].split()[0]
    u1 = lines[i1].split()[1]
    lines[i1] = f"{r0} {u1}"
    pot_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_publish_qlip_outputs_success_and_failure_paths(tmp_path: Path) -> None:
    spp_root = tmp_path / "out_spp"
    fit_res = _run_cmd(
        "-m",
        "spp_maker.cli",
        "fit",
        "--cif_dir",
        "tests/fixtures/cifs",
        "--out_root",
        str(spp_root),
        "--r_cut",
        "8.0",
    )
    assert fit_res.returncode == 0, fit_res.stderr

    qlip_outputs = tmp_path / "QLIP_Outputs"
    pub_res = _run_cmd(
        "scripts/publish_qlip_outputs.py",
        "--kind",
        "spp",
        "--artifact_root",
        str(spp_root),
        "--name",
        "test_run",
        "--qlip_outputs",
        str(qlip_outputs),
    )
    assert pub_res.returncode == 0, pub_res.stdout + pub_res.stderr

    run_id = _extract_run_id(pub_res.stdout)
    run_dir = qlip_outputs / "SPP" / "runs" / run_id
    assert run_dir.exists()
    assert (run_dir / "spp_root").exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "compat_report.txt").exists()
    assert (run_dir / "publish_meta.json").exists()

    index_path = qlip_outputs / "index.json"
    assert index_path.exists()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    run_ids = [
        item["run_id"] for item in index["artifacts"]["spp"]["runs"]
    ]
    assert run_id in run_ids

    latest_path = qlip_outputs / "SPP" / "latest.txt"
    assert latest_path.exists()
    latest_rel = latest_path.read_text(encoding="utf-8").strip()
    assert latest_rel == f"SPP/runs/{run_id}"

    # Failure path: break POT compatibility and ensure publish aborts.
    broken_root = tmp_path / "broken_spp"
    shutil.copytree(spp_root, broken_root)
    _break_one_pot_file(broken_root)

    qlip_outputs_fail = tmp_path / "QLIP_Outputs_fail"
    fail_res = _run_cmd(
        "scripts/publish_qlip_outputs.py",
        "--kind",
        "spp",
        "--artifact_root",
        str(broken_root),
        "--name",
        "should_fail",
        "--qlip_outputs",
        str(qlip_outputs_fail),
    )
    assert fail_res.returncode == 1
    runs_dir = qlip_outputs_fail / "SPP" / "runs"
    if runs_dir.exists():
        run_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
        assert not run_dirs
