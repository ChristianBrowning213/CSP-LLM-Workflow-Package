"""ONE bounded, telemetry-only reproducer for the scaled-cell incumbent audit.

Purpose (see artifacts/Paper_results_scaled_cell_incumbent_audit_*/README.md):
forensic analysis of the frozen Paper_results_native_cell_size_test_*
package proved (from Pyomo/Gurobi interface source, not speculation) that
the CELLSIZE_NA3ZR2SI2PO12_COMPOSITION_SCALED row's Gurobi TIME_LIMIT
termination had SolCount >= 1 (a feasible incumbent existed and was loaded
into the Pyomo model), but neither the incumbent's objective/bound/gap nor
its variable vector was ever persisted to disk. This script reproduces
that EXACT frozen solve -- same request text, same normalised task, same
cell (composition_scaled, a=7.112060346378155 A, density=8), same
proximity.atomic_radii(scale=1.0) constraint, same SPP weights, same
300s Gurobi TimeLimit -- by reusing the frozen request-SPP POT files and
frozen regulator root already on disk, so it does NOT re-run retrieval or
SPP fitting and does NOT alter any scientific parameter.

It changes exactly one thing beyond frozen production behavior: it adds a
Gurobi ``LogFile`` parameter (pure diagnostics, not a solver behavior
change) and, after the real unmodified qlip.core.solve.solve() call
returns, independently inspects the Pyomo model it already populated to
attempt CIF recovery -- entirely OUTSIDE qlip's own status gate, so the
production SolveResult and its ERROR status are completely unaffected.

Never writes into the frozen source package. Output goes only to a new
audit package.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
)


FROZEN_ROW_TRACE = Path(
    "artifacts/Paper_results_native_cell_size_test_2026-08-19_155735/table_run/rows/"
    "CELLSIZE_NA3ZR2SI2PO12_COMPOSITION_SCALED/attempts/"
    "20260819T224301.900320Z-c59573362ca8/workflow_trace.json"
)


def load_frozen_trace() -> dict[str, Any]:
    return json.loads(FROZEN_ROW_TRACE.read_text(encoding="utf-8"))


def build_frozen_request_spp(trace: dict[str, Any]) -> dict[str, Any]:
    pot_root = Path(trace["request_spp_root"])
    regulator_root = Path(trace["regulator_root"])
    if not pot_root.is_dir():
        raise FileNotFoundError(f"frozen request-SPP POT root no longer exists: {pot_root}")
    if not regulator_root.is_dir():
        raise FileNotFoundError(f"frozen regulator root no longer exists: {regulator_root}")
    return {
        "pot_root": pot_root,
        "regulator_root": regulator_root,
        "quality": {"request_pair_results": trace["request_pair_results"]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Audit package directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    log_path = (args.output / "gurobi_reproducer.log").resolve()
    telemetry_path = args.output / "REPRODUCER_TELEMETRY.json"
    cif_path = args.output / "recovered_CELLSIZE_NA3ZR2SI2PO12_COMPOSITION_SCALED.cif"

    trace = load_frozen_trace()
    request_text = trace["request"]
    frozen_run_id = trace["run_id"]

    stages = ProductionWorkflowStages()
    task = stages.normalise(request_text)
    assert task == trace["normalised_task"], "reconstructed task does not match the frozen row"

    config = WorkflowConfig(
        output_root=args.output,
        retrieval_depth=40,
        embedding_model="text-embedding-bge-m3",
        embedding_version="lmstudio_v1",
        retrieval_demo_export=True,
        cutoff=11.0,
        request_coefficient=1.0,
        regulator_coefficient=2.0,
        outer_objective_scale=10.0,
        request_spp_convention="reward",
        regulator_id="icsd_broad_regulator_v1",
        scaffold_mode="none",
        native_qlip=True,
        request_spp_mode="enabled",
        cell_mode="composition_scaled",
        cell_volume_per_atom=None,
        run_id=frozen_run_id,
        attempt_id="incumbent-audit-reproducer",
    )
    request_spp = build_frozen_request_spp(trace)
    run_root = args.output / "run_root"
    run_root.mkdir(parents=True, exist_ok=True)

    import qlip.core.solve  # noqa: F401 - ensure sys.modules is populated

    # `qlip.core.__init__` rebinds the attribute `qlip.core.solve` to the
    # `solve` FUNCTION (shadowing the submodule), so `import qlip.core.solve
    # as x` -- which resolves via attribute traversal -- would silently bind
    # the function instead of the module. sys.modules is the unambiguous
    # source of truth for the actual submodule object.
    qlip_solve_module = sys.modules["qlip.core.solve"]
    original_solve_model = qlip_solve_module._solve_model
    captured: dict[str, Any] = {}

    def wrapped_solve_model(allocation, solver_cfg):
        solver_cfg = dict(solver_cfg)
        params = dict(solver_cfg.get("parameters") or {})
        params.setdefault("LogFile", str(log_path))
        solver_cfg["parameters"] = params
        assert solver_cfg.get("time_limit_s") == 300, "frozen manifest TimeLimit must stay 300s"
        started = time.perf_counter()
        results = original_solve_model(allocation, solver_cfg)
        captured["solve_model_wall_s"] = time.perf_counter() - started
        captured["allocation"] = allocation
        captured["results"] = results
        return results

    qlip_solve_module._solve_model = wrapped_solve_model
    workflow_stage_error: WorkflowStageError | None = None
    solve_result_summary: dict[str, Any] | None = None
    try:
        started_total = time.perf_counter()
        # ProductionWorkflowStages.solve() applies QLIP_ALLOWED_PATH_ROOTS
        # authorization internally (see runner.py _qlip_pot_authorization).
        solved = stages.solve(task, request_spp, config, run_root)
        captured["total_wall_s"] = time.perf_counter() - started_total
        solve_result_summary = {
            "status": solved["status"],
            "solver_objective": solved["solver_objective"],
        }
    except WorkflowStageError as exc:
        captured["total_wall_s"] = time.perf_counter() - started_total
        workflow_stage_error = exc
    finally:
        qlip_solve_module._solve_model = original_solve_model

    telemetry: dict[str, Any] = {
        "schema_version": "scaled_cell_incumbent_reproducer_telemetry.v1",
        "frozen_source_row": "CELLSIZE_NA3ZR2SI2PO12_COMPOSITION_SCALED",
        "frozen_source_trace": str(FROZEN_ROW_TRACE),
        "frozen_run_id": frozen_run_id,
        "request": request_text,
        "solve_model_wall_s": captured.get("solve_model_wall_s"),
        "total_wall_s": captured.get("total_wall_s"),
        "solve_result_summary": solve_result_summary,
        "workflow_stage_error": (
            {"stage": workflow_stage_error.stage, "code": workflow_stage_error.code, "message": str(workflow_stage_error)}
            if workflow_stage_error is not None
            else None
        ),
    }

    results_obj = captured.get("results")
    if results_obj is not None:
        solver = getattr(results_obj, "solver", None)
        problem = getattr(results_obj, "problem", None)
        telemetry["pyomo_solver_status"] = str(getattr(solver, "status", None))
        telemetry["pyomo_termination_condition"] = str(getattr(solver, "termination_condition", None))
        telemetry["pyomo_termination_message"] = str(getattr(solver, "termination_message", None))
        telemetry["pyomo_number_of_solutions"] = getattr(problem, "number_of_solutions", None)
        telemetry["pyomo_lower_bound"] = getattr(problem, "lower_bound", None)
        telemetry["pyomo_upper_bound"] = getattr(problem, "upper_bound", None)
        telemetry["pyomo_num_solution_entries"] = len(getattr(results_obj, "solution", []) or [])
        try:
            soln0 = results_obj.solution[0]
            telemetry["pyomo_solution0_objective"] = dict(soln0.objective).get("__default_objective__", {}).get("Value")
            telemetry["pyomo_solution0_status"] = str(soln0.status)
            telemetry["pyomo_solution0_gap"] = getattr(soln0, "gap", None)
        except Exception as exc:  # noqa: BLE001 - audit-only best-effort extraction
            telemetry["pyomo_solution0_extraction_error"] = repr(exc)
    else:
        telemetry["pyomo_solver_status"] = "NOT_CAPTURED_SOLVE_DID_NOT_REACH_GUROBI"

    allocation = captured.get("allocation")
    recovery: dict[str, Any] = {"attempted": allocation is not None}
    if allocation is not None:
        try:
            from qlip.core.solve import _build_cif_text, _classify_cif_output

            cif_kind, cif_text, cif_details = _classify_cif_output(_build_cif_text(allocation))
            recovery["cif_kind"] = cif_kind
            recovery["cif_details"] = cif_details
            if cif_kind == "valid_cif_like" and cif_text:
                cif_path.write_text(cif_text, encoding="latin-1")
                recovery["cif_written_to"] = str(cif_path)
                recovery["status_label"] = "FEASIBLE_TIME_LIMIT"
            else:
                recovery["status_label"] = "INCUMBENT_CONFIRMED_NOT_RECOVERABLE"
        except Exception as exc:  # noqa: BLE001 - audit-only best-effort extraction
            recovery["error"] = repr(exc)
            recovery["status_label"] = "INCUMBENT_CONFIRMED_NOT_RECOVERABLE"
    telemetry["independent_cif_recovery_attempt"] = recovery

    telemetry_path.write_text(json.dumps(telemetry, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(telemetry, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
