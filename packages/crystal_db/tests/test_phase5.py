import json
from pathlib import Path

from crystal_db.crystalcard import build_crystalcard
from crystal_db.db import connect, init_db
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


def _structure_id_for_source(db_path: str, source: str, source_id: str) -> str:
    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT structure_id FROM provenance WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    conn.close()
    return row["structure_id"]


def test_crystalcard_deterministic(tmp_path):
    db_path = tmp_path / "crystal.db"
    gold_dir = Path(__file__).resolve().parents[1] / "data" / "gold"

    ingest_folder(
        db_path=str(db_path),
        folder_path=str(gold_dir),
        source="gold",
        policy_name="synthetic",
        cache_dir=None,
    )

    expectations = json.loads((gold_dir / "gold_expectations.json").read_text(encoding="utf-8"))
    sample = expectations[0]
    structure_id = _structure_id_for_source(str(db_path), "gold", sample["file"])

    card1 = build_crystalcard(structure_id=structure_id, db_path=str(db_path), engine="baseline")
    card2 = build_crystalcard(structure_id=structure_id, db_path=str(db_path), engine="baseline")

    assert card1["schema_version"] == "v1"
    assert card1["card_hash"] == card2["card_hash"]
    assert card1["summary"]["space_group"] == sample["space_group"]
    assert card1["summary"]["crystal_system"] == sample["crystal_system"]


def test_report_includes_crystalcard_section(tmp_path):
    db_path = tmp_path / "crystal.db"
    ingest_sample(db_path=str(db_path), count=6)

    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    _make_cif(cand_dir / "cand_01.cif", "Li2O", "cand01")

    manifest = {"candidates": [{"file": "cand_01.cif", "candidate_id": "cand-01"}]}
    (cand_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    propose = propose_candidates(
        db_path=str(db_path),
        run_name="phase5-report",
        candidates_path=str(cand_dir),
        source="csp",
    )
    run_id = propose["run_id"]

    report_out = tmp_path / "reports" / run_id
    report = generate_report(
        db_path=str(db_path),
        run_id=run_id,
        out_dir=str(report_out),
        k=3,
        threshold=25.0,
    )

    report_text = Path(report["report_path"]).read_text(encoding="utf-8")
    bundle = json.loads(Path(report["bundle_path"]).read_text(encoding="utf-8"))

    assert "CrystalCard (baseline):" in report_text
    assert "Neighbor CrystalCards:" in report_text
    assert bundle["results"]["cand-01"]["crystalcard"]


def test_crystalcard_policy_restriction(tmp_path):
    db_path = tmp_path / "crystal.db"

    cif_dir = tmp_path / "restricted"
    cif_dir.mkdir()
    _make_cif(cif_dir / "restricted.cif", "Li2O", "restricted")

    ingest_folder(
        db_path=str(db_path),
        folder_path=str(cif_dir),
        source="restricted",
        policy_name="default",
        cache_dir=None,
    )

    structure_id = _structure_id_for_source(str(db_path), "restricted", "restricted.cif")
    card = build_crystalcard(structure_id=structure_id, db_path=str(db_path), engine="baseline")
    assert card.get("error") == "derivatives_restricted"
