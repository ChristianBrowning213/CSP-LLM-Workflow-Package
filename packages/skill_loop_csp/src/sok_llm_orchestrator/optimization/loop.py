from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.llm.client import LLMClient
from sok_llm_orchestrator.optimization.ablation import classify_ablation_change
from sok_llm_orchestrator.optimization.action_compile import compile_action, compiled_config_signature
from sok_llm_orchestrator.optimization.action_registry import list_registered_actions
from sok_llm_orchestrator.optimization.arbitration import arbitrate_action
from sok_llm_orchestrator.optimization.bandit import EpsilonGreedyBandit
from sok_llm_orchestrator.optimization.backend_sensitivity import (
    action_dimensions_from_compiled,
    build_sensitivity_trace_matrix,
    execution_signature_from_compiled,
    objective_audit_from_execution,
    objective_audit_from_run_dir,
    request_trace_from_run_dir,
)
from sok_llm_orchestrator.optimization.best_result import promote_best_result
from sok_llm_orchestrator.optimization.budget import BudgetTracker, OptimizationBudgetConfig
from sok_llm_orchestrator.optimization.infeasibility_recovery import (
    derive_recovery_state,
    recovery_priority,
)
from sok_llm_orchestrator.optimization.midloop_clarification import evaluate_midloop_clarification
from sok_llm_orchestrator.optimization.plan_schema import OptimizationPlan
from sok_llm_orchestrator.optimization.planner import build_optimization_plan
from sok_llm_orchestrator.optimization.preflight import run_optimization_preflight
from sok_llm_orchestrator.optimization.reporting import build_optimization_report, write_optimization_report
from sok_llm_orchestrator.optimization.reward_schema import RewardRecord, validate_reward_record
from sok_llm_orchestrator.optimization.scoring import score_reward_with_view
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession, stable_session_id
from sok_llm_orchestrator.optimization.session_store import OptimizationSessionStore
from sok_llm_orchestrator.optimization.stop_hook import evaluate_stop_hook
from sok_llm_orchestrator.optimization.stop_policy import evaluate_stop_policy
from sok_llm_orchestrator.optimization.stuck_detector import detect_stuck
from sok_llm_orchestrator.orchestrator.paired_run import run_paired_baseline_guided
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_payload, task_spec_from_query
from sok_llm_orchestrator.verification.qlip_outputs import structure_signature_from_cif_path


ExecutorFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def _merge_query_with_answers(query: str, clarification_answers: list[str] | None) -> str:
    if not clarification_answers:
        return query.strip()
    merged = query.strip()
    for answer in clarification_answers:
        text = str(answer).strip()
        if not text:
            continue
        merged = f"{merged} {text}".strip()
    return merged


def _non_improving_streak(iteration_history: list[dict[str, Any]]) -> int:
    streak = 0
    for item in reversed(iteration_history):
        if bool(item.get("best_updated", False)):
            break
        streak += 1
    return streak


def _structure_static_streak(iteration_history: list[dict[str, Any]]) -> int:
    streak = 0
    for item in reversed(iteration_history):
        changed = item.get("structure_changed_vs_previous")
        if isinstance(changed, bool) and changed:
            break
        if isinstance(changed, bool):
            streak += 1
            continue
        objective_vs_structure = item.get("objective_vs_structure_change", {})
        if isinstance(objective_vs_structure, dict):
            static = objective_vs_structure.get("structure_changed")
            if isinstance(static, bool):
                if static:
                    break
                streak += 1
                continue
        break
    return streak


def _clarification_policy_effects_from_answer(answer: str) -> dict[str, Any]:
    text = str(answer or "").strip().lower()
    if not text:
        return {}
    effects: dict[str, Any] = {}
    if "feasibility" in text and ("prioritize" in text or "first" in text or "over" in text):
        effects["prefer_feasibility"] = True
    if ("strict" in text and "symmetry" in text) or "keep rutile strict" in text:
        effects["preserve_strict_symmetry"] = True
    if ("relax" in text and "symmetry" in text) or ("soften" in text and "symmetry" in text):
        effects["allow_symmetry_relaxation"] = True
    if "broaden" in text and ("retrieval" in text or "corpus" in text):
        effects["broaden_retrieval_preference"] = True
    if "narrow" in text and ("retrieval" in text or "search" in text):
        effects["narrow_retrieval_preference"] = True
    return effects


def _merged_clarification_policy(session: OptimizationSession) -> dict[str, Any]:
    base = session.policy_state.get("clarification_policy", {})
    out = dict(base) if isinstance(base, dict) else {}
    entries = session.policy_state.get("clarification_policy_effects", [])
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            effects = item.get("effects", {})
            if not isinstance(effects, dict):
                continue
            for key, value in effects.items():
                if isinstance(value, bool):
                    out[str(key)] = bool(value)
    if bool(out.get("preserve_strict_symmetry", False)):
        out["allow_symmetry_relaxation"] = False
    return out


def _accumulate_controller_stats(
    session: OptimizationSession,
    *,
    channel: str,
    telemetry: dict[str, Any] | None,
    source: str | None = None,
) -> None:
    if not isinstance(telemetry, dict):
        return
    stats = session.policy_state.get("controller_output_stats", {})
    if not isinstance(stats, dict):
        stats = {}
    row = stats.get(channel, {})
    if not isinstance(row, dict):
        row = {}
    row["call_count"] = int(row.get("call_count", 0) or 0) + 1
    row["prompt_chars_total"] = int(row.get("prompt_chars_total", 0) or 0) + int(telemetry.get("prompt_chars", 0) or 0)
    row["completion_chars_total"] = int(row.get("completion_chars_total", 0) or 0) + int(
        telemetry.get("completion_chars", 0) or 0
    )
    row["parse_failures"] = int(row.get("parse_failures", 0) or 0) + int(telemetry.get("parse_failures", 0) or 0)
    row["schema_failures"] = int(row.get("schema_failures", 0) or 0) + int(telemetry.get("schema_failures", 0) or 0)
    row["retry_count"] = int(row.get("retry_count", 0) or 0) + int(telemetry.get("retry_count", 0) or 0)
    row["fallback_count"] = int(row.get("fallback_count", 0) or 0) + int(telemetry.get("fallback_count", 0) or 0)
    row["contains_think_count"] = int(row.get("contains_think_count", 0) or 0) + int(
        telemetry.get("contains_think_count", 0) or 0
    )
    row["contains_fence_count"] = int(row.get("contains_fence_count", 0) or 0) + int(
        telemetry.get("contains_fence_count", 0) or 0
    )
    if int(telemetry.get("parse_failures", 0) or 0) > 0 or int(telemetry.get("schema_failures", 0) or 0) > 0:
        row["malformed_output_events"] = int(row.get("malformed_output_events", 0) or 0) + 1
    if isinstance(telemetry.get("failure_reason"), str) and str(telemetry.get("failure_reason")).strip():
        reasons = row.get("failure_reasons", {})
        if not isinstance(reasons, dict):
            reasons = {}
        reason = str(telemetry.get("failure_reason")).strip()
        reasons[reason] = int(reasons.get(reason, 0) or 0) + 1
        row["failure_reasons"] = reasons
    if isinstance(source, str) and source.strip():
        sources = row.get("sources", {})
        if not isinstance(sources, dict):
            sources = {}
        key = source.strip()
        sources[key] = int(sources.get(key, 0) or 0) + 1
        row["sources"] = sources
    stats[channel] = row
    session.policy_state["controller_output_stats"] = stats


