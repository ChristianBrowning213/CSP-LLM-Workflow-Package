"""Dependency-free evaluators for unique verifiable CSP benchmarks."""

from __future__ import annotations

import re
from typing import Any

from sca.schemas import BenchmarkEvaluatorResult
from sca.traceability.io import inspect_run_bundle, load_run_bundle
from sca.traceability.schema import TraceableRunBundle


class EvidenceTraceabilityBenchmarkEvaluator:
    name = "evidence_traceability"
    description = "Retrieval evidence presence, relevance, and evidence-to-constraint link audit."

    def evaluate_row(self, row: dict[str, Any]) -> BenchmarkEvaluatorResult:
        bundle, error = _bundle_from_row(row)
        if bundle is None:
            return _error(self.name, "missing_bundle", error)
        retrieval = bundle.retrieval_trace
        constraints = _constraints(bundle)
        evidence = retrieval.retrieved if retrieval else []
        metrics = _evidence_trace_metrics(bundle, row)
        metrics["evidence_trace_present"] = retrieval is not None
        metrics["num_retrieved_structures"] = len(evidence)
        linked = _linked_constraints(constraints, evidence)
        metrics["num_constraints_linked_to_evidence"] = sum(1 for item in linked if item["status"] == "linked")
        metrics["unsupported_constraint_count"] = sum(1 for item in linked if item["status"] == "unsupported")
        metrics["constraint_evidence_link_rate"] = _rate(metrics["num_constraints_linked_to_evidence"], len(constraints))
        spp_pairs = bundle.spp_trace.pairs if bundle.spp_trace else []
        metrics["spp_pair_coverage_rate"] = _rate(len(spp_pairs), _num_expected_pairs(bundle, row))
        metrics["evidence_to_constraint_links_present"] = metrics["num_constraints_linked_to_evidence"] > 0
        metrics["evidence_trace_score"] = (
            0.25 * _bool_score(metrics["evidence_trace_present"])
            + 0.20 * metrics["fraction_retrieved_parseable"]
            + 0.20 * metrics["fraction_retrieved_family_relevant"]
            + 0.20 * metrics["constraint_evidence_link_rate"]
            + 0.15 * metrics["spp_pair_coverage_rate"]
        )
        metrics["evidence_trace_error"] = None
        return _result(self.name, metrics, metrics["evidence_trace_score"])


class ConstraintFaithfulnessBenchmarkEvaluator:
    name = "constraint_faithfulness"
    description = "Checks generated output against prompt-derived formula, SG, family, and contact constraints."

    def evaluate_row(self, row: dict[str, Any]) -> BenchmarkEvaluatorResult:
        bundle, error = _bundle_from_row(row)
        if bundle is None:
            return _error(self.name, "missing_bundle", error)
        constraints = _constraints(bundle)
        checks = [_check_constraint(constraint, row, bundle) for constraint in constraints]
        checked = [check for check in checks if check["checked"]]
        satisfied = [check for check in checked if check["satisfied"]]
        violations = [check for check in checked if not check["satisfied"]]
        metrics = {
            "constraint_trace_present": bundle.constraint_trace is not None,
            "num_prompt_constraints": len(bundle.structured_intent.constraints if bundle.structured_intent else []),
            "num_solver_constraints": _as_int(row.get("num_constraints")) or len(constraints),
            "num_posthoc_checked_constraints": len(checked),
            "formula_constraint_satisfied": _category_value(checks, "formula"),
            "space_group_constraint_satisfied": _category_value(checks, "space_group"),
            "crystal_system_constraint_satisfied": _category_value(checks, "crystal_system"),
            "prototype_constraint_satisfied": _category_value(checks, "prototype_family"),
            "site_role_constraint_satisfied": _category_value(checks, "site_role"),
            "coordination_constraint_satisfied": _category_value(checks, "coordination_motif"),
            "minimum_distance_constraint_satisfied": _category_value(checks, "minimum_distance"),
            "forbidden_contact_violation_count": _forbidden_contact_count(checks),
            "constraint_satisfaction_rate": _rate(len(satisfied), len(checked)),
            "constraint_violation_count": len(violations),
            "constraint_violation_summary": "; ".join(v["summary"] for v in violations),
        }
        metrics["constraint_faithfulness_score"] = _weighted_constraint_score(checks)
        metrics["constraint_faithfulness_error"] = None
        return _result(self.name, metrics, metrics["constraint_faithfulness_score"])


