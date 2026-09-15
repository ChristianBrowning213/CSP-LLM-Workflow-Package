from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sok_llm_orchestrator.llm.client import LLMClient
from sok_llm_orchestrator.optimization.controller_json import extract_single_json_object

STOP_HOOK_DECISIONS = {
    "continue_autonomously",
    "continue_with_recovery_regime",
    "ask_user_clarification",
    "stop_exhausted",
}


@dataclass(slots=True)
class StopHookDecision:
    decision: str
    reason: str
    question: str | None
    recommended_policy_change: dict[str, Any] | None
    evidence_summary: str
    trigger_class: str | None = None
    source: str = "heuristic"
    telemetry: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "question": self.question,
            "recommended_policy_change": dict(self.recommended_policy_change or {}),
            "evidence_summary": self.evidence_summary,
            "trigger_class": self.trigger_class,
            "source": self.source,
            "telemetry": dict(self.telemetry or {}),
        }

def _chat_with_cap(
    llm_client: LLMClient,
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> dict[str, Any]:
    try:
        return llm_client.chat(messages=messages, max_tokens=int(max_tokens), temperature=0.0)
    except TypeError:
        return llm_client.chat(messages=messages)


def _extract_response_text(response: dict[str, Any]) -> str:
    text = ""
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {})
        if isinstance(msg, dict):
            text = str(msg.get("content", ""))
    return text


def _validate_stop_hook_payload(
    payload: dict[str, Any],
    *,
    allow_user_clarification: bool,
) -> str | None:
    decision = payload.get("decision")
    if not isinstance(decision, str) or decision.strip() not in STOP_HOOK_DECISIONS:
        return "invalid_decision"
    if decision.strip() == "ask_user_clarification" and not allow_user_clarification:
        return "clarification_not_allowed"
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return "missing_reason"
    if len(reason) > 320:
        return "reason_too_long"
    evidence = payload.get("evidence_summary")
    if not isinstance(evidence, str) or not evidence.strip():
        return "missing_evidence_summary"
    if len(evidence) > 520:
        return "evidence_summary_too_long"
    question = payload.get("question")
    if question is not None and not isinstance(question, str):
        return "question_wrong_type"
    if isinstance(question, str) and len(question.strip()) > 700:
        return "question_too_long"
    rpc = payload.get("recommended_policy_change")
    if rpc is not None and not isinstance(rpc, dict):
        return "recommended_policy_change_wrong_type"
    trigger = payload.get("trigger_class")
    if trigger is not None and not isinstance(trigger, str):
        return "trigger_class_wrong_type"
    return None


def build_compact_stop_hook_prompt(
    *,
    context: dict[str, Any],
    allow_user_clarification: bool,
) -> dict[str, Any]:
    hard = context.get("hard_constraints", {})
    if not isinstance(hard, dict):
        hard = {}
    sym = hard.get("symmetry_request", {})
    if not isinstance(sym, dict):
        sym = {}
    best = context.get("best_so_far", {})
    if not isinstance(best, dict):
        best = {}
    return {
        "schema": "stop_hook.control.v1",
        "instruction": (
            "Return exactly one JSON object with keys: decision, reason, question, "
            "recommended_policy_change, evidence_summary, trigger_class."
        ),
        "task": {
            "query_text": context.get("query_text"),
            "composition_target": hard.get("composition_target"),
            "symmetry_hardness": sym.get("hardness"),
        },
        "state": {
            "stuck_reason": context.get("stuck_reason"),
            "infeasible_streak": context.get("infeasible_streak"),
            "recovery_stage": context.get("recovery_stage"),
            "recovery_regime": context.get("recovery_regime"),
            "recovery_regimes_tried": (
                list(context.get("recovery_regimes_tried", []))[:6]
                if isinstance(context.get("recovery_regimes_tried"), list)
                else []
            ),
            "recovery_attempt_count": context.get("recovery_attempt_count"),
            "max_recovery_attempts": context.get("max_recovery_attempts"),
            "recovery_exhausted": context.get("recovery_exhausted"),
            "remaining_iterations": context.get("remaining_iterations"),
            "remaining_solver_calls": context.get("remaining_solver_calls"),
            "remaining_recovery_attempts": context.get("remaining_recovery_attempts"),
            "hard_constraint_boundary_reached": context.get("hard_constraint_boundary_reached"),
            "task_meaning_ambiguity": context.get("task_meaning_ambiguity"),
            "best_score": best.get("score"),
            "has_best_candidate": bool(best),
            "allow_user_clarification": bool(allow_user_clarification),
        },
        "decision_enum": sorted(STOP_HOOK_DECISIONS),
    }


