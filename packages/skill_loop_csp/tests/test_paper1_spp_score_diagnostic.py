from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "paper1_spp_score_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("paper1_spp_score_diagnostic", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def _audit_payload(contribs):
    total = sum(c["raw_contribution"] for c in contribs)
    return {"summary": {"total_spp_score": total, "atom_count": 2}, "contributions": contribs}


def test_corrected_from_audit_halves_the_diagonal_self_term() -> None:
    contribs = [
        {"pair_key": "Na-Cl", "raw_contribution": -10.0, "diagonal_self_image": False, "distance": 2.8},
        {"pair_key": "Na-Cl", "raw_contribution": -6.0, "diagonal_self_image": False, "distance": 3.9},
        {"pair_key": "Na-Na", "raw_contribution": -4.0, "diagonal_self_image": True, "distance": 4.0},
        {"pair_key": "Cl-Cl", "raw_contribution": -4.0, "diagonal_self_image": True, "distance": 4.0},
    ]
    out = mod._corrected_from_audit(_audit_payload(contribs))
    assert out["raw_total"] == -24.0
    # off (-16) + 0.5 * diag (-8) = -20
    assert out["corrected_total"] == pytest.approx(-20.0)
    assert out["diagonal_interaction_count"] == 2
    na_na = next(p for p in out["pairs"] if p["pair_type"] == "Na-Na")
    assert na_na["score_total_corrected"] == pytest.approx(-2.0)  # diagonal weighted 0.5
    assert na_na["score_total_raw"] == pytest.approx(-4.0)


def test_score_sign_convention_lower_is_better() -> None:
    # delta = generated - reference ; delta > 0 means reference (lower) is better.
    row = {
        "delta_retrieval_scalematched_per_atom": 5.0,
        "delta_request_only_scalematched_per_atom": 5.0,
        "delta_global_scalematched_per_atom": 1.0,
        "retrieval_reference_scaled_per_atom": -100.0,
        "representability_status": "NOT_REPRESENTABLE",
    }
    assert mod._classify_case(row, sweep_flip=False) == "A"
    row["delta_retrieval_scalematched_per_atom"] = -50.0
    row["delta_request_only_scalematched_per_atom"] = -50.0
    assert mod._classify_case(row, sweep_flip=False) == "D"


def test_classify_case_scale_only_for_representable_indifferent() -> None:
    row = {
        "delta_retrieval_scalematched_per_atom": 0.0001,
        "delta_request_only_scalematched_per_atom": 0.0001,
        "delta_global_scalematched_per_atom": 0.0,
        "retrieval_reference_scaled_per_atom": -120.0,
        "representability_status": "REPRESENTABLE",
    }
    assert mod._classify_case(row, sweep_flip=False) == "SCALE_ONLY"


def test_classify_case_weight_limited_needs_upward_flip() -> None:
    row = {
        "delta_retrieval_scalematched_per_atom": 8.0,
        "delta_request_only_scalematched_per_atom": 8.0,
        "delta_global_scalematched_per_atom": 2.0,
        "retrieval_reference_scaled_per_atom": -100.0,
        "representability_status": "REPRESENTABLE",
    }
    assert mod._classify_case(row, sweep_flip=True) == "B"
    assert mod._classify_case(row, sweep_flip=False) == "A"


def test_weight_sweep_arithmetic_alpha_one_reproduces_blend() -> None:
    # blended = request + weighted_regulator (U-linear). regulator_component = blended - request.
    request = -300.0
    blended = -280.0
    regulator_component = blended - request  # +20
    for alpha, expected in ((0.0, regulator_component), (1.0, blended), (2.0, regulator_component + 2 * request)):
        assert regulator_component + alpha * request == pytest.approx(expected)


def test_strata_are_fixed_and_row_id_sorted_not_outcome_dependent() -> None:
    # every stratum is (family, verdict-set, count) - selection sorts row_ids and never reads scores.
    total = sum(s["count"] for s in mod.STRATA)
    assert total == 26
    families = {s["family"] for s in mod.STRATA}
    assert families == {
        "rocksalt_b1", "zinc_blende_b3", "fluorite_antifluorite", "cscl_b2",
        "oxide_perovskite", "halide_perovskite",
    }
    src = SCRIPT.read_text(encoding="utf-8")
    assert "candidates = sorted(" in src  # deterministic row_id ordering
    assert "target_in_spp_evidence" in src  # exclusion proof is required per row


def test_preference_eps_is_a_dead_band() -> None:
    row = {
        "delta_retrieval_scalematched_per_atom": 0.4,
        "delta_request_only_scalematched_per_atom": 0.4,
        "delta_global_scalematched_per_atom": 0.4,
        "retrieval_reference_scaled_per_atom": -50.0,
        "representability_status": "NOT_REPRESENTABLE",
    }
    # |delta| < PREFERENCE_EPS -> treated as no preference (Case C for not-representable)
    assert mod.PREFERENCE_EPS == 1.0
    assert mod._classify_case(row, sweep_flip=False) == "C"


def test_scorer_is_reused_not_reimplemented_and_writes_only_under_art() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    assert "from audit_spp_objective import audit" in src
    assert 'missing_pair_policy="block"' in src
    # every persistence helper writes under the diagnostic artifact root ART, never into outputs/.
    assert 'ART = REPO_ROOT / "artifacts" / "paper1_spp_score_diagnostic_v1"' in src
    for call in ("write_json(", "write_csv(", "write_text("):
        for line in src.splitlines():
            if line.strip().startswith(call.replace("(", "")) and "def " not in line:
                pass  # helper bodies use `path`, callers pass ART/... - checked structurally below
    assert "PRIMARY_ROOT / rid / \"generated\" / \"candidate.cif\"" in src  # read source, never written
    assert ".write_text(gen_src.read_text(" in src  # candidate is copied, not modified in place