class SolverCertificateBenchmarkEvaluator:
    name = "solver_certificate"
    description = "Audits solver backend, status, objective, counts, timing, and infeasibility explanations."

    def evaluate_row(self, row: dict[str, Any]) -> BenchmarkEvaluatorResult:
        bundle, error = _bundle_from_row(row)
        if bundle is None:
            return _error(self.name, "missing_bundle", error)
        solver = bundle.solver_trace
        status = (solver.solver_status if solver else None) or row.get("solver_status")
        status_norm = str(status or "").strip().lower()
        valid_statuses = {"optimal", "feasible", "infeasible", "invalid", "timeout", "failed"}
        metrics = {
            "solver_trace_present": solver is not None,
            "solver_backend": solver.backend if solver else row.get("solver_backend"),
            "solver_status": status,
            "solver_status_valid": status_norm in valid_statuses,
            "solver_optimal": status_norm == "optimal",
            "solver_feasible": status_norm in {"optimal", "feasible"},
            "solver_infeasible": status_norm == "infeasible",
            "objective_value_present": solver is not None and solver.objective_value is not None,
            "objective_value": solver.objective_value if solver else None,
            "variable_count_present": solver is not None and solver.num_variables is not None,
            "constraint_count_present": solver is not None and solver.num_constraints is not None,
            "num_variables": solver.num_variables if solver else None,
            "num_constraints": solver.num_constraints if solver else None,
            "solve_time_seconds": solver.solve_time_seconds if solver else None,
            "infeasible_case_detected": status_norm == "infeasible",
            "infeasibility_explanation_present": bool(solver and solver.infeasibility_explanation),
        }
        metrics["solver_certificate_score"] = _mean(
            [
                _bool_score(metrics["solver_trace_present"]),
                _bool_score(metrics["solver_status_valid"]),
                _bool_score(metrics["objective_value_present"] or metrics["solver_infeasible"]),
                _bool_score(metrics["variable_count_present"]),
                _bool_score(metrics["constraint_count_present"]),
                _bool_score(metrics["infeasibility_explanation_present"] or not metrics["solver_infeasible"]),
            ]
        )
        metrics["solver_certificate_error"] = None
        return _result(self.name, metrics, metrics["solver_certificate_score"])


class EvidenceFaithfulnessBenchmarkEvaluator:
    name = "evidence_faithfulness"
    description = "Detects unsupported evidence claims in final explanations using transparent rules."

    def evaluate_row(self, row: dict[str, Any]) -> BenchmarkEvaluatorResult:
        bundle, error = _bundle_from_row(row)
        if bundle is None:
            return _error(self.name, "missing_bundle", error)
        explanation = bundle.final_decision.explanation if bundle.final_decision else ""
        claims = _extract_claims(explanation or "")
        evidence_ids = {
            item.evidence_id.lower()
            for item in (bundle.retrieval_trace.retrieved if bundle.retrieval_trace else [])
        }
        evidence_text = " ".join(evidence_ids)
        supported = [
            claim
            for claim in claims
            if any(evidence_id and evidence_id in claim for evidence_id in evidence_ids)
            or any(token in evidence_text for token in _claim_tokens(claim) if token.startswith("mp-"))
        ]
        unsupported = [claim for claim in claims if claim not in supported]
        wrong_family = _wrong_family_claim_rate(claims, bundle)
        citation_count = len(bundle.final_decision.citations if bundle.final_decision else [])
        metrics = {
            "final_explanation_present": bool(explanation),
            "num_evidence_claims": len(claims),
            "num_supported_evidence_claims": len(supported),
            "num_unsupported_evidence_claims": len(unsupported),
            "unsupported_evidence_claim_rate": _rate(len(unsupported), len(claims)),
            "wrong_family_evidence_rate": wrong_family,
            "retrieval_citation_completeness": _rate(citation_count, len(claims)),
            "evidence_constraint_consistency": _evidence_constraint_consistency(bundle),
        }
        metrics["evidence_faithfulness_score"] = _mean(
            [
                _bool_score(metrics["final_explanation_present"]),
                1.0 - metrics["unsupported_evidence_claim_rate"],
                1.0 - metrics["wrong_family_evidence_rate"],
                metrics["retrieval_citation_completeness"],
                metrics["evidence_constraint_consistency"],
            ]
        )
        metrics["evidence_faithfulness_error"] = None
        return _result(self.name, metrics, metrics["evidence_faithfulness_score"])


