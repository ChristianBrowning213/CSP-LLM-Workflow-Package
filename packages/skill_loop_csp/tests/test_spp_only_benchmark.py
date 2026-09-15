from __future__ import annotations

import tempfile
from pathlib import Path

from sok_llm_orchestrator.orchestrator.logging import sha256_text
from sok_llm_orchestrator.workflow.evidence import EvidenceItem, SPPEvidenceBundle, required_pairs_for_formula
from sok_llm_orchestrator.workflow.spp_only_benchmark import (
    SPPOnlyBenchmarkPolicy,
    _base_result,
    _classify_target_exception,
    _qlip_terminal_classification,
    _sha256_normalized_text,
    leakage_safe_neighbourhood,
    normalize_pair_for_match,
    strict_pair_preflight,
    strict_spp_artifact_preflight,
)
from sok_llm_orchestrator.workflow.runner import WorkflowStageError


def _bundle(*, counts: dict[str, int], selected_ids: tuple[str, ...]) -> SPPEvidenceBundle:
    selected = tuple(
        EvidenceItem(
            structure_id=value, retrieval_rank=index, retrieval_score=1.0,
            cif_path=str(Path("unused.cif")), cif_sha256="0" * 64,
            inclusion_reason="test", species_pairs_contributed=tuple(counts),
        )
        for index, value in enumerate(selected_ids, start=1)
    )
    return SPPEvidenceBundle(
        corpus_id="test", corpus_hash="1" * 64, selection_policy="test",
        required_pairs=tuple(counts), pair_structure_counts=counts,
        pair_evidence_status={}, selected=selected, exclusion_audit=(), bundle_hash="2" * 64,
    )


def test_policy_rejects_spp_cohort_larger_than_candidate_neighbourhood() -> None:
    try:
        SPPOnlyBenchmarkPolicy(candidate_retrieval_depth=20, spp_corpus_size=30)
    except ValueError as exc:
        assert "retrieval depth" in str(exc)
    else:
        raise AssertionError("invalid benchmark policy was accepted")


def test_benchmark_policy_uses_bounded_generic_uniform_grid() -> None:
    policy = SPPOnlyBenchmarkPolicy()
    assert policy.native_grid_density == 4
    assert policy.native_grid_density ** 3 == 64


def test_frozen_cif_hash_verification_normalizes_lf_and_crlf() -> None:
    cif_lf = "data_test\n_cell_length_a 3.0\n"
    expected = sha256_text(cif_lf)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lf_path = root / "lf.cif"
        crlf_path = root / "crlf.cif"
        lf_path.write_bytes(cif_lf.encode("utf-8"))
        crlf_path.write_bytes(cif_lf.replace("\n", "\r\n").encode("utf-8"))
        assert _sha256_normalized_text(lf_path) == expected
        assert _sha256_normalized_text(crlf_path) == expected


def test_leakage_safe_neighbourhood_excludes_before_fixed_cohort_selection() -> None:
    retrieval = {"selected": [{"structure_id": "target"}, {"structure_id": "a"}, {"structure_id": "b"}, {"structure_id": "c"}]}
    filtered, audit = leakage_safe_neighbourhood(retrieval, excluded_structure_ids=("target",), limit=2)
    assert [row["structure_id"] for row in filtered["selected"]] == ["a", "b"]
    assert {row["reason"] for row in audit if row["structure_id"] == "target"} == {"frozen_target_or_equivalent"}


def test_strict_pair_preflight_blocks_missing_request_local_pair() -> None:
    checks = strict_pair_preflight(_bundle(counts={"Li-O": 2, "Co-O": 0}, selected_ids=("analogue",)), ("target",))
    assert checks["NO_TARGET_LEAKAGE"] is True
    assert checks["PAIR_COVERAGE_COMPLETE"] is False
    assert checks["missing_pairs"] == ["Co-O"]


