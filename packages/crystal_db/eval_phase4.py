import json
import os
from pathlib import Path
from typing import Dict, Any

from crystal_db.calibrate import calibrate_novelty
from crystal_db.ingest import ingest_sample
from crystal_db.ingest_folder import ingest_folder
from crystal_db.propose import propose_candidates
from crystal_db.report import generate_report


def _make_cif(path: Path, formula: str, tag: str) -> None:
    text = (
        f"data_{tag}\n"
        "_symmetry_space_group_name_H-M 'P1'\n"
        "_cell_length_a 5.0\n"
        "_cell_length_b 5.0\n"
        "_cell_length_c 5.0\n"
        "_cell_angle_alpha 90\n"
        "_cell_angle_beta 90\n"
        "_cell_angle_gamma 90\n"
        f"_chemical_formula_sum '{formula}'\n"
    )
    path.write_text(text, encoding="utf-8")


def run_eval_phase4(base_dir: Path) -> Dict[str, Any]:
    base_dir.mkdir(parents=True, exist_ok=True)
    db_path = base_dir / "phase4.db"

    ingest_sample(db_path=str(db_path), count=10)

    restricted_dir = base_dir / "restricted"
    restricted_dir.mkdir(exist_ok=True)
    restricted_cif = restricted_dir / "restricted.cif"
    _make_cif(restricted_cif, "Li2O", "restricted")

    ingest_folder(
        db_path=str(db_path),
        folder_path=str(restricted_dir),
        source="local_cif",
        policy_name="restricted",
        cache_dir=None,
    )

    cand_dir = base_dir / "candidates"
    cand_dir.mkdir(exist_ok=True)
    cand1 = cand_dir / "cand_01.cif"
    cand2 = cand_dir / "cand_02.cif"
    _make_cif(cand1, "Li2O", "restricted")
    _make_cif(cand2, "NaCl", "novel")

    manifest = {
        "candidates": [
            {"file": "cand_01.cif", "candidate_id": "cand-01", "predicted_energy": -1.0},
            {"file": "cand_02.cif", "candidate_id": "cand-02", "predicted_energy": -2.0},
        ]
    }
    (cand_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    propose = propose_candidates(
        db_path=str(db_path),
        run_name="phase4-eval",
        candidates_path=str(cand_dir),
        source="csp",
    )
    run_id = propose["run_id"]

    report_out = base_dir / "reports" / run_id
    report = generate_report(
        db_path=str(db_path),
        run_id=run_id,
        out_dir=str(report_out),
        k=5,
        threshold=25.0,
    )

    report_md = Path(report["report_path"])
    bundle_json = Path(report["bundle_path"])

    if not report_md.exists() or not bundle_json.exists():
        return {"error": "report_missing", "run_id": run_id}

    report_text = report_md.read_text(encoding="utf-8")
    bundle_text = bundle_json.read_text(encoding="utf-8")

    if "Crystal-DB Phase 4 Report" not in report_text:
        return {"error": "report_invalid", "run_id": run_id}

    if "data_restricted" in report_text or "data_restricted" in bundle_text:
        return {"error": "restricted_leak", "run_id": run_id}

    calibration_out = base_dir / "calibration"
    calibration = calibrate_novelty(db_path=str(db_path), k=10, out_dir=str(calibration_out))
    calibration_json = Path(calibration["json_path"]).read_text(encoding="utf-8")

    if "recommended_threshold" not in calibration_json:
        return {"error": "calibration_missing", "run_id": run_id}

    return {
        "status": "ok",
        "run_id": run_id,
        "report_dir": str(report_out),
        "calibration_dir": str(calibration_out),
    }


def main() -> int:
    base_dir = Path("data") / "phase4_eval"
    result = run_eval_phase4(base_dir)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
