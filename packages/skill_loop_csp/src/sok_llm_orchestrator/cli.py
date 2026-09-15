from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.bench.external import (
    EXTERNAL_DATASETS,
    EXTERNAL_REGIMES,
    EXTERNAL_SPLITS,
    compare_external_benchmark_reports,
    import_external_datasets,
    regenerate_external_benchmark_report,
    run_external_benchmark_matrix,
)
from sok_llm_orchestrator.bench.reporting import compare_benchmark_reports
from sok_llm_orchestrator.bench.runner import run_benchmark_cases, run_optimization_benchmark_cases
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.phase1_properties import phase1_property_report
from sok_llm_orchestrator.contracts.phase2_external_predictors import phase2_external_predictor_report
from sok_llm_orchestrator.contracts.phase3_external_predictors import phase3_external_predictor_report
from sok_llm_orchestrator.evals.live_llm import default_eval_cases, run_live_llm_eval
from sok_llm_orchestrator.experiments.first_crystal import (
    default_first_crystal_case_pack,
    regenerate_first_crystal_summary,
    regenerate_repeated_first_crystal_summary,
    run_repeated_first_crystal_analysis,
    run_first_crystal_experiment,
)
from sok_llm_orchestrator.experiments.guided_sweep import (
    regenerate_guided_variant_sweep_report,
    run_guided_variant_sweep,
)
from sok_llm_orchestrator.experiments.sensitivity import (
    regenerate_per_key_ablation_report,
    regenerate_forced_sensitivity_report,
    run_per_key_ablation_experiment,
    run_forced_sensitivity_experiment,
)
from sok_llm_orchestrator.llm.client import LLMClient
from sok_llm_orchestrator.llm.discovery import (
    is_local_base_url,
    resolve_llm_credentials,
    smoke_chat_api_v1,
)
from sok_llm_orchestrator.orchestrator.paired_run import run_paired_baseline_guided
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command, run_csp_pipeline
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation
from sok_llm_orchestrator.orchestrator.task_spec import load_task_spec_file
from sok_llm_orchestrator.optimization.llm_action_selector import propose_action
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.plan_render import render_optimization_plan
from sok_llm_orchestrator.optimization.plan_schema import OptimizationPlan
from sok_llm_orchestrator.optimization.render import render_session_summary
from sok_llm_orchestrator.optimization.reporting import build_optimization_report
from sok_llm_orchestrator.skills.loader import load_skillcards, render_skills_index, validate_skillcards


def _to_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def _load_settings(config: str | None) -> Settings:
    cfg_path = Path(config).resolve() if config else None
    return Settings.from_sources(cfg_path)


def _doctor_mode_commands(mode: str, settings: Settings) -> tuple[str | list[str], str | list[str], str | list[str]]:
    if mode == "stub":
        return (
            _stub_command("mcp_crystaldb_server.py"),
            _stub_command("mcp_spp_server.py"),
            _stub_command("mcp_qlip_server.py"),
        )
    return settings.crystaldb_mcp_cmd, settings.spp_mcp_cmd, settings.qlip_mcp_cmd


def _run_action_selector_health_probe(llm_client: LLMClient) -> dict[str, object]:
    candidate_action_ids = ["baseline_control", "guided_hybrid_balanced"]
    proposal = propose_action(
        llm_client=llm_client,
        candidate_action_ids=candidate_action_ids,
        registry_summary_payload=[
            {
                "action_id": "baseline_control",
                "family": "baseline",
                "retrieval_policy": "minimal",
                "corpus_strategy": "default",
                "qlip_guidance_mode": "none",
                "weighting_profile": "balanced",
                "structure_perturbation_profile": "minimal",
                "symmetry_relaxation_profile": "preserve",
                "risk_reward": "low",
            },
            {
                "action_id": "guided_hybrid_balanced",
                "family": "guided",
                "retrieval_policy": "hybrid",
                "corpus_strategy": "fit_ready",
                "qlip_guidance_mode": "energy_spp",
                "weighting_profile": "balanced",
                "structure_perturbation_profile": "moderate",
                "symmetry_relaxation_profile": "soften",
                "risk_reward": "medium",
            },
        ],
        session_context={
            "task_spec": {
                "query_text": "Selector health probe for TiO2 feasibility.",
                "composition_target": "TiO2",
                "property_bias": "stability",
                "solve_mode": "feasibility",
                "symmetry_request": {"hardness": "soft"},
            },
            "iteration_count": 0,
            "recovery_stage": "initial",
            "recovery_regime": "baseline",
            "infeasible_streak": 0,
            "no_improve_streak": 0,
            "structure_static_streak": 0,
            "recent_iterations": [],
            "bandit_ranked": list(candidate_action_ids),
        },
    )
    telemetry = dict(proposal.telemetry) if isinstance(proposal.telemetry, dict) else {}
    failure_reason = (
        str(telemetry.get("failure_reason")).strip()
        if isinstance(telemetry.get("failure_reason"), str)
        else None
    )
    warnings: list[str] = []
    if proposal.source == "llm_retry":
        warnings.append("selector_probe_recovered_after_retry")
    if int(telemetry.get("contains_think_count", 0) or 0) > 0:
        warnings.append("selector_probe_contains_think")
    if int(telemetry.get("contains_fence_count", 0) or 0) > 0:
        warnings.append("selector_probe_contains_fence")
    ok = proposal.source in {"llm", "llm_retry"} and proposal.action_id in set(candidate_action_ids)
    detail = "selector_structured_output_ok"
    if not ok:
        detail = "selector output fell back before a valid structured action proposal"
        if failure_reason:
            detail = f"{detail}: {failure_reason}"
    check: dict[str, object] = {
        "name": "action_selector_health",
        "ok": bool(ok),
        "detail": detail,
        "source": proposal.source,
        "selected_action_id": proposal.action_id,
        "warnings": warnings,
        "telemetry": telemetry,
    }
    if failure_reason:
        check["error"] = failure_reason
    return check


