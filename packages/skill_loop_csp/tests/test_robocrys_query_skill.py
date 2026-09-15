from __future__ import annotations

import csv
import importlib
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from sok_llm_orchestrator.agentic.robocrys_adapter import describe_cif_with_robocrys
from sok_llm_orchestrator.agentic.skills.robocrys_query_skill import build_robocrys_style_crystal_db_query


REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "challenge_queries_100.csv"


def _query(formula: str, family: str, motifs: str, original: str = "Generate a candidate.") -> dict:
    return build_robocrys_style_crystal_db_query(
        original,
        target_formula=formula,
        chemistry_family=family,
        expected_motifs_or_priors=motifs,
    )


def _contains(payload: dict, *needles: str) -> None:
    haystack = " ".join(
        [
            payload["crystal_db_retrieval_query"],
            payload["compact_retrieval_query"],
            " ".join(payload["terms_added"]),
        ]
    ).lower()
    for needle in needles:
        assert needle.lower() in haystack


def test_required_example_queries_use_robocrys_style_terms() -> None:
    cases = [
        ("BaTiO3", "oxide_perovskite", "corner-sharing TiO6 octahedra; A-site Ba; perovskite topology", ["TiO6", "corner-sharing", "perovskite", "octahedral tilt angles"]),
        ("MgAl2O4", "oxide_spinel", "close-packed oxygen lattice; tetrahedral Mg; octahedral Al", ["MgO4", "AlO6", "spinel", "tetrahedral geometry"]),
        ("LiCoO2", "layered_oxide", "edge-sharing CoO6 slabs; Li intercalation layers", ["layered", "CoO6", "Li interlayer", "two-dimensional"]),
        ("LiFePO4", "phosphate_olivine", "olivine framework; Li channels; FeO6 octahedra; PO4 tetrahedra", ["olivine", "FeO6", "PO4", "Li channels"]),
        ("FeS2", "sulfide_pyrite", "S2 dumbbells; FeS6 octahedra", ["pyrite", "S-S dimer", "FeS6", "bond lengths"]),
        ("CuFeS2", "sulfide_chalcopyrite", "tetrahedral sulfide network; ordered Cu/Fe sublattices", ["chalcopyrite-like", "tetrahedral geometry", "Cu-S bond lengths", "Fe-S bond lengths"]),
        ("MoS2", "layered_chalcogenide", "S-Mo-S sheets; layered van der Waals motif", ["molybdenite structured", "two-dimensional", "MoS2 sheets", "edge-sharing"]),
        ("Na3Zr2Si2PO12", "phosphate_silicate_framework", "ZrO6 octahedra linked to SiO4/PO4 tetrahedra; Na channels", ["NASICON-like", "ZrO6", "SiO4", "PO4", "Na channels"]),
    ]
    for formula, family, motifs, expected in cases:
        payload = _query(formula, family, motifs)
        _contains(payload, *expected)
        assert payload["query_style"] == "robocrys_descriptive"
        assert payload["pair_evidence_targets"]


def test_unknown_family_preserves_original_query_without_inventing_known_family_terms() -> None:
    original = "Generate a plain AB compound with only the stated motif."
    payload = _query("AB", "unknown_family", "stated motif only", original)
    assert payload["original_query"] == original
    assert any("unknown_chemistry_family" in warning for warning in payload["warnings"])
    text = payload["crystal_db_retrieval_query"].lower()
    assert "perovskite structured" not in text
    assert "spinel structured" not in text


def test_all_challenge_csv_families_have_template_or_safe_warning() -> None:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    families = sorted({row["chemistry_family"] for row in rows})
    assert families
    for family in families:
        sample = next(row for row in rows if row["chemistry_family"] == family)
        payload = build_robocrys_style_crystal_db_query(
            sample["query"],
            target_formula=sample["target_formula"],
            chemistry_family=family,
            challenge_type=sample["challenge_type"],
            expected_motifs_or_priors=sample["expected_motifs_or_priors"],
        )
        assert payload["crystal_db_retrieval_query"]
        assert payload["compact_retrieval_query"]
        assert payload["pair_evidence_query"]
        if any("unknown_chemistry_family" in warning for warning in payload["warnings"]):
            assert payload["original_query"] == sample["query"]


def test_expected_motifs_are_preserved_or_translated() -> None:
    payload = _query("LiFePO4", "phosphate_olivine", "olivine framework; Li channels; FeO6 octahedra; PO4 tetrahedra")
    assert "olivine framework" in payload["motif_terms_from_input"]
    _contains(payload, "framework", "Li channels", "FeO6 octahedra", "PO4 tetrahedra")


