from __future__ import annotations

from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession
from sok_llm_orchestrator.optimization.stats import summarize_action_families


def render_session_summary(session: OptimizationSession) -> str:
    best = session.best_so_far or {}
    best_score = best.get("score")
    best_action = best.get("action_id")
    family_stats = summarize_action_families(session.iteration_history)
    report = build_optimization_report(session)
    diagnostics = report.get("diagnostics", {}) if isinstance(report, dict) else {}
    lines = [
        f"Session: {session.session_id}",
        f"Status: {session.status}",
        f"Iterations: {len(session.iteration_history)}",
        f"Best score: {best_score}",
        f"Best action: {best_action}",
        f"Termination reason: {session.termination_reason}",
        f"Blocked state: {session.blocked_state}",
        f"Action-family stats: {family_stats}",
        f"Unique actions/families: {diagnostics.get('unique_action_id_count')}/{diagnostics.get('unique_action_family_count')}",
        f"Unique score values: {diagnostics.get('unique_score_value_count')}",
        f"Flat objective: {diagnostics.get('flat_objective_flag')} ({diagnostics.get('likely_flatness_reason')})",
        f"Backend sensitivity: {diagnostics.get('backend_sensitivity_classification')}",
    ]
    return "\n".join(lines)