def _resolve_runtime_llm(settings: Settings) -> tuple[bool, list[dict[str, object]]]:
    api_key, model, notes = resolve_llm_credentials(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    settings.llm_api_key = api_key
    settings.llm_model = model
    warnings: list[str] = list(notes)
    checks: list[dict[str, object]] = []

    if not settings.llm_model:
        checks.append(
            {"name": "llm_config", "ok": False, "warnings": warnings, "error": "Could not discover LLM_MODEL."}
        )
        return False, checks
    if not settings.llm_api_key and not is_local_base_url(settings.llm_base_url):
        checks.append(
            {
                "name": "llm_config",
                "ok": False,
                "warnings": warnings,
                "error": "LLM_API_KEY is required for non-local llm_base_url.",
            }
        )
        return False, checks

    smoke_ok, smoke_detail = smoke_chat_api_v1(settings.llm_base_url, settings.llm_model)
    if not smoke_ok:
        checks.append(
            {
                "name": "llm_config",
                "ok": False,
                "warnings": warnings,
                "error": f"LLM smoke chat failed: {smoke_detail}",
                "resolved_model": settings.llm_model,
            }
        )
        return False, checks
    checks.append(
        {
            "name": "llm_config",
            "ok": True,
            "warnings": warnings,
            "resolved_model": settings.llm_model,
        }
    )
    selector_check = _run_action_selector_health_probe(
        LLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "",
            model=settings.llm_model,
            timeout_s=min(int(settings.llm_timeout_s), 20),
            max_retries=0,
        )
    )
    checks.append(selector_check)
    return bool(selector_check.get("ok", False)), checks


def _build_optimization_engine(
    *,
    settings: Settings,
    workspace: Path,
    mode: str,
) -> OptimizationEngine:
    llm_client: LLMClient | None = None
    if mode == "live":
        llm_ok, llm_checks = _resolve_runtime_llm(settings)
        if not llm_ok:
            raise RuntimeError(f"LLM runtime not ready: {llm_checks}")
        llm_client = LLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "",
            model=settings.llm_model or "",
            timeout_s=settings.llm_timeout_s,
        )
    return OptimizationEngine(
        workspace=workspace,
        settings=settings,
        mode=mode,
        llm_client=llm_client,
    )


def _run_startup_checks(
    *,
    settings: Settings,
    workspace: Path,
    mode: str,
    strict: bool = True,
) -> dict[str, Any]:
    commands = _doctor_mode_commands(mode, settings)
    return run_startup_validation(
        mode=mode,
        settings=settings,
        workspace=workspace,
        commands=commands,
        strict=strict,
    )


def _enforce_startup_gate_or_exit(
    *,
    settings: Settings,
    workspace: Path,
    mode: str,
    strict: bool = True,
) -> bool:
    report = _run_startup_checks(settings=settings, workspace=workspace, mode=mode, strict=strict)
    if bool(report.get("startup_ok", False)):
        return True
    summary = {
        "startup_ok": report.get("startup_ok"),
        "blocked_by": report.get("blocked_by"),
        "detail": report.get("detail"),
        "startup_report": report.get("artifacts", {}).get("startup_report"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True), file=sys.stderr)
    return False


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    report_path = workspace / "doctor_report.json"
    strict = bool(getattr(args, "strict", True))
    report: dict[str, object] = {"mode": args.mode, "checks": []}
    ok = True
    if args.mode != "stub":
        llm_ok, llm_checks = _resolve_runtime_llm(settings)
        report["checks"].extend(llm_checks)
        if not llm_ok:
            ok = False
    startup_report = _run_startup_checks(settings=settings, workspace=workspace, mode=args.mode, strict=strict)
    report["checks"].append(
        {
            "name": "startup_validation",
            "ok": bool(startup_report.get("startup_ok", False)),
            "blocked_by": startup_report.get("blocked_by"),
            "detail": startup_report.get("detail"),
            "artifact": startup_report.get("artifacts", {}).get("startup_report"),
        }
    )
    ok = ok and bool(startup_report.get("startup_ok", False))
    report["startup"] = startup_report
    report["ok"] = bool(ok)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(report_path))
    return 0 if bool(ok) else 1