def test_query_skill_deduplicates_terms_and_emits_validator_aliases() -> None:
    payload = _query(
        "BaTiO3",
        "oxide_perovskite",
        "TiO6 octahedra; TiO6 octahedra; corner-sharing TiO6 octahedra",
    )
    assert len(payload["terms_added"]) == len({term.lower() for term in payload["terms_added"]})
    requirements = payload["validator_requirements"]
    assert requirements
    tio6 = [item for item in requirements if item["id"] == "coordination.tio6"]
    assert tio6
    assert "TiO6" in tio6[0]["aliases"]
    assert payload["requirement_aliases"]["coordination.tio6"]


def test_query_skill_limits_repetition_in_calibrated_batio3_query() -> None:
    payload = _query(
        "BaTiO3",
        "oxide_perovskite",
        "perovskite topology; corner-sharing TiO6 octahedra; corner-sharing TiO6 octahedra",
    )
    query = payload["crystal_db_retrieval_query"].lower()
    assert query.count("corner-sharing tio6 octahedra") <= 1
    assert query.count("perovskite") <= 4
    assert "batio3" in query
    assert "titanate" in query or "oxide" in query
    assert "o-ti" in query or "ti-o" in query
    assert "tio6" in query or "octahedra" in query
    assert "corner-sharing" in query or "corner" in query
    assert "a-site ba" in query or "ba" in query
    assert "tio6-like 6-coordinate environments" not in query
    assert len(payload["terms_added"]) == len({term.lower() for term in payload["terms_added"]})
    assert payload["validator_requirements"]
    aliases = " ".join(
        alias
        for requirement in payload["validator_requirements"]
        for alias in requirement.get("aliases", [])
    ).lower()
    assert "6-coordinate" in aliases
    assert payload["implicit_condensed_rules"]["coordination.tio6"]["coordination_number"] == 6
    assert any("corner" in item["label"].lower() for item in payload["validator_requirements"])
    assert payload["requirement_source"] == "chemistry_family_and_expected_motifs_or_priors"


def test_query_skill_keeps_retrieval_facing_terms_separate_from_validator_aliases() -> None:
    payload = _query(
        "BaTiO3",
        "oxide_perovskite",
        "corner-sharing TiO6 octahedra; A-site Ba; perovskite topology",
    )
    query = payload["crystal_db_retrieval_query"].lower()
    assert "batio3" in query
    assert "titanate" in query
    assert "oxide" in query
    assert "perovskite" in query
    assert "ba-o" in query
    assert "o-ti" in query
    assert "tio6 octahedra" in query
    assert "corner-sharing octahedra" in query
    assert "ti bonded to o in tio6-like" not in query

    requirements = {item["id"]: item for item in payload["validator_requirements"]}
    assert "coordination.tio6" in requirements
    assert "Ti-O 6-coordinate" in requirements["coordination.tio6"]["aliases"]
    assert payload["implicit_condensed_rules"]["coordination.tio6"]["rule"]


def test_describe_cif_with_robocrys_missing_cif_is_structured() -> None:
    payload = describe_cif_with_robocrys(REPO_ROOT / "does_not_exist.cif")
    assert payload["robocrys_available"] is False
    assert payload["error"] == "no_solution_cif"


def test_describe_cif_with_robocrys_returns_unavailable_when_imports_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory(prefix="robocrys_adapter_test_") as tmp:
        cif = Path(tmp) / "sample.cif"
        cif.write_text("data_sample\n", encoding="utf-8")

        def fake_import(name: str):  # noqa: ANN001
            raise ModuleNotFoundError(name)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        payload = describe_cif_with_robocrys(cif)
        assert payload["robocrys_available"] is False
        assert payload["error"]


def test_describe_cif_with_robocrys_uses_mocked_crystal_db_textgen(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory(prefix="robocrys_adapter_test_") as tmp:
        cif = Path(tmp) / "sample.cif"
        cif.write_text("data_sample\n", encoding="utf-8")
        textgen = SimpleNamespace(generate_text=lambda **_: {"text": "Mock robocrys description."})

        def fake_import(name: str):  # noqa: ANN001
            if name == "crystal_db.textgen":
                return textgen
            raise ModuleNotFoundError(name)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        payload = describe_cif_with_robocrys(cif)
        assert payload["robocrys_available"] is True
        assert payload["description"] == "Mock robocrys description."