def _regime_strength(action: Any) -> int:
    weight = str(getattr(action, "weighting_profile", "") or "balanced").strip().lower()
    perturb = str(getattr(action, "structure_perturbation_profile", "") or "minimal").strip().lower()
    seed = str(getattr(action, "template_seed_profile", "") or "canonical").strip().lower()
    lattice = str(getattr(action, "lattice_candidate_profile", "") or "narrow").strip().lower()
    symmetry = str(getattr(action, "symmetry_relaxation_profile", "") or "strict").strip().lower()
    ordering = str(getattr(action, "ordering_perturbation_profile", "") or "none").strip().lower()
    weight_rank = {
        "base_dominant": 0,
        "balanced": 1,
        "guidance_dominant": 2,
        "property_push_strong": 3,
        "experimental_extreme": 4,
    }.get(weight, 1)
    perturb_rank = {
        "minimal": 0,
        "moderate": 1,
        "aggressive": 2,
        "template_shuffle": 3,
    }.get(perturb, 0)
    seed_rank = {
        "canonical": 0,
        "polymorph_mix": 1,
        "framework_bias": 2,
        "ordering_bias": 3,
    }.get(seed, 0)
    lattice_rank = {
        "narrow": 0,
        "expanded": 1,
        "multibasin": 2,
    }.get(lattice, 0)
    symmetry_rank = {
        "strict": 0,
        "soft": 1,
        "relaxed": 2,
    }.get(symmetry, 0)
    ordering_rank = {
        "none": 0,
        "site_shuffle": 1,
        "cation_swap_bias": 2,
    }.get(ordering, 0)
    return weight_rank * 100 + perturb_rank * 20 + seed_rank * 10 + lattice_rank * 5 + symmetry_rank * 2 + ordering_rank


