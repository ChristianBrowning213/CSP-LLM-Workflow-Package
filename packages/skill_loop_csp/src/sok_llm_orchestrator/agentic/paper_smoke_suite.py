from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Callable, Mapping

from .demo_bundle import write_demo_showcase_bundle
from .demo_loop import (
    DEFAULT_DEMO_ALLOWED_TOOLS,
    build_demo_mcp_settings,
    build_showcase_six_tool_run_plan,
    run_demo_execution_loop,
)
from .plan_compile import compile_run_plan_to_tool_proposals
from .schemas import assert_json_serializable, to_json_dict
from .tool_execution_adapters import get_default_tool_execution_adapters

PAPER_SMOKE_SUITE_SCHEMA_VERSION = "agentic_csp.paper_smoke_suite.v1"

DemoRunner = Callable[[Mapping[str, Any], Path], Mapping[str, Any]]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.exists():
        return {}
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return to_json_dict(payload) if isinstance(payload, Mapping) else {}


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _mapping_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [to_json_dict(item) for item in value if isinstance(item, Mapping)]


def _string_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _text_blob(payload: Any) -> str:
    if isinstance(payload, Mapping):
        return " ".join(f"{key} {_text_blob(value)}" for key, value in payload.items())
    if isinstance(payload, list):
        return " ".join(_text_blob(item) for item in payload)
    return str(payload) if payload is not None else ""


def _artifact_ref(step: Mapping[str, Any] | None, name: str) -> str:
    if not isinstance(step, Mapping):
        return ""
    for item in _mapping_list(step, "artifact_refs"):
        if _safe_string(item, "ref_name") == name:
            return _safe_string(item, "value")
    return ""


def _step(execution_run: Mapping[str, Any], tool_name: str) -> dict[str, Any] | None:
    for item in _mapping_list(execution_run, "step_results"):
        if _safe_string(item, "tool_name") == tool_name:
            return item
    return None


def _first_failed_step(execution_run: Mapping[str, Any]) -> dict[str, Any] | None:
    for item in _mapping_list(execution_run, "step_results"):
        if _safe_string(item, "status") in {"failed", "blocked"}:
            return item
    return None


def _status_matches(expected: str, actual: str) -> bool:
    if expected == "partial":
        return actual in {"partial", "blocked"}
    if expected == "blocked_or_partial":
        return actual in {"blocked", "partial", "failed"}
    return expected == actual


def _score_meets_threshold(score: int | float | None, threshold: int | float | None) -> bool:
    if threshold is None:
        return True
    if score is None:
        return False
    return float(score) >= float(threshold)


def _failure_family_matches(expected_family: str, code: str, diagnostic_text: str) -> bool:
    if not expected_family:
        return True
    haystack = f"{code} {diagnostic_text}".lower()
    families = {
        "non_concrete_formula": ("non_concrete_formula", "prototype pattern", "concrete composition"),
        "missing_pot_or_request_ref": (
            "spp_request_ref_unavailable",
            "pot_root_material_system_mismatch",
            "missing_pairs",
            "missing pot",
            "request_ref",
        ),
        "unsupported_material": (
            "unsupported_material",
            "unobtainium",
            "no_exact_crystaldb",
            "spp_request_ref_unavailable",
            "missing_corpus",
            "empty_corpus",
        ),
        "no_crystaldb_entry": ("no_crystaldb", "no exact reduced-formula", "missing_corpus", "empty_corpus"),
        "qlip_error": ("qlip_error", "qlip_infeasible", "non_solution_status", "solve_error"),
    }
    needles = families.get(expected_family, (expected_family,))
    return any(needle.lower() in haystack for needle in needles)


def _expectation_result(
    *,
    expected_outcome: str,
    actual_status: str,
    score: int | float | None,
    threshold: int | float | None,
    expected_error_codes: list[str],
    expected_failure_family: str,
    actual_failure_code: str,
    diagnostic_text: str,
) -> bool:
    if expected_outcome == "completed":
        return actual_status == "completed" and _score_meets_threshold(score, threshold)
    if not _status_matches(expected_outcome, actual_status):
        return False
    if expected_error_codes:
        haystack = f"{actual_failure_code} {diagnostic_text}"
        if not any(code in haystack for code in expected_error_codes):
            return False
    return _failure_family_matches(expected_failure_family, actual_failure_code, diagnostic_text)


