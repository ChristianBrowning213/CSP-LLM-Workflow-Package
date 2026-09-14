import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile

from crystal_db.db import init_db


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_paper_scaffolds_specialist_corpora.py"
SPEC = importlib.util.spec_from_file_location("audit_paper_scaffolds_specialist_corpora", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit)


def test_structure_hash_count_and_pipeline_coverage_are_audited_without_mutation():
    with tempfile.TemporaryDirectory() as temporary_directory:
        db_path = Path(temporary_directory) / "fixture.db"
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        init_db(connection)
        cif = (
            "data_fixture\n_symmetry_space_group_name_H-M 'P1'\n"
            "_cell_length_a 5\n_cell_length_b 5\n_cell_length_c 5\n"
            "_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n"
            "_chemical_formula_sum 'Li2 O1'\n"
            "loop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n"
            "_atom_site_fract_y\n_atom_site_fract_z\nLi1 Li 0 0 0\nLi2 Li 0.5 0.5 0.5\nO1 O 0.25 0.25 0.25\n"
        )
        for structure_id in ("one", "two"):
            connection.execute(
                "INSERT INTO structures VALUES (?,?,?,?,?,?)",
                (structure_id, cif, "Li2O", 3, 125.0, 0),
            )
            connection.execute(
                "INSERT INTO metadata VALUES (?,?,?,?,?)",
                (structure_id, "Li2O", ",Li,O,", "P1", None),
            )
            connection.execute(
                "INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?,?,?)",
                (structure_id, "fixture", structure_id, "2026-01-01T00:00:00Z", "", "synthetic", 1, 1, 1, 1),
            )
        connection.commit()
        connection.close()
        original_hash = audit.sha256_file(db_path)

        result = audit.audit_database(db_path, run_retrieval=False)

        assert result["row_count"] == 2
        assert result["unique_structure_hashes"] == 1
        assert result["duplicate_rate"] == 0.5
        assert result["robocrys_rows"] == 0
        assert result["paper_suitable"] is False
        assert audit.sha256_file(db_path) == original_hash


def test_provenance_output_never_contains_environment_secret(monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "must-not-be-written")
    with tempfile.TemporaryDirectory() as temporary_directory:
        output_root = Path(temporary_directory)
        audit.write_outputs(output_root, [], [
            {
                "family": family,
                "existing_corpus": "",
                "existing_path": "",
                "existing_rows": 0,
                "hash_unique": 0,
                "robocrys_complete": False,
                "fingerprint_complete": False,
                "vector_complete": False,
                "retrieval_ready": False,
                "family_validation_method": "fixture",
                "validated_family_rows": 0,
                "composition_count": 0,
                "space_group_count": 0,
                "median_atoms_primitive": None,
                "max_atoms_primitive": None,
                "decision": "CREATE_NEW",
                "reason": "fixture",
            }
            for family in audit.TARGET_FAMILIES
        ])
        payload = "\n".join(
            path.read_text(encoding="utf-8")
            for path in output_root.rglob("*")
            if path.is_file()
        )
        assert "must-not-be-written" not in payload
        assert json.loads((output_root / "PROVENANCE.json").read_text(encoding="utf-8"))["api_secret_persisted"] is False


def test_legacy_text_docs_without_text_view_are_audited():
    with tempfile.TemporaryDirectory() as temporary_directory:
        db_path = Path(temporary_directory) / "legacy.db"
        connection = sqlite3.connect(db_path)
        connection.execute(
            "CREATE TABLE structures (structure_id TEXT PRIMARY KEY,cif_text TEXT,reduced_formula TEXT,nsites INTEGER,volume REAL,license_restricted INTEGER)"
        )
        connection.execute(
            "CREATE TABLE text_docs (id INTEGER PRIMARY KEY,structure_id TEXT,engine TEXT,engine_version TEXT,text TEXT,status TEXT)"
        )
        connection.execute(
            "INSERT INTO structures VALUES ('one',NULL,'Li2O',3,125,0)"
        )
        connection.execute(
            "INSERT INTO text_docs VALUES (1,'one','robocrys','robocrys.v1','description','OK')"
        )
        connection.commit()
        connection.close()

        result = audit.audit_database(db_path, run_retrieval=False)

        assert result["robocrys_rows"] == 1
        assert result["robocrys_condensed_rows"] == 0


def test_database_inventory_accepts_extra_read_only_roots():
    with tempfile.TemporaryDirectory() as temporary_directory:
        extra_root = Path(temporary_directory)
        (extra_root / "external.sqlite").write_bytes(b"fixture")

        paths = audit.database_paths(Path(temporary_directory) / "missing", [extra_root])

        assert paths == [(extra_root / "external.sqlite").resolve()]


def test_generic_crystaldb_filename_uses_parent_corpus_name():
    with tempfile.TemporaryDirectory() as temporary_directory:
        db_path = Path(temporary_directory) / "named_corpus" / "crystaldb.sqlite"
        db_path.parent.mkdir()
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        try:
            init_db(connection)
        finally:
            connection.close()

        result = audit.audit_database(db_path, run_retrieval=False)

        assert result["corpus_name"] == "named_corpus"


def test_topology_tier_counts_are_loaded_from_frozen_manifest():
    with tempfile.TemporaryDirectory() as temporary_directory:
        manifest = Path(temporary_directory) / "manifest.jsonl"
        manifest.write_text(
            '{"topology_tier":"TIER_1_TOPOLOGY_PROXY"}\n'
            '{"topology_tier":"TIER_2_CHEMICAL_FRAMEWORK"}\n'
            '{"topology_tier":"TIER_1_TOPOLOGY_PROXY"}\n',
            encoding="utf-8",
        )

        assert audit.topology_tier_counts_from_manifest(manifest) == {
            "TIER_1_TOPOLOGY_PROXY": 2,
            "TIER_2_CHEMICAL_FRAMEWORK": 1,
        }