def _fallback_question(context: dict[str, Any], evidence_summary: str) -> str:
    tried = context.get("recovery_regimes_tried", [])
    tried_text = ", ".join(str(item) for item in tried if isinstance(item, str)) or "none"
    return (
        f"I tried recovery regimes [{tried_text}] and still hit a decision boundary. "
        f"{evidence_summary} Should I prioritize feasibility-first relaxation or preserve strict intent constraints?"
    )


def _heuristic_stop_hook(
    *,
    context: dict[str, Any],
    allow_user_clarification: bool,
) -> StopHookDecision:
    infeasible_streak = int(context.get("infeasible_streak", 0) or 0)
    recovery_attempt_count = int(context.get("recovery_attempt_count", 0) or 0)
    max_recovery_attempts = int(context.get("max_recovery_attempts", 0) or 0)
    remaining_iterations = int(context.get("remaining_iterations", 0) or 0)
    remaining_solver_calls = int(context.get("remaining_solver_calls", 0) or 0)
    remaining_recovery_attempts = int(context.get("remaining_recovery_attempts", 0) or 0)
    recovery_exhausted = bool(context.get("recovery_exhausted", False))
    hard_boundary = bool(context.get("hard_constraint_boundary_reached", False))
    task_ambiguity = bool(context.get("task_meaning_ambiguity", False))
    regime = str(context.get("recovery_regime", "normal_search"))
    reason_hint = str(context.get("stuck_reason", "none"))
    evidence_summary = (
        f"infeasible_streak={infeasible_streak}, recovery_attempt_count={recovery_attempt_count}, "
        f"max_recovery_attempts={max_recovery_attempts}, "
        f"recovery_regime={regime}, remaining_iterations={remaining_iterations}, "
        f"remaining_solver_calls={remaining_solver_calls}, "
        f"remaining_recovery_attempts={remaining_recovery_attempts}, stuck_reason={reason_hint}"
    )
    if hard_boundary and allow_user_clarification:
        return StopHookDecision(
            decision="ask_user_clarification",
            reason="hard_constraint_boundary_reached",
            question=_fallback_question(context, evidence_summary),
            recommended_policy_change={"preserve_hard_constraints": True},
            evidence_summary=evidence_summary,
            trigger_class="hard_constraint_boundary",
            source="heuristic",
            telemetry={"fallback_count": 1, "reason": "heuristic_decision"},
        )
    if task_ambiguity and allow_user_clarification:
        return StopHookDecision(
            decision="ask_user_clarification",
            reason="task_meaning_ambiguity",
            question=_fallback_question(context, evidence_summary),
            recommended_policy_change={"request_policy_disambiguation": True},
            evidence_summary=evidence_summary,
            trigger_class="task_meaning_ambiguity",
            source="heuristic",
            telemetry={"fallback_count": 1, "reason": "heuristic_decision"},
        )
    if recovery_exhausted and remaining_iterations <= 0:
        return StopHookDecision(
            decision="stop_exhausted",
            reason="recovery_exhausted_with_budget_spent",
            question=None,
            recommended_policy_change={"stop": True},
            evidence_summary=evidence_summary,
            trigger_class="budget_exhaustion",
            source="heuristic",
            telemetry={"fallback_count": 1, "reason": "heuristic_decision"},
        )
    if recovery_exhausted and allow_user_clarification:
        return StopHookDecision(
            decision="ask_user_clarification",
            reason="recovery_exhausted_needs_policy_decision",
            question=_fallback_question(context, evidence_summary),
            recommended_policy_change={"force_recovery_stage": 3, "need_user_policy": True},
            evidence_summary=evidence_summary,
            trigger_class="recovery_exhaustion",
            source="heuristic",
            telemetry={"fallback_count": 1, "reason": "heuristic_decision"},
        )
    if recovery_exhausted:
        return StopHookDecision(
            decision="continue_with_recovery_regime",
            reason="recovery_exhausted_but_budget_remains",
            question=None,
            recommended_policy_change={
                "force_recovery_stage": 5,
                "recovery_regime": "spp_weighting_and_package_variation",
            },
            evidence_summary=evidence_summary,
            trigger_class="recovery_exhaustion",
            source="heuristic",
            telemetry={"fallback_count": 1, "reason": "heuristic_decision"},
        )
    if infeasible_streak > 0:
        next_stage = int(context.get("recovery_stage", 0) or 0)
        return StopHookDecision(
            decision="continue_with_recovery_regime",
            reason="infeasibility_requires_recovery",
            question=None,
            recommended_policy_change={"force_recovery_stage": max(1, next_stage)},
            evidence_summary=evidence_summary,
            trigger_class="repeated_infeasibility",
            source="heuristic",
            telemetry={"fallback_count": 1, "reason": "heuristic_decision"},
        )
    return StopHookDecision(
        decision="continue_autonomously",
        reason="search_progressing",
        question=None,
        recommended_policy_change=None,
        evidence_summary=evidence_summary,
        trigger_class=None,
        source="heuristic",
        telemetry={"fallback_count": 1, "reason": "heuristic_decision"},
    )