def _build_planner_compile_run(item: Mapping[str, Any], *, mcp_backend: str, crystal_export_mode: str) -> dict[str, Any]:
    run_plan = build_showcase_six_tool_run_plan(
        goal=_safe_string(item, "goal"),
        run_id=_safe_string(item, "id", "paper_smoke_run"),
        material_system=_safe_string(item, "material_system"),
        crystal_export_mode=crystal_export_mode,
        crystal_demo_export_enabled=True,
    )
    compile_result = compile_run_plan_to_tool_proposals(run_plan)
    result = {
        "schema_version": "agentic_csp.planner_compile_run.v1",
        "run_id": _safe_string(run_plan, "run_id"),
        "run_plan": run_plan,
        "compile_result": compile_result,
        "proposal_count": len(compile_result["proposals"]),
        "valid_proposal_count": sum(1 for row in compile_result["validation_results"] if row.get("valid") is True),
        "invalid_proposal_count": sum(1 for row in compile_result["validation_results"] if row.get("valid") is False),
        "warnings": list(compile_result["warnings"]),
        "plan_source": "deterministic_showcase",
        "material_system": _safe_string(item, "material_system"),
        "mcp_backend": mcp_backend,
        "live_llm_used": False,
        "crystal_export_mode": crystal_export_mode,
        "crystal_demo_export_enabled": True,
    }
    assert_json_serializable(result)
    return result


def run_single_demo_case(item: Mapping[str, Any], run_dir: Path, *, mcp_backend: str = "configured") -> dict[str, Any]:
    raw_run_dir = run_dir / "_raw_run"
    settings = build_demo_mcp_settings(raw_run_dir, mcp_backend, allow_crystal_demo_export=True)
    crystal_export_mode = "demo" if settings.crystaldb_policy_mode == "demo" else "safe"
    planner_compile_run = _build_planner_compile_run(
        item,
        mcp_backend=mcp_backend,
        crystal_export_mode=crystal_export_mode,
    )
    demo_result = run_demo_execution_loop(
        out_dir=raw_run_dir,
        planner_compile_run=planner_compile_run,
        allow_real_execution=True,
        allowed_tools=list(DEFAULT_DEMO_ALLOWED_TOOLS),
        adapters=get_default_tool_execution_adapters(settings),
        plan_source="deterministic_showcase",
        mcp_backend=mcp_backend,
        material_system=_safe_string(item, "material_system"),
        crystal_export_mode=crystal_export_mode,
        crystal_demo_export_enabled=True,
    )
    bundle = write_demo_showcase_bundle(demo_result, run_dir, zip_bundle=False)
    return to_json_dict(bundle)


