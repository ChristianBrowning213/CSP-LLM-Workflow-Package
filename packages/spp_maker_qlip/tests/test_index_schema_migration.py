"""Tests for legacy-to-v1 index migration during publish."""

from __future__ import annotations

import json
import os
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


def test_publish_migrates_legacy_index(tmp_path: Path) -> None:
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
    qlip_outputs.mkdir(parents=True, exist_ok=True)
    legacy_index = {
        "spp_runs": [
            {
                "run_id": "legacy_run_001",
                "name": "legacy",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "path": "SPP/runs/legacy_run_001",
                "manifest": "SPP/runs/legacy_run_001/manifest.json",
                "compat_strict": True,
                "compat_failed": 0,
            }
        ]
    }
    (qlip_outputs / "index.json").write_text(
        json.dumps(legacy_index, indent=2),
        encoding="utf-8",
    )

    pub_res = _run_cmd(
        "scripts/publish_qlip_outputs.py",
        "--kind",
        "spp",
        "--artifact_root",
        str(spp_root),
        "--name",
        "after_migration",
        "--qlip_outputs",
        str(qlip_outputs),
    )
    assert pub_res.returncode == 0, pub_res.stdout + pub_res.stderr

    index = json.loads((qlip_outputs / "index.json").read_text(encoding="utf-8"))
    assert index["schema_version"] == "QLIPOutputsIndex.v1"
    assert "artifacts" in index
    assert "spp" in index["artifacts"]
    assert "guidances" in index["artifacts"]
    assert "constraints" in index["artifacts"]
    assert "packages" in index["artifacts"]

    migrated_run_ids = [item["run_id"] for item in index["artifacts"]["spp"]["runs"]]
    assert "legacy_run_001" in migrated_run_ids
    assert isinstance(index["artifacts"]["guidances"]["runs"], list)
    assert isinstance(index["artifacts"]["constraints"]["runs"], list)
    assert isinstance(index["artifacts"]["packages"]["runs"], list)