class AuditBundleCompletenessBenchmarkEvaluator:
    name = "audit_bundle_completeness"
    description = "Checks whether run artifacts and reproducibility metadata are complete and crosslinked."

    def evaluate_row(self, row: dict[str, Any]) -> BenchmarkEvaluatorResult:
        run_dir = _bundle_dir_from_row(row)
        if not run_dir:
            return _error(self.name, "missing_bundle", "No run_bundle_dir/bundle_dir column was provided.")
        inspection = inspect_run_bundle(run_dir, include_bundle=False)
        presence = inspection.artifact_presence
        required = {
            "prompt_present": presence.get("prompt", False),
            "structured_intent_present": presence.get("structured_intent", False),
            "retrieval_trace_present": presence.get("retrieval_trace", False),
            "retrieved_evidence_present": presence.get("retrieval_trace", False),
            "constraint_trace_present": presence.get("constraint_trace", False),
            "spp_trace_present": presence.get("spp_trace", False),
            "solver_trace_present": presence.get("solver_trace", False),
            "generated_cif_present": presence.get("generated_candidates", False),
            "validation_report_present": presence.get("validation_trace", False),
            "relaxation_report_present": presence.get("relaxation_trace", False),
            "diagnostics_report_present": presence.get("diagnostics_trace", False),
            "final_decision_present": presence.get("final_decision", False),
        }
        complete_count = sum(1 for value in required.values() if value)
        metrics = {
            **required,
            "artifact_bundle_complete": inspection.bundle_valid,
            "artifact_bundle_complete_rate": _rate(complete_count, len(required)),
            "artifact_crosslink_validity_rate": 1.0 if not inspection.crosslink_errors else 0.0,
            "missing_artifact_count": len(inspection.missing_artifacts),
            "missing_artifacts": ";".join(inspection.missing_artifacts),
            "reproducibility_metadata_present": inspection.reproducibility_metadata_present,
            "missing_reproducibility_fields": ";".join(inspection.missing_reproducibility_fields),
        }
        metrics["audit_bundle_score"] = _mean(
            [
                metrics["artifact_bundle_complete_rate"],
                metrics["artifact_crosslink_validity_rate"],
                _bool_score(metrics["reproducibility_metadata_present"]),
            ]
        )
        metrics["audit_bundle_error"] = None
        return _result(self.name, metrics, metrics["audit_bundle_score"])


def _bundle_from_row(row: dict[str, Any]) -> tuple[TraceableRunBundle | None, str | None]:
    run_dir = _bundle_dir_from_row(row)
    if not run_dir:
        return None, "No run_bundle_dir/bundle_dir column was provided."
    try:
        inspection = inspect_run_bundle(run_dir, manifest_row=row)
        if not inspection.bundle_valid:
            reason = "; ".join(
                inspection.missing_artifacts + inspection.parse_errors + inspection.crosslink_errors
            )
            return None, reason or "Bundle inspection failed."
        return load_run_bundle(run_dir, manifest_row=row), None
    except Exception as exc:
        return None, str(exc)


