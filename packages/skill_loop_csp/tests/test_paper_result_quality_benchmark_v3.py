from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_paper_result_quality_benchmark_v3.py"
SPEC = importlib.util.spec_from_file_location("run_paper_result_quality_benchmark_v3", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
quality_benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality_benchmark)


def test_quality_group_summary_counts_geometry_and_optional_backend_statuses() -> None:
    rows = [
        {"row_id": "row_1"},
        {"row_id": "row_2"},
    ]
    quality_by_id = {
        "row_1": {
            "parse_ok": True,
            "formula_match": True,
            "symmetry_match": True,
            "bad_contact_flag": False,
            "severe_geometry_warning": False,
            "quality_screen_status": "surrogate_unavailable_geometry_screen_passed",
            "reference_match_status": "exact_match",
            "novelty_status": "reference_rediscovery",
            "chgnet_static_status": "unavailable_missing_dependency",
            "relax_status": "unavailable_missing_dependency",
        },
        "row_2": {
            "parse_ok": True,
            "formula_match": True,
            "symmetry_match": True,
            "bad_contact_flag": True,
            "severe_geometry_warning": True,
            "quality_screen_status": "geometry_screen_flagged",
            "reference_match_status": "no_match",
            "novelty_status": "novel_candidate",
            "chgnet_static_status": "unavailable_missing_dependency",
            "relax_status": "unavailable_missing_dependency",
        },
    }

    summary = quality_benchmark._summarize_group(rows, quality_by_id)

    assert summary["total"] == 2
    assert summary["parse_ok"] == 2
    assert summary["geometry_screen_passed"] == 1
    assert summary["bad_contact_flagged"] == 1
    assert summary["reference_match_status"] == {"exact_match": 1, "no_match": 1}
    assert summary["chgnet_static_status"] == {"unavailable_missing_dependency": 2}


def test_quality_cautious_claim_does_not_make_surrogate_claim_when_backend_missing() -> None:
    headline = {
        "total": 2,
        "geometry_screen_passed": 2,
    }

    claim = quality_benchmark._cautious_claim(headline)

    assert "CHGNet surrogate and relaxation backends were unavailable" in claim
    assert "DFT-level claim is made" in claim
