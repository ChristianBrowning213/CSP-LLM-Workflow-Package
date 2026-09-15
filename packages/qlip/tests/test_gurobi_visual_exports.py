import importlib
import json
from pathlib import Path

import pyomo.environ as pyo

from tests.helpers.solve_test_support import (
    DummySPP,
    assign_sequential_solution,
    base_request,
    make_solver_result,
)

solve_mod = importlib.import_module("qlip.core.solve")


def _assign_and_return_optimal(allocation, solver_cfg):
    assign_sequential_solution(allocation)
    return make_solver_result(pyo.TerminationCondition.optimal)


def test_visual_export_flag_writes_matrix_and_trace_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(solve_mod, "_solve_model", _assign_and_return_optimal)
    request = base_request("SrTiO3")
    request.setdefault("runtime", {})["export_gurobi_visuals"] = True
    request.setdefault("context", {})["gurobi_visuals_dir"] = str(tmp_path / "gurobi_visuals")

    result = solve_mod.solve(request)

    assert result.status == "OPTIMAL"
    diagnostics = result.certificates["diagnostics"]
    visuals = diagnostics["gurobi_visuals"]
    assert visuals["enabled"] is True
    assert Path(visuals["constraint_matrix_meta_path"]).is_file()
    assert Path(visuals["constraint_matrix_spy_path"]).is_file()
    assert Path(visuals["mip_trace_json_path"]).is_file()
    assert Path(visuals["mip_trace_plot_path"]).is_file()
    meta = json.loads(Path(visuals["constraint_matrix_meta_path"]).read_text(encoding="utf-8"))
    assert meta["n_constraints"] > 0
    assert meta["n_variables"] > 0
    assert meta["nnz"] > 0
    trace = json.loads(Path(visuals["mip_trace_json_path"]).read_text(encoding="utf-8"))
    assert trace["trace_sparse"] is True
    artifact_kinds = {artifact.kind for artifact in result.outputs.artifacts}
    assert "constraint_matrix_spy_path" in artifact_kinds
    assert "mip_trace_plot_path" in artifact_kinds


def test_visual_export_env_flag_preserves_solve_status(monkeypatch, tmp_path):
    monkeypatch.setenv("QLIP_EXPORT_GUROBI_VISUALS", "1")
    monkeypatch.setenv("QLIP_GUROBI_VISUALS_DIR", str(tmp_path / "env_visuals"))
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(solve_mod, "_solve_model", _assign_and_return_optimal)

    result = solve_mod.solve(base_request("SrTiO3"))

    assert result.status == "OPTIMAL"
    assert result.summary.termination == str(pyo.TerminationCondition.optimal)
    assert result.certificates["diagnostics"]["gurobi_visuals"]["enabled"] is True
