from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from sok_llm_orchestrator.agentic import robocrys_adapter
from sok_llm_orchestrator.agentic.robocrys_intent_validator import (
    build_llm_intent_judge_prompt,
    combine_rule_based_and_llm_validation,
    decompose_requirement_phrase,
    extract_robocrys_vocabulary_features,
    judge_robocrys_intent_alignment_with_llm,
    summarize_intent_validation_results,
)
from sok_llm_orchestrator.agentic.robocrys_intent_validator import validate_generated_cif_against_query


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_paper_evidence_pack_v2.py"
CSV_PATH = REPO_ROOT / "challenge_queries_100.csv"


def test_perovskite_description_is_aligned() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate BaTiO3 perovskite with corner-sharing TiO6 octahedra.",
        crystal_db_retrieval_query="BaTiO3 perovskite structured oxide with TiO6 octahedra and corner-sharing octahedral tilt angles.",
        generated_cif_robocrys_description=(
            "BaTiO3 is Perovskite structured and crystallizes in the tetragonal space group. "
            "Ti is bonded to six O atoms to form corner-sharing TiO6 octahedra. "
            "The corner-sharing octahedral tilt angles are small."
        ),
        target_formula="BaTiO3",
        chemistry_family="oxide_perovskite",
        expected_motifs_or_priors="corner-sharing TiO6 octahedra; perovskite topology",
    )

    assert result["available"] is True
    assert result["judgement"] == "aligned"
    assert result["scores"]["overall_intent_alignment"] >= 0.75


def test_condensed_json_implicit_match_relaxes_phrase_literal_batio3() -> None:
    condensed = {
        "dimensionality": "3",
        "sites": {
            "0": {"element": "Ba", "nn": [2, 2, 2, 2], "geometry": {"type": "8-coordinate"}},
            "1": {"element": "Ti", "nn": [2, 2, 2, 2, 3, 3], "geometry": {"type": "6-coordinate"}, "nnn": {"corner": [1, 1]}},
            "2": {"element": "O", "nn": [1, 1]},
            "3": {"element": "O", "nn": [1, 1]},
        },
        "angles": {"1": {"1": {"corner": [180.0]}}},
    }
    result = validate_generated_cif_against_query(
        original_query="Generate BaTiO3 perovskite with corner-sharing TiO6 octahedra.",
        crystal_db_retrieval_query="BaTiO3 perovskite structured oxide with TiO6 octahedra and corner-sharing octahedra.",
        generated_cif_robocrys_description="BaTiO3 crystallizes in an orthorhombic space group. Ti is bonded to O atoms.",
        target_formula="BaTiO3",
        chemistry_family="oxide_perovskite",
        expected_motifs_or_priors="TiO6 octahedra; corner-sharing octahedra",
        generated_cif_condensed_structure=condensed,
        validator_requirements=[
            {
                "id": "coordination.tio6",
                "category": "coordination",
                "label": "TiO6 octahedra",
                "aliases": ["TiO6", "Ti bonded to six O atoms"],
                "center_element": "Ti",
                "ligand_element": "O",
                "coordination_number": 6,
            },
            {
                "id": "connectivity.corner_sharing",
                "category": "connectivity",
                "label": "corner-sharing",
                "aliases": ["corner-sharing"],
            },
        ],
    )

    evidence = result["requirement_evidence"]
    assert evidence["implicit_condensed_match_count"] >= 2
    assert evidence["missing_count"] == 0
    assert result["scores"]["requirement_match"] == 1.0


def test_corpus_calibrated_batio3_alias_and_condensed_evidence_not_incorrect() -> None:
    condensed = {
        "sites": {
            "0": {"element": "Ba", "nn": [2, 2, 2, 2, 3, 3, 3, 3], "geometry": {"type": "8-coordinate"}},
            "1": {"element": "Ti", "nn": [2, 2, 2, 2, 3, 3], "geometry": {"type": "6-coordinate"}, "nnn": {"corner": [1, 1]}},
            "2": {"element": "O", "nn": [1, 1]},
            "3": {"element": "O", "nn": [1, 1]},
        },
        "angles": {"1": {"1": {"corner": [179.9]}}},
    }
    result = validate_generated_cif_against_query(
        original_query="Generate BaTiO3 with corner-sharing TiO6 octahedra.",
        crystal_db_retrieval_query="BaTiO3 perovskite-like oxide with TiO6-like 6-coordinate environments and corner-sharing connectivity.",
        generated_cif_robocrys_description=(
            "BaTiO3 crystallizes in the orthorhombic Pmm2 space group. "
            "Ba is bonded in a 8-coordinate geometry to O atoms. "
            "Ti is bonded in a 6-coordinate geometry to O atoms. "
            "All Ti-O bond lengths are 1.95 A."
        ),
        target_formula="BaTiO3",
        chemistry_family="oxide_perovskite",
        generated_cif_condensed_structure=condensed,
        validator_requirements=[
            {
                "id": "coordination.tio6",
                "category": "coordination",
                "label": "TiO6-like environment",
                "aliases": ["TiO6", "Ti-O 6-coordinate"],
                "center_element": "Ti",
                "ligand_element": "O",
                "coordination_number": 6,
            },
            {"id": "connectivity.corner_sharing", "category": "connectivity", "label": "corner-sharing", "aliases": ["corner-sharing"]},
        ],
    )

    evidence = result["requirement_evidence"]
    assert evidence["alias_text_match_count"] >= 1
    assert evidence["implicit_condensed_match_count"] >= 1
    assert result["judgement"] in {"aligned", "partially_aligned"}


