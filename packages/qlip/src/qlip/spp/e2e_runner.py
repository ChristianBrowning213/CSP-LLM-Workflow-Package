from __future__ import annotations

import importlib.util
import math
import time
from dataclasses import dataclass
from typing import Any

from qlip.spp.baseline_tasks import make_baseline_task
from qlip.spp.e2e_task import make_task
from qlip.spp.guidance import SPPGuidance


@dataclass(frozen=True)
class SolveOutcome:
    status: str
    objective_total: float
    objective_decomposition: dict[str, float]
    final_structure: object
    solver_info: dict[str, Any]


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _first_entry(container):
    if container is None:
        return None
    try:
        return container[0]
    except Exception:
        pass
    for accessor in ("values", "items", "keys"):
        try:
            data = getattr(container, accessor)()
            if accessor == "items":
                data = [item[1] for item in data]
            elif accessor == "keys":
                data = [container[key] for key in data]
            data = list(data)
            if data:
                return data[0]
        except Exception:
            continue
    return container


def _extract_solver_metrics(res, objective_total: float, elapsed: float) -> dict[str, Any]:
    solver_block = _first_entry(getattr(res, "solver", None))
    problem_block = _first_entry(getattr(res, "problem", None))

    status = str(getattr(solver_block, "status", "")) if solver_block is not None else ""
    termination = (
        str(getattr(solver_block, "termination_condition", "")) if solver_block is not None else ""
    )
    message = str(getattr(solver_block, "message", "")) if solver_block is not None else ""

    incumbent = None
    best_bound = None
    raw_gap = None

    if problem_block is not None:
        incumbent = _safe_float(getattr(problem_block, "upper_bound", None))
        best_bound = _safe_float(getattr(problem_block, "lower_bound", None))
    if solver_block is not None:
        raw_gap = _safe_float(
            getattr(solver_block, "gap", None)
            or getattr(solver_block, "mip_gap", None)
            or getattr(solver_block, "relative_gap", None)
        )
        if incumbent is None:
            incumbent = _safe_float(
                getattr(solver_block, "upper_bound", None)
                or getattr(solver_block, "objective", None)
                or getattr(solver_block, "objective_value", None)
            )
        if best_bound is None:
            best_bound = _safe_float(
                getattr(solver_block, "lower_bound", None)
                or getattr(solver_block, "best_bound", None)
                or getattr(solver_block, "best_objective_bound", None)
            )

    if incumbent is None:
        incumbent = _safe_float(objective_total)

    mip_gap = raw_gap
    if mip_gap is None and incumbent is not None and best_bound is not None:
        denom = max(abs(incumbent), 1.0e-9)
        mip_gap = abs(incumbent - best_bound) / denom

    return {
        "status": status,
        "termination_condition": termination,
        "message": message if message else None,
        "solve_seconds": float(elapsed),
        "incumbent_objective": incumbent,
        "best_bound": best_bound,
        "mip_gap": _safe_float(mip_gap),
    }


def solver_available() -> tuple[bool, str]:
    if importlib.util.find_spec("pyomo") is None:
        return False, "pyomo is not installed"
    if importlib.util.find_spec("gurobipy") is None:
        return False, "gurobipy is not installed"

    try:
        import pyomo.environ as pyo
    except Exception as exc:
        return False, f"failed to import pyomo: {exc}"

    try:
        import gurobipy  # noqa: F401
    except Exception as exc:
        return False, f"failed to import gurobipy: {exc}"

    try:
        solver = pyo.SolverFactory("gurobi")
        if solver is None:
            return False, "pyomo could not create gurobi solver factory"
        if not solver.available(exception_flag=False):
            return False, "gurobi solver is unavailable to pyomo"

        model = pyo.ConcreteModel()
        model.x = pyo.Var(domain=pyo.NonNegativeReals)
        model.obj = pyo.Objective(expr=model.x, sense=pyo.minimize)
        model.c = pyo.Constraint(expr=model.x >= 1.0)
        solver.options["TimeLimit"] = 3
        solver.options["Threads"] = 1
        _ = solver.solve(model, tee=False)
    except Exception as exc:
        return False, f"gurobi test solve failed: {exc}"

    return True, "ok"


def solve_task(task, spp_guidance=None, seed: int = 7, max_seconds: int = 60) -> SolveOutcome:
    import pyomo.environ as pyo

    if spp_guidance is not None:
        spp_guidance.ensure_pairs(task.pairs)
        task.cost = spp_guidance.as_cost()

    task.encode()
    t0 = time.time()
    res = task.solve(seed=seed, max_seconds=max_seconds, threads=1, tee=False)
    elapsed = float(time.time() - t0)

    termination = str(res.solver.termination_condition)
    status = str(res.solver.status)
    if res.solver.termination_condition == pyo.TerminationCondition.infeasible:
        raise RuntimeError("QLIP solve is infeasible for the configured e2e task")

    objective_total = float(pyo.value(task.m.obj))
    decomposition = task.objective_decomposition()
    final_structure = task.solution_structure()
    solver_info = _extract_solver_metrics(res, objective_total=objective_total, elapsed=elapsed)
    return SolveOutcome(
        status=termination if termination else status,
        objective_total=objective_total,
        objective_decomposition=decomposition,
        final_structure=final_structure,
        solver_info=solver_info,
    )


def solve_task_key(
    *,
    task_key: str,
    spp_package_path,
    spp_enabled: bool,
    seed: int = 7,
    max_seconds: int = 60,
) -> SolveOutcome:
    guidance = None
    if spp_enabled:
        guidance = SPPGuidance.from_package(spp_package_path)
    task = make_task(task_key=task_key, spp_guidance=guidance, seed=seed)
    return solve_task(task, spp_guidance=None, seed=seed, max_seconds=max_seconds)


def solve_baseline_task_key(
    *,
    task_key: str,
    seed: int = 7,
    max_seconds: int = 60,
) -> SolveOutcome:
    task = make_baseline_task(task_key=task_key, seed=seed)
    return solve_task(task, spp_guidance=None, seed=seed, max_seconds=max_seconds)