def evaluate_stop_hook(
    *,
    llm_client: LLMClient | None,
    context: dict[str, Any],
    allow_user_clarification: bool,
) -> StopHookDecision:
    fallback = _heuristic_stop_hook(
        context=context,
        allow_user_clarification=allow_user_clarification,
    )
    if llm_client is None:
        return fallback
    prompt = build_compact_stop_hook_prompt(
        context=context,
        allow_user_clarification=allow_user_clarification,
    )
    prompt_text = json.dumps(prompt, sort_keys=True, separators=(",", ":"))
    telemetry: dict[str, Any] = {
        "prompt_chars": len(prompt_text),
        "retry_count": 0,
        "parse_failures": 0,
        "schema_failures": 0,
        "fallback_count": 0,
        "contains_think_count": 0,
        "contains_fence_count": 0,
    }
    messages = [
        {"role": "system", "content": "Return exactly one JSON object only. No markdown, no think tags, no prose."},
        {"role": "user", "content": prompt_text},
    ]
    strict_messages = [
        {"role": "system", "content": "STRICT MODE: Output one minified JSON object and nothing else."},
        {
            "role": "user",
            "content": (
                "JSON only with keys decision, reason, question, recommended_policy_change, "
                "evidence_summary, trigger_class."
            ),
        },
    ]
    last_text = ""
    last_reason = "unknown"
    for attempt in range(2):
        if attempt == 1:
            telemetry["retry_count"] = 1
        try:
            response = _chat_with_cap(
                llm_client,
                messages=(strict_messages if attempt == 1 else messages),
                max_tokens=160,
            )
        except Exception:
            break
        text = _extract_response_text(response)
        last_text = text
        extracted = extract_single_json_object(text, max_chars=2800)
        telemetry["completion_chars"] = extracted.output_chars
        telemetry["contains_think_count"] = int(extracted.contains_think)
        telemetry["contains_fence_count"] = int(extracted.contains_fence)
        if not extracted.ok or not isinstance(extracted.payload, dict):
            telemetry["parse_failures"] = int(telemetry["parse_failures"]) + 1
            last_reason = str(extracted.reason or "json_parse_failed")
            continue
        data = extracted.payload
        invalid_reason = _validate_stop_hook_payload(
            data,
            allow_user_clarification=allow_user_clarification,
        )
        if invalid_reason is not None:
            telemetry["schema_failures"] = int(telemetry["schema_failures"]) + 1
            last_reason = invalid_reason
            continue
        decision = str(data.get("decision", "")).strip()
        question = data.get("question")
        question_text = str(question).strip() if isinstance(question, str) and str(question).strip() else None
        if decision == "ask_user_clarification" and not question_text:
            question_text = _fallback_question(context, fallback.evidence_summary)
        rpc = data.get("recommended_policy_change")
        recommended_policy_change = dict(rpc) if isinstance(rpc, dict) else None
        reason = str(data.get("reason", "")).strip() or fallback.reason
        evidence_summary = str(data.get("evidence_summary", "")).strip() or fallback.evidence_summary
        trigger_class = str(data.get("trigger_class", "")).strip() or fallback.trigger_class
        return StopHookDecision(
            decision=decision,
            reason=reason,
            question=question_text,
            recommended_policy_change=recommended_policy_change,
            evidence_summary=evidence_summary,
            trigger_class=trigger_class or None,
            source="llm_retry" if attempt == 1 else "llm",
            telemetry=telemetry,
        )

    telemetry["fallback_count"] = 1
    telemetry["failure_reason"] = last_reason
    out = StopHookDecision(
        decision=fallback.decision,
        reason=fallback.reason,
        question=fallback.question,
        recommended_policy_change=fallback.recommended_policy_change,
        evidence_summary=fallback.evidence_summary,
        trigger_class=fallback.trigger_class,
        source="fallback_after_invalid_output",
        telemetry=telemetry,
    )
    return out