def _normalize_hypotheses(case_metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(case_metadata, dict):
        return []
    raw = case_metadata.get("hypotheses")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        hyp_id = item.get("hypothesis_id")
        if not isinstance(hyp_id, str) or not hyp_id.strip():
            continue
        out.append(dict(item))
    return out


def _active_hypothesis(session: OptimizationSession) -> dict[str, Any] | None:
    state = session.hypothesis_state if isinstance(session.hypothesis_state, dict) else {}
    active_id = state.get("active_hypothesis_id")
    hypotheses = state.get("available_hypotheses", [])
    if not isinstance(active_id, str) or not isinstance(hypotheses, list):
        return None
    for item in hypotheses:
        if isinstance(item, dict) and str(item.get("hypothesis_id")) == active_id:
            return dict(item)
    return None


def _hypothesis_compatibility(action: Any, hypothesis: dict[str, Any] | None) -> int:
    if not isinstance(hypothesis, dict):
        return 0
    family = str(hypothesis.get("hypothesis_family", "")).strip().lower()
    challenge = str(hypothesis.get("challenge_type", "")).strip().lower()
    corpus_bias = str(hypothesis.get("suggested_corpus_bias", "")).strip().lower()
    perturb_bias = str(hypothesis.get("suggested_perturbation_bias", "")).strip().lower()
    score = 0

    if "framework" in family or "nasicon" in family:
        if str(getattr(action, "template_seed_profile", "")).strip().lower() == "framework_bias":
            score += 4
        if str(getattr(action, "lattice_candidate_profile", "")).strip().lower() in {"expanded", "multibasin"}:
            score += 3
    if "ordering" in family:
        if str(getattr(action, "ordering_perturbation_profile", "")).strip().lower() != "none":
            score += 4
        if str(getattr(action, "template_seed_profile", "")).strip().lower() == "ordering_bias":
            score += 3
    if "perovskite" in family or "polymorph" in family:
        if str(getattr(action, "template_seed_profile", "")).strip().lower() == "polymorph_mix":
            score += 3
        if str(getattr(action, "symmetry_relaxation_profile", "")).strip().lower() in {"soft", "relaxed"}:
            score += 2
    if "template_relaxed" in family:
        if str(getattr(action, "structure_perturbation_profile", "")).strip().lower() == "template_shuffle":
            score += 4

    if challenge == "framework_sensitive":
        if str(getattr(action, "corpus_strategy", "")).strip().lower() == "family_biased":
            score += 2
    if challenge == "ordering_sensitive":
        if str(getattr(action, "ordering_perturbation_profile", "")).strip().lower() in {"site_shuffle", "cation_swap_bias"}:
            score += 2
    if challenge == "polymorph_ambiguous":
        if str(getattr(action, "structure_perturbation_profile", "")).strip().lower() in {"moderate", "aggressive", "template_shuffle"}:
            score += 2

    if "family" in corpus_bias and str(getattr(action, "corpus_strategy", "")).strip().lower() == "family_biased":
        score += 1
    if "tight" in corpus_bias and str(getattr(action, "corpus_strategy", "")).strip().lower() == "composition_tight":
        score += 1
    if "property" in corpus_bias and str(getattr(action, "corpus_strategy", "")).strip().lower() == "property_biased":
        score += 1

    if "ordering" in perturb_bias and str(getattr(action, "ordering_perturbation_profile", "")).strip().lower() != "none":
        score += 1
    if "symmetry" in perturb_bias and str(getattr(action, "symmetry_relaxation_profile", "")).strip().lower() in {"soft", "relaxed"}:
        score += 1
    if "template" in perturb_bias and str(getattr(action, "structure_perturbation_profile", "")).strip().lower() == "template_shuffle":
        score += 1
    return score


def _current_hypothesis_iteration_count(session: OptimizationSession) -> int:
    active = session.hypothesis_state.get("active_hypothesis_id") if isinstance(session.hypothesis_state, dict) else None
    if not isinstance(active, str):
        return 0
    count = 0
    for item in reversed(session.iteration_history):
        if str(item.get("active_hypothesis_id", "")) != active:
            break
        count += 1
    return count


def _update_hypothesis_branch_best(session: OptimizationSession, row: dict[str, Any]) -> None:
    if not isinstance(session.hypothesis_state, dict):
        return
    hyp_id = row.get("active_hypothesis_id")
    if not isinstance(hyp_id, str) or not hyp_id:
        return
    score = row.get("score")
    if not isinstance(score, (int, float)):
        return
    branch_best = session.hypothesis_state.get("branch_best", {})
    if not isinstance(branch_best, dict):
        branch_best = {}
    current = branch_best.get(hyp_id)
    current_score = current.get("score") if isinstance(current, dict) else None
    if not isinstance(current_score, (int, float)) or float(score) > float(current_score):
        branch_best[hyp_id] = {
            "score": float(score),
            "iteration_index": row.get("iteration_index"),
            "action_id": row.get("action_id"),
            "action_family": row.get("action_family"),
            "structure_signature": row.get("structure_signature"),
            "property_estimate": (
                row.get("reward", {}).get("property_estimate")
                if isinstance(row.get("reward"), dict)
                else None
            ),
        }
    session.hypothesis_state["branch_best"] = branch_best


def _maybe_switch_hypothesis(
    session: OptimizationSession,
    *,
    stagnation_window: int,
) -> dict[str, Any] | None:
    state = session.hypothesis_state if isinstance(session.hypothesis_state, dict) else {}
    available = state.get("available_hypotheses", [])
    active_id = state.get("active_hypothesis_id")
    if not isinstance(active_id, str) or not isinstance(available, list) or len(available) <= 1:
        return None

    active_count = _current_hypothesis_iteration_count(session)
    min_iters_before_switch = max(1, min(2, int(stagnation_window)))
    if active_count < min_iters_before_switch:
        return None

    no_improve = _non_improving_streak(session.iteration_history)
    structure_static = _structure_static_streak(session.iteration_history)
    if no_improve < max(1, int(stagnation_window) - 1) and structure_static < max(1, int(stagnation_window) - 1):
        return None

    tried = [str(item) for item in state.get("tried_hypothesis_ids", []) if isinstance(item, str)]
    available_ids = [
        str(item.get("hypothesis_id"))
        for item in available
        if isinstance(item, dict) and isinstance(item.get("hypothesis_id"), str)
    ]
    untried = [item for item in available_ids if item and item not in tried]
    target_id: str | None = untried[0] if untried else None

    if target_id is None:
        branch_best = state.get("branch_best", {})
        if not isinstance(branch_best, dict):
            return None
        ranked = sorted(
            [
                (hid, float(data.get("score")))
                for hid, data in branch_best.items()
                if isinstance(hid, str)
                and isinstance(data, dict)
                and isinstance(data.get("score"), (int, float))
                and hid != active_id
            ],
            key=lambda item: (-item[1], item[0]),
        )
        if ranked:
            target_id = ranked[0][0]
    if not isinstance(target_id, str) or not target_id or target_id == active_id:
        return None

    event = {
        "iteration_index": len(session.iteration_history),
        "from_hypothesis_id": active_id,
        "to_hypothesis_id": target_id,
        "reason": "stagnation_or_structure_static",
        "no_improve_streak": no_improve,
        "structure_static_streak": structure_static,
    }
    state["active_hypothesis_id"] = target_id
    if target_id not in tried:
        tried.append(target_id)
    state["tried_hypothesis_ids"] = tried
    switch_events = state.get("switch_events", [])
    if not isinstance(switch_events, list):
        switch_events = []
    switch_events.append(event)
    state["switch_events"] = switch_events
    return event


def _ordered_candidates(
    *,
    session: OptimizationSession,
    budget: BudgetTracker,
    enforce_diversity: bool,
    structure_stagnation_escalation: bool,
    recovery_stage: int = 0,
    clarification_policy: dict[str, Any] | None = None,
) -> list[str]:
    policy = clarification_policy if isinstance(clarification_policy, dict) else {}
    hypothesis = _active_hypothesis(session)
    last_row = session.iteration_history[-1] if session.iteration_history else {}
    if not isinstance(last_row, dict):
        last_row = {}
    last_action_id = str(last_row.get("action_id")) if isinstance(last_row.get("action_id"), str) else None
    last_action_family = (
        str(last_row.get("action_family")) if isinstance(last_row.get("action_family"), str) else None
    )
    actions = [
        action
        for action in list_registered_actions()
        if budget.is_action_family_allowed(action.action_family) and budget.is_action_allowed(action.action_id)
    ]
    if bool(policy.get("preserve_strict_symmetry", False)):
        strict_only = [
            action
            for action in actions
            if str(getattr(action, "symmetry_relaxation_profile", "") or "strict").strip().lower() == "strict"
        ]
        if strict_only:
            actions = strict_only
    if structure_stagnation_escalation and actions:
        strengths = [_regime_strength(action) for action in actions]
        max_strength = max(strengths)
        threshold = max_strength - 5
        escalated = [action for action in actions if _regime_strength(action) >= threshold]
        if escalated:
            actions = escalated
    priorities: list[str] = []
    if isinstance(session.optimization_plan, dict):
        raw_priorities = session.optimization_plan.get("action_family_priorities")
        if isinstance(raw_priorities, list):
            priorities = [str(item) for item in raw_priorities if isinstance(item, str)]
    priority_rank = {family: idx for idx, family in enumerate(priorities)}
    allowlist_rank = {
        str(action_id): idx
        for idx, action_id in enumerate(list(budget.config.action_allowlist))
        if isinstance(action_id, str) and action_id.strip()
    }
    best_family = None
    if isinstance(session.best_so_far, dict):
        if isinstance(session.best_so_far.get("action_family"), str):
            best_family = str(session.best_so_far["action_family"])
    actions_sorted = sorted(
        actions,
        key=lambda action: (
            -_hypothesis_compatibility(action, hypothesis),
            (
                -recovery_priority(
                    action=action,
                    stage=int(recovery_stage),
                    preserve_strict_symmetry=bool(policy.get("preserve_strict_symmetry", False)),
                    broaden_retrieval_preference=bool(policy.get("broaden_retrieval_preference", False)),
                )
                if int(recovery_stage) > 0
                else 0
            ),
            (
                1
                if int(recovery_stage) > 0
                and isinstance(last_action_id, str)
                and action.action_id == last_action_id
                else 0
            ),
            (
                1
                if int(recovery_stage) >= 3
                and isinstance(last_action_family, str)
                and action.action_family == last_action_family
                else 0
            ),
            1 if (enforce_diversity and best_family and action.action_family == best_family) else 0,
            (
                -_regime_strength(action)
                if structure_stagnation_escalation
                else 0
            ),
            priority_rank.get(action.action_family, len(priority_rank) + 1),
            allowlist_rank.get(action.action_id, len(allowlist_rank) + 1),
            action.action_id,
        ),
    )
    return [action.action_id for action in actions_sorted]


def _extract_structure_artifact_path(run_dir: Path) -> str | None:
    solve_path = run_dir / "artifacts" / "qlip_solve.json"
    if not solve_path.exists():
        return None
    payload = json.loads(solve_path.read_text(encoding="utf-8"))
    root = payload.get("result", payload)
    if not isinstance(root, dict):
        return None
    nested = root.get("result")
    if isinstance(nested, dict):
        outputs = nested.get("outputs")
        if isinstance(outputs, dict) and isinstance(outputs.get("cif"), str):
            return str(outputs["cif"])
        if isinstance(nested.get("cif_path"), str):
            return str(nested["cif_path"])
    if isinstance(root.get("cif_path"), str):
        return str(root["cif_path"])
    fallback = run_dir / "artifacts" / "qlip" / "solution.cif"
    if fallback.exists():
        return str(fallback)
    return None


def _classify_objective_vs_structure_change(
    *,
    objective_changed: bool,
    guidance_changed: bool,
    structure_changed: bool,
    property_delta: float | None,
) -> str:
    if objective_changed and not structure_changed:
        return "objective_changed_structure_unchanged"
    if guidance_changed and not structure_changed:
        return "guidance_changed_structure_unchanged"
    if structure_changed:
        if isinstance(property_delta, (int, float)) and float(property_delta) > 1e-12:
            return "structure_changed_property_gain"
        return "structure_changed_no_property_gain"
    if objective_changed or guidance_changed:
        return "objective_or_guidance_changed_structure_static"
    return "no_meaningful_change"


@dataclass(slots=True)
class OptimizationRunResult:
    session_id: str
    status: str
    session_path: Path


class OptimizationEngine:
    def __init__(
        self,
        *,
        workspace: Path,
        settings: Settings,
        mode: str,
        llm_client: LLMClient | None = None,
        executor: ExecutorFn | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.mode = mode
        self.llm_client = llm_client
        self.executor = executor
        self.store = OptimizationSessionStore(self.workspace)

    def start(
        self,
        *,
        query: str | None = None,
        task_spec_payload: dict[str, Any] | None = None,
        auto_run: bool = True,
        seed_hint: str = "default",
        clarification_answers: list[str] | None = None,
        case_metadata: dict[str, Any] | None = None,
        strict_phase1_benchmark_mode: bool = False,
    ) -> OptimizationRunResult:
        if task_spec_payload is not None:
            task_spec = task_spec_from_payload(
                task_spec_payload,
                strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
            )
            query_text = str(task_spec.query_text)
        else:
            if not isinstance(query, str) or not query.strip():
                raise ValueError("query is required when task_spec_payload is not provided.")
            merged_query = _merge_query_with_answers(query, clarification_answers)
            task_spec = task_spec_from_query(
                merged_query,
                strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
            )
            query_text = str(query)
        preflight = run_optimization_preflight(task_spec)
        budget_cfg = OptimizationBudgetConfig.from_settings(self.settings)
        budget_tracker = BudgetTracker(config=budget_cfg)
        session_id = stable_session_id(
            task_spec=preflight.task_spec.to_dict(),
            mode=self.mode,
            budget_signature=budget_cfg.to_dict(),
            seed_hint=seed_hint,
        )

        plan: OptimizationPlan | None = None
        status = "PENDING_CLARIFICATION"
        if preflight.ready:
            case_hypotheses = _normalize_hypotheses(case_metadata)
            hypothesis_labels = [
                str(item.get("label"))
                for item in case_hypotheses
                if isinstance(item.get("label"), str) and str(item.get("label")).strip()
            ]
            plan = build_optimization_plan(
                task_spec=preflight.task_spec.to_dict(),
                max_iterations=budget_cfg.max_iterations,
                exploration_rate=budget_cfg.exploration_rate,
                stagnation_window=budget_cfg.stagnation_window,
                llm_client=self.llm_client if self.mode == "live" else None,
            )
            if hypothesis_labels:
                plan.initial_hypotheses = hypothesis_labels[:4]
            status = "READY"

        conversation = [{"role": "chemist", "text": query_text}]
        if clarification_answers:
            for answer in clarification_answers:
                text = str(answer).strip()
                if not text:
                    continue
                conversation.append({"role": "chemist", "text": text})
        if preflight.questions:
            for question in preflight.questions:
                conversation.append({"role": "orchestrator", "text": question})

        bandit = EpsilonGreedyBandit(epsilon=budget_cfg.exploration_rate, seed=0)
        available_hypotheses = _normalize_hypotheses(case_metadata)
        active_hypothesis_id = None
        if available_hypotheses and isinstance(available_hypotheses[0].get("hypothesis_id"), str):
            active_hypothesis_id = str(available_hypotheses[0]["hypothesis_id"])
        case_execution_overrides = {}
        if isinstance(case_metadata, dict) and isinstance(case_metadata.get("qlip_objective"), dict):
            case_execution_overrides["qlip_objective"] = dict(case_metadata["qlip_objective"])
        if isinstance(case_metadata, dict) and isinstance(case_metadata.get("external_predictors"), list):
            case_execution_overrides["external_predictors"] = list(case_metadata["external_predictors"])
        session = OptimizationSession(
            session_id=session_id,
            status=status,
            task_spec=preflight.task_spec.to_dict(),
            clarification_state={
                "ready": preflight.ready,
                "unresolved_critical_fields": preflight.unresolved_critical_fields,
                "pending_questions": list(preflight.questions),
                "defaults_used": list(preflight.defaults_used),
                "supplied_answers": [str(a).strip() for a in (clarification_answers or []) if str(a).strip()],
                "deferred_questions": [],
                "assumptions_log": [],
                "answer_applied": False,
                "answer_policy_effects": {},
            },
            optimization_plan=plan.to_dict() if plan else None,
            budget_state=budget_tracker.to_dict(),
            conversation_history=conversation,
            policy_state={
                "bandit": bandit.to_dict(),
                "recovery_state": {
                    "attempt_count": 0,
                    "regimes_tried": [],
                    "first_feasible_iteration": None,
                    "first_feasible_regime": None,
                    "forced_stage": 0,
                },
                "stop_hook_invocations": [],
                "clarification_policy": {},
                "clarification_policy_effects": [],
                "controller_output_stats": {},
                "strict_phase1_benchmark_mode": bool(strict_phase1_benchmark_mode),
                "case_execution_overrides": case_execution_overrides,
            },
            hypothesis_state={
                "available_hypotheses": available_hypotheses,
                "active_hypothesis_id": active_hypothesis_id,
                "tried_hypothesis_ids": [active_hypothesis_id] if isinstance(active_hypothesis_id, str) else [],
                "branch_history": [],
                "switch_events": [],
                "branch_best": {},
            },
        )
        path = self.store.save(session)
        write_optimization_report(session, path.parent)
        if auto_run and preflight.ready:
            session = self._run_loop(session, max_new_iterations=None)
            path = self.store.save(session)
            write_optimization_report(session, path.parent)
        return OptimizationRunResult(session_id=session.session_id, status=session.status, session_path=path)

    def get(self, session_id: str) -> OptimizationSession:
        return self.store.load(session_id)

    def continue_session(
        self,
        *,
        session_id: str,
        clarification_answer: str | None = None,
        max_new_iterations: int | None = None,
    ) -> OptimizationRunResult:
        session = self.store.load(session_id)
        if clarification_answer:
            merged_query = f"{session.task_spec.get('query_text', '').strip()} {clarification_answer.strip()}".strip()
            updated_spec = task_spec_from_query(
                merged_query,
                strict_phase1_benchmark_mode=bool(
                    session.policy_state.get("strict_phase1_benchmark_mode", False)
                ),
            )
            preflight = run_optimization_preflight(updated_spec)
            policy_effects = _clarification_policy_effects_from_answer(clarification_answer)
            merged_policy = _merged_clarification_policy(session)
            for key, value in policy_effects.items():
                if isinstance(value, bool):
                    merged_policy[str(key)] = bool(value)
            if bool(merged_policy.get("preserve_strict_symmetry", False)):
                merged_policy["allow_symmetry_relaxation"] = False
            entries = session.policy_state.get("clarification_policy_effects", [])
            if not isinstance(entries, list):
                entries = []
            entries.append(
                {
                    "iteration_index": len(session.iteration_history),
                    "answer": clarification_answer.strip(),
                    "effects": dict(policy_effects),
                }
            )
            session.policy_state["clarification_policy_effects"] = entries
            session.policy_state["clarification_policy"] = merged_policy
            session.task_spec = preflight.task_spec.to_dict()
            session.clarification_state = {
                "ready": preflight.ready,
                "unresolved_critical_fields": preflight.unresolved_critical_fields,
                "pending_questions": list(preflight.questions),
                "defaults_used": list(preflight.defaults_used),
                "supplied_answers": list(session.clarification_state.get("supplied_answers", [])) + [clarification_answer.strip()],
                "deferred_questions": list(session.clarification_state.get("deferred_questions", [])),
                "assumptions_log": list(session.clarification_state.get("assumptions_log", [])),
                "answer_applied": bool(policy_effects),
                "answer_policy_effects": dict(policy_effects),
            }
            session.conversation_history.append({"role": "chemist", "text": clarification_answer})
            if preflight.ready and session.optimization_plan is None:
                cfg = BudgetTracker.from_dict(session.budget_state).config
                session.optimization_plan = build_optimization_plan(
                    task_spec=preflight.task_spec.to_dict(),
                    max_iterations=cfg.max_iterations,
                    exploration_rate=cfg.exploration_rate,
                    stagnation_window=cfg.stagnation_window,
                ).to_dict()
                session.status = "READY"
                session.blocked_state = None
            elif not preflight.ready:
                session.status = "PENDING_CLARIFICATION"

        if session.status in {"PENDING_CLARIFICATION", "WAITING_CLARIFICATION"} and not clarification_answer:
            path = self.store.save(session)
            write_optimization_report(session, path.parent)
            return OptimizationRunResult(session_id=session.session_id, status=session.status, session_path=path)

        if session.optimization_plan is None:
            path = self.store.save(session)
            write_optimization_report(session, path.parent)
            return OptimizationRunResult(session_id=session.session_id, status=session.status, session_path=path)

        session = self._run_loop(session, max_new_iterations=max_new_iterations)
        path = self.store.save(session)
        write_optimization_report(session, path.parent)
        return OptimizationRunResult(session_id=session.session_id, status=session.status, session_path=path)

    def _run_loop(self, session: OptimizationSession, max_new_iterations: int | None) -> OptimizationSession:
        budget = BudgetTracker.from_dict(session.budget_state)
        bandit = EpsilonGreedyBandit(
            epsilon=budget.config.exploration_rate,
            seed=0,
            state=session.policy_state.get("bandit", {}),
        )
        recovery_state = session.policy_state.get("recovery_state", {})
        if not isinstance(recovery_state, dict):
            recovery_state = {}
        recovery_state.setdefault("attempt_count", 0)
        recovery_state.setdefault("regimes_tried", [])
        recovery_state.setdefault("first_feasible_iteration", None)
        recovery_state.setdefault("first_feasible_regime", None)
        recovery_state.setdefault("forced_stage", 0)
        session.policy_state["recovery_state"] = recovery_state
        if not isinstance(session.policy_state.get("stop_hook_invocations"), list):
            session.policy_state["stop_hook_invocations"] = []
        if not isinstance(session.policy_state.get("clarification_policy"), dict):
            session.policy_state["clarification_policy"] = {}
        if not isinstance(session.policy_state.get("clarification_policy_effects"), list):
            session.policy_state["clarification_policy_effects"] = []
        if not isinstance(session.policy_state.get("controller_output_stats"), dict):
            session.policy_state["controller_output_stats"] = {}
        session.status = "RUNNING"
        started = 0
        while True:
            if max_new_iterations is not None and started >= max_new_iterations:
                break
            budget_reason = budget.can_take_iteration(include_failed_limit=False)
            if budget_reason:
                session.status = "STOPPED"
                session.termination_reason = budget_reason
                break

            structure_static_streak = _structure_static_streak(session.iteration_history)
            escalation_threshold = max(1, int(budget.config.stagnation_window) - 1)
            stagnation_escalation_active = structure_static_streak >= escalation_threshold
            clarification_policy = _merged_clarification_policy(session)
            recovery = derive_recovery_state(
                iteration_history=session.iteration_history,
                repeated_infeasible_limit=budget.config.max_failed_iterations,
                forced_stage=int(recovery_state.get("forced_stage", 0) or 0),
                prefer_feasibility=bool(clarification_policy.get("prefer_feasibility", False)),
            )
            candidates = [
                action_id
                for action_id in _ordered_candidates(
                    session=session,
                    budget=budget,
                    enforce_diversity=_non_improving_streak(session.iteration_history) >= escalation_threshold,
                    structure_stagnation_escalation=stagnation_escalation_active,
                    recovery_stage=int(recovery.stage),
                    clarification_policy=clarification_policy,
                )
            ]
            if not candidates:
                session.status = "STOPPED"
                session.termination_reason = "budget_exhausted:action_family_limits"
                break

            no_improve_streak = _non_improving_streak(session.iteration_history)
            active_hypothesis = _active_hypothesis(session)
            ctx = {
                "iteration_count": len(session.iteration_history),
                "best_so_far": session.best_so_far,
                "task_spec": session.task_spec,
                "clarification_state": session.clarification_state,
                "clarification_policy": clarification_policy,
                "hypothesis_state": session.hypothesis_state if isinstance(session.hypothesis_state, dict) else {},
                "active_hypothesis": active_hypothesis,
                "recent_iterations": session.iteration_history[-5:],
                "shortlist_size": min(5, max(3, len(candidates))),
                "exploration_rate_override": (
                    min(0.6, budget.config.exploration_rate + 0.2)
                    if no_improve_streak >= max(2, budget.config.stagnation_window - 1)
                    else budget.config.exploration_rate
                ),
                "no_improve_streak": no_improve_streak,
                "structure_static_streak": structure_static_streak,
                "stagnation_escalation_active": stagnation_escalation_active,
                "recovery_stage": int(recovery.stage),
                "recovery_regime": str(recovery.regime),
                "infeasible_streak": int(recovery.infeasible_streak),
                "recovery_active": bool(recovery.recovery_active),
            }
            arbitration = arbitrate_action(
                bandit=bandit,
                candidate_action_ids=candidates,
                llm_client=self.llm_client,
                session_context=ctx,
            )
            _accumulate_controller_stats(
                session,
                channel="action_selector",
                telemetry=(
                    arbitration.llm_proposal.telemetry
                    if isinstance(arbitration.llm_proposal.telemetry, dict)
                    else {}
                ),
                source=arbitration.llm_proposal.source,
            )
            action = arbitration.chosen_action
            active_hypothesis = _active_hypothesis(session)
            try:
                compiled = compile_action(action, hypothesis=active_hypothesis)
            except TypeError:
                compiled = compile_action(action)
            compiled_dict = compiled.to_dict()
            case_execution_overrides = (
                dict(session.policy_state.get("case_execution_overrides", {}))
                if isinstance(session.policy_state.get("case_execution_overrides"), dict)
                else {}
            )
            if case_execution_overrides:
                for key in ("baseline_overrides", "guided_overrides"):
                    current = compiled_dict.get(key, {})
                    if not isinstance(current, dict):
                        current = {}
                    merged = dict(current)
                    merged.update(case_execution_overrides)
                    compiled_dict[key] = merged
            compiled_sig = compiled_config_signature(compiled_dict, include_action_identity=False)
            executable_sig = execution_signature_from_compiled(
                query=str(session.task_spec["query_text"]),
                mode=self.mode,
                compiled=compiled_dict,
            )
            execution = self._execute(
                session.task_spec["query_text"],
                compiled_dict,
                strict_phase1_benchmark_mode=bool(
                    session.policy_state.get("strict_phase1_benchmark_mode", False)
                ),
            )
            objective_audit = objective_audit_from_execution(execution)
            action_dimensions = action_dimensions_from_compiled(compiled_dict)
            request_trace = (
                dict(execution.get("guided_request_trace", {}))
                if isinstance(execution.get("guided_request_trace"), dict)
                else {"effective_overrides": dict(compiled_dict.get("guided_overrides", {}))}
            )
            effective_overrides = (
                dict(request_trace.get("effective_overrides", {}))
                if isinstance(request_trace.get("effective_overrides"), dict)
                else {}
            )
            weighting_profile = str(effective_overrides.get("weighting_profile", "balanced")).strip().lower()
            perturbation_profile = str(
                effective_overrides.get("structure_perturbation_profile", "minimal")
            ).strip().lower()
            template_seed_profile = str(
                effective_overrides.get("template_seed_profile", "canonical")
            ).strip().lower()
            lattice_candidate_profile = str(
                effective_overrides.get("lattice_candidate_profile", "narrow")
            ).strip().lower()
            symmetry_relaxation_profile = str(
                effective_overrides.get("symmetry_relaxation_profile", "strict")
            ).strip().lower()
            ordering_perturbation_profile = str(
                effective_overrides.get("ordering_perturbation_profile", "none")
            ).strip().lower()
            run_reference = execution.get("run_reference", {})
            if not isinstance(run_reference, dict):
                run_reference = {}
            structure_path = (
                str(run_reference.get("structure_artifact_path"))
                if isinstance(run_reference.get("structure_artifact_path"), str)
                else None
            )
            structure_tracking = structure_signature_from_cif_path(structure_path)
            if structure_path is not None:
                run_reference["structure_artifact_path"] = structure_path
            run_reference["structure_tracking"] = {
                "structure_signature": structure_tracking.get("structure_signature"),
                "structure_source": structure_tracking.get("structure_source"),
                "structure_content_hash": structure_tracking.get("structure_content_hash"),
                "formula_signature": structure_tracking.get("formula_signature"),
                "lattice_signature": structure_tracking.get("lattice_signature"),
                "path_exists": bool(structure_tracking.get("path_exists", False)),
            }
            baseline_request_trace = (
                dict(execution.get("baseline_request_trace", {}))
                if isinstance(execution.get("baseline_request_trace"), dict)
                else {"effective_overrides": dict(compiled_dict.get("baseline_overrides", {}))}
            )

            reward = RewardRecord(
                action_id=action.action_id,
                action_family=action.action_family,
                primary_objective=execution.get("primary_objective"),
                feasibility=bool(execution.get("feasible", False)),
                solver_stability=1.0 if bool(execution.get("feasible", False)) else 0.0,
                novelty=None,
                property_estimate=(float(execution["property_estimate"]) if isinstance(execution.get("property_estimate"), (int, float)) else None),
                analogue_quality=None,
                valid_for_learning=bool(execution.get("valid_for_learning", True)),
                run_reference=run_reference,
            )
            validate_reward_record(reward.to_dict())
            score, score_components = score_reward_with_view(
                reward,
                selection_metric_view=str(budget.config.selection_metric_view),
                objective_audit=objective_audit,
                request_trace=request_trace,
            )
            if reward.valid_for_learning:
                bandit.update(action.action_id, score)

            best_candidate = {
                "iteration_index": len(session.iteration_history),
                "action_id": action.action_id,
                "action_family": action.action_family,
                "score": score,
                "primary_objective": reward.primary_objective,
                "run_reference": run_reference,
            }
            session.best_so_far, best_updated = promote_best_result(session.best_so_far, best_candidate)
            prev_row = session.iteration_history[-1] if session.iteration_history else None
            prev_compiled = prev_row.get("compiled_action") if isinstance(prev_row, dict) else None
            delta = (
                classify_ablation_change(prev_compiled, compiled_dict).to_dict()
                if isinstance(prev_compiled, dict)
                else {"changed_knobs": ["initial_action"], "category": "initial"}
            )
            prev_sig = prev_row.get("compiled_config_signature") if isinstance(prev_row, dict) else None
            prev_exec_sig = prev_row.get("executable_signature") if isinstance(prev_row, dict) else None
            prev_score = prev_row.get("score") if isinstance(prev_row, dict) else None
            prev_obj = prev_row.get("primary_objective") if isinstance(prev_row, dict) else None
            prev_property = (
                prev_row.get("reward", {}).get("property_estimate")
                if isinstance(prev_row, dict) and isinstance(prev_row.get("reward"), dict)
                else None
            )
            score_delta = (
                float(score) - float(prev_score)
                if isinstance(prev_score, (int, float))
                else None
            )
            objective_delta = (
                float(reward.primary_objective) - float(prev_obj)
                if isinstance(reward.primary_objective, (int, float)) and isinstance(prev_obj, (int, float))
                else None
            )
            material_config_change = (
                compiled_sig != prev_sig
                if isinstance(prev_sig, str)
                else True
            )
            material_executable_change = (
                executable_sig != prev_exec_sig
                if isinstance(prev_exec_sig, str)
                else True
            )
            curr_obj_sig = objective_audit.get("objective_terms_signature")
            prev_obj_sig = (
                prev_row.get("objective_audit", {}).get("objective_terms_signature")
                if isinstance(prev_row, dict) and isinstance(prev_row.get("objective_audit"), dict)
                else None
            )
            objective_changed = bool(
                (isinstance(objective_delta, (int, float)) and abs(float(objective_delta)) > 1e-12)
                or (isinstance(curr_obj_sig, str) and isinstance(prev_obj_sig, str) and curr_obj_sig != prev_obj_sig)
            )
            curr_guidance_sig = request_trace.get("guidance_structure_signature")
            prev_guidance_sig = (
                prev_row.get("request_trace", {}).get("guidance_structure_signature")
                if isinstance(prev_row, dict) and isinstance(prev_row.get("request_trace"), dict)
                else None
            )
            guidance_changed = bool(
                isinstance(curr_guidance_sig, str)
                and isinstance(prev_guidance_sig, str)
                and curr_guidance_sig != prev_guidance_sig
            )
            prev_structure_sig = prev_row.get("structure_signature") if isinstance(prev_row, dict) else None
            curr_structure_sig = structure_tracking.get("structure_signature")
            structure_changed = bool(
                isinstance(curr_structure_sig, str)
                and isinstance(prev_structure_sig, str)
                and curr_structure_sig != prev_structure_sig
            )
            if prev_row is None and isinstance(curr_structure_sig, str):
                structure_changed = True
            property_delta = (
                float(reward.property_estimate) - float(prev_property)
                if isinstance(reward.property_estimate, (int, float)) and isinstance(prev_property, (int, float))
                else None
            )
            objective_vs_structure = _classify_objective_vs_structure_change(
                objective_changed=objective_changed,
                guidance_changed=guidance_changed,
                structure_changed=structure_changed,
                property_delta=property_delta,
            )
            sensitivity_matrix = build_sensitivity_trace_matrix(
                prev_row if isinstance(prev_row, dict) else None,
                {
                    "action_dimensions": action_dimensions,
                    "request_trace": request_trace,
                    "objective_audit": objective_audit,
                },
            )

            row = {
                "iteration_index": len(session.iteration_history),
                "action_id": action.action_id,
                "action_family": action.action_family,
                "active_hypothesis_id": (
                    str(active_hypothesis.get("hypothesis_id"))
                    if isinstance(active_hypothesis, dict)
                    and isinstance(active_hypothesis.get("hypothesis_id"), str)
                    else None
                ),
                "active_hypothesis_label": (
                    str(active_hypothesis.get("label"))
                    if isinstance(active_hypothesis, dict)
                    and isinstance(active_hypothesis.get("label"), str)
                    else None
                ),
                "active_hypothesis_family": (
                    str(active_hypothesis.get("hypothesis_family"))
                    if isinstance(active_hypothesis, dict)
                    and isinstance(active_hypothesis.get("hypothesis_family"), str)
                    else None
                ),
                "candidate_action_ids": list(candidates),
                "compiled_action": compiled_dict,
                "compiled_config_signature": compiled_sig,
                "executable_signature": executable_sig,
                "compiled_delta": delta,
                "material_config_change": material_config_change,
                "material_executable_change": material_executable_change,
                "action_dimensions": action_dimensions,
                "request_trace": request_trace,
                "baseline_request_trace": baseline_request_trace,
                "objective_audit": objective_audit,
                "sensitivity_trace_matrix": sensitivity_matrix,
                "arbitration": arbitration.to_dict(),
                "primary_objective": reward.primary_objective,
                "objective_delta_vs_previous": objective_delta,
                "feasible": reward.feasibility,
                "score": score,
                "selection_metric_view": str(budget.config.selection_metric_view),
                "score_components": score_components,
                "score_delta_vs_previous": score_delta,
                "reward": reward.to_dict(),
                "run_reference": run_reference,
                "structure_artifact_path": structure_path,
                "structure_signature": curr_structure_sig,
                "structure_source": structure_tracking.get("structure_source"),
                "structure_content_hash": structure_tracking.get("structure_content_hash"),
                "formula_signature": structure_tracking.get("formula_signature"),
                "lattice_signature": structure_tracking.get("lattice_signature"),
                "structure_changed_vs_previous": structure_changed,
                "infeasible_streak_before_iteration": int(recovery.infeasible_streak),
                "recovery_stage": int(recovery.stage),
                "recovery_regime": str(recovery.regime),
                "recovery_active": bool(recovery.recovery_active),
                "best_updated": best_updated,
                "objective_vs_structure_change": {
                    "classification": objective_vs_structure,
                    "objective_changed": objective_changed,
                    "guidance_changed": guidance_changed,
                    "structure_changed": structure_changed,
                    "property_delta_vs_previous": property_delta,
                },
                "action_effectiveness": {
                    "changed_compiled_config": material_config_change,
                    "changed_executable_semantics": material_executable_change,
                    "score_delta_vs_previous": score_delta,
                    "objective_delta_vs_previous": objective_delta,
                    "best_so_far_changed": best_updated,
                    "backend_objective_total": objective_audit.get("objective_total"),
                    "objective_terms_signature": objective_audit.get("objective_terms_signature"),
                    "structure_signature": curr_structure_sig,
                    "structure_changed_vs_previous": structure_changed,
                    "objective_vs_structure_classification": objective_vs_structure,
                    "selection_metric_view": str(budget.config.selection_metric_view),
                    "stagnation_escalation_active": stagnation_escalation_active,
                    "recovery_stage": int(recovery.stage),
                    "recovery_regime": str(recovery.regime),
                    "template_seed_profile": template_seed_profile,
                    "lattice_candidate_profile": lattice_candidate_profile,
                    "symmetry_relaxation_profile": symmetry_relaxation_profile,
                    "ordering_perturbation_profile": ordering_perturbation_profile,
                },
                "weighting_profile": weighting_profile,
                "structure_perturbation_profile": perturbation_profile,
                "template_seed_profile": template_seed_profile,
                "lattice_candidate_profile": lattice_candidate_profile,
                "symmetry_relaxation_profile": symmetry_relaxation_profile,
                "ordering_perturbation_profile": ordering_perturbation_profile,
            }
            session.iteration_history.append(row)
            _update_hypothesis_branch_best(session, row)
            if isinstance(session.hypothesis_state, dict):
                history = session.hypothesis_state.get("branch_history", [])
                if not isinstance(history, list):
                    history = []
                history.append(
                    {
                        "iteration_index": int(row["iteration_index"]),
                        "hypothesis_id": row.get("active_hypothesis_id"),
                        "action_id": row.get("action_id"),
                        "score": row.get("score"),
                        "best_updated": bool(row.get("best_updated", False)),
                        "structure_changed_vs_previous": bool(row.get("structure_changed_vs_previous", False)),
                    }
                )
                session.hypothesis_state["branch_history"] = history
            budget.consume(
                action_family=action.action_family,
                solver_calls=int(execution.get("solver_calls", 1)),
                retrieval_calls=int(execution.get("retrieval_calls", 1)),
                failed=not reward.feasibility,
                recovery_attempt=bool(recovery.recovery_active),
            )
            if bool(recovery.recovery_active):
                recovery_state["attempt_count"] = int(budget.recovery_attempts_used)
                tried = recovery_state.get("regimes_tried", [])
                if not isinstance(tried, list):
                    tried = []
                if str(recovery.regime) not in {str(item) for item in tried}:
                    tried.append(str(recovery.regime))
                recovery_state["regimes_tried"] = tried
            if bool(reward.feasibility) and recovery_state.get("first_feasible_iteration") is None:
                recovery_state["first_feasible_iteration"] = int(row["iteration_index"])
                recovery_state["first_feasible_regime"] = str(recovery.regime)
            session.policy_state["recovery_state"] = recovery_state

            _maybe_switch_hypothesis(
                session,
                stagnation_window=int(budget.config.stagnation_window),
            )

            lightweight_recent = [
                {
                    "primary_objective": item.get("primary_objective"),
                    "feasible": item.get("feasible"),
                }
                for item in session.iteration_history[-budget.config.stagnation_window :]
            ]
            stuck = detect_stuck(
                session.iteration_history,
                stagnation_window=budget.config.stagnation_window,
                repeated_infeasible_limit=budget.config.max_failed_iterations,
            )
            mid = evaluate_midloop_clarification(
                recent_iterations=lightweight_recent,
                stagnation_window=budget.config.stagnation_window,
                max_repeated_infeasible=budget.config.max_failed_iterations,
                ambiguity_between_families=arbitration.gate.via_fallback and arbitration.llm_proposal.action_id is not None,
            )
            if mid.should_trigger:
                deferred_questions = list(session.clarification_state.get("deferred_questions", []))
                assumptions = list(session.clarification_state.get("assumptions_log", []))
                if mid.deferred and mid.question and mid.question not in deferred_questions:
                    deferred_questions.append(mid.question)
                    session.conversation_history.append({"role": "orchestrator", "text": f"[Deferred] {mid.question}"})
                if mid.assumption and mid.assumption not in assumptions:
                    assumptions.append(mid.assumption)
                session.clarification_state["deferred_questions"] = deferred_questions
                session.clarification_state["assumptions_log"] = assumptions

            remaining_iterations = budget.remaining_iterations()
            remaining_solver_calls = budget.remaining_solver_calls()
            remaining_retrieval_calls = budget.remaining_retrieval_calls()
            remaining_recovery_attempts = budget.remaining_recovery_attempts()
            max_recovery_attempts = int(budget.config.max_recovery_attempts)
            failed_limit_reason = budget.can_take_iteration(include_failed_limit=True)
            recovery_exhausted = budget.recovery_exhausted()
            symmetry_request = (
                session.task_spec.get("symmetry_request", {})
                if isinstance(session.task_spec.get("symmetry_request"), dict)
                else {}
            )
            hard_boundary = bool(
                stuck.stuck
                and stuck.reason == "repeated_infeasibility"
                and str(symmetry_request.get("hardness", "none")).strip().lower() == "hard"
                and int(recovery.stage) >= 2
            )
            task_ambiguity = bool(mid.should_trigger and mid.reason == "action_family_ambiguity")
            should_invoke_stop_hook = bool(
                stuck.stuck and (bool(hard_boundary) or task_ambiguity or recovery_exhausted)
            )
            if should_invoke_stop_hook:
                stop_hook_context = {
                    "query_text": session.task_spec.get("query_text"),
                    "hard_constraints": {
                        "composition_target": session.task_spec.get("composition_target"),
                        "symmetry_request": symmetry_request,
                    },
                    "stuck_reason": stuck.reason if stuck.stuck else None,
                    "infeasible_streak": int(recovery.infeasible_streak),
                    "recovery_stage": int(recovery.stage),
                    "recovery_regime": str(recovery.regime),
                    "recovery_regimes_tried": list(recovery_state.get("regimes_tried", []))
                    if isinstance(recovery_state.get("regimes_tried"), list)
                    else [],
                    "recovery_attempt_count": int(budget.recovery_attempts_used),
                    "max_recovery_attempts": max_recovery_attempts,
                    "remaining_iterations": remaining_iterations,
                    "remaining_solver_calls": remaining_solver_calls,
                    "remaining_retrieval_calls": remaining_retrieval_calls,
                    "remaining_recovery_attempts": remaining_recovery_attempts,
                    "recovery_exhausted": bool(recovery_exhausted),
                    "hard_constraint_boundary_reached": bool(hard_boundary),
                    "task_meaning_ambiguity": bool(task_ambiguity),
                    "recent_iterations": session.iteration_history[-4:],
                    "best_so_far": session.best_so_far,
                }
                stop_hook_decision = evaluate_stop_hook(
                    llm_client=self.llm_client if self.mode == "live" else None,
                    context=stop_hook_context,
                    allow_user_clarification=bool(budget.config.allow_midloop_clarification),
                )
                _accumulate_controller_stats(
                    session,
                    channel="stop_hook",
                    telemetry=(
                        stop_hook_decision.telemetry
                        if isinstance(stop_hook_decision.telemetry, dict)
                        else {}
                    ),
                    source=stop_hook_decision.source,
                )
                invocations = session.policy_state.get("stop_hook_invocations", [])
                if not isinstance(invocations, list):
                    invocations = []
                invocation_entry = stop_hook_decision.to_dict()
                invocation_entry["iteration_index"] = int(row["iteration_index"])
                invocations.append(invocation_entry)
                session.policy_state["stop_hook_invocations"] = invocations
                session.policy_state["last_stop_hook_decision"] = dict(invocation_entry)
                policy_change = (
                    dict(stop_hook_decision.recommended_policy_change)
                    if isinstance(stop_hook_decision.recommended_policy_change, dict)
                    else {}
                )
                if isinstance(policy_change.get("force_recovery_stage"), (int, float)):
                    recovery_state["forced_stage"] = max(
                        int(recovery_state.get("forced_stage", 0) or 0),
                        int(policy_change["force_recovery_stage"]),
                    )
                if stop_hook_decision.decision == "ask_user_clarification":
                    question = (
                        str(stop_hook_decision.question).strip()
                        if isinstance(stop_hook_decision.question, str) and str(stop_hook_decision.question).strip()
                        else (
                            "I ran multiple recovery regimes and hit a policy boundary. "
                            "Should I preserve strict constraints or prioritize feasibility-first exploration?"
                        )
                    )
                    session.status = "WAITING_CLARIFICATION"
                    session.blocked_state = {
                        "reason": "stop_hook_clarification",
                        "question": question,
                        "trigger_class": stop_hook_decision.trigger_class,
                    }
                    session.clarification_state["pending_questions"] = [question]
                    session.clarification_state["stop_hook_evidence_summary"] = stop_hook_decision.evidence_summary
                    session.clarification_state["clarification_trigger_class"] = stop_hook_decision.trigger_class
                    session.conversation_history.append({"role": "orchestrator", "text": question})
                    session.termination_reason = "stop_hook_clarification_required"
                    break
                if stop_hook_decision.decision == "stop_exhausted":
                    session.status = "STOPPED"
                    session.blocked_state = {
                        "reason": "stop_hook_exhausted",
                        "trigger_class": stop_hook_decision.trigger_class,
                    }
                    session.termination_reason = "stop_hook_exhausted"
                    break

            budget_stop_reason = budget.can_take_iteration(include_failed_limit=True)
            if budget_stop_reason == "budget_exhausted:max_failed_iterations" and not bool(recovery_exhausted):
                budget_stop_reason = None
            decision = evaluate_stop_policy(
                budget_exhausted_reason=budget_stop_reason,
                stuck_reason=stuck.reason if stuck.stuck else None,
                target_threshold=(
                    float(session.optimization_plan.get("stopping_criteria", {}).get("target_threshold"))
                    if isinstance(session.optimization_plan, dict)
                    and session.optimization_plan.get("stopping_criteria", {}).get("target_threshold") is not None
                    else None
                ),
                best_score=(float(session.best_so_far["score"]) if session.best_so_far and isinstance(session.best_so_far.get("score"), (int, float)) else None),
                user_requested_stop=False,
            )
            if decision.stop:
                session.status = "COMPLETED" if decision.reason == "target_threshold_reached" else "STOPPED"
                session.termination_reason = decision.reason
                break

            started += 1

        session.budget_state = budget.to_dict()
        session.policy_state["bandit"] = bandit.to_dict()
        session.policy_state["report_preview"] = {
            "iteration_count": len(session.iteration_history),
            "solver_call_count": int(budget.solver_calls_used),
            "recovery_attempt_count": int(budget.recovery_attempts_used),
            "best_so_far": session.best_so_far,
        }
        session.policy_state["selection_metric_view"] = str(budget.config.selection_metric_view)
        session.policy_state["failure_taxonomy"] = build_optimization_report(session).get("failure_taxonomy")
        if session.status == "RUNNING":
            session.status = "READY"
        return session

    def _execute(
        self,
        query: str,
        compiled: dict[str, Any],
        *,
        strict_phase1_benchmark_mode: bool = False,
    ) -> dict[str, Any]:
        if self.executor is not None:
            return self.executor(query, compiled)
        suffix = str(compiled.get("query_suffix", "")).strip()
        query_with_hints = query if not suffix else f"{query} {suffix}".strip()
        paired = run_paired_baseline_guided(
            query=query_with_hints,
            mode=self.mode,
            workspace=self.workspace,
            settings=self.settings,
            baseline_execution_overrides=compiled.get("baseline_overrides"),
            guided_execution_overrides=compiled.get("guided_overrides"),
            guided_with_spp=bool(compiled.get("guided_with_spp", True)),
            strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        )
        payload = json.loads(paired.report_path.read_text(encoding="utf-8"))
        objective = payload.get("guided_objective")
        structure_path = _extract_structure_artifact_path(paired.guided.run_dir)
        guided_objective_audit = objective_audit_from_run_dir(paired.guided.run_dir)
        baseline_objective_audit = objective_audit_from_run_dir(paired.baseline.run_dir)
        guided_request_trace = request_trace_from_run_dir(paired.guided.run_dir)
        baseline_request_trace = request_trace_from_run_dir(paired.baseline.run_dir)
        return {
            "feasible": paired.guided.status == "SUCCEEDED",
            "primary_objective": (float(objective) if isinstance(objective, (int, float)) else None),
            "objective_total": (
                guided_objective_audit.get("objective_total")
                if isinstance(guided_objective_audit, dict)
                else None
            ),
            "objective_terms": (
                list(guided_objective_audit.get("objective_terms", []))
                if isinstance(guided_objective_audit, dict)
                else []
            ),
            "objective_audit": guided_objective_audit,
            "baseline_objective_audit": baseline_objective_audit,
            "property_estimate": payload.get("guided_property"),
            "valid_for_learning": paired.guided.status == "SUCCEEDED",
            "solver_calls": 2,
            "retrieval_calls": 2,
            "guided_request_trace": guided_request_trace,
            "baseline_request_trace": baseline_request_trace,
            "run_reference": {
                "pair_id": paired.pair_id,
                "baseline_run_id": paired.baseline.run_id,
                "guided_run_id": paired.guided.run_id,
                "baseline_run_dir": str(paired.baseline.run_dir),
                "guided_run_dir": str(paired.guided.run_dir),
                "report_path": str(paired.report_path),
                "structure_artifact_path": structure_path,
            },
        }
