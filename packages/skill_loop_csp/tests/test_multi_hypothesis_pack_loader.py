from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.bench.cases import load_case_set


def test_multi_hypothesis_pack_loader_preserves_hypothesis_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "multi_hypothesis_complex_cases.json"
    cases = load_case_set(case_file)
    by_id = {str(case["case_id"]): case for case in cases}

    srtio3 = by_id["mh_srtio3_polymorph"]
    srtio3_hyp = srtio3.get("hypotheses")
    assert isinstance(srtio3_hyp, list)
    assert [str(item["hypothesis_id"]) for item in srtio3_hyp if isinstance(item, dict)] == [
        "srtio3_h1_cubic_perovskite",
        "srtio3_h2_tilted_perovskite",
        "srtio3_h3_relaxed_alt_template",
    ]

    nzsp = by_id["mh_na3zr2si2po12_framework"]
    assert nzsp.get("challenge_class") == "framework_sensitive"
    assert nzsp.get("suggested_corpus_bias") == "framework_and_topology_diverse_corpus"
    nzsp_hyp = nzsp.get("hypotheses")
    assert isinstance(nzsp_hyp, list)
    assert len(nzsp_hyp) == 3
