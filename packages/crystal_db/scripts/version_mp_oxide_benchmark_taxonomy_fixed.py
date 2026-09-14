"""Create the v4 taxonomy-fixed freeze from immutable v3 scientific inputs."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.benchmark_freeze import canonical_hash  # noqa: E402
from crystal_db.family_dataset import write_json_atomic  # noqa: E402


PARENT_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v3_spp_repaired"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed"
SKILL_LOOP_ROOT = REPO_ROOT.parent / "Skill-Loop-CSP"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if OUTPUT_ROOT.exists():
        raise SystemExit(f"refusing to overwrite existing benchmark root: {OUTPUT_ROOT}")

    parent_freeze_path = PARENT_ROOT / "frozen_benchmark.json"
    parent_methodology_path = PARENT_ROOT / "FROZEN_METHODOLOGY.json"
    parent_targets_json_path = PARENT_ROOT / "benchmark_targets_final.json"
    parent_targets_csv_path = PARENT_ROOT / "benchmark_targets_final.csv"
    corrected_runner_path = (
        SKILL_LOOP_ROOT / "src" / "sok_llm_orchestrator" / "workflow" / "spp_only_benchmark.py"
    )
    for required in (
        parent_freeze_path,
        parent_methodology_path,
        parent_targets_json_path,
        parent_targets_csv_path,
        corrected_runner_path,
    ):
        if not required.is_file():
            raise SystemExit(f"required immutable input is missing: {required}")

    parent = _read(parent_freeze_path)
    methodology = _read(parent_methodology_path)
    targets = _read(parent_targets_json_path)
    if parent["targets"] != targets:
        raise SystemExit("v3 target manifest and frozen payload disagree")
    if parent["methodology_sha256"] != methodology["methodology_sha256"]:
        raise SystemExit("v3 methodology hash linkage is invalid")
    if len(targets) != 100:
        raise SystemExit("v3 target manifest does not contain exactly 100 targets")
    if sum(row["family"] == "layered" for row in targets) != 50:
        raise SystemExit("v3 target manifest does not contain exactly 50 layered targets")
    if sum(row["family"] == "spinel" for row in targets) != 50:
        raise SystemExit("v3 target manifest does not contain exactly 50 spinel targets")

    payload = {key: value for key, value in parent.items() if key != "freeze_sha256"}
    payload["freeze_version"] = "spp_only_oxide_benchmark.freeze.v4.taxonomy_fixed"
    payload["provenance"] = {
        "parent_artifact_root": str(PARENT_ROOT.resolve()),
        "parent_freeze_version": parent["freeze_version"],
        "parent_freeze_sha256": parent["freeze_sha256"],
        "parent_methodology_sha256": parent["methodology_sha256"],
        "target_roster_changed": False,
        "scientific_parameters_changed": False,
        "code_correction": {
            "scope": "benchmark failure-taxonomy mapping only",
            "before": {
                "qlip_status": "INFEASIBLE",
                "benchmark_outcome": "FAILED_OTHER",
            },
            "after": {
                "qlip_status": "INFEASIBLE",
                "benchmark_outcome": "FAILED_QLIP_INFEASIBLE",
            },
            "timeout_without_incumbent": {
                "qlip_status": "TIME_LIMIT_NO_SOLUTION",
                "benchmark_outcome": "FAILED_QLIP_TIMEOUT",
            },
            "corrected_runner_path": str(corrected_runner_path.resolve()),
            "corrected_runner_sha256": _sha256(corrected_runner_path),
        },
        "superseded_v3_partial_run": {
            "processed_targets": 70,
            "valid_candidate_cifs": 68,
            "optimal": 46,
            "feasible_time_limit_with_incumbent": 22,
            "solver_proven_infeasible_misclassified_as_failed_other": 2,
            "intentionally_resumed": False,
        },
    }
    payload["freeze_sha256"] = canonical_hash(payload)

    OUTPUT_ROOT.mkdir(parents=True)
    shutil.copy2(parent_methodology_path, OUTPUT_ROOT / parent_methodology_path.name)
    shutil.copy2(parent_targets_json_path, OUTPUT_ROOT / parent_targets_json_path.name)
    shutil.copy2(parent_targets_csv_path, OUTPUT_ROOT / parent_targets_csv_path.name)
    write_json_atomic(OUTPUT_ROOT / "frozen_benchmark.json", payload)
    write_json_atomic(OUTPUT_ROOT / "CODE_CORRECTION_PROVENANCE.json", payload["provenance"])
    (OUTPUT_ROOT / "V3_SUPERSESSION_PROVENANCE.md").write_text(
        "\n".join(
            [
                "# v3 Supersession Provenance",
                "",
                "The frozen v3 benchmark was intentionally halted after 70 targets and was not resumed.",
                "It contained 68 valid generated CIFs and two solver-proven infeasible targets whose",
                "structured QLIP status was incorrectly persisted as `FAILED_OTHER` rather than",
                "`FAILED_QLIP_INFEASIBLE`. The scientific target roster, retrieval/SPP policy, QLIP",
                "search parameters, and SCA configuration are unchanged in v4. All 100 v4 result",
                "rows must be generated from target 1 under the corrected runner.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "artifact_root": str(OUTPUT_ROOT.resolve()),
                "freeze_sha256": payload["freeze_sha256"],
                "methodology_sha256": payload["methodology_sha256"],
                "parent_freeze_sha256": parent["freeze_sha256"],
                "scientific_parameters_changed": False,
                "target_roster_changed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
