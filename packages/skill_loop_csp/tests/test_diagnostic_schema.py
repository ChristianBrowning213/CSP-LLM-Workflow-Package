from __future__ import annotations

from sok_llm_orchestrator.verification.diagnostic_schema import DiagnosticReport, validate_diagnostic_report


def test_diagnostic_schema_valid() -> None:
    report = DiagnosticReport(
        failure_type="infeasible",
        probable_cause="over_constrained",
        evidence=["solver reported infeasible"],
        suggested_deltas=["reduce_guidance", "relax_symmetry"],
    )
    validate_diagnostic_report(report.to_dict())