def _bundle_dir_from_row(row: dict[str, Any]) -> str | None:
    for key in ("run_bundle_dir", "bundle_dir", "run_dir"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _evidence_trace_metrics(bundle: TraceableRunBundle, row: dict[str, Any]) -> dict[str, Any]:
    evidence = bundle.retrieval_trace.retrieved if bundle.retrieval_trace else []
    target_formula = _lower(row.get("target_formula") or (bundle.structured_intent.formula if bundle.structured_intent else None))
    target_family = _lower(row.get("target_structure_family") or (bundle.structured_intent.prototype_family if bundle.structured_intent else None))
    target_sg = _lower(row.get("target_space_group") or (bundle.structured_intent.space_group if bundle.structured_intent else None))
    target_elements = set(_formula_elements(target_formula or ""))
    parseable = [item for item in evidence if item.parseable is not False]
    formula_relevant = [item for item in evidence if _lower(item.formula) == target_formula and target_formula]
    family_relevant = [item for item in evidence if _lower(item.family) == target_family and target_family]
    sg_relevant = [item for item in evidence if _lower(item.space_group) == target_sg and target_sg]
    system_relevant = [
        item
        for item in evidence
        if target_elements and target_elements.issubset(set(_formula_elements(item.formula or item.chemical_system or "")))
    ]
    return {
        "num_retrieved_parseable": len(parseable),
        "fraction_retrieved_parseable": _rate(len(parseable), len(evidence)),
        "fraction_retrieved_formula_relevant": _rate(len(formula_relevant), len(evidence)),
        "fraction_retrieved_family_relevant": _rate(len(family_relevant), len(evidence)),
        "fraction_retrieved_space_group_relevant": _rate(len(sg_relevant), len(evidence)),
        "fraction_retrieved_chemical_system_relevant": _rate(len(system_relevant), len(evidence)),
    }


def _constraints(bundle: TraceableRunBundle) -> list[dict[str, Any]]:
    if bundle.constraint_trace and bundle.constraint_trace.constraints:
        return bundle.constraint_trace.constraints
    if bundle.structured_intent and bundle.structured_intent.constraints:
        return bundle.structured_intent.constraints
    return []


def _linked_constraints(constraints: list[dict[str, Any]], evidence: list[Any]) -> list[dict[str, str]]:
    family_values = {_lower(item.family) for item in evidence if item.family}
    sg_values = {_lower(item.space_group) for item in evidence if item.space_group}
    formula_values = {_lower(item.formula) for item in evidence if item.formula}
    linked = []
    for constraint in constraints:
        kind = _constraint_type(constraint)
        value = _lower(constraint.get("expected") or constraint.get("value") or constraint.get("expected_value"))
        evidence_ids = constraint.get("evidence_ids") or constraint.get("source_evidence_ids") or []
        if evidence_ids:
            status = "linked"
        elif kind == "prototype_family" and value in family_values:
            status = "linked"
        elif kind == "space_group" and value in sg_values:
            status = "linked"
        elif kind in {"formula", "chemical_system"} and value in formula_values:
            status = "linked"
        elif kind in {"target_property", "site_role"}:
            status = "uncertain"
        else:
            status = "unsupported"
        linked.append({"constraint_id": str(constraint.get("constraint_id", "")), "status": status})
    return linked


def _check_constraint(constraint: dict[str, Any], row: dict[str, Any], bundle: TraceableRunBundle) -> dict[str, Any]:
    kind = _constraint_type(constraint)
    expected = constraint.get("expected") or constraint.get("value") or constraint.get("expected_value")
    severity = str(constraint.get("severity") or "hard")
    observed = None
    satisfied = None
    checked = True
    if kind == "formula":
        observed = row.get("reduced_formula") or row.get("formula")
        satisfied = _bool_or_compare(row.get("target_formula_match"), observed, expected)
    elif kind == "space_group":
        observed = row.get("detected_space_group") or row.get("declared_space_group")
        satisfied = _bool_or_compare(row.get("space_group_consistent"), observed, expected)
    elif kind == "crystal_system":
        observed = row.get("target_crystal_system")
        satisfied = _lower(observed) == _lower(expected)
    elif kind == "prototype_family":
        observed = row.get("target_structure_family") or row.get("prototype_family")
        satisfied = _lower(observed) == _lower(expected)
    elif kind == "minimum_distance":
        observed = _as_float(row.get("min_distance"))
        threshold = _as_float(expected)
        satisfied = observed is not None and threshold is not None and observed >= threshold
    elif kind == "forbidden_contact":
        observed = _as_int(row.get("num_bad_contacts")) or 0
        satisfied = observed == 0
    elif kind in {"site_role", "coordination_motif", "chemical_system", "target_property"}:
        observed = row.get(kind) or getattr(bundle.structured_intent, kind, None) if bundle.structured_intent else None
        satisfied = _lower(observed) == _lower(expected) if observed and expected else None
        checked = satisfied is not None
    else:
        checked = False
    return {
        "constraint_id": str(constraint.get("constraint_id") or constraint.get("id") or kind),
        "constraint_type": kind,
        "expected_value": expected,
        "observed_value": observed,
        "severity": severity,
        "source_text": constraint.get("source_text"),
        "solver_enforced": bool(constraint.get("solver_enforced", False)),
        "posthoc_checked": checked,
        "checked": checked,
        "satisfied": bool(satisfied) if satisfied is not None else False,
        "summary": f"{kind}: expected {expected}, observed {observed}",
    }


def _weighted_constraint_score(checks: list[dict[str, Any]]) -> float:
    checked = [check for check in checks if check["checked"]]
    total = sum(2.0 if check["severity"] == "hard" else 1.0 for check in checked)
    if total == 0:
        return 0.0
    earned = sum(
        (2.0 if check["severity"] == "hard" else 1.0)
        for check in checked
        if check["satisfied"]
    )
    return earned / total


def _category_value(checks: list[dict[str, Any]], kind: str) -> bool | None:
    for check in checks:
        if check["constraint_type"] == kind and check["checked"]:
            return bool(check["satisfied"])
    return None


def _forbidden_contact_count(checks: list[dict[str, Any]]) -> int:
    return sum(1 for check in checks if check["constraint_type"] == "forbidden_contact" and not check["satisfied"])


def _extract_claims(text: str) -> list[str]:
    if not text:
        return []
    pattern = r"(?i)(?:used|based on|retrieved|similar to|evidence from|constraint derived from)\s+([^.;]+)"
    return [match.strip().lower() for match in re.findall(pattern, text)]


def _claim_tokens(claim: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", claim.lower()) if len(token) > 2}


def _wrong_family_claim_rate(claims: list[str], bundle: TraceableRunBundle) -> float:
    families = {_lower(item.family) for item in (bundle.retrieval_trace.retrieved if bundle.retrieval_trace else []) if item.family}
    if not claims or not families:
        return 0.0
    family_words = {"spinel", "perovskite", "fluorite", "rutile", "pyrite", "rocksalt", "argyrodite"}
    wrong = 0
    for claim in claims:
        mentioned = family_words.intersection(_claim_tokens(claim))
        if mentioned and mentioned.difference(families):
            wrong += 1
    return _rate(wrong, len(claims))


def _evidence_constraint_consistency(bundle: TraceableRunBundle) -> float:
    constraints = _constraints(bundle)
    evidence = bundle.retrieval_trace.retrieved if bundle.retrieval_trace else []
    linked = _linked_constraints(constraints, evidence)
    return _rate(sum(1 for item in linked if item["status"] != "unsupported"), len(linked))


def _num_expected_pairs(bundle: TraceableRunBundle, row: dict[str, Any]) -> int:
    expected = _as_int(row.get("expected_spp_pairs"))
    if expected is not None:
        return expected
    elements = _formula_elements(row.get("target_formula") or (bundle.structured_intent.formula if bundle.structured_intent else "") or "")
    return max(len(elements), 1)


def _constraint_type(constraint: dict[str, Any]) -> str:
    return str(constraint.get("constraint_type") or constraint.get("type") or "").strip()


def _result(name: str, metrics: dict[str, Any], score: float) -> BenchmarkEvaluatorResult:
    return BenchmarkEvaluatorResult(
        name=name,
        ok=score >= 0.5,
        summary=f"score={score:.3f}",
        metrics=metrics,
    )


def _error(name: str, error_type: str, message: str | None) -> BenchmarkEvaluatorResult:
    return BenchmarkEvaluatorResult(
        name=name,
        ok=False,
        skipped=False,
        summary="failed",
        metrics={f"{name}_error": message},
        error_type=error_type,
        error_message=message,
    )


def _formula_elements(formula: str) -> list[str]:
    return re.findall(r"[A-Z][a-z]?", str(formula))


def _bool_or_compare(flag: Any, observed: Any, expected: Any) -> bool:
    parsed = _as_bool(flag)
    if parsed is not None:
        return parsed
    return _lower(observed) == _lower(expected)


def _lower(value: Any) -> str:
    return "" if value is None else str(value).strip().lower()


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def _as_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return None if number is None else int(number)


def _rate(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def _bool_score(value: Any) -> float:
    return 1.0 if value is True else 0.0


def _mean(values: list[float]) -> float:
    values = [float(value) for value in values]
    return sum(values) / len(values) if values else 0.0