def test_prototype_word_absence_is_supporting_penalty_not_incorrect() -> None:
    condensed = {
        "sites": {
            "1": {"element": "Ti", "nn": [2, 2, 2, 2, 3, 3], "geometry": {"type": "6-coordinate"}, "nnn": {"corner": [1, 1]}},
            "2": {"element": "O", "nn": [1, 1]},
            "3": {"element": "O", "nn": [1, 1]},
        },
        "angles": {"1": {"1": {"corner": [180.0]}}},
    }
    result = validate_generated_cif_against_query(
        original_query="Generate BaTiO3 perovskite topology with corner-sharing TiO6 octahedra.",
        crystal_db_retrieval_query="BaTiO3 perovskite structured TiO6 octahedra corner-sharing",
        generated_cif_robocrys_description=(
            "BaTiO3 crystallizes in the Pmm2 space group. "
            "Ti is bonded in a 6-coordinate geometry to O atoms. "
            "All Ti-O bond lengths are 1.92 A."
        ),
        target_formula="BaTiO3",
        chemistry_family="oxide_perovskite",
        generated_cif_condensed_structure=condensed,
        validator_requirements=[
            {"id": "prototype.perovskite_structured", "category": "prototype", "label": "perovskite structured", "aliases": ["perovskite structured"]},
            {"id": "coordination.tio6", "category": "coordination", "label": "TiO6 octahedra", "aliases": ["TiO6"], "center_element": "Ti", "ligand_element": "O", "coordination_number": 6},
            {"id": "connectivity.corner_sharing", "category": "connectivity", "label": "corner-sharing", "aliases": ["corner-sharing"]},
        ],
    )

    evidence = result["requirement_evidence"]
    rows = {item["id"]: item for item in evidence["requirements"]}
    assert rows["prototype.perovskite_structured"]["requirement_type"] == "supporting_label"
    assert rows["prototype.perovskite_structured"]["penalty_weight"] == "low"
    assert rows["coordination.tio6"]["requirement_type"] == "core_structural"
    assert evidence["core_structural_score"] >= 0.8
    assert result["judgement"] != "not_aligned"


def test_requirement_decomposition_splits_corner_sharing_tio6() -> None:
    requirements = decompose_requirement_phrase("corner-sharing TiO6 octahedra")
    labels = {item["label"] for item in requirements}
    assert "TiO6" in labels
    assert "corner-sharing" in labels


def test_formula_only_description_does_not_become_correct() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate BaTiO3.",
        crystal_db_retrieval_query="BaTiO3.",
        generated_cif_robocrys_description="BaTiO3 crystallizes in a cubic cell.",
        target_formula="BaTiO3",
    )

    assert result["scores"]["formula_match"] == 1.0
    assert result["scores"]["overall_intent_alignment"] == 0.0
    assert result["judgement"] == "not_aligned"


def test_intent_specificity_changes_rule_based_thresholds() -> None:
    common = {
        "original_query": "Generate BaTiO3 oxide with broad design intent.",
        "crystal_db_retrieval_query": "BaTiO3 oxide broad design intent.",
        "generated_cif_robocrys_description": "BaTiO3 crystallizes in a plausible oxide structure.",
        "target_formula": "BaTiO3",
        "chemistry_family": "oxide_perovskite",
        "expected_motifs_or_priors": "",
    }

    loose = validate_generated_cif_against_query(**common, intent_specificity="loose")
    specific = validate_generated_cif_against_query(**common, intent_specificity="specific")

    assert loose["intent_specificity"] == "loose"
    assert loose["specificity_thresholds"] == {"aligned": 0.45, "partial": 0.25}
    assert loose["judgement"] == "partially_aligned"
    assert specific["intent_specificity"] == "specific"
    assert specific["specificity_thresholds"] == {"aligned": 0.75, "partial": 0.5}
    assert specific["judgement"] == "not_aligned"


def test_core_structural_missing_remains_incorrect() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate corner-sharing TiO6-like environment.",
        crystal_db_retrieval_query="BaTiO3 TiO6 octahedra corner-sharing",
        generated_cif_robocrys_description="BaTiO3 crystallizes in a cell. Ba is bonded to O atoms.",
        target_formula="BaTiO3",
        chemistry_family="oxide_perovskite",
        validator_requirements=[
            {"id": "coordination.tio6", "category": "coordination", "label": "TiO6 octahedra", "aliases": ["TiO6"], "center_element": "Ti", "ligand_element": "O", "coordination_number": 6},
            {"id": "connectivity.corner_sharing", "category": "connectivity", "label": "corner-sharing", "aliases": ["corner-sharing"]},
        ],
    )

    assert result["requirement_evidence"]["core_structural_score"] == 0.0
    assert result["judgement"] == "not_aligned"