def collect_run_summary(item: Mapping[str, Any], run_dir: Path, bundle_result: Mapping[str, Any]) -> dict[str, Any]:
    evaluation_path = _safe_string(bundle_result, "workflow_evaluation_json_path") or str(run_dir / "report" / "workflow_evaluation.json")
    execution_run_path = str(run_dir / "_raw_run" / "execution" / "execution_run.json")
    evaluation = _read_json(evaluation_path)
    execution_run = _read_json(execution_run_path)
    scores = evaluation.get("scores") if isinstance(evaluation.get("scores"), Mapping) else {}
    final_status = _safe_string(evaluation, "final_status") or _safe_string(execution_run, "status")
    solve_step = _step(execution_run, "qlip.solve")
    novelty_step = _step(execution_run, "crystal.novelty_check")
    failed_step = _first_failed_step(execution_run)
    solve_summary = solve_step.get("output_summary", {}) if isinstance(solve_step, Mapping) and isinstance(solve_step.get("output_summary"), Mapping) else {}
    novelty_summary = novelty_step.get("output_summary", {}) if isinstance(novelty_step, Mapping) and isinstance(novelty_step.get("output_summary"), Mapping) else {}
    failed_error = failed_step.get("error", {}) if isinstance(failed_step, Mapping) and isinstance(failed_step.get("error"), Mapping) else {}
    expected_outcome = _safe_string(item, "expected_outcome", _safe_string(item, "expected_final_status"))
    expected_status = _safe_string(item, "expected_final_status", expected_outcome)
    expected_error_codes = _string_list(item, "expected_error_codes")
    expected_failure_family = _safe_string(item, "expected_failure_family")
    threshold = item.get("expected_min_overall_score")
    overall_score = scores.get("overall_score_0_100") if isinstance(scores, Mapping) else None
    diagnostic_text = _text_blob(
        {
            "failed_step": failed_step or {},
            "evaluation_errors": evaluation.get("errors"),
            "evaluation_warnings": evaluation.get("warnings"),
            "recommended_next_actions": evaluation.get("recommended_next_actions"),
            "failure_assessment": evaluation.get("failure_assessment"),
        }
    )
    outcome_pass = _expectation_result(
        expected_outcome=expected_outcome,
        actual_status=final_status,
        score=overall_score,
        threshold=threshold,
        expected_error_codes=expected_error_codes,
        expected_failure_family=expected_failure_family,
        actual_failure_code=_safe_string(failed_error, "code"),
        diagnostic_text=diagnostic_text,
    )
    result = {
        "run_id": _safe_string(item, "id"),
        "material_system": _safe_string(item, "material_system"),
        "goal": _safe_string(item, "goal"),
        "expected_final_status": expected_status,
        "expected_outcome": expected_outcome,
        "expected_min_overall_score": threshold,
        "expected_error_codes": expected_error_codes,
        "expected_failure_family": expected_failure_family,
        "final_status": final_status,
        "overall_score_0_100": overall_score,
        "solve_quality_score_0_100": scores.get("solve_quality_score_0_100") if isinstance(scores, Mapping) else None,
        "novelty_score_0_100": scores.get("novelty_score_0_100") if isinstance(scores, Mapping) else None,
        "qlip_status": solve_summary.get("status") or solve_summary.get("qlip_status"),
        "solution_cif_path": solve_summary.get("solution_cif_path") or _artifact_ref(solve_step, "solution_cif_path"),
        "novelty_is_novel": novelty_summary.get("is_novel"),
        "failed_tool": _safe_string(failed_step or {}, "tool_name"),
        "failure_code": _safe_string(failed_error, "code"),
        "actual_failed_tool": _safe_string(failed_step or {}, "tool_name"),
        "actual_failure_code": _safe_string(failed_error, "code"),
        "expected_outcome_pass": outcome_pass,
        "expectation_result": "pass" if outcome_pass else "fail",
        "artifact_paths": {
            "run_dir": str(run_dir),
            "workflow_evaluation_md": _safe_string(bundle_result, "workflow_evaluation_markdown_path") or str(run_dir / "report" / "workflow_evaluation.md"),
            "workflow_evaluation_json": evaluation_path,
            "execution_loop_report_md": _safe_string(bundle_result, "execution_loop_report_markdown_path") or str(run_dir / "report" / "execution_loop_report.md"),
            "execution_run_json": execution_run_path,
        },
        "evidence_dimensions": {
            "retrieval_executed": _step(execution_run, "crystal.csp_pack") is not None,
            "spp_executed": _step(execution_run, "spp.run_pipeline") is not None,
            "qlip_validated": _step(execution_run, "qlip.validate_request") is not None
            and _safe_string(_step(execution_run, "qlip.validate_request") or {}, "status") == "succeeded",
            "qlip_solved": isinstance(solve_step, Mapping) and _safe_string(solve_step, "status") == "succeeded",
            "novelty_checked": isinstance(novelty_step, Mapping) and _safe_string(novelty_step, "status") == "succeeded",
        },
    }
    assert_json_serializable(result)
    return result


def build_suite_summary(suite: Mapping[str, Any], rows: list[Mapping[str, Any]], out_dir: Path) -> dict[str, Any]:
    passed = sum(1 for row in rows if row.get("expected_outcome_pass") is True)
    result = {
        "schema_version": PAPER_SMOKE_SUITE_SCHEMA_VERSION,
        "suite_name": _safe_string(suite, "suite_name", "paper_smoke_suite"),
        "suite_json_path": _safe_string(suite, "suite_json_path"),
        "out_dir": str(out_dir),
        "run_count": len(rows),
        "pass_count": passed,
        "fail_count": len(rows) - passed,
        "runs": [to_json_dict(row) for row in rows],
        "paper_claim_supported": (
            "The workflow can produce solver-backed crystal candidates for supported material systems, "
            "and produces explicit diagnostic reports for unsupported inputs."
        ),
    }
    assert_json_serializable(result)
    return result


