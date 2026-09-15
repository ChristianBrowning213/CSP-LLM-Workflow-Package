from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_paper1_simple_ordered_preflight.py"
SPEC = importlib.util.spec_from_file_location("paper1_preflight_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
auditor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = auditor
SPEC.loader.exec_module(auditor)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_audit_row_distinguishes_raw_hit_from_spp_leakage() -> None:
    with tempfile.TemporaryDirectory() as directory:
        row_root = Path(directory)
        target = "mp-target"
        _write(row_root / "retrieval" / "retrieval_manifest.json", {
            "selected": [{"structure_id": target}],
            "spp_evidence": {
                "selected": [{"structure_id": "mp-neighbour"}],
                "exclusion_audit": [{
                    "structure_id": target, "decision": "excluded", "reason": "structure_holdout_id",
                }],
            },
        })
        _write(row_root / "status" / "generation_status.json", {"preflight_status": "PASS"})
        _write(row_root / "cell" / "dynamic_cell.json", {})
        _write(row_root / "spp" / "request_spp_cache.json", {
            "quality": {"status": "PASS_COMMON_CONTRACT"},
        })
        row = auditor.audit_row(row_root, {
            "row_id": "rocksalt_b1_001_mgo", "family": "rocksalt_b1",
            "target_reference_id": target,
        })
        assert row["target_in_raw_retrieval"] is True
        assert row["target_in_spp_evidence"] is False
        assert row["target_disposition_recorded"] is True
        assert row["holdout_exclusion_recorded"] is True
        assert row["classification"] == "EXECUTABLE"


def test_audit_row_classifies_missing_pair_as_scientific_coverage() -> None:
    with tempfile.TemporaryDirectory() as directory:
        row_root = Path(directory)
        target = "mp-target"
        _write(row_root / "retrieval" / "retrieval_manifest.json", {
            "selected": [{"structure_id": "mp-neighbour"}],
            "spp_evidence": {
                "selected": [{"structure_id": "mp-neighbour"}],
                "exclusion_audit": [{
                    "structure_id": target, "decision": "excluded", "reason": "structure_holdout_id",
                }],
            },
        })
        _write(row_root / "status" / "generation_status.json", {
            "error": "Required pair lacks both a valid local common-contract POT and global fallback: Ac-Mg",
        })
        row = auditor.audit_row(row_root, {
            "row_id": "cscl_b2_012_acmg", "family": "cscl_b2", "target_reference_id": target,
        })
        assert row["classification"] == "SCIENTIFIC_SPP_PAIR_COVERAGE_FAILURE"
        assert row["unsupported_pair"] == "Ac-Mg"


def test_candidate_scan_ignores_retrieval_and_spp_inputs() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative in ("retrieval/neighbours/a.cif", "spp/build/b.cif", "runs/x/spp_evidence/c.cif"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("data", encoding="utf-8")
        assert auditor._candidate_cifs(root) == []
        candidate = root / "candidate" / "result.cif"
        candidate.parent.mkdir()
        candidate.write_text("data", encoding="utf-8")
        assert auditor._candidate_cifs(root) == [candidate]
