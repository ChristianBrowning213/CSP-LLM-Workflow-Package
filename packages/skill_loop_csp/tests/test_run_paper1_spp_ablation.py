from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_paper1_spp_ablation.py"
SPEC = importlib.util.spec_from_file_location("paper1_ablation_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def test_evidence_round_trip_preserves_frozen_hashes_and_pairs() -> None:
    payload = {
        "corpus_id": "fixture", "corpus_hash": "corpus-hash", "selection_policy": "fixed",
        "required_pairs": ["Na-Na", "Na-O"],
        "pair_structure_counts": {"Na-Na": 1, "Na-O": 1},
        "pair_evidence_status": {}, "exclusion_audit": [], "bundle_hash": "bundle-hash",
        "selected": [{
            "structure_id": "mp-one", "retrieval_rank": 1, "retrieval_score": 0.9,
            "cif_path": "one.cif", "cif_sha256": "abc", "inclusion_reason": "fixed",
            "species_pairs_contributed": ["Na-Na", "Na-O"], "source_id": "mp-1.cif", "family": None,
        }],
    }
    evidence = runner.evidence_from_dict(payload)
    assert evidence.bundle_hash == "bundle-hash"
    assert evidence.required_pairs == ("Na-Na", "Na-O")
    assert evidence.selected[0].species_pairs_contributed == ("Na-Na", "Na-O")


def test_condition_is_global_regulator_only() -> None:
    assert runner.CONDITION == "B_GLOBAL_REGULATOR_ONLY"


def test_missing_global_pair_is_a_scientific_ablation_failure() -> None:
    assert runner.is_scientific_failure("GUIDANCE_PAIR_UNSUPPORTED") is True
    assert runner.is_scientific_failure("QLIP_INFEASIBLE") is True
    assert runner.is_scientific_failure("PRIMARY_PREFLIGHT_NO_DYNAMIC_CELL") is True
    assert runner.is_scientific_failure("PATH_ERROR") is False
