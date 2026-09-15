from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.contracts.qlip_schema import QLIPValidationError, validate_solve_request
from sok_llm_orchestrator.llm.client import LLMClient


@dataclass(slots=True)
class EvalCase:
    case_id: str
    query: str
    with_spp: bool


def default_eval_cases() -> list[EvalCase]:
    return [
        EvalCase(case_id="baseline_tio2", query="TiO2 rutile-like", with_spp=False),
        EvalCase(case_id="spp_srti03", query="SrTiO3 perovskite-like", with_spp=True),
        EvalCase(case_id="spp_lifepo4", query="LiFePO4 olivine-like", with_spp=True),
    ]


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _extract_balanced_json_objects(text: str) -> list[str]:
    candidates: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    candidates.append(text[start : i + 1])
    return candidates


def parse_json_object(text: str) -> dict[str, Any]:
    return parse_json_objects(text)[0]


def parse_json_objects(text: str) -> list[dict[str, Any]]:
    cleaned = _strip_code_fences(text)
    objects: list[dict[str, Any]] = []
    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            objects.append(payload)
            return objects
    except json.JSONDecodeError:
        pass

    for candidate in _extract_balanced_json_objects(cleaned):
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                objects.append(payload)
        except json.JSONDecodeError:
            continue
    if not objects:
        raise json.JSONDecodeError("No JSON object found", cleaned, 0)
    return objects


def build_eval_messages(case: EvalCase) -> list[dict[str, str]]:
    guidance_instruction = (
        "Set guidance to: [{\"id\":\"objective.energy_spp\",\"params\":{\"spp_package_path\":\"SPPs/TEST_RUN\"}}]."
        if case.with_spp
        else "Set guidance to an empty array []."
    )
    template = (
        "{\"version\":\"1.0\","
        "\"problem\":{\"chemistry\":{\"formula\":\"<FORMULA>\"},\"design_space\":{\"template\":{},\"sites\":{}}},"
        "\"constraints\":[],"
        "\"guidance\":[{\"id\":\"objective.energy_spp\",\"params\":{\"spp_package_path\":\"SPPs/TEST_RUN\"}}],"
        "\"solver\":{\"name\":\"gurobi\"}}"
    )
    user = (
        "Return ONLY valid JSON for a QLIP SolveRequest (no markdown, no explanation, no preamble). "
        "Required top-level keys: version, problem, constraints, guidance, solver. "
        "version must be '1.0'; solver.name must be 'gurobi'. "
        "Do not include <think> or reasoning text. "
        "guidance MUST be an array of objects, never an object. "
        "Do not use legacy keys like objective, chemistry/chemsys, or solver/output_dir. "
        f"Case query: {case.query}. {guidance_instruction} "
        f"Template shape: {template}"
    )
    return [
        {
            "role": "system",
            "content": (
                "You generate strict JSON objects only. "
                "Never output prose. Never output code fences. "
                "Output exactly one JSON object."
            ),
        },
        {"role": "user", "content": user},
    ]


def validate_case_response(case: EvalCase, response_text: str) -> tuple[bool, str]:
    try:
        payloads = parse_json_objects(response_text)
    except Exception as exc:  # noqa: BLE001
        return False, f"invalid_json: {exc}"
    last_error = "no_candidate_matched"
    for payload in payloads:
        try:
            validate_solve_request(payload)
        except QLIPValidationError as exc:
            last_error = f"schema_error: {exc}"
            continue

        has_spp = any(item.get("id") == "objective.energy_spp" for item in payload.get("guidance", []))
        if case.with_spp and not has_spp:
            last_error = "missing_spp_guidance"
            continue
        if not case.with_spp and has_spp:
            last_error = "unexpected_spp_guidance"
            continue
        return True, "ok"
    return False, last_error


def run_live_llm_eval(
    client: LLMClient,
    cases: list[EvalCase],
    trials_per_case: int = 2,
    out_path: Path | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        for trial in range(trials_per_case):
            response = client.chat(build_eval_messages(case))
            content = response["choices"][0]["message"]["content"]
            passed, reason = validate_case_response(case, content)
            rows.append(
                {
                    "case_id": case.case_id,
                    "query": case.query,
                    "with_spp": case.with_spp,
                    "trial": trial,
                    "passed": passed,
                    "reason": reason,
                    "response_preview": content[:240],
                }
            )
    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    report = {
        "schema_version": "live_llm_eval.v1",
        "total": total,
        "passed": passed,
        "pass_rate": (passed / total) if total else 0.0,
        "rows": rows,
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
