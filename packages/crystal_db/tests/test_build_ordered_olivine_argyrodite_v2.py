from __future__ import annotations

import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from pymatgen.core import Lattice, Structure

from crystal_db.db import connect, init_db
from crystal_db.ingest_folder import _hash_text
from scripts.build_ordered_olivine_argyrodite_v2 import (
    artifacts_contain_secret,
    canonical_cif,
    pipeline_complete,
    register_structure_hash,
    smoke_queries,
    vectors_are_finite_1024,
)


def test_structural_deduplication_uses_canonical_crystaldb_hash():
    structure = Structure(Lattice.cubic(4), ["Li", "F"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    structure_hash = _hash_text(canonical_cif(structure))
    seen: dict[str, str] = {}

    assert register_structure_hash(seen, structure_hash, "mp-first") is None
    assert register_structure_hash(seen, structure_hash, "mp-duplicate") == "mp-first"
    assert len(seen) == 1


def test_pipeline_completeness_and_vector_dimension_are_strict():
    complete = {name: 2 for name in ("structures", "robocrys", "fingerprints", "vectors")}
    assert pipeline_complete(complete, 2)
    assert not pipeline_complete({**complete, "vectors": 1}, 2)
    assert vectors_are_finite_1024([(1024, [0.0] * 1024)], 1)
    assert not vectors_are_finite_1024([(64, [0.0] * 64)], 1)
    assert not vectors_are_finite_1024([(1024, [float("nan")] * 1024)], 1)


def test_retrieval_smoke_opens_database_and_records_family_metadata():
    with tempfile.TemporaryDirectory() as temporary_directory:
        database = Path(temporary_directory) / "smoke.sqlite"
        connection = connect(str(database))
        init_db(connection)
        structure_id = "materials_project-test"
        connection.execute(
            "INSERT INTO structures (structure_id,cif_text,reduced_formula,nsites,volume,license_restricted) VALUES (?,?,?,?,?,?)",
            (structure_id, "data_test\n", "LiFePO4", 28, 1.0, 0),
        )
        connection.execute(
            "INSERT INTO metadata (structure_id,formula,elements_csv,space_group,band_gap_eV) VALUES (?,?,?,?,?)",
            (structure_id, "LiFePO4", ",Fe,Li,O,P,", "Pnma", None),
        )
        connection.execute(
            "INSERT INTO structure_annotations (structure_id,corpus_id,topology_tier,family_assignment,family_assignment_method,family_assignment_evidence_json,source_version,chemical_system,crystal_system,number_of_sites,cif_sha256,exact_target_exclusion_status,near_duplicate_score,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (structure_id, "test", "STRUCTURALLY_VALIDATED_ORDERED", "OLIVINE", "test",
             json.dumps({"subtype": "OLIVINE_LIMPO4"}), "test", "Fe;Li;O;P", None,
             28, "hash", "not_evaluated", None, "2026-01-01T00:00:00Z"),
        )
        connection.commit()
        connection.close()
        retrieval = {"status": "ok", "neighbors": [{"structure_id": structure_id, "score": 1.0}]}
        with patch(
            "scripts.build_ordered_olivine_argyrodite_v2.text_search", return_value=retrieval
        ):
            rows = smoke_queries(
                "OLIVINE", database, [{"subtype": "OLIVINE_LIMPO4"}]
            )

    assert len(rows) == 4
    assert all(row["family_consistency"] for row in rows)
    assert all(row["subtypes"] == "OLIVINE_LIMPO4" for row in rows)


def test_secret_scanner_checks_text_artifacts_without_reading_environment():
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        (root / "manifest.json").write_text('{"api_secret_persisted": false}', encoding="utf-8")
        assert artifacts_contain_secret(root, "test-secret-value") is False
        (root / "bad.csv").write_text("test-secret-value", encoding="utf-8")
        assert artifacts_contain_secret(root, "test-secret-value") is True
