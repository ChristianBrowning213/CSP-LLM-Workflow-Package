from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.bench.cases import load_case_set, validate_case


def test_adversarial_hard_pack_schema_and_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "adversarial_hard_crystal_cases.json"
    cases = load_case_set(case_file)
    assert len(cases) == 5
    assert {str(case["case_id"]) for case in cases} == {
        "adv_li4brocl_unseen",
        "adv_coas2_hard_rediscovery",
        "adv_sr2femoo6_ordering",
        "adv_na3zr2si2po12_framework",
        "adv_batio3_polymorph",
    }
    assert {str(case.get("challenge_class")) for case in cases} == {
        "low_support_hypothetical",
        "broad_corpus_failure_risk",
        "ordering_sensitive",
        "framework_ambiguous",
        "polymorph_trap",
    }
    for case in cases:
        validate_case(case)
        assert isinstance(case.get("guidance_rationale"), str) and case["guidance_rationale"]
        assert isinstance(case.get("recommended_guidance_focus"), str) and case["recommended_guidance_focus"]
        assert isinstance(case.get("hypotheses"), list)
        assert 2 <= len(case["hypotheses"]) <= 3
