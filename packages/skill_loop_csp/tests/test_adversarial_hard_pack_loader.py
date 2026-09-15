from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.bench.cases import load_case_set


def test_adversarial_hard_pack_loader_preserves_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "adversarial_hard_crystal_cases.json"
    cases = load_case_set(case_file)
    by_id = {str(case["case_id"]): case for case in cases}

    li_case = by_id["adv_li4brocl_unseen"]
    assert li_case["challenge_class"] == "low_support_hypothetical"
    assert li_case["suggested_corpus_bias"] == "family_biased_with_broad_rescue"
    assert li_case["suggested_perturbation_bias"] == "template_relaxed_with_multibasin_lattice"
    assert isinstance(li_case.get("hypotheses"), list) and len(li_case["hypotheses"]) == 3

    co_case = by_id["adv_coas2_hard_rediscovery"]
    hypothesis_ids = [
        str(item["hypothesis_id"])
        for item in co_case.get("hypotheses", [])
        if isinstance(item, dict) and isinstance(item.get("hypothesis_id"), str)
    ]
    assert hypothesis_ids == [
        "coas2_h1_tight_nearest_analog",
        "coas2_h2_broad_pnictide_family",
        "coas2_h3_relaxed_template_rescue",
    ]
