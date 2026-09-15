from __future__ import annotations

import csv
import sqlite3
import tempfile
from pathlib import Path

from sok_llm_orchestrator.experiments.paper_workflow import REQUIRED_COLUMNS, run_paper_workflow


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE structures (structure_id TEXT PRIMARY KEY, reduced_formula TEXT, cif_text TEXT)")
    conn.execute("CREATE TABLE metadata (structure_id TEXT, formula TEXT, space_group TEXT)")
    conn.execute("CREATE TABLE provenance (structure_id TEXT, source TEXT, source_id TEXT, allow_export INTEGER)")
    conn.execute("CREATE TABLE text_docs (structure_id TEXT, text TEXT)")
    cif = """# generated fixture
data_NaCl
_symmetry_space_group_name_H-M   'Fm-3m'
_cell_length_a   5.640
_cell_length_b   5.640
_cell_length_c   5.640
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_Int_Tables_number 225
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
Na1 Na 0 0 0
Cl1 Cl 0.5 0.5 0.5
"""
    conn.execute("INSERT INTO structures VALUES (?, ?, ?)", ("fixture-nacl", "NaCl", cif))
    conn.execute("INSERT INTO metadata VALUES (?, ?, ?)", ("fixture-nacl", "NaCl", "Fm-3m"))
    conn.execute("INSERT INTO provenance VALUES (?, ?, ?, ?)", ("fixture-nacl", "fixture", "fixture-nacl", 1))
    conn.execute("INSERT INTO text_docs VALUES (?, ?)", ("fixture-nacl", "rocksalt sodium chloride NaCl halide evidence"))
    conn.commit()
    conn.close()


def _write_csv(path: Path, *, should_generate: str = "false") -> None:
    row = {
        "experiment_id": "fixture_experiment",
        "row_id": "fixture_nacl",
        "input_text": "Attempt a rocksalt sodium chloride structure.",
        "target_formula": "NaCl",
        "target_reduced_formula": "NaCl",
        "target_family": "rocksalt",
        "target_space_group_symbol": "Fm-3m",
        "target_space_group_number": "225",
        "target_crystal_system": "cubic",
        "expected_mode": "retrieval_only",
        "expected_validation_tier": "retrieval_ready_solver_blocked",
        "source_db_scope": "fixture",
        "retrieval_query_hint": "rocksalt sodium chloride NaCl halide evidence",
        "spp_required": "true",
        "qlip_scaffold_hint": "rocksalt",
        "should_generate": should_generate,
        "expected_blocker_if_any": "fixture blocked row",
        "paper_task": "fixture",
        "notes": "tiny fixture",
    }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerow(row)


def test_fixture_run_writes_archival_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "fixture.db"
        csv_path = tmp_path / "input.csv"
        out_root = tmp_path / "run"
        artifacts = tmp_path / "artifacts"
        _make_db(db_path)
        _write_csv(csv_path)

        summary = run_paper_workflow(
            source_db=db_path,
            input_text_csv=csv_path,
            out_root=out_root,
            experiment_id="fixture_experiment",
            crystaldb_root=tmp_path,
            artifacts_dir=artifacts,
            make_workflow_diagrams=True,
        )

        row_dir = out_root / "fixture_nacl"
        assert summary["row_count"] == 1
        assert summary["blocked_count"] == 1
        assert (row_dir / "failure_reason.json").exists()
        assert (row_dir / "workflow_diagram.svg").exists()
        assert (row_dir / "artifact_manifest.json").exists()
        assert (out_root / "EXPERIMENT_ARCHIVE_MANIFEST.json").exists()


def test_trace_records_no_direct_mp_lookup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "fixture.db"
        csv_path = tmp_path / "input.csv"
        _make_db(db_path)
        _write_csv(csv_path)

        run_paper_workflow(
            source_db=db_path,
            input_text_csv=csv_path,
            out_root=tmp_path / "run",
            experiment_id="fixture_experiment",
            crystaldb_root=tmp_path,
            artifacts_dir=tmp_path / "artifacts",
            make_workflow_diagrams=True,
        )
        trace = (tmp_path / "run" / "fixture_nacl" / "workflow_trace.json").read_text(encoding="utf-8")
        assert '"used_direct_mp_generation_lookup": false' in trace