def test_tetrahedral_geometry_accepts_four_coordinate_alias_as_partial_support() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate an oxide with tetrahedral geometry around M.",
        crystal_db_retrieval_query="M oxide with tetrahedral geometry and MX4-like environment.",
        generated_cif_robocrys_description="M is bonded in a 4-coordinate geometry to O atoms. All M-O bond lengths are similar.",
        target_formula="MO2",
        validator_requirements=[
            {
                "id": "coordination.mo4_geometry",
                "category": "coordination",
                "label": "tetrahedral geometry",
                "aliases": ["tetrahedral geometry"],
            },
            {
                "id": "connectivity.corner_sharing",
                "category": "connectivity",
                "label": "corner-sharing",
                "aliases": ["corner-sharing"],
            },
        ],
    )

    evidence = result["requirement_evidence"]
    assert evidence["alias_text_match_count"] == 1
    assert result["judgement"] == "partially_aligned"


def test_octahedral_geometry_accepts_six_coordinate_alias_as_partial_support() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate an oxide with octahedral geometry around M.",
        crystal_db_retrieval_query="M oxide with octahedral geometry and MX6-like environment.",
        generated_cif_robocrys_description="M is bonded in a 6-coordinate geometry to O atoms. All M-O bond lengths are similar.",
        target_formula="MO3",
        validator_requirements=[
            {
                "id": "coordination.mo6_geometry",
                "category": "coordination",
                "label": "octahedral geometry",
                "aliases": ["octahedral geometry"],
            },
            {
                "id": "connectivity.edge_sharing",
                "category": "connectivity",
                "label": "edge-sharing",
                "aliases": ["edge-sharing"],
            },
        ],
    )

    evidence = result["requirement_evidence"]
    assert evidence["alias_text_match_count"] == 1
    assert result["judgement"] == "partially_aligned"


def test_generic_tetrahedral_geometry_does_not_match_anion_centered_coordination() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate chalcopyrite-like CuFeS2 with tetrahedral sulfide coordination.",
        crystal_db_retrieval_query="CuFeS2 chalcopyrite-like tetrahedral geometry Cu-S bond lengths Fe-S bond lengths.",
        generated_cif_robocrys_description=(
            "CuFeS2 crystallizes in an orthorhombic space group. "
            "Fe is bonded in a 6-coordinate geometry to S atoms. "
            "Cu is bonded in a 6-coordinate geometry to S atoms. "
            "S is bonded in a 4-coordinate geometry to two equivalent Fe and two equivalent Cu atoms."
        ),
        target_formula="CuFeS2",
        validator_requirements=[
            {"id": "prototype.chalcopyrite_like", "category": "prototype", "label": "chalcopyrite-like", "aliases": ["chalcopyrite-like"]},
            {"id": "coordination.tetrahedral_geometry", "category": "coordination", "label": "tetrahedral geometry", "aliases": ["tetrahedral geometry"]},
            {"id": "coordination.tetrahedra", "category": "coordination", "label": "tetrahedra", "aliases": ["tetrahedra"]},
        ],
    )

    evidence = result["requirement_evidence"]
    assert evidence["alias_text_match_count"] == 0
    assert evidence["core_structural_score"] == 0.0
    assert result["judgement"] == "not_aligned"


def test_requested_n_coordination_absence_remains_not_aligned() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate a nitride with tetrahedral M-N coordination.",
        crystal_db_retrieval_query="M nitride with MN4 tetrahedra and bonded to N atoms.",
        generated_cif_robocrys_description="M is bonded in a 4-coordinate geometry to O atoms. There is no nitrogen coordination described.",
        target_formula="MN",
        validator_requirements=[
            {
                "id": "coordination.mn4",
                "category": "coordination",
                "label": "MN4 tetrahedra",
                "aliases": ["MN4", "M bonded to four N atoms"],
                "center_element": "M",
                "ligand_element": "N",
                "coordination_number": 4,
            }
        ],
    )

    assert result["requirement_evidence"]["core_structural_score"] == 0.0
    assert result["judgement"] == "not_aligned"


def test_spinel_description_is_partially_aligned_when_tetrahedral_site_missing() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate MgAl2O4 spinel with MgO4 tetrahedra and AlO6 octahedra.",
        crystal_db_retrieval_query="MgAl2O4 spinel structured oxide with MgO4 tetrahedra, AlO6 octahedra, tetrahedral geometry, and octahedral geometry.",
        generated_cif_robocrys_description=(
            "MgAl2O4 crystallizes in a cubic structure. "
            "Al is bonded to O atoms to form AlO6 octahedra with octahedral geometry."
        ),
        target_formula="MgAl2O4",
        chemistry_family="oxide_spinel",
        expected_motifs_or_priors="MgO4 tetrahedra; AlO6 octahedra",
    )

    assert result["judgement"] == "partially_aligned"
    assert any(term.lower() == "mgo4" for term in result["missing_terms"]["coordination_terms"])


