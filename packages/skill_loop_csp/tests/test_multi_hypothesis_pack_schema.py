from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.bench.cases import load_case_set, validate_case


def test_multi_hypothesis_pack_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "multi_hypothesis_complex_cases.json"
    cases = load_case_set(case_file)

    assert len(cases) == 4
    assert {str(case["case_id"]) for case in cases} == {
        "mh_srtio3_polymorph",
        "mh_batio3_polymorph",
        "mh_na3zr2si2po12_framework",
        "mh_sr2femoo6_ordering",
    }

    for case in cases:
        validate_case(case)
        hypotheses = case.get("hypotheses")
        assert isinstance(hypotheses, list)
        assert 2 <= len(hypotheses) <= 3
        for hypothesis in hypotheses:
            assert isinstance(hypothesis, dict)
            assert isinstance(hypothesis.get("hypothesis_id"), str) and hypothesis["hypothesis_id"]
            assert isinstance(hypothesis.get("label"), str) and hypothesis["label"]
            assert isinstance(hypothesis.get("rationale"), str) and hypothesis["rationale"]
            assert isinstance(hypothesis.get("hypothesis_family"), str) and hypothesis["hypothesis_family"]