def render_suite_summary_markdown(summary: Mapping[str, Any]) -> str:
    rows = _mapping_list(summary, "runs")
    complete_rows = [row for row in rows if _safe_string(row, "expected_outcome") == "completed"]
    partial_rows = [row for row in rows if _safe_string(row, "expected_outcome") != "completed"]

    def table(items: list[dict[str, Any]]) -> list[str]:
        lines = [
            "| run | material | expected_outcome | expected_error_codes | actual | score | QLIP | actual_failed_tool | actual_failure_code | expectation_result |",
            "|---|---|---:|---|---:|---:|---|---|---|---|",
        ]
        for row in items:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _safe_string(row, "run_id"),
                        _safe_string(row, "material_system"),
                        _safe_string(row, "expected_outcome"),
                        ", ".join(_string_list(row, "expected_error_codes")) or "-",
                        _safe_string(row, "final_status"),
                        str(row.get("overall_score_0_100")),
                        str(row.get("qlip_status")),
                        _safe_string(row, "actual_failed_tool") or "-",
                        _safe_string(row, "actual_failure_code") or "-",
                        _safe_string(row, "expectation_result"),
                    ]
                )
                + " |"
            )
        return lines

    lines = [
        "# Paper Smoke Suite",
        "",
        "## Suite Overview",
        f"- Suite: {_safe_string(summary, 'suite_name')}",
        f"- Runs: {summary.get('run_count')}",
        f"- Passed expected outcomes: {summary.get('pass_count')}",
        f"- Failed expected outcomes: {summary.get('fail_count')}",
        "",
        "## Expected Complete Runs",
        *table(complete_rows),
        "",
        "## Expected Partial / Negative Controls",
        *table(partial_rows),
        "",
        "## Evidence Dimensions",
        "| run | retrieval | SPP/POT | QLIP validated | QLIP solved | novelty checked | evaluator score |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        evidence = row.get("evidence_dimensions") if isinstance(row.get("evidence_dimensions"), Mapping) else {}
        lines.append(
            "| "
            + " | ".join(
                [
                    _safe_string(row, "run_id"),
                    str(bool(evidence.get("retrieval_executed"))),
                    str(bool(evidence.get("spp_executed"))),
                    str(bool(evidence.get("qlip_validated"))),
                    str(bool(evidence.get("qlip_solved"))),
                    str(bool(evidence.get("novelty_checked"))),
                    str(row.get("overall_score_0_100")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Per-Run Artifact Links",
        ]
    )
    for row in rows:
        artifacts = row.get("artifact_paths") if isinstance(row.get("artifact_paths"), Mapping) else {}
        lines.append(
            f"- {_safe_string(row, 'run_id')}: {artifacts.get('workflow_evaluation_md')} "
            f"(trace: {artifacts.get('execution_loop_report_md')})"
        )
    lines.extend(
        [
            "",
            "## Failure Honesty",
            "- Unsupported systems are reported as blocked or partial when evidence or POT-root compatibility is insufficient.",
            "- Non-concrete prototype requests are blocked instead of being silently mapped to a concrete composition.",
            "- The suite does not fake solution CIFs, missing POT roots, novelty results, or QLIP success.",
            "",
            "## Paper Claim Supported",
            str(summary.get("paper_claim_supported")),
        ]
    )
    return "\n".join(lines) + "\n"


def run_paper_smoke_suite(
    *,
    suite_json: str | Path,
    out_dir: str | Path,
    zip_bundle: bool = False,
    mcp_backend: str = "configured",
    run_demo_case: DemoRunner | None = None,
) -> dict[str, Any]:
    suite_path = Path(suite_json)
    suite = _read_json(suite_path)
    suite["suite_json_path"] = str(suite_path)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    runner = run_demo_case
    rows: list[dict[str, Any]] = []
    for item in _mapping_list(suite, "runs"):
        run_id = _safe_string(item, "id", _safe_string(item, "material_system", "run"))
        run_dir = root / run_id
        if runner is None:
            bundle_result = run_single_demo_case(item, run_dir, mcp_backend=mcp_backend)
        else:
            bundle_result = to_json_dict(runner(item, run_dir))
        rows.append(collect_run_summary(item, run_dir, bundle_result))
    summary = build_suite_summary(suite, rows, root)
    summary_json_path = root / "suite_summary.json"
    summary_md_path = root / "suite_summary.md"
    _write_json(summary_json_path, summary)
    _write_text(summary_md_path, render_suite_summary_markdown(summary))
    zip_path: str | None = None
    if zip_bundle:
        zip_path = shutil.make_archive(str(root), "zip", root)
    result = {
        "schema_version": PAPER_SMOKE_SUITE_SCHEMA_VERSION,
        "summary_json_path": str(summary_json_path),
        "summary_markdown_path": str(summary_md_path),
        "zip_path": zip_path,
        "summary": summary,
    }
    assert_json_serializable(result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the paper smoke suite.")
    parser.add_argument("--suite-json", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--zip", action="store_true")
    parser.add_argument("--mcp-backend", default="configured", choices=["configured", "fake"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_paper_smoke_suite(
        suite_json=args.suite_json,
        out_dir=args.out_dir,
        zip_bundle=bool(args.zip),
        mcp_backend=args.mcp_backend,
    )
    print(f"PAPER_SMOKE_SUITE_SUMMARY_MD={result['summary_markdown_path']}")
    print(f"PAPER_SMOKE_SUITE_SUMMARY_JSON={result['summary_json_path']}")
    print(f"PAPER_SMOKE_SUITE_ZIP={result['zip_path'] or 'NONE'}")
    return 0


__all__ = [
    "PAPER_SMOKE_SUITE_SCHEMA_VERSION",
    "collect_run_summary",
    "render_suite_summary_markdown",
    "run_paper_smoke_suite",
    "run_single_demo_case",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