def test_layered_query_vs_rocksalt_description_is_not_aligned() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate layered MoS2 sheets.",
        crystal_db_retrieval_query="MoS2 molybdenite structured two-dimensional MoS2 sheets with edge-sharing polyhedra.",
        generated_cif_robocrys_description=(
            "MoS2 is Rocksalt structured and crystallizes in a cubic three-dimensional lattice. "
            "Mo is bonded in octahedral geometry to S atoms."
        ),
        target_formula="MoS2",
        chemistry_family="layered_chalcogenide",
        expected_motifs_or_priors="S-Mo-S sheets; layered van der Waals motif",
    )

    assert result["judgement"] == "not_aligned"
    assert result["scores"]["overall_intent_alignment"] < 0.45


def test_missing_robocrys_description_is_not_scored() -> None:
    result = validate_generated_cif_against_query(
        original_query="Generate BaTiO3 perovskite.",
        crystal_db_retrieval_query="BaTiO3 perovskite structured oxide.",
        generated_cif_robocrys_description=None,
        target_formula="BaTiO3",
    )

    assert result["available"] is False
    assert result["skip_reason"] == "robocrys_output_unavailable"
    assert result["judgement"] == "not_scored"


def test_external_robocrys_subprocess_success_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory(prefix="robocrys_external_test_") as tmp:
        root = Path(tmp)
        cif = root / "sample.cif"
        python = root / "python.exe"
        cif.write_text("data_sample\n", encoding="utf-8")
        python.write_text("", encoding="utf-8")
        payload = {
            "robocrys_available": True,
            "description": "BaTiO3 is Perovskite structured.",
            "condensed_structure": {"formula": "BaTiO3"},
            "engine": "robocrys",
            "text_view": "robocrys",
            "robocrys_version": "mock",
            "warnings": [],
            "error": None,
        }

        def fake_import(name: str):  # noqa: ANN001
            raise ModuleNotFoundError(name)

        def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        monkeypatch.setattr(robocrys_adapter.importlib, "import_module", fake_import)
        monkeypatch.setattr(robocrys_adapter.subprocess, "run", fake_run)
        result = robocrys_adapter.describe_cif_with_robocrys(cif, robocrys_python=str(python))
        assert result["robocrys_available"] is True
        assert result["description"] == payload["description"]
        assert result["condensed_structure"] == payload["condensed_structure"]


def test_external_robocrys_subprocess_failure_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory(prefix="robocrys_external_test_") as tmp:
        root = Path(tmp)
        cif = root / "sample.cif"
        python = root / "python.exe"
        cif.write_text("data_sample\n", encoding="utf-8")
        python.write_text("", encoding="utf-8")

        def fake_import(name: str):  # noqa: ANN001
            raise ModuleNotFoundError(name)

        def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            return SimpleNamespace(returncode=2, stdout="", stderr="import failed")

        monkeypatch.setattr(robocrys_adapter.importlib, "import_module", fake_import)
        monkeypatch.setattr(robocrys_adapter.subprocess, "run", fake_run)
        result = robocrys_adapter.describe_cif_with_robocrys(cif, robocrys_python=str(python))
        assert result["robocrys_available"] is False
        assert "external_robocrys_returncode:2" in result["error"]


def test_expected_motifs_raise_score_when_present() -> None:
    base_kwargs = {
        "original_query": "Generate pyrite-like FeS2.",
        "crystal_db_retrieval_query": "FeS2 pyrite structured disulfide with FeS6 octahedra and S-S dimer motifs.",
        "target_formula": "FeS2",
        "chemistry_family": "sulfide_pyrite",
        "expected_motifs_or_priors": "S-S dumbbells; FeS6 octahedra",
    }
    with_motifs = validate_generated_cif_against_query(
        generated_cif_robocrys_description="FeS2 is Pyrite structured. Fe is bonded to S atoms to form FeS6 octahedra with S-S dumbbells.",
        **base_kwargs,
    )
    without_motifs = validate_generated_cif_against_query(
        generated_cif_robocrys_description="FeS2 is a sulfide structure. Fe is bonded to S atoms.",
        **base_kwargs,
    )

    assert with_motifs["scores"]["overall_intent_alignment"] > without_motifs["scores"]["overall_intent_alignment"]


def test_llm_judge_prompt_includes_inputs_and_physical_validation_warning() -> None:
    prompt = build_llm_intent_judge_prompt(
        original_query="Generate BaTiO3 perovskite.",
        crystal_db_retrieval_query="BaTiO3 perovskite structured oxide with TiO6 octahedra.",
        generated_cif_robocrys_description="BaTiO3 is Perovskite structured.",
        target_formula="BaTiO3",
        chemistry_family="oxide_perovskite",
        expected_motifs_or_priors="TiO6 octahedra",
    )
    assert "Generate BaTiO3 perovskite." in prompt
    assert "BaTiO3 perovskite structured oxide" in prompt
    assert "BaTiO3 is Perovskite structured." in prompt
    assert "Do not judge thermodynamic stability" in prompt
    assert "Return JSON only" in prompt
    assert "exact polyhedral formula strings such as TiO6" in prompt
    assert "bonded in 6-coordinate geometry" in prompt
    assert "Prototype/family labels" in prompt
    assert "Prioritize core structural evidence" in prompt
    assert "Formula-only matches are never sufficient" in prompt
    assert "Count condensed JSON evidence as implicit support" in prompt
    assert "Coordination-number evidence without exact geometry wording" in prompt
    assert "Do not mark incorrect merely because exact geometry words" in prompt


