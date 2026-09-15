from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_paper_result_section_smokes.py"
SPEC = importlib.util.spec_from_file_location("run_paper_result_section_smokes", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
paper_smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paper_smoke)


def test_paper_smoke_labels_only_explicit_simple_rows_variable_spp() -> None:
    pot = {"pot_coverage_status": "complete", "missing_pairs": []}
    solver = {"support_status": "fixed_orbit_supported"}
    retrieval = {"retrieval_status": "hit"}

    assert paper_smoke._expected_tier({"formula": "NiO", "source_status": "OK"}, pot, solver, retrieval) == "variable_spp_scored"
    assert paper_smoke._expected_tier({"formula": "CeO2", "source_status": "OK"}, pot, solver, retrieval) == "variable_spp_scored"
    assert paper_smoke._expected_tier({"formula": "CsPbBr3", "source_status": "OK"}, pot, solver, retrieval) == "variable_spp_scored"
    assert paper_smoke._expected_tier({"formula": "CsSnI3", "source_status": "OK"}, pot, {"support_status": "retrieval_only"}, retrieval) == "variable_spp_scored"


def test_paper_smoke_preserves_blocked_tiers() -> None:
    pot = {"pot_coverage_status": "complete", "missing_pairs": []}
    retrieval = {"retrieval_status": "hit"}

    assert (
        paper_smoke._expected_tier(
            {"formula": "KPbBr3", "source_status": "MISSING"},
            pot,
            {"support_status": "retrieval_only"},
            retrieval,
        )
        == "missing_from_source"
    )
    assert (
        paper_smoke._expected_tier(
            {"formula": "CoAs2", "source_status": "OK"},
            pot,
            {"support_status": "retrieval_only"},
            retrieval,
        )
        == "retrieval_ready_solver_blocked"
    )
    assert (
        paper_smoke._expected_tier(
            {"formula": "RbPbBr3", "source_status": "OK"},
            pot,
            {"support_status": "retrieval_only"},
            retrieval,
        )
        == "parameterised_wyckoff_required"
    )


def test_paper_smoke_halide_extensibility_metadata_marks_source_symmetry_honestly() -> None:
    orthorhombic_source = {
        "dataset_id": "halide_perovskite",
        "source_symmetry": {"number": 62, "symbol": "Pnma"},
    }
    cubic_source = {
        "dataset_id": "halide_perovskite",
        "source_symmetry": {"number": 221, "symbol": "Pm-3m"},
    }

    ortho_meta = paper_smoke._extensibility_metadata("CsPbBr3", orthorhombic_source, generated=True, target_sg_number=221)
    cubic_meta = paper_smoke._extensibility_metadata("CsSnI3", cubic_source, generated=True, target_sg_number=221)

    assert ortho_meta["extension_case"] == "halide_perovskite_specialist_corpus"
    assert ortho_meta["prototype_constraint_mode"] == "ideal_cubic_abx3"
    assert ortho_meta["source_faithful_symmetry"] is False
    assert ortho_meta["pipeline_changes_required"] == "qlip_scaffold_only_no_retrieval_spp_validation_changes"
    assert cubic_meta["source_faithful_symmetry"] is True
