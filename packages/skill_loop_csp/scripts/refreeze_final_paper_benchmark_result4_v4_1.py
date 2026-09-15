"""Create the provenance-corrected Result-4-only V4.1 freeze without solving."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "artifacts" / "final_paper_benchmark_result4_v4"
NEW = ROOT / "artifacts" / "final_paper_benchmark_result4_v4_1"
OLD_COMMIT = "1238bb09a5f1325d7021422ea406df87a5f7a2e3"
NEW_COMMIT = "31feff023515b2ac32165fe95fb803412e21a5bc"
ADAPTER = ROOT / "src/sok_llm_orchestrator/bench/prospective.py"
ADAPTER_SHA256 = "a2959a8fcbd9c3afc66463fac4049c685f72f5d3714551ca6b01030e2d08a6e0"
OLD_HASHES = {
    "RESULT4_V4_PROTOCOL.md": "f1e8ff1ff7e6e31102269024a1e6c0b91f5118eab430c582ea98d4fefbed0191",
    "RESULT4_V4_CASES.csv": "54cd5265822784cc67f61bce02f9be749dc538c7a833d46a6eaffc1b0db2be3d",
    "RESULT4_V4_REFERENCES.csv": "f1c40a613c44f4fbf03c78cac8ed344340af4ed7108678f42505070daf4116c0",
    "RESULT4_V4_CONFIG.json": "9681245f852d123454f0859b579acdd01fccc7404ed7b2f143b7b857e23e10f6",
    "RESULT4_V4_FREEZE.json": "e0b40d85addee3604dba8871c1ecf2c3757c7ec98844bdbb3a91ca817540b58c",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("path", "sha256"))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if NEW.exists():
        raise RuntimeError(f"refusing to overwrite existing freeze: {NEW}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != NEW_COMMIT:
        raise RuntimeError(f"unexpected workflow commit: {head}")
    for name, expected in OLD_HASHES.items():
        actual = sha256(OLD / name)
        if actual != expected:
            raise RuntimeError(f"superseded freeze changed: {name}: {actual}")
    if sha256(ADAPTER) != ADAPTER_SHA256:
        raise RuntimeError("prospective adapter content changed")
    tracked = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", NEW_COMMIT, "--", "src/sok_llm_orchestrator/bench/prospective.py"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked != "src/sok_llm_orchestrator/bench/prospective.py":
        raise RuntimeError("prospective adapter is absent from workflow commit")
    source_diff = subprocess.check_output(
        ["git", "diff", "--name-only", NEW_COMMIT, "--", "src"], cwd=ROOT, text=True
    ).strip()
    source_untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"], cwd=ROOT, text=True
    ).strip()
    if source_diff or source_untracked:
        raise RuntimeError(f"scientific workflow diff: tracked={source_diff!r}, untracked={source_untracked!r}")

    NEW.mkdir(parents=True)
    copies = {
        "RESULT4_V4_PROTOCOL.md": "RESULT4_V4_1_PROTOCOL.md",
        "RESULT4_V4_CASES.csv": "RESULT4_V4_1_CASES.csv",
        "RESULT4_V4_REFERENCES.csv": "RESULT4_V4_1_REFERENCES.csv",
    }
    for old_name, new_name in copies.items():
        shutil.copyfile(OLD / old_name, NEW / new_name)

    config = json.loads((OLD / "RESULT4_V4_CONFIG.json").read_text(encoding="utf-8"))
    config["workflow_commit"] = NEW_COMMIT
    write_json(NEW / "RESULT4_V4_1_CONFIG.json", config)

    frozen_names = [
        "RESULT4_V4_1_PROTOCOL.md",
        "RESULT4_V4_1_CASES.csv",
        "RESULT4_V4_1_REFERENCES.csv",
        "RESULT4_V4_1_CONFIG.json",
    ]
    file_hashes = {name: sha256(NEW / name) for name in frozen_names}
    old_freeze = json.loads((OLD / "RESULT4_V4_FREEZE.json").read_text(encoding="utf-8"))
    freeze = {
        **old_freeze,
        "schema_version": "result4_v4_1_freeze.v1",
        "workflow_commit": NEW_COMMIT,
        "execution_status": "FROZEN_NOT_STARTED",
        "prospective_adapter": {
            "path": "src/sok_llm_orchestrator/bench/prospective.py",
            "sha256": ADAPTER_SHA256,
            "tracked_in_workflow_commit": True,
            "classification": "PROVENANCE_ONLY_MISSING_FROM_COMMIT",
        },
        "supersedes": {
            "path": "artifacts/final_paper_benchmark_result4_v4",
            "workflow_commit": OLD_COMMIT,
            "freeze_sha256": OLD_HASHES["RESULT4_V4_FREEZE.json"],
            "status": "SUPERSEDED_BEFORE_EXECUTION_PROVENANCE_INCOMPLETE",
            "attempted": 0,
            "benchmark_solves": 0,
        },
        "result4_v4_1_file_hashes": file_hashes,
    }
    freeze.pop("result4_v4_file_hashes", None)
    write_json(NEW / "RESULT4_V4_1_FREEZE.json", freeze)
    manifest_names = frozen_names + ["RESULT4_V4_1_FREEZE.json"]
    manifest = [{"path": name, "sha256": sha256(NEW / name)} for name in manifest_names]
    write_manifest(NEW / "OUTPUT_HASH_MANIFEST.csv", manifest)
    print(json.dumps({"workflow_commit": NEW_COMMIT, "hashes": {row["path"]: row["sha256"] for row in manifest}}, indent=2))


if __name__ == "__main__":
    main()
