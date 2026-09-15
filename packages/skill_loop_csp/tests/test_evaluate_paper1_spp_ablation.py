from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_paper1_spp_ablation.py"
SPEC = importlib.util.spec_from_file_location("paper1_ablation_sca", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
evaluator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evaluator
SPEC.loader.exec_module(evaluator)


RAW_ROCKSALT_PARTIAL = {
    "parse_ok": True,
    "target_formula_match": True,
    "geometry_ok": True,
    "num_bad_contacts": 0,
    "topology_status": "NOT_APPLICABLE",
    "topology_policy": "ROCKSALT",
    "detected_space_group": "P4mm",
    "space_group_consistent": False,
}


def test_summary_uses_canonical_raw_sca_keys() -> None:
    row = evaluator.summarize_sca("row", "hash", RAW_ROCKSALT_PARTIAL)
    assert row["parse_ok"] is True
    assert row["composition_match"] is True
    assert row["geometry_valid"] is True
    assert row["bad_contacts"] == 0
    assert row["topology_result"] == "NOT_APPLICABLE"
    # parse+composition true but topology not PASS/NOT_EVALUATED -> PARTIAL, matching _sca_one.
    assert row["sca_status"] == "PARTIAL"
    assert row["source_candidate_sha256"] == row["candidate_sha256_after"]


def test_summary_pass_requires_clean_topology() -> None:
    raw = dict(RAW_ROCKSALT_PARTIAL, topology_status="PASS")
    assert evaluator.summarize_sca("row", "hash", raw)["sca_status"] == "PASS"


def test_summary_fail_when_composition_mismatch() -> None:
    raw = dict(RAW_ROCKSALT_PARTIAL, target_formula_match=False)
    assert evaluator.summarize_sca("row", "hash", raw)["sca_status"] == "FAIL"


def test_summary_matches_csv_workflow_sca_one_mapping() -> None:
    from sok_llm_orchestrator.workflow import csv_workflow

    src = Path(csv_workflow.__file__).read_text(encoding="utf-8")
    # Guard against drift: the canonical status rule must still be the one we copied.
    assert 'topology in {"PASS", "NOT_EVALUATED"}' in src