def test_final_decision_calibrates_overstrict_llm_with_core_evidence() -> None:
    rule = validate_generated_cif_against_query(
        "Generate MgAl2O4 spinel with MgO4 tetrahedra and AlO6 octahedra.",
        "MgAl2O4 spinel structured MgO4 tetrahedra AlO6 octahedra.",
        "MgAl2O4 crystallizes. Mg is bonded in a 4-coordinate geometry to O atoms. Al is bonded in a 6-coordinate geometry to O atoms.",
        target_formula="MgAl2O4",
        validator_requirements=[
            {"id": "prototype.spinel_structured", "category": "prototype", "label": "spinel structured", "aliases": ["spinel structured"]},
            {"id": "coordination.mgo4", "category": "coordination", "label": "MgO4 tetrahedra", "aliases": ["MgO4"], "center_element": "Mg", "ligand_element": "O", "coordination_number": 4},
            {"id": "coordination.alo6", "category": "coordination", "label": "AlO6 octahedra", "aliases": ["AlO6"], "center_element": "Al", "ligand_element": "O", "coordination_number": 6},
        ],
    )
    llm = {
        "available": True,
        "score": 0.55,
        "correct": False,
        "judgement": "incorrect",
        "explicit_text_matches": [],
        "alias_text_matches": ["Mg/O 4-coordinate", "Al/O 6-coordinate"],
        "implicit_condensed_matches": [],
        "matched_requirements": ["MgO4 tetrahedra", "AlO6 octahedra"],
        "missing_requirements": ["spinel structured"],
        "contradictions": [],
        "concerns": ["Missing spinel structured"],
        "explanation": "Overly strict prototype wording penalty.",
        "not_physical_validation_notice": True,
    }
    combined = combine_rule_based_and_llm_validation(rule, llm)
    assert combined["llm_judge"]["judgement"] == "incorrect"
    assert combined["final_decision"]["judgement"] == "partially_correct"
    assert combined["final_decision"]["decision_source"] == "llm_judge_calibrated_with_rule_based"


def test_final_decision_promotes_meaningful_incomplete_core_evidence_to_partial() -> None:
    rule = validate_generated_cif_against_query(
        "Generate ZnS with sphalerite-like tetrahedral Zn-S coordination.",
        "ZnS sphalerite tetrahedral geometry ZnS4 coordination.",
        "ZnS crystallizes. Zn is bonded in a 4-coordinate geometry to S atoms.",
        target_formula="ZnS",
        validator_requirements=[
            {"id": "prototype.sphalerite", "category": "prototype", "label": "sphalerite structured", "aliases": ["sphalerite structured"]},
            {"id": "coordination.zns4", "category": "coordination", "label": "ZnS4 tetrahedra", "aliases": ["ZnS4"], "center_element": "Zn", "ligand_element": "S", "coordination_number": 4},
            {"id": "coordination.tetrahedral_geometry", "category": "coordination", "label": "tetrahedral geometry", "aliases": ["tetrahedral geometry"]},
            {"id": "connectivity.corner_sharing", "category": "connectivity", "label": "corner-sharing", "aliases": ["corner-sharing"]},
        ],
    )
    llm = {
        "available": True,
        "score": 0.25,
        "correct": False,
        "judgement": "incorrect",
        "explicit_text_matches": [],
        "alias_text_matches": ["Zn/S 4-coordinate"],
        "implicit_condensed_matches": [],
        "matched_requirements": ["ZnS4 tetrahedra"],
        "missing_requirements": ["sphalerite structured", "corner-sharing"],
        "contradictions": [],
        "concerns": ["Missing exact sphalerite label and connectivity."],
        "explanation": "Too strict.",
        "not_physical_validation_notice": True,
    }
    combined = combine_rule_based_and_llm_validation(rule, llm)
    assert combined["final_decision"]["judgement"] == "partially_correct"
    assert combined["final_decision"]["correct"] is False


def test_llm_judge_prompt_includes_aliases_and_condensed_evidence() -> None:
    prompt = build_llm_intent_judge_prompt(
        original_query="Generate BaTiO3 perovskite.",
        crystal_db_retrieval_query="BaTiO3 perovskite structured oxide with TiO6 octahedra.",
        generated_cif_robocrys_description="BaTiO3 crystallizes in an orthorhombic space group.",
        target_formula="BaTiO3",
        chemistry_family="oxide_perovskite",
        validator_requirements=[
            {"id": "coordination.tio6", "label": "TiO6 octahedra", "aliases": ["TiO6", "Ti bonded to six O atoms"]}
        ],
        requirement_evidence={"implicit_condensed_match_count": 1},
        generated_cif_condensed_structure={"dimensionality": "3", "sites": {"1": {"element": "Ti", "geometry": {"type": "6-coordinate"}}}},
    )

    assert "calibrated_validator_requirements" in prompt
    assert "Ti bonded to six O atoms" in prompt
    assert "implicit_condensed_match_count" in prompt
    assert "generated_cif_condensed_structure_excerpt" in prompt