def cmd_doctor_startup(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    report = _run_startup_checks(
        settings=settings,
        workspace=workspace,
        mode=args.mode,
        strict=bool(args.strict),
    )
    out_path = Path(str(report.get("artifacts", {}).get("startup_report", workspace / "startup" / "startup_report.json")))
    print(str(out_path))
    return 0 if bool(report.get("startup_ok", False)) else 1


def cmd_doctor_phase1_properties(args: argparse.Namespace) -> int:
    report = phase1_property_report()
    if bool(args.implemented_only):
        report["all_entries"] = list(report.get("implemented_now", []))
    out_path = Path(args.out).resolve() if args.out else None
    payload = json.dumps(report, indent=2, sort_keys=True)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(str(out_path))
    else:
        print(payload)
    return 0


def cmd_doctor_phase2_external_predictors(args: argparse.Namespace) -> int:
    report = phase2_external_predictor_report()
    if bool(args.implemented_only):
        implemented = list(report.get("implemented_now", []))
        report["all_entries"] = implemented
        report["nonimplemented"] = []
        report["counts"] = {
            "total": len(implemented),
            "implemented_now": len(implemented),
            "not_implemented": 0,
            "benchmark_approved": sum(1 for row in implemented if bool(row.get("benchmark_approved"))),
            "exploratory_only": sum(1 for row in implemented if bool(row.get("exploratory_only"))),
        }
    out_path = Path(args.out).resolve() if args.out else None
    payload = json.dumps(report, indent=2, sort_keys=True)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(str(out_path))
    else:
        print(payload)
    return 0


def cmd_doctor_phase3_external_predictors(args: argparse.Namespace) -> int:
    report = phase3_external_predictor_report()
    if bool(args.implemented_only):
        implemented = list(report.get("implemented_now", []))
        report["all_entries"] = implemented
        report["nonimplemented"] = []
        report["counts"] = {
            "total": len(implemented),
            "implemented_now": len(implemented),
            "not_implemented": 0,
            "benchmark_approved": sum(1 for row in implemented if bool(row.get("benchmark_approved"))),
            "exploratory_only": sum(1 for row in implemented if bool(row.get("exploratory_only"))),
        }
    out_path = Path(args.out).resolve() if args.out else None
    payload = json.dumps(report, indent=2, sort_keys=True)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(str(out_path))
    else:
        print(payload)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    task_spec_payload = None
    query = args.query
    if args.task_spec_file:
        if query:
            raise ValueError("--query and --task-spec-file are mutually exclusive.")
        task_spec_payload = load_task_spec_file(args.task_spec_file).to_dict()
        query = None
    elif not query:
        raise ValueError("Either --query or --task-spec-file is required.")
    result = run_csp_pipeline(
        query=query,
        with_spp=_to_bool(args.with_spp),
        mode=args.mode,
        workspace=workspace,
        settings=settings,
        task_spec_payload=task_spec_payload,
    )
    print(str(result.run_dir))
    return 0 if result.status == "SUCCEEDED" else 1


def cmd_chat(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    if not bool(getattr(args, "skip_startup_checks", False)):
        if not _enforce_startup_gate_or_exit(settings=settings, workspace=workspace, mode=args.mode, strict=True):
            return 1
    opt_engine = _build_optimization_engine(settings=settings, workspace=workspace, mode=args.mode)
    active_optimization_session: str | None = None

    print("sokllm chat (type 'exit' to quit)")
    while True:
        try:
            query = input("> ").strip()
        except EOFError:
            print("")
            return 0
        if query.lower() in {"exit", "quit"}:
            return 0
        if not query:
            continue
        if query.lower().startswith("optimize "):
            opt_query = query[len("optimize ") :].strip()
            result = opt_engine.start(query=opt_query, auto_run=True)
            session = opt_engine.get(result.session_id)
            print(render_session_summary(session))
            if session.status in {"PENDING_CLARIFICATION", "WAITING_CLARIFICATION"}:
                active_optimization_session = session.session_id
            else:
                active_optimization_session = None
            continue
        if active_optimization_session is not None:
            result = opt_engine.continue_session(
                session_id=active_optimization_session,
                clarification_answer=query,
            )
            session = opt_engine.get(result.session_id)
            print(render_session_summary(session))
            if session.status not in {"PENDING_CLARIFICATION", "WAITING_CLARIFICATION"}:
                active_optimization_session = None
            continue
        result = run_csp_pipeline(
            query=query,
            with_spp=_to_bool(args.with_spp),
            mode=args.mode,
            workspace=workspace,
            settings=settings,
        )
        print(f"{result.status} {result.run_dir}")


def cmd_optimize_start(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    if args.max_iterations is not None:
        settings.optimization_max_iterations = int(args.max_iterations)
    if args.exploration_rate is not None:
        settings.optimization_exploration_rate = float(args.exploration_rate)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    if not bool(getattr(args, "skip_startup_checks", False)):
        if not _enforce_startup_gate_or_exit(settings=settings, workspace=workspace, mode=args.mode, strict=True):
            return 1
    engine = _build_optimization_engine(settings=settings, workspace=workspace, mode=args.mode)
    task_spec_payload = None
    query = args.query
    if args.task_spec_file:
        if query:
            raise ValueError("--query and --task-spec-file are mutually exclusive.")
        task_spec_payload = load_task_spec_file(args.task_spec_file).to_dict()
        query = None
    elif not query:
        raise ValueError("Either --query or --task-spec-file is required.")
    result = engine.start(
        query=query,
        task_spec_payload=task_spec_payload,
        auto_run=not bool(args.no_run),
    )
    session = engine.get(result.session_id)
    print(render_session_summary(session))
    print(str(result.session_path))
    return 0


def cmd_optimize_status(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    engine = _build_optimization_engine(settings=settings, workspace=workspace, mode=args.mode)
    session = engine.get(args.session_id)
    print(render_session_summary(session))
    return 0


def cmd_optimize_continue(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    if not bool(getattr(args, "skip_startup_checks", False)):
        if not _enforce_startup_gate_or_exit(settings=settings, workspace=workspace, mode=args.mode, strict=True):
            return 1
    engine = _build_optimization_engine(settings=settings, workspace=workspace, mode=args.mode)
    result = engine.continue_session(
        session_id=args.session_id,
        clarification_answer=args.answer,
        max_new_iterations=args.max_new_iterations,
    )
    session = engine.get(result.session_id)
    print(render_session_summary(session))
    print(str(result.session_path))
    return 0


def cmd_optimize_show_plan(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    engine = _build_optimization_engine(settings=settings, workspace=workspace, mode=args.mode)
    session = engine.get(args.session_id)
    if session.optimization_plan is None:
        print("No plan available for this session.")
        return 1
    plan = OptimizationPlan(
        objective_target=str(session.optimization_plan["objective_target"]),
        initial_hypotheses=list(session.optimization_plan["initial_hypotheses"]),
        action_family_priorities=list(session.optimization_plan["action_family_priorities"]),
        exploration_strategy=dict(session.optimization_plan["exploration_strategy"]),
        stopping_criteria=dict(session.optimization_plan["stopping_criteria"]),
        fallback_strategy=list(session.optimization_plan["fallback_strategy"]),
        escalation_conditions=list(session.optimization_plan["escalation_conditions"]),
    )
    print(render_optimization_plan(plan))
    return 0


def cmd_optimize_show_best(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    engine = _build_optimization_engine(settings=settings, workspace=workspace, mode=args.mode)
    session = engine.get(args.session_id)
    report = build_optimization_report(session)
    if bool(args.json):
        print(json.dumps(report.get("best_so_far"), indent=2, sort_keys=True))
    else:
        print(f"best={report.get('best_so_far')}")
    return 0


def cmd_optimize_diagnose(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    engine = _build_optimization_engine(settings=settings, workspace=workspace, mode=args.mode)
    session = engine.get(args.session_id)
    report = build_optimization_report(session)
    payload = {
        "session_id": report.get("session_id"),
        "status": report.get("status"),
        "termination_reason": report.get("termination_reason"),
        "diagnostics": report.get("diagnostics"),
        "llm_selection_summary": report.get("llm_selection_summary"),
    }
    if bool(args.include_objective_breakdown):
        payload["objective_audit_trace"] = report.get("objective_audit_trace")
        payload["iteration_effectiveness_trace"] = report.get("iteration_effectiveness_trace")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_skills_list(args: argparse.Namespace) -> int:
    skills_dir = Path(args.skills_dir).resolve()
    cards = load_skillcards(skills_dir)
    for card in cards:
        print(f"{card['id']}\t{card['tool_name']}")
    return 0


def cmd_skills_show(args: argparse.Namespace) -> int:
    skills_dir = Path(args.skills_dir).resolve()
    path = skills_dir / f"{args.skill_id}.skillcard.json"
    if not path.exists():
        print(f"Missing skillcard: {path}", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_skills_validate(args: argparse.Namespace) -> int:
    skills_dir = Path(args.skills_dir).resolve()
    errors = validate_skillcards(skills_dir)
    cards = load_skillcards(skills_dir)
    skills_index = render_skills_index(cards)
    skills_index_path = Path(args.prompts_dir).resolve() / "skills_index.md"
    skills_index_path.write_text(skills_index, encoding="utf-8")
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print(f"Validated {len(cards)} skillcards.")
    return 0


def cmd_eval_live_llm(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    api_key, model, _ = resolve_llm_credentials(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    settings.llm_api_key = api_key
    settings.llm_model = model
    settings.validate_llm()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=int(args.timeout_s) if args.timeout_s is not None else settings.llm_timeout_s,
    )
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    out_path = workspace / "evals" / "live_llm_report.json"
    report = run_live_llm_eval(
        client=client,
        cases=default_eval_cases(),
        trials_per_case=int(args.trials),
        out_path=out_path,
    )
    print(f"pass_rate={report['pass_rate']:.3f} ({report['passed']}/{report['total']})")
    print(str(out_path))
    return 0 if report["pass_rate"] >= float(args.min_pass_rate) else 1


def cmd_eval_e2e(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]

    report: dict[str, object] = {
        "schema_version": "eval.e2e.v1",
        "mode": args.mode,
        "query": args.query,
        "cases": str(Path(args.cases).resolve()),
        "steps": [],
    }

    def record(name: str, ok: bool, detail: str, artifact: str | None = None) -> None:
        row: dict[str, object] = {"name": name, "ok": ok, "detail": detail}
        if artifact:
            row["artifact"] = artifact
        report["steps"].append(row)

    if args.mode == "live":
        llm_ok, llm_checks = _resolve_runtime_llm(settings)
        record("llm_config", llm_ok, json.dumps(llm_checks, sort_keys=True))
        if not llm_ok and not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1

    try:
        doctor_rc = cmd_doctor(argparse.Namespace(config=args.config, workspace=str(workspace), mode=args.mode))
        record("doctor", doctor_rc == 0, f"exit_code={doctor_rc}", str(workspace / "doctor_report.json"))
        if doctor_rc != 0 and not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1
    except Exception as exc:  # noqa: BLE001
        record("doctor", False, str(exc))
        if not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1

    try:
        if args.mode == "live":
            client = LLMClient(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key or "",
                model=settings.llm_model or "",
                timeout_s=settings.llm_timeout_s,
            )
            llm_report = run_live_llm_eval(
                client=client,
                cases=default_eval_cases(),
                trials_per_case=1,
                out_path=workspace / "evals" / "live_llm_e2e_report.json",
            )
            llm_pass = llm_report["pass_rate"] >= float(args.min_live_llm_pass_rate)
            record(
                "live_llm_contract",
                llm_pass,
                f"pass_rate={llm_report['pass_rate']:.3f}",
                str(workspace / "evals" / "live_llm_e2e_report.json"),
            )
            if not llm_pass and not bool(args.continue_on_failure):
                report["ok"] = False
                out = workspace / "evals" / f"e2e_report_{args.mode}.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                print(str(out))
                return 1

        guided = run_csp_pipeline(
            query=args.query,
            with_spp=True,
            mode=args.mode,
            workspace=workspace,
            settings=settings,
        )
        guided_ok = guided.status == "SUCCEEDED"
        record("pipeline_guided", guided_ok, guided.status, str(guided.run_dir))
        if not guided_ok and not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1
    except Exception as exc:  # noqa: BLE001
        record("pipeline_guided", False, str(exc))
        if not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1

    try:
        paired = run_paired_baseline_guided(
            query=args.query,
            mode=args.mode,
            workspace=workspace,
            settings=settings,
        )
        paired_payload = json.loads(paired.report_path.read_text(encoding="utf-8"))
        pair_ok = paired.baseline.status == "SUCCEEDED" and paired.guided.status == "SUCCEEDED"
        property_status = str(paired_payload.get("property_assertion_status", "not_available"))
        if property_status == "fail":
            pair_ok = False
        detail = f"{paired.baseline.status}/{paired.guided.status};property_assertion={property_status}"
        record("paired_run", pair_ok, detail, str(paired.report_path))
        if not pair_ok and not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1
    except Exception as exc:  # noqa: BLE001
        record("paired_run", False, str(exc))
        if not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1

    try:
        bench = run_benchmark_cases(
            case_file=Path(args.cases).resolve(),
            mode=args.mode,
            workspace=workspace,
            settings=settings,
        )
        bench_raw = json.loads(Path(bench["results_path"]).read_text(encoding="utf-8"))
        bench_report = json.loads(Path(bench["report_path"]).read_text(encoding="utf-8"))
        rows = bench_raw.get("rows", [])
        failed_rows = [
            row["case_id"]
            for row in rows
            if row.get("baseline_status") != "SUCCEEDED" or row.get("guided_status") != "SUCCEEDED"
        ]
        property_fail_count = int(bench_report.get("property_comparison", {}).get("fail_count", 0))
        bench_ok = (not failed_rows) and property_fail_count == 0
        detail = "ok" if bench_ok else f"failed_cases={failed_rows};property_fail_count={property_fail_count}"
        record("benchmark_run", bench_ok, detail, str(bench["report_path"]))
        if not bench_ok and not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1
    except Exception as exc:  # noqa: BLE001
        record("benchmark_run", False, str(exc))
        if not bool(args.continue_on_failure):
            report["ok"] = False
            out = workspace / "evals" / f"e2e_report_{args.mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(out))
            return 1

    report["ok"] = all(bool(step.get("ok")) for step in report["steps"])
    out = workspace / "evals" / f"e2e_report_{args.mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out))
    return 0 if bool(report["ok"]) else 1


def cmd_benchmark_run(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    try:
        if args.execution_family == "optimization":
            if not _enforce_startup_gate_or_exit(settings=settings, workspace=workspace, mode=args.mode, strict=True):
                return 1
            result = run_optimization_benchmark_cases(
                case_file=Path(args.cases).resolve(),
                mode=args.mode,
                workspace=workspace,
                settings=settings,
                max_iterations=args.max_iterations,
                strict_phase1_benchmark_mode=bool(args.strict_phase1),
            )
        else:
            result = run_benchmark_cases(
                case_file=Path(args.cases).resolve(),
                mode=args.mode,
                workspace=workspace,
                settings=settings,
                strict_phase1_benchmark_mode=bool(args.strict_phase1),
            )
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    print(result["report_path"])
    return 0


def cmd_benchmark_compare(args: argparse.Namespace) -> int:
    left = json.loads(Path(args.left).read_text(encoding="utf-8"))
    right = json.loads(Path(args.right).read_text(encoding="utf-8"))
    report = compare_benchmark_reports(left, right)
    out_path = Path(args.out).resolve() if args.out else Path(args.right).resolve().with_name("benchmark_compare.json")
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


def cmd_benchmark_import_external(args: argparse.Namespace) -> int:
    datasets: list[str]
    if str(args.dataset).strip().lower() == "all":
        datasets = list(EXTERNAL_DATASETS)
    else:
        datasets = [str(args.dataset).strip().lower()]
    try:
        summary = import_external_datasets(
            datasets=datasets,
            max_records_per_split=args.max_records_per_split,
            overwrite=not bool(args.no_overwrite),
        )
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_benchmark_run_external(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    if not _enforce_startup_gate_or_exit(settings=settings, workspace=workspace, mode=args.mode, strict=True):
        return 1
    dataset_values = (
        list(EXTERNAL_DATASETS)
        if str(args.dataset).strip().lower() == "all"
        else [str(args.dataset).strip().lower()]
    )
    regime_values = (
        list(EXTERNAL_REGIMES)
        if str(args.regimes).strip().lower() == "all"
        else [item.strip().lower() for item in str(args.regimes).split(",") if item.strip()]
    )
    split_values = (
        list(EXTERNAL_SPLITS)
        if str(args.splits).strip().lower() == "all"
        else [item.strip().lower() for item in str(args.splits).split(",") if item.strip()]
    )
    try:
        result = run_external_benchmark_matrix(
            datasets=dataset_values,
            mode=args.mode,
            workspace=workspace,
            settings=settings,
            splits=split_values,
            regimes=regime_values,
            max_cases_per_split=args.max_cases_per_split,
            max_iterations=int(args.max_iterations),
            selection_metric_view=str(args.selection_view),
        )
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    print(result["results_path"])
    print(result["report_path"])
    return 0


def cmd_benchmark_regenerate_external(args: argparse.Namespace) -> int:
    results_path = Path(args.results).resolve()
    try:
        report = regenerate_external_benchmark_report(results_path)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    out_path = (
        Path(args.out).resolve()
        if args.out
        else results_path.parent / "external_benchmark_matrix_report.regenerated.json"
    )
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


def cmd_benchmark_compare_external(args: argparse.Namespace) -> int:
    try:
        left = json.loads(Path(args.left).read_text(encoding="utf-8"))
        right = json.loads(Path(args.right).read_text(encoding="utf-8"))
        report = compare_external_benchmark_reports(left, right)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    out_path = (
        Path(args.out).resolve()
        if args.out
        else Path(args.right).resolve().with_name("external_benchmark_matrix_compare.json")
    )
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


def cmd_experiment_run(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    if args.selection_view is not None:
        settings.optimization_selection_metric_view = str(args.selection_view)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    if not _enforce_startup_gate_or_exit(settings=settings, workspace=workspace, mode=args.mode, strict=True):
        return 1
    case_file = Path(args.cases).resolve() if args.cases else default_first_crystal_case_pack().resolve()
    repeats = int(args.repeats)
    try:
        if repeats > 1:
            result = run_repeated_first_crystal_analysis(
                case_file=case_file,
                mode=args.mode,
                workspace=workspace,
                settings=settings,
                repeats=repeats,
                max_iterations=int(args.max_iterations),
                reward_version=str(args.reward_version),
                action_profile=str(args.action_profile),
                analysis_metric_view=str(args.analysis_metric_view),
                include_baseline_control=bool(args.include_baseline_control),
                clarification_answers=list(args.clarification_answer or []),
                strict_phase1_benchmark_mode=bool(args.strict_phase1),
            )
        else:
            result = run_first_crystal_experiment(
                case_file=case_file,
                mode=args.mode,
                workspace=workspace,
                settings=settings,
                max_iterations=int(args.max_iterations),
                reward_version=str(args.reward_version),
                action_profile=str(args.action_profile),
                analysis_metric_view=str(args.analysis_metric_view),
                include_baseline_control=bool(args.include_baseline_control),
                clarification_answers=list(args.clarification_answer or []),
                strict_phase1_benchmark_mode=bool(args.strict_phase1),
            )
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    print(result["manifest_path"])
    print(result["summary_path"])
    return 0


def cmd_experiment_summarize(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = str(payload.get("schema_version", ""))
    if schema == "first_crystal.repeated.experiment.v1":
        summary = regenerate_repeated_first_crystal_summary(manifest_path)
    else:
        summary = regenerate_first_crystal_summary(manifest_path)
    out_path = (
        Path(args.out).resolve()
        if args.out
        else manifest_path.parent
        / (
            "first_crystal_repeated_summary.regenerated.json"
            if schema == "first_crystal.repeated.experiment.v1"
            else "first_crystal_summary.regenerated.json"
        )
    )
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


def cmd_experiment_sensitivity(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    action_ids = [item.strip() for item in str(args.actions).split(",") if item.strip()]
    result = run_forced_sensitivity_experiment(
        query=str(args.query),
        mode=args.mode,
        workspace=workspace,
        settings=settings,
        action_ids=action_ids,
    )
    print(result["results_path"])
    print(result["report_path"])
    return 0


def cmd_experiment_sensitivity_regen(args: argparse.Namespace) -> int:
    results_path = Path(args.results).resolve()
    report = regenerate_forced_sensitivity_report(results_path)
    out_path = (
        Path(args.out).resolve()
        if args.out
        else results_path.parent / "forced_sensitivity_report.regenerated.json"
    )
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


def cmd_experiment_key_ablation(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    dims = [item.strip() for item in str(args.dimensions).split(",") if item.strip()]
    overrides: dict[str, object] = {}
    for item in list(args.override or []):
        if "=" not in item:
            raise ValueError(f"Invalid --override '{item}', expected dimension=value.")
        key, value = item.split("=", 1)
        overrides[key.strip()] = value.strip()
    result = run_per_key_ablation_experiment(
        query=str(args.query),
        mode=args.mode,
        workspace=workspace,
        settings=settings,
        base_action_id=str(args.base_action),
        dimensions=dims,
        variant_values=overrides or None,
    )
    print(result["results_path"])
    print(result["report_path"])
    return 0


def cmd_experiment_key_ablation_regen(args: argparse.Namespace) -> int:
    results_path = Path(args.results).resolve()
    report = regenerate_per_key_ablation_report(results_path)
    out_path = (
        Path(args.out).resolve()
        if args.out
        else results_path.parent / "key_ablation_report.regenerated.json"
    )
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


def cmd_experiment_guided_sweep(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    workspace = Path(args.workspace).resolve() if args.workspace else settings.workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    case_file = Path(args.cases).resolve() if args.cases else default_first_crystal_case_pack().resolve()
    variants = [item.strip() for item in str(args.variants).split(",") if item.strip()]
    result = run_guided_variant_sweep(
        case_file=case_file,
        mode=args.mode,
        workspace=workspace,
        settings=settings,
        repeats=int(args.repeats),
        variant_action_ids=variants,
        metric_view=str(args.metric_view),
    )
    print(result["results_path"])
    print(result["report_path"])
    return 0


def cmd_experiment_guided_sweep_regen(args: argparse.Namespace) -> int:
    results_path = Path(args.results).resolve()
    report = regenerate_guided_variant_sweep_report(results_path)
    out_path = (
        Path(args.out).resolve()
        if args.out
        else results_path.parent / "guided_variant_sweep_report.regenerated.json"
    )
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


def _csv_row_selectors(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def cmd_workflow_doctor(_args: argparse.Namespace) -> int:
    from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
    from sok_llm_orchestrator.workflow.csv_workflow import doctor

    roots = ComponentRoots.load(Path(__file__).resolve().parents[2], required=())
    result = doctor(roots)
    for row in result["components"]:
        print(f"{row['variable']:<18} {row['status']:<4} {row['resolved_root']}")
        for missing in row["missing_subpaths"]:
            print(f"  missing: {missing}")
    return 0 if result["status"] == "PASS" else 2


def cmd_workflow_generate(args: argparse.Namespace) -> int:
    from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
    from sok_llm_orchestrator.workflow.csv_workflow import generate_batch

    roots = ComponentRoots.load(Path(__file__).resolve().parents[2])
    result = generate_batch(
        input_path=Path(args.input).resolve(),
        output_root=Path(args.output).resolve(),
        roots=roots,
        rows=_csv_row_selectors(args.rows),
        resume=args.resume,
        fail_fast=args.fail_fast,
        dry_run=args.dry_run,
        preflight_only=args.preflight_only,
        retry_technical_failures=args.retry_technical_failures,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_workflow_sca(args: argparse.Namespace) -> int:
    from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
    from sok_llm_orchestrator.workflow.csv_workflow import run_sca

    roots = ComponentRoots.load(
        Path(__file__).resolve().parents[2],
        required=("SCA_ROOT",),
    )
    result = run_sca(
        roots=roots,
        row=Path(args.row).resolve() if args.row else None,
        run=Path(args.run).resolve() if args.run else None,
        rows=_csv_row_selectors(args.rows),
        force=args.force,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def cmd_workflow_visualise(args: argparse.Namespace) -> int:
    from sok_llm_orchestrator.workflow.csv_workflow import visualise_row

    result = visualise_row(Path(args.row).resolve())
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sokllm")
    parser.add_argument("--config", default=None, help="Optional YAML config path.")
    parser.add_argument("--workspace", default=None, help="Workspace root override.")
    sub = parser.add_subparsers(dest="command", required=True)

    workflow = sub.add_parser("workflow", help="Frozen csv_workflow_v1 batch interface")
    workflow_sub = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_doctor = workflow_sub.add_parser("doctor", help="Validate configured component roots")
    workflow_doctor.set_defaults(func=cmd_workflow_doctor)
    workflow_generate = workflow_sub.add_parser("generate", help="Generate one independent task per CSV row")
    workflow_generate.add_argument("--input", required=True)
    workflow_generate.add_argument("--output", required=True)
    workflow_generate.add_argument("--rows", default=None, help="Comma-separated stable row IDs")
    workflow_generate.add_argument("--resume", action="store_true")
    workflow_generate.add_argument("--fail-fast", action="store_true")
    workflow_generate.add_argument("--dry-run", action="store_true")
    workflow_generate.add_argument("--preflight-only", action="store_true")
    workflow_generate.add_argument("--retry-technical-failures", action="store_true")
    workflow_generate.set_defaults(func=cmd_workflow_generate)
    workflow_sca = workflow_sub.add_parser("sca", help="Run SCA separately on one row or run")
    sca_target = workflow_sca.add_mutually_exclusive_group(required=True)
    sca_target.add_argument("--row")
    sca_target.add_argument("--run")
    workflow_sca.add_argument("--rows", default=None, help="Run mode: comma-separated row IDs")
    workflow_sca.add_argument("--force", action="store_true")
    workflow_sca.set_defaults(func=cmd_workflow_sca)
    workflow_visualise = workflow_sub.add_parser(
        "visualise", help="Render from one persisted row bundle only"
    )
    workflow_visualise.add_argument("--row", required=True)
    workflow_visualise.set_defaults(func=cmd_workflow_visualise)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--mode", default="stub", choices=["stub", "live"])
    doctor.add_argument("--strict", type=_to_bool, default=True)
    doctor.set_defaults(func=cmd_doctor)
    doctor_sub = doctor.add_subparsers(dest="doctor_command", required=False)
    doctor_startup = doctor_sub.add_parser("startup")
    doctor_startup.add_argument("--mode", default="stub", choices=["stub", "live"])
    doctor_startup.add_argument("--strict", type=_to_bool, default=True)
    doctor_startup.set_defaults(func=cmd_doctor_startup)
    doctor_phase1 = doctor_sub.add_parser("phase1-properties")
    doctor_phase1.add_argument("--implemented-only", action="store_true")
    doctor_phase1.add_argument("--out", default=None)
    doctor_phase1.set_defaults(func=cmd_doctor_phase1_properties)
    doctor_phase2 = doctor_sub.add_parser("phase2-external-predictors")
    doctor_phase2.add_argument("--implemented-only", action="store_true")
    doctor_phase2.add_argument("--out", default=None)
    doctor_phase2.set_defaults(func=cmd_doctor_phase2_external_predictors)
    doctor_phase3 = doctor_sub.add_parser("phase3-external-predictors")
    doctor_phase3.add_argument("--implemented-only", action="store_true")
    doctor_phase3.add_argument("--out", default=None)
    doctor_phase3.set_defaults(func=cmd_doctor_phase3_external_predictors)

    run = sub.add_parser("run")
    run.add_argument("--mode", default="stub", choices=["stub", "live"])
    run.add_argument("--query", default=None)
    run.add_argument("--task-spec-file", default=None)
    run.add_argument("--with-spp", default="true")
    run.set_defaults(func=cmd_run)

    chat = sub.add_parser("chat")
    chat.add_argument("--mode", default="stub", choices=["stub", "live"])
    chat.add_argument("--with-spp", default="true")
    chat.add_argument("--skip-startup-checks", action="store_true")
    chat.set_defaults(func=cmd_chat)

    skills = sub.add_parser("skills")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills.add_argument("--skills-dir", default="skills")
    skills.add_argument("--prompts-dir", default="prompts")

    skills_list = skills_sub.add_parser("list")
    skills_list.set_defaults(func=cmd_skills_list)

    skills_show = skills_sub.add_parser("show")
    skills_show.add_argument("skill_id")
    skills_show.set_defaults(func=cmd_skills_show)

    skills_validate = skills_sub.add_parser("validate")
    skills_validate.set_defaults(func=cmd_skills_validate)

    eval_cmd = sub.add_parser("eval")
    eval_sub = eval_cmd.add_subparsers(dest="eval_command", required=True)
    live_llm = eval_sub.add_parser("live-llm")
    live_llm.add_argument("--trials", default=2, type=int)
    live_llm.add_argument("--min-pass-rate", default=0.8, type=float)
    live_llm.add_argument("--timeout-s", default=None, type=int)
    live_llm.set_defaults(func=cmd_eval_live_llm)
    e2e = eval_sub.add_parser("e2e")
    e2e.add_argument("--mode", default="stub", choices=["stub", "live"])
    e2e.add_argument("--query", default="TiO2 rutile-like")
    e2e.add_argument(
        "--cases",
        default=str(Path("docs/branch/benchmarks/internal_rediscovery_cases.json")),
    )
    e2e.add_argument("--continue-on-failure", action="store_true")
    e2e.add_argument("--min-live-llm-pass-rate", default=0.34, type=float)
    e2e.set_defaults(func=cmd_eval_e2e)

    benchmark = sub.add_parser("benchmark")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)

    benchmark_run = benchmark_sub.add_parser("run")
    benchmark_run.add_argument("--mode", default="stub", choices=["stub", "live"])
    benchmark_run.add_argument("--cases", required=True)
    benchmark_run.add_argument("--execution-family", default="paired", choices=["paired", "optimization"])
    benchmark_run.add_argument("--max-iterations", default=None, type=int)
    benchmark_run.add_argument(
        "--strict-phase1",
        type=_to_bool,
        default=False,
        help="When true, benchmark mode rejects unknown Phase 1 requests and malformed objective payloads.",
    )
    benchmark_run.set_defaults(func=cmd_benchmark_run)

    benchmark_compare = benchmark_sub.add_parser("compare")
    benchmark_compare.add_argument("--left", required=True)
    benchmark_compare.add_argument("--right", required=True)
    benchmark_compare.add_argument("--out", default=None)
    benchmark_compare.set_defaults(func=cmd_benchmark_compare)

    benchmark_import_external = benchmark_sub.add_parser("import-external")
    benchmark_import_external.add_argument("--dataset", default="all", choices=["all", *EXTERNAL_DATASETS])
    benchmark_import_external.add_argument("--max-records-per-split", default=None, type=int)
    benchmark_import_external.add_argument("--no-overwrite", action="store_true")
    benchmark_import_external.set_defaults(func=cmd_benchmark_import_external)

    benchmark_run_external = benchmark_sub.add_parser("run-external")
    benchmark_run_external.add_argument("--mode", default="stub", choices=["stub", "live"])
    benchmark_run_external.add_argument("--dataset", default="all", choices=["all", *EXTERNAL_DATASETS])
    benchmark_run_external.add_argument("--splits", default="test")
    benchmark_run_external.add_argument("--regimes", default="all")
    benchmark_run_external.add_argument("--max-cases-per-split", default=8, type=int)
    benchmark_run_external.add_argument("--max-iterations", default=4, type=int)
    benchmark_run_external.add_argument(
        "--selection-view",
        default="property_decomp_aware",
        choices=["objective_total", "property_aware", "property_decomp_aware"],
    )
    benchmark_run_external.set_defaults(func=cmd_benchmark_run_external)

    benchmark_regen_external = benchmark_sub.add_parser("regenerate-external")
    benchmark_regen_external.add_argument("--results", required=True)
    benchmark_regen_external.add_argument("--out", default=None)
    benchmark_regen_external.set_defaults(func=cmd_benchmark_regenerate_external)

    benchmark_compare_external = benchmark_sub.add_parser("compare-external")
    benchmark_compare_external.add_argument("--left", required=True)
    benchmark_compare_external.add_argument("--right", required=True)
    benchmark_compare_external.add_argument("--out", default=None)
    benchmark_compare_external.set_defaults(func=cmd_benchmark_compare_external)

    experiment = sub.add_parser("experiment")
    experiment_sub = experiment.add_subparsers(dest="experiment_command", required=True)

    exp_run = experiment_sub.add_parser("run")
    exp_run.add_argument("--mode", default="stub", choices=["stub", "live"])
    exp_run.add_argument("--cases", default=None)
    exp_run.add_argument("--max-iterations", default=4, type=int)
    exp_run.add_argument("--repeats", default=1, type=int)
    exp_run.add_argument("--reward-version", default="v1")
    exp_run.add_argument("--action-profile", default="default")
    exp_run.add_argument(
        "--analysis-metric-view",
        default="score",
        choices=["score", "property_x", "spp_term", "objective_total"],
    )
    exp_run.add_argument(
        "--selection-view",
        default=None,
        choices=["objective_total", "property_aware", "property_decomp_aware"],
        help="Optimization loop selection metric view. If omitted, uses config/profile defaults.",
    )
    exp_run.add_argument(
        "--include-baseline-control",
        action="store_true",
        help="Include baseline_control alongside structural allowlist variants.",
    )
    exp_run.add_argument("--clarification-answer", action="append", default=None)
    exp_run.add_argument(
        "--strict-phase1",
        type=_to_bool,
        default=False,
        help="When true, experiment mode rejects unknown Phase 1 requests and malformed objective payloads.",
    )
    exp_run.set_defaults(func=cmd_experiment_run)

    exp_sum = experiment_sub.add_parser("summarize")
    exp_sum.add_argument("--manifest", required=True)
    exp_sum.add_argument("--out", default=None)
    exp_sum.set_defaults(func=cmd_experiment_summarize)

    exp_sense = experiment_sub.add_parser("sensitivity")
    exp_sense.add_argument("--mode", default="stub", choices=["stub", "live"])
    exp_sense.add_argument("--query", required=True)
    exp_sense.add_argument(
        "--actions",
        default="baseline_control,guided_hybrid_balanced,guided_property_push,retrieval_text_explore,cell_policy_probe",
    )
    exp_sense.set_defaults(func=cmd_experiment_sensitivity)

    exp_sense_regen = experiment_sub.add_parser("sensitivity-regenerate")
    exp_sense_regen.add_argument("--results", required=True)
    exp_sense_regen.add_argument("--out", default=None)
    exp_sense_regen.set_defaults(func=cmd_experiment_sensitivity_regen)

    exp_key_abl = experiment_sub.add_parser("key-ablation")
    exp_key_abl.add_argument("--mode", default="stub", choices=["stub", "live"])
    exp_key_abl.add_argument("--query", required=True)
    exp_key_abl.add_argument("--base-action", default="baseline_control")
    exp_key_abl.add_argument(
        "--dimensions",
        default="retrieval_policy,spp_corpus_strategy,spp_weighting_calibration,qlip_guidance,cell_selection",
    )
    exp_key_abl.add_argument(
        "--override",
        action="append",
        default=None,
        help="Optional explicit variant value as dimension=value (repeatable).",
    )
    exp_key_abl.set_defaults(func=cmd_experiment_key_ablation)

    exp_key_abl_regen = experiment_sub.add_parser("key-ablation-regenerate")
    exp_key_abl_regen.add_argument("--results", required=True)
    exp_key_abl_regen.add_argument("--out", default=None)
    exp_key_abl_regen.set_defaults(func=cmd_experiment_key_ablation_regen)

    exp_guided_sweep = experiment_sub.add_parser("guided-sweep")
    exp_guided_sweep.add_argument("--mode", default="stub", choices=["stub", "live"])
    exp_guided_sweep.add_argument("--cases", default=None)
    exp_guided_sweep.add_argument("--repeats", default=2, type=int)
    exp_guided_sweep.add_argument(
        "--variants",
        default="baseline_control,guided_hybrid_balanced,guided_property_push",
    )
    exp_guided_sweep.add_argument(
        "--metric-view",
        default="property_aware",
        choices=["property_aware", "decomposition_aware", "total_objective"],
    )
    exp_guided_sweep.set_defaults(func=cmd_experiment_guided_sweep)

    exp_guided_sweep_regen = experiment_sub.add_parser("guided-sweep-regenerate")
    exp_guided_sweep_regen.add_argument("--results", required=True)
    exp_guided_sweep_regen.add_argument("--out", default=None)
    exp_guided_sweep_regen.set_defaults(func=cmd_experiment_guided_sweep_regen)

    optimize = sub.add_parser("optimize")
    optimize_sub = optimize.add_subparsers(dest="optimize_command", required=True)

    optimize_start = optimize_sub.add_parser("start")
    optimize_start.add_argument("--mode", default="stub", choices=["stub", "live"])
    optimize_start.add_argument("--query", default=None)
    optimize_start.add_argument("--task-spec-file", default=None)
    optimize_start.add_argument("--no-run", action="store_true")
    optimize_start.add_argument("--max-iterations", default=None, type=int)
    optimize_start.add_argument("--exploration-rate", default=None, type=float)
    optimize_start.add_argument("--skip-startup-checks", action="store_true")
    optimize_start.set_defaults(func=cmd_optimize_start)

    optimize_status = optimize_sub.add_parser("status")
    optimize_status.add_argument("--mode", default="stub", choices=["stub", "live"])
    optimize_status.add_argument("--session-id", required=True)
    optimize_status.set_defaults(func=cmd_optimize_status)

    optimize_continue = optimize_sub.add_parser("continue")
    optimize_continue.add_argument("--mode", default="stub", choices=["stub", "live"])
    optimize_continue.add_argument("--session-id", required=True)
    optimize_continue.add_argument("--answer", default=None)
    optimize_continue.add_argument("--max-new-iterations", default=None, type=int)
    optimize_continue.add_argument("--skip-startup-checks", action="store_true")
    optimize_continue.set_defaults(func=cmd_optimize_continue)

    optimize_show_plan = optimize_sub.add_parser("show-plan")
    optimize_show_plan.add_argument("--mode", default="stub", choices=["stub", "live"])
    optimize_show_plan.add_argument("--session-id", required=True)
    optimize_show_plan.set_defaults(func=cmd_optimize_show_plan)

    optimize_show_best = optimize_sub.add_parser("show-best")
    optimize_show_best.add_argument("--mode", default="stub", choices=["stub", "live"])
    optimize_show_best.add_argument("--session-id", required=True)
    optimize_show_best.add_argument("--json", action="store_true")
    optimize_show_best.set_defaults(func=cmd_optimize_show_best)

    optimize_diagnose = optimize_sub.add_parser("diagnose")
    optimize_diagnose.add_argument("--mode", default="stub", choices=["stub", "live"])
    optimize_diagnose.add_argument("--session-id", required=True)
    optimize_diagnose.add_argument("--include-objective-breakdown", action="store_true")
    optimize_diagnose.set_defaults(func=cmd_optimize_diagnose)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
