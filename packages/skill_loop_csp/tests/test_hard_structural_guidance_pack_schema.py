from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.bench.cases import load_case_set, validate_case


def test_hard_structural_guidance_pack_schema_and_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "hard_structural_guidance_cases.json"
    cases = load_case_set(case_file)
    assert len(cases) == 5
    expected_ids = {
        "hard_srtio3_polymorph",
        "hard_batio3_polymorph",
        "hard_na3zr2si2po12_framework",
        "hard_mgal2o4_coordination",
        "hard_sr2femoo6_ordering",
    }
    assert {str(case["case_id"]) for case in cases} == expected_ids
    expected_challenge_classes = {
        "polymorph_ambiguous",
        "framework_sensitive",
        "coordination_sensitive",
        "ordering_sensitive",
    }
    assert {str(case["challenge_class"]) for case in cases} == expected_challenge_classes
    for case in cases:
        validate_case(case)
        assert isinstance(case.get("guidance_rationale"), str)
        assert case.get("guidance_rationale")
        assert isinstance(case.get("recommended_guidance_focus"), str)
        assert case.get("recommended_guidance_focus")

