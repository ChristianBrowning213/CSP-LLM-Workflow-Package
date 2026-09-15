from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sok_llm_orchestrator.llm.client import LLMClient
from sok_llm_orchestrator.optimization.controller_json import extract_single_json_object

_ACTION_SELECTOR_MAX_TOKENS = 180
_ACTION_SELECTOR_MAX_CHARS = 3200
_ACTION_SELECTOR_RATIONALE_LIMIT = 80


@dataclass(slots=True)
class LLMActionProposal:
    action_id: str | None
    rationale: str
    raw_text: str
    source: str
    ranked_action_ids: list[str] = field(default_factory=list)
    telemetry: dict[str, Any] = field(default_factory=dict)


def _normalize_ranked_ids(raw: object, candidates: list[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    allowed = set(candidates)
    ranked: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if not candidate or candidate not in allowed or candidate in ranked:
            continue
        ranked.append(candidate)
    return ranked


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


def _validate_action_selector_payload(
    payload: dict[str, Any],
    *,
    candidates: list[str],
) -> str | None:
    allowed = set(candidates)
    action_id = payload.get("action_id")
    has_valid_action = isinstance(action_id, str) and str(action_id).strip() in allowed
    ranked_raw = payload.get("ranked_action_ids")
    if action_id is not None and not has_valid_action and ranked_raw is None:
        return "invalid_action_id"
    if ranked_raw is not None:
        if not isinstance(ranked_raw, list):
            return "ranked_action_ids_wrong_type"
        seen: set[str] = set()
        for item in ranked_raw:
            if not isinstance(item, str):
                return "ranked_action_ids_non_string"
            aid = item.strip()
            if not aid or aid not in allowed:
                return "ranked_action_ids_invalid_candidate"
            if aid in seen:
                return "ranked_action_ids_duplicate"
            seen.add(aid)
    elif not has_valid_action:
        return "missing_ranked_action_ids"
    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return "missing_rationale"
    if len(rationale) > 320:
        return "rationale_too_long"
    return None


def build_compact_action_selector_prompt(
    *,
    candidate_action_ids: list[str],
    registry_summary_payload: list[dict[str, object]],
    session_context: dict[str, object],
) -> dict[str, Any]:
    registry_map: dict[str, dict[str, object]] = {}
    for item in registry_summary_payload:
        if not isinstance(item, dict):
            continue
        aid = item.get("action_id")
        if isinstance(aid, str) and aid.strip():
            registry_map[aid] = item
    task_spec = session_context.get("task_spec", {})
    if not isinstance(task_spec, dict):
        task_spec = {}
    sym = task_spec.get("symmetry_request", {})
    if not isinstance(sym, dict):
        sym = {}
    recent = session_context.get("recent_iterations", [])
    recent_rows: list[dict[str, Any]] = []
    if isinstance(recent, list):
        for row in recent[-3:]:
            if not isinstance(row, dict):
                continue
            recent_rows.append(
                {
                    "iter": row.get("iteration_index"),
                    "action": row.get("action_id"),
                    "feasible": bool(row.get("feasible", False)),
                    "score": row.get("score"),
                    "objective": row.get("primary_objective"),
                    "recovery_stage": row.get("recovery_stage"),
                }
            )
    action_summaries: list[dict[str, Any]] = []
    for aid in candidate_action_ids[:6]:
        reg = registry_map.get(aid, {})
        action_summaries.append(
            {
                "action_id": aid,
                "family": reg.get("family"),
                "retrieval_policy": reg.get("retrieval_policy"),
                "corpus_strategy": reg.get("corpus_strategy"),
                "guidance_mode": reg.get("qlip_guidance_mode"),
                "weighting_profile": reg.get("weighting_profile"),
                "perturbation_profile": reg.get("structure_perturbation_profile"),
                "symmetry_profile": reg.get("symmetry_relaxation_profile"),
                "risk_reward": reg.get("risk_reward"),
            }
        )
    return {
        "schema": "action_selector.control.v1",
        "instruction": (
            "Return exactly one minified JSON object: {action_id, ranked_action_ids, rationale}. "
            f"Keep rationale <= {_ACTION_SELECTOR_RATIONALE_LIMIT} chars. No prose."
        ),
        "task": {
            "query_text": task_spec.get("query_text"),
            "composition_target": task_spec.get("composition_target"),
            "property_bias": task_spec.get("property_bias"),
            "solve_mode": task_spec.get("solve_mode"),
            "symmetry_hardness": sym.get("hardness"),
        },
        "state": {
            "iteration_count": session_context.get("iteration_count"),
            "recovery_stage": session_context.get("recovery_stage"),
            "recovery_regime": session_context.get("recovery_regime"),
            "infeasible_streak": session_context.get("infeasible_streak"),
            "no_improve_streak": session_context.get("no_improve_streak"),
            "structure_static_streak": session_context.get("structure_static_streak"),
            "recent_outcomes": recent_rows,
            "bandit_ranked_top": (
                list(session_context.get("bandit_ranked", []))[:5]
                if isinstance(session_context.get("bandit_ranked"), list)
                else []
            ),
        },
        "candidates": action_summaries,
        "candidate_action_ids": list(candidate_action_ids),
    }


def propose_action(
    *,
    llm_client: LLMClient | None,
    candidate_action_ids: list[str],
    registry_summary_payload: list[dict[str, object]],
    session_context: dict[str, object],
) -> LLMActionProposal:
    if not candidate_action_ids:
        return LLMActionProposal(None, "No candidates available.", "", "fallback", [])
    if llm_client is None:
        return LLMActionProposal(
            action_id=candidate_action_ids[0],
            rationale="No live LLM configured; selected top policy candidate.",
            raw_text="",
            source="fallback",
            ranked_action_ids=list(candidate_action_ids),
            telemetry={"fallback_count": 1, "reason": "llm_unavailable"},
        )

    prompt = build_compact_action_selector_prompt(
        candidate_action_ids=candidate_action_ids,
        registry_summary_payload=registry_summary_payload,
        session_context=session_context,
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
        {
            "role": "system",
            "content": (
                "Return one compact JSON object only. Never output prose, markdown, think tags, "
                f"or commentary. Keep rationale <= {_ACTION_SELECTOR_RATIONALE_LIMIT} chars."
            ),
        },
        {"role": "user", "content": prompt_text},
    ]
    strict_messages = [
        {
            "role": "system",
            "content": (
                "STRICT MODE: Output exactly one minified JSON object and nothing else. "
                f"Keep rationale <= {_ACTION_SELECTOR_RATIONALE_LIMIT} chars."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return only JSON with keys action_id, ranked_action_ids, rationale. "
                f"Rationale max {_ACTION_SELECTOR_RATIONALE_LIMIT} chars. "
                f"Candidates={json.dumps(candidate_action_ids, separators=(',', ':'))}"
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
                max_tokens=_ACTION_SELECTOR_MAX_TOKENS,
            )
        except Exception:
            telemetry["fallback_count"] = 1
            telemetry["failure_reason"] = "llm_call_failed"
            return LLMActionProposal(
                action_id=candidate_action_ids[0],
                rationale="LLM call failed; fallback to top candidate.",
                raw_text="",
                source="fallback",
                ranked_action_ids=list(candidate_action_ids),
                telemetry=telemetry,
            )
        text = _extract_response_text(response)
        last_text = text
        extracted = extract_single_json_object(text, max_chars=_ACTION_SELECTOR_MAX_CHARS)
        telemetry["completion_chars"] = extracted.output_chars
        telemetry["contains_think_count"] = int(extracted.contains_think)
        telemetry["contains_fence_count"] = int(extracted.contains_fence)
        if not extracted.ok or not isinstance(extracted.payload, dict):
            telemetry["parse_failures"] = int(telemetry["parse_failures"]) + 1
            last_reason = str(extracted.reason or "json_parse_failed")
            continue
        data = extracted.payload
        invalid_reason = _validate_action_selector_payload(data, candidates=candidate_action_ids)
        if invalid_reason is not None:
            telemetry["schema_failures"] = int(telemetry["schema_failures"]) + 1
            last_reason = invalid_reason
            continue
        ranked = _normalize_ranked_ids(data.get("ranked_action_ids"), candidate_action_ids)
        action_id = str(data.get("action_id")).strip() if isinstance(data.get("action_id"), str) else None
        if not ranked and isinstance(action_id, str) and action_id in set(candidate_action_ids):
            ranked = [action_id] + [aid for aid in candidate_action_ids if aid != action_id]
        if action_id not in set(candidate_action_ids):
            action_id = ranked[0] if ranked else candidate_action_ids[0]
        return LLMActionProposal(
            action_id=action_id,
            rationale=str(data.get("rationale", "LLM response parsed.")),
            raw_text=text,
            source="llm_retry" if attempt == 1 else "llm",
            ranked_action_ids=ranked if ranked else list(candidate_action_ids),
            telemetry=telemetry,
        )

    telemetry["fallback_count"] = 1
    telemetry["failure_reason"] = last_reason
    return LLMActionProposal(
        action_id=candidate_action_ids[0],
        rationale="Invalid LLM structured output; fallback to top candidate.",
        raw_text=last_text,
        source="fallback_after_invalid_output",
        ranked_action_ids=list(candidate_action_ids),
        telemetry=telemetry,
    )