def test_robocrys_vocabulary_feature_extraction() -> None:
    features = extract_robocrys_vocabulary_features(
        "Ti is bonded to six O atoms to form TiO6 octahedra that share corners with TiO6 octahedra. "
        "The corner-sharing octahedral tilt angles are 180 degrees."
    )
    assert "TIO6" in features["polyhedra_terms"]
    assert "corner-sharing" in features["connectivity_terms"]
    assert features["has_space_group_language"] is False


def test_calibration_extracts_existing_text_docs_without_regeneration() -> None:
    from scripts.build_robocrys_vocabulary_calibration import build_calibration

    with tempfile.TemporaryDirectory(prefix="robocrys_calibration_test_") as tmp:
        root = Path(tmp)
        db_path = root / "calibration.db"
        csv_path = root / "challenge.csv"
        con = sqlite3.connect(db_path)
        try:
            con.execute(
                "CREATE TABLE text_docs (id INTEGER PRIMARY KEY, structure_id TEXT, engine TEXT, text_view TEXT, status TEXT, text TEXT)"
            )
            con.execute(
                "INSERT INTO text_docs (structure_id, engine, text_view, status, text) VALUES (?, ?, ?, ?, ?)",
                (
                    "mp-test",
                    "robocrys",
                    "robocrys",
                    "OK",
                    "BaTiO3 is perovskite structured. Ti is bonded to six O atoms to form TiO6 octahedra that share corners.",
                ),
            )
            con.commit()
        finally:
            con.close()
        csv_path.write_text(
            "case_id,short_name,target_formula,query,chemistry_family,challenge_type,expected_motifs_or_priors,difficulty_notes\n"
            "challenge_001,batio3,BaTiO3,Generate BaTiO3,oxide_perovskite,smoke,TiO6 octahedra,\n",
            encoding="utf-8",
        )
        calibration = build_calibration(db_path, csv_path, limit=10)
        assert calibration["text_doc_count"] == 1
        row = next(item for item in calibration["family_summary"] if item["chemistry_family"] == "oxide_perovskite")
        assert row["example_count"] == 1
        assert row["recommended_validator_strictness"] == "strict_motif_with_aliases"


def test_mock_llm_judge_json_response_is_parsed() -> None:
    class MockClient:
        def chat(self, **kwargs):  # noqa: ANN001
            content = json.dumps(
                {
                    "score": 0.82,
                    "correct": True,
                    "judgement": "correct",
                    "explicit_text_matches": ["perovskite"],
                    "alias_text_matches": [],
                    "implicit_condensed_matches": ["TiO6 octahedra"],
                    "matched_requirements": ["perovskite", "TiO6 octahedra"],
                    "missing_requirements": [],
                    "contradictions": [],
                    "concerns": [],
                    "explanation": "The description matches the requested motif.",
                    "not_physical_validation_notice": True,
                }
            )
            return {"choices": [{"message": {"content": content}}]}

    result = judge_robocrys_intent_alignment_with_llm(
        "Generate BaTiO3 perovskite.",
        "BaTiO3 perovskite structured oxide with TiO6 octahedra.",
        "BaTiO3 is Perovskite structured with TiO6 octahedra.",
        target_formula="BaTiO3",
        model_config={"client": MockClient()},
    )
    assert result["available"] is True
    assert result["score"] == 0.82
    assert result["judgement"] == "correct"
    assert result["correct"] is True


def test_malformed_llm_response_returns_not_scored() -> None:
    class MockClient:
        def chat(self, **kwargs):  # noqa: ANN001
            return {"choices": [{"message": {"content": "not-json"}}]}

    result = judge_robocrys_intent_alignment_with_llm(
        "Generate BaTiO3 perovskite.",
        "BaTiO3 perovskite structured oxide.",
        "BaTiO3 is Perovskite structured.",
        model_config={"client": MockClient()},
    )
    assert result["available"] is False
    assert result["judgement"] == "not_scored"
    assert result["skip_reason"] == "llm_json_parse_error"
    assert result["raw_response"] == "not-json"
    assert result["parse_error"]


def test_incomplete_llm_json_returns_json_parse_error() -> None:
    class MockClient:
        def chat(self, **kwargs):  # noqa: ANN001
            return {"choices": [{"message": {"content": '{"score": 0.5, "not_physical_validation_notice": true'}}]}

    result = judge_robocrys_intent_alignment_with_llm(
        "Generate BaTiO3 perovskite.",
        "BaTiO3 perovskite structured oxide.",
        "BaTiO3 is Perovskite structured.",
        model_config={"client": MockClient()},
    )
    assert result["available"] is False
    assert result["judgement"] == "not_scored"
    assert result["skip_reason"] == "llm_json_parse_error"
    assert "not_physical_validation_notice" in result["raw_response"]


