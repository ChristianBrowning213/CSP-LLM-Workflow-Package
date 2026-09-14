"""Tests for multi-kind publishing into QLIP_Outputs registry."""

from __future__ import annotations

import json
import os
import re
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


def test_publish_multiple_kinds_and_posix_paths(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"

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

    guidance_root = tmp_path / "guidance_payload"
    guidance_root.mkdir(parents=True, exist_ok=True)
    (guidance_root / "guidance.json").write_text('{"kind":"guidance"}\n', encoding="utf-8")

    constraint_root = tmp_path / "constraint_payload"
    constraint_root.mkdir(parents=True, exist_ok=True)
    (constraint_root / "constraint.txt").write_text("constraint\n", encoding="utf-8")

    spp_pub = _run_cmd(
        "scripts/publish_qlip_outputs.py",
        "--kind",
        "spp",
        "--artifact_root",
        str(spp_root),
        "--name",
        "spp_run",
        "--qlip_outputs",
        str(qlip_outputs),
    )
    assert spp_pub.returncode == 0, spp_pub.stdout + spp_pub.stderr
    spp_run_id = _extract_run_id(spp_pub.stdout)

    g_pub = _run_cmd(
        "scripts/publish_qlip_outputs.py",
        "--kind",
        "guidance",
        "--artifact_root",
        str(guidance_root),
        "--name",
        "g1",
        "--qlip_outputs",
        str(qlip_outputs),
    )
    assert g_pub.returncode == 0, g_pub.stdout + g_pub.stderr
    g_run_id = _extract_run_id(g_pub.stdout)

    c_pub = _run_cmd(
        "scripts/publish_qlip_outputs.py",
        "--kind",
        "constraint",
        "--artifact_root",
        str(constraint_root),
        "--name",
        "c1",
        "--qlip_outputs",
        str(qlip_outputs),
    )
    assert c_pub.returncode == 0, c_pub.stdout + c_pub.stderr
    c_run_id = _extract_run_id(c_pub.stdout)

    assert (qlip_outputs / "SPP" / "latest.txt").read_text(encoding="utf-8").strip() == (
        f"SPP/runs/{spp_run_id}"
    )
    assert (
        qlip_outputs / "GUIDANCES" / "latest.txt"
    ).read_text(encoding="utf-8").strip() == f"GUIDANCES/runs/{g_run_id}"
    assert (
        qlip_outputs / "CONSTRAINTS" / "latest.txt"
    ).read_text(encoding="utf-8").strip() == f"CONSTRAINTS/runs/{c_run_id}"

    index = json.loads((qlip_outputs / "index.json").read_text(encoding="utf-8"))
    spp_ids = [item["run_id"] for item in index["artifacts"]["spp"]["runs"]]
    guidance_ids = [item["run_id"] for item in index["artifacts"]["guidances"]["runs"]]
    constraint_ids = [item["run_id"] for item in index["artifacts"]["constraints"]["runs"]]
    assert spp_run_id in spp_ids
    assert g_run_id in guidance_ids
    assert c_run_id in constraint_ids

    assert isinstance(index["artifacts"]["packages"]["runs"], list)

    for bucket in ("spp", "guidances", "constraints", "packages"):
        for run in index["artifacts"][bucket]["runs"]:
            assert "\\" not in run["path"]
