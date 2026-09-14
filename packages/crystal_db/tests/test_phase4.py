import json
from pathlib import Path

from crystal_db.calibrate import calibrate_novelty
from crystal_db.ingest import ingest_sample
from crystal_db.ingest_folder import ingest_folder
from crystal_db.propose import propose_candidates
from crystal_db.report import generate_report
from eval_phase4 import run_eval_phase4


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


def test_propose_and_report(tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=8)

    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    _make_cif(cand_dir / "cand_01.cif", "Li2O", "cand01")
    _make_cif(cand_dir / "cand_02.cif", "NaCl", "cand02")

    manifest = {
        "candidates": [
            {"file": "cand_01.cif", "candidate_id": "cand-01", "predicted_energy": -1.0},
            {"file": "cand_02.cif", "candidate_id": "cand-02", "predicted_energy": -2.0},
        ]
    }
    (cand_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    propose = propose_candidates(
        db_path=str(db_path),
        run_name="test-run",
        candidates_path=str(cand_dir),
        source="csp",
    )
    run_id = propose["run_id"]
    assert len(propose["candidates"]) == 2

    report_out = tmp_path / "reports" / run_id
    report = generate_report(
        db_path=str(db_path),
        run_id=run_id,
        out_dir=str(report_out),
        k=5,
        threshold=25.0,
    )

    report_path = Path(report["report_path"])
    bundle_path = Path(report["bundle_path"])
    assert report_path.exists()
    assert bundle_path.exists()
    assert "Candidate Summary" in report_path.read_text(encoding="utf-8")


def test_restricted_redaction_in_report(tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=6)

    restricted_dir = tmp_path / "restricted"
    restricted_dir.mkdir()
    restricted_cif = restricted_dir / "restricted.cif"
    _make_cif(restricted_cif, "Li2O", "restricted")

    ingest_folder(
        db_path=str(db_path),
        folder_path=str(restricted_dir),
        source="local_cif",
        policy_name="restricted",
        cache_dir=None,
    )

    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    _make_cif(cand_dir / "cand_01.cif", "Li2O", "restricted")
    (cand_dir / "manifest.json").write_text(
        json.dumps({"candidates": [{"file": "cand_01.cif", "candidate_id": "cand-01"}]}, indent=2),
        encoding="utf-8",
    )

    propose = propose_candidates(
        db_path=str(db_path),
        run_name="restricted-run",
        candidates_path=str(cand_dir),
        source="csp",
    )
    run_id = propose["run_id"]

    report_out = tmp_path / "reports" / run_id
    report = generate_report(
        db_path=str(db_path),
        run_id=run_id,
        out_dir=str(report_out),
        k=5,
        threshold=25.0,
    )

    report_text = Path(report["report_path"]).read_text(encoding="utf-8")
    bundle_text = Path(report["bundle_path"]).read_text(encoding="utf-8")
    assert "data_restricted" not in report_text
    assert "data_restricted" not in bundle_text
    assert "redacted" in bundle_text


def test_calibrate_outputs(tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=12)

    out_dir = tmp_path / "calibration"
    result = calibrate_novelty(db_path=str(db_path), k=10, out_dir=str(out_dir))
    calibration = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert calibration.get("recommended_threshold") is not None


def test_eval_phase4_end_to_end(tmp_path):
    result = run_eval_phase4(tmp_path / "phase4_eval")
    assert result.get("status") == "ok"