def test_combined_validation_prefers_llm_when_available_and_keeps_rule_based() -> None:
    rule = validate_generated_cif_against_query(
        "Generate BaTiO3 perovskite.",
        "BaTiO3 perovskite structured oxide.",
        "BaTiO3 is Perovskite structured.",
        target_formula="BaTiO3",
    )
    llm = {
        "available": True,
        "score": 0.71,
        "correct": True,
        "judgement": "correct",
        "skip_reason": None,
        "explicit_text_matches": ["perovskite"],
        "alias_text_matches": [],
        "implicit_condensed_matches": [],
        "matched_requirements": ["perovskite"],
        "missing_requirements": [],
        "contradictions": [],
        "concerns": [],
        "explanation": "ok",
        "not_physical_validation_notice": True,
    }
    combined = combine_rule_based_and_llm_validation(rule, llm)
    assert combined["rule_based"]["available"] is True
    assert combined["llm_judge"]["available"] is True
    assert combined["final_decision"]["decision_source"] == "llm_judge"
    assert combined["final_decision"]["correct"] is True


def test_summary_uses_explicit_counts_without_x_y_correct() -> None:
    rule = validate_generated_cif_against_query(
        "Generate BaTiO3 perovskite.",
        "BaTiO3 perovskite structured oxide.",
        "BaTiO3 is Perovskite structured.",
        target_formula="BaTiO3",
    )
    payload = combine_rule_based_and_llm_validation(rule)
    payload["intent_specificity"] = "loose"
    payload["benchmark_split"] = "loose_design_intent"
    summary = summarize_intent_validation_results([payload])
    assert "x_y_correct" not in summary
    assert summary["scored_count"] == 1
    assert summary["rule_based_scored_count"] == 1
    assert summary["llm_judged_count"] == 0
    assert summary["score_basis"] == "rule_based_fallback"
    assert summary["mean_llm_score"] is None
    assert summary["median_llm_score"] is None
    judgement = payload["final_decision"]["judgement"]
    assert summary["intent_specificity_counts"]["loose"][judgement] == 1
    assert summary["benchmark_split_counts"]["loose_design_intent"][judgement] == 1


def test_summary_counts_mocked_llm_judgement_separately_from_rule_based() -> None:
    rule = validate_generated_cif_against_query(
        "Generate BaTiO3 perovskite.",
        "BaTiO3 perovskite structured oxide.",
        "BaTiO3 is Perovskite structured.",
        target_formula="BaTiO3",
    )
    llm = {
        "available": True,
        "score": 0.8,
        "correct": True,
        "judgement": "correct",
        "skip_reason": None,
        "explicit_text_matches": ["perovskite"],
        "alias_text_matches": [],
        "implicit_condensed_matches": [],
        "matched_requirements": ["perovskite"],
        "missing_requirements": [],
        "contradictions": [],
        "concerns": [],
        "explanation": "ok",
        "not_physical_validation_notice": True,
    }
    summary = summarize_intent_validation_results([combine_rule_based_and_llm_validation(rule, llm)])
    assert summary["llm_judged_count"] == 1
    assert summary["rule_based_scored_count"] == 1
    assert summary["correct_count"] == 1
    assert summary["score_basis"] == "llm_judge"
    assert summary["mean_llm_score"] == 0.8
    assert summary["median_llm_score"] == 0.8


def test_runner_parser_defaults_llm_judge_backend_to_ollama() -> None:
    from scripts.run_paper_evidence_pack_v2 import _parser

    args = _parser().parse_args([])
    assert args.llm_intent_judge_backend == "ollama"


def test_runner_dry_run_validator_sidecar_is_not_scored_when_robocrys_unavailable() -> None:
    with tempfile.TemporaryDirectory(prefix="robocrys_intent_runner_test_") as tmp:
        out_root = Path(tmp) / "pack"
        command = [
            sys.executable,
            str(RUNNER),
            "--csv",
            str(CSV_PATH),
            "--out-root",
            str(out_root),
            "--limit",
            "1",
            "--dry-run",
            "--use-robocrys-query-skill",
            "--validate-robocrys-intent-alignment",
        ]
        subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=True)
        manifest = json.loads((out_root / "manifests" / "paper_evidence_pack_v2_manifest.json").read_text(encoding="utf-8"))
        row = manifest["rows"][0]
        assert row["robocrys_intent_judgement"] == "not_scored"
        assert row["robocrys_intent_skip_reason"] == "robocrys_output_unavailable"
        validation_path = REPO_ROOT / row["robocrys_intent_validation_path"]
        if not validation_path.exists():
            validation_path = out_root / row["case_dir"].split("raw_runs", 1)[-1].strip("\\/") / "robocrys" / "robocrys_intent_validation.json"
        assert validation_path.exists()
        payload = json.loads(validation_path.read_text(encoding="utf-8"))
        assert "rule_based" in payload
        assert "llm_judge" in payload
        assert payload["final_decision"]["judgement"] == "not_scored"
        assert payload["final_decision"]["decision_source"] == "not_scored"