def test_strict_pair_preflight_detects_target_leakage() -> None:
    checks = strict_pair_preflight(_bundle(counts={"Li-O": 1}, selected_ids=("target",)), ("target",))
    assert checks["PAIR_COVERAGE_COMPLETE"] is True
    assert checks["NO_TARGET_LEAKAGE"] is False


def test_strict_spp_audit_uses_uppercase_artifact_pair_names(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_audit(root: Path, *, required_pairs, max_cap_fraction_threshold: float):
        seen["required_pairs"] = required_pairs
        return {
            "pairs": [
                {
                    "pair": "CO-LI", "raw_point_count": 10,
                    "x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0,
                    "pot_quality": "usable",
                }
            ],
            "spp_pot_quality_status": "usable",
        }

    monkeypatch.setattr("spp_maker_qlip.pot_quality.audit_pot_root", fake_audit)
    with tempfile.TemporaryDirectory() as tmp:
        request_spp = {
            "pot_root": Path(tmp),
            "quality": {"request_pair_results": [{
                "species_pair": "Co-Li", "observations": 10, "request_pair_status": "REQUEST_USABLE",
            }]},
        }
        checks = strict_spp_artifact_preflight(request_spp, ["Co-Li"])
    assert seen["required_pairs"] is None
    assert checks["SPP_ARTIFACT_VALID"] is True


def test_pair_match_key_is_case_and_order_insensitive() -> None:
    assert normalize_pair_for_match("Cl-Na") == normalize_pair_for_match("NA-CL")


def test_unrelated_pair_match_key_remains_distinct() -> None:
    assert normalize_pair_for_match("Cl-Na") != normalize_pair_for_match("K-Cl")


def test_required_pairs_include_all_unordered_combinations_with_self_pairs() -> None:
    assert required_pairs_for_formula("NaCl") == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert required_pairs_for_formula("LiCoO2") == [
        "Co-Co", "Co-Li", "Co-O", "Li-Li", "Li-O", "O-O",
    ]


def _solver_ready_row() -> dict[str, object]:
    row = _base_result(
        {"benchmark_id": "spinel-regression", "family": "spinel", "material_id": "mp-test", "formula": "A2BO4"},
        Path("unused-run"),
    )
    row.update(retrieval_k=30, SPP_ARTIFACT_VALID=True)
    return row


def test_solver_proven_infeasible_uses_structured_taxonomy() -> None:
    row = _solver_ready_row()
    exc = WorkflowStageError(
        "solve", "QLIP_INFEASIBLE", "QLIP did not emit a candidate",
        details={"qlip_status": "INFEASIBLE", "qlip_errors": ["solver-proven infeasible"]},
    )
    _classify_target_exception(row, exc)
    assert row["qlip_status"] == "INFEASIBLE"
    assert row["final_classification"] == "FAILED_QLIP_INFEASIBLE"


def test_feasible_time_limit_with_incumbent_is_not_timeout_failure() -> None:
    assert _qlip_terminal_classification("FEASIBLE_TIME_LIMIT", candidate_present=True) is None


def test_optimal_with_candidate_uses_normal_generation_path() -> None:
    assert _qlip_terminal_classification("OPTIMAL", candidate_present=True) is None


def test_time_limit_without_incumbent_uses_timeout_taxonomy() -> None:
    row = _solver_ready_row()
    exc = WorkflowStageError(
        "solve", "QLIP_TIME_LIMIT_NO_SOLUTION", "QLIP did not emit a candidate",
        details={"qlip_status": "TIME_LIMIT_NO_SOLUTION"},
    )
    _classify_target_exception(row, exc)
    assert row["qlip_status"] == "TIME_LIMIT_NO_SOLUTION"
    assert row["final_classification"] == "FAILED_QLIP_TIMEOUT"


def test_unexpected_solver_exception_remains_failed_other() -> None:
    row = _solver_ready_row()
    _classify_target_exception(row, RuntimeError("unexpected solver failure"))
    assert row["qlip_status"] == "NOT_RUN"
    assert row["final_classification"] == "FAILED_OTHER"