def test_runner_dry_run_with_llm_enabled_does_not_attempt_llm_without_robocrys() -> None:
    with tempfile.TemporaryDirectory(prefix="robocrys_intent_runner_test_") as tmp:
        out_root = Path(tmp) / "pack"
        command = [
            sys.executable,
            str(RUNNER),
            "--csv",
            str(CSV_PATH),
            "--out-root",
            str(out_root),
            "--limit",
            "1",
            "--dry-run",
            "--use-robocrys-query-skill",
            "--validate-robocrys-intent-alignment",
            "--llm-robocrys-intent-judge",
        ]
        subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=True)
        manifest = json.loads((out_root / "manifests" / "paper_evidence_pack_v2_manifest.json").read_text(encoding="utf-8"))
        row = manifest["rows"][0]
        payload = json.loads((out_root / row["case_dir"] / "robocrys" / "robocrys_intent_validation.json").read_text(encoding="utf-8"))
        assert payload["rule_based"]["skip_reason"] == "robocrys_output_unavailable"
        assert payload["llm_judge"]["skip_reason"] == "robocrys_output_unavailable"
        assert payload["llm_judge"]["judgement"] == "not_scored"


def test_runner_llm_preflight_records_unavailable_backend() -> None:
    with tempfile.TemporaryDirectory(prefix="llm_preflight_test_") as tmp:
        out_root = Path(tmp) / "pack"
        command = [
            sys.executable,
            str(RUNNER),
            "--csv",
            str(CSV_PATH),
            "--out-root",
            str(out_root),
            "--llm-intent-judge-preflight-only",
            "--llm-intent-judge-backend",
            "openai_compatible",
            "--llm-intent-judge-url",
            "http://127.0.0.1:9/v1/chat/completions",
            "--llm-intent-judge-model",
            "mock-model",
            "--llm-intent-judge-timeout-s",
            "1",
        ]
        subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=True)
        payload = json.loads((out_root / "reports" / "LLM_INTENT_JUDGE_PREFLIGHT.json").read_text(encoding="utf-8"))
        assert payload["backend_configured"] is True
        assert payload["available"] is False
        assert payload["json_parse_succeeded"] is False


def test_runner_llm_preflight_records_mocked_backend_available() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "score": 0.77,
                                        "correct": True,
                                        "judgement": "correct",
                                        "explicit_text_matches": ["perovskite"],
                                        "alias_text_matches": [],
                                        "implicit_condensed_matches": [],
                                        "matched_requirements": ["perovskite"],
                                        "missing_requirements": [],
                                        "contradictions": [],
                                        "concerns": [],
                                        "explanation": "matches",
                                        "not_physical_validation_notice": True,
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002, ANN001
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="llm_preflight_test_") as tmp:
            out_root = Path(tmp) / "pack"
            url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
            command = [
                sys.executable,
                str(RUNNER),
                "--csv",
                str(CSV_PATH),
                "--out-root",
                str(out_root),
                "--llm-intent-judge-preflight-only",
                "--llm-intent-judge-backend",
                "openai_compatible",
                "--llm-intent-judge-url",
                url,
                "--llm-intent-judge-model",
                "mock-model",
                "--llm-intent-judge-timeout-s",
                "3",
            ]
            subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=True)
            payload = json.loads((out_root / "reports" / "LLM_INTENT_JUDGE_PREFLIGHT.json").read_text(encoding="utf-8"))
            assert payload["backend_configured"] is True
            assert payload["reachable"] is True
            assert payload["test_prompt_succeeded"] is True
            assert payload["json_parse_succeeded"] is True
            assert payload["available"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_runner_ollama_preflight_records_mocked_backend_available() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path != "/api/tags":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"models": [{"name": "tiny-json-model"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            body = json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "score": 0.77,
                                "correct": True,
                                "judgement": "correct",
                                "explicit_text_matches": ["perovskite"],
                                "alias_text_matches": [],
                                "implicit_condensed_matches": [],
                                "matched_requirements": ["perovskite"],
                                "missing_requirements": [],
                                "contradictions": [],
                                "concerns": [],
                                "explanation": "matches",
                                "not_physical_validation_notice": True,
                            }
                        )
                    }
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002, ANN001
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="ollama_preflight_test_") as tmp:
            out_root = Path(tmp) / "pack"
            command = [
                sys.executable,
                str(RUNNER),
                "--csv",
                str(CSV_PATH),
                "--out-root",
                str(out_root),
                "--llm-intent-judge-preflight-only",
                "--llm-intent-judge-backend",
                "ollama",
                "--llm-intent-judge-url",
                f"http://127.0.0.1:{server.server_port}",
                "--llm-intent-judge-model",
                "tiny-json-model",
                "--llm-intent-judge-timeout-s",
                "3",
            ]
            subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=True)
            payload = json.loads((out_root / "reports" / "LLM_INTENT_JUDGE_PREFLIGHT.json").read_text(encoding="utf-8"))
            assert payload["backend_type"] == "ollama"
            assert payload["models_available"] == ["tiny-json-model"]
            assert payload["model_found"] is True
            assert payload["reachable"] is True
            assert payload["json_parse_succeeded"] is True
            assert payload["available"] is True
    finally:
        server.shutdown()
        server.server_close()
