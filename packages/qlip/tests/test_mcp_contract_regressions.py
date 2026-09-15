import copy
import json
import tempfile
from pathlib import Path

from qlip.core.models import SolveError, SolveOutputs, SolveResult, SolveSummary
from qlip.core.solve import solve
from qlip.core.validate import validate_request
from qlip.mcp import server


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _pot_root() -> str:
    return str(_repo_root() / "src" / "qlip" / "interactions" / "SPP" / "SPP")


def _request() -> dict:
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "SrTiO3"},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 3.9,
                        "b": 3.9,
                        "c": 3.9,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    }
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
            },
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
        "context": {"pot_root": _pot_root()},
    }


class _AvailableSolver:
    def available(self, exception_flag=False):
        return True


def test_valid_validate_request_input_passes_and_output_schema_validates(monkeypatch):
    monkeypatch.setattr("qlip.core.validate.pyo.SolverFactory", lambda name: _AvailableSolver())
    result = server.validate_request_tool(_request())
    assert result["valid"] is True
    assert server._validate_tool_output_errors("qlip.validate_request", result) == []


def test_invalid_validate_request_input_returns_structured_mcp_error():
    response = server._dispatch_tool_call("qlip.validate_request", {})
    assert response["ok"] is False
    assert response["result"] is None
    assert response["errors"]
    assert response["errors"][0]["code"] == "SCHEMA_VALIDATION_ERROR"
    assert response["errors"][0]["pointer"].startswith("/")


def test_validate_request_semantic_failure_output_schema_validates():
    req = _request()
    req.pop("context")
    req["guidance"] = [{"id": "objective.energy_spp", "params": {"invented": 1}}]
    result = server.validate_request_tool(req)
    assert result["valid"] is False
    assert {"pot_root_missing", "invalid_guidance_params"}.issubset(
        set(result["validation_error_codes"])
    )
    assert result["invalid_guidance_params"][0]["offending_keys"] == ["invented"]
    assert server._validate_tool_output_errors("qlip.validate_request", result) == []


def _write_pot(root: Path, pair: str) -> None:
    path = root / pair / f"{pair}.POT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0.5 0.0\n1.0 0.3\n2.0 0.1\n3.0 0.0\n", encoding="utf-8")


def test_validate_request_output_schema_allows_soft_repulsive_regularisation_capabilities(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(root))
        pot_root = root / "partial_spp"
        regularisation_root = root / "regularisation_spp"
        _write_pot(pot_root, "Cl-Na")
        _write_pot(regularisation_root, "Cl-Cl")
        request = _request()
        request["problem"]["chemistry"]["formula"] = "NaCl"
        request["context"] = {"pot_root": str(pot_root)}
        request["guidance"] = [
            {
                "id": "objective.energy_spp",
                "weight": 10.0,
                "params": {
                    "pot_root": str(pot_root),
                    "mode": "partial",
                    "supported_pairs": ["Cl-Na"],
                    "missing_pairs": ["Cl-Cl", "Na-Na"],
                    "missing_pair_policy": "soft_repulsive",
                    "missing_pair_penalty": 0.0,
                    "strict_pair_coverage": False,
                    "regularisation_spp_dir": str(regularisation_root),
                    "regularisation_weight": 1.0,
                },
            }
        ]

        result = server.validate_request_tool(request)

        assert result["valid"] is True
        assert result["capabilities"]["spp_partial_guidance"]["missing_pairs_use_soft_repulsive"] is True
        assert result["capabilities"]["spp_missing_pairs_soft_repulsive"] == ["Cl-Cl", "Na-Na"]
        assert result["capabilities"]["spp_regularisation"]["enabled"] is True
        assert result["capabilities"]["spp_regularisation"]["regularisation_pairs_loaded"] == 1
        assert server._validate_tool_output_errors("qlip.validate_request", result) == []


def test_solve_error_output_validates_against_solve_result_schema():
    result = solve({})
    payload = result.to_dict()
    assert payload["status"] == "ERROR"
    assert payload["errors"]
    assert all(error["details"] == error.get("details", {}) for error in payload["errors"])
    assert server._validate_tool_output_errors(
        "qlip.solve",
        {"run_id": "test-run", "result": payload},
    ) == []


def test_solve_result_details_empty_object_when_no_details_exist():
    result = SolveResult(
        status="ERROR",
        summary=SolveSummary(solver="gurobi", timing_ms=0, termination="error"),
        outputs=SolveOutputs(),
        errors=[SolveError(code="solve_error", message="failed")],
    )
    payload = result.to_dict()
    assert payload["errors"][0]["details"] == {}


def test_failed_solve_tool_output_validates():
    output = server.solve_tool({})
    assert output["result"]["status"] == "ERROR"
    assert server._validate_tool_output_errors("qlip.solve", output) == []


def test_current_spp_bad_request_fails_truthfully_and_schema_validates():
    request_path = (
        _repo_root().parent
        / "Skill-Loop-CSP"
        / "test_workdir"
        / "demo_loop_showcase_coas2_real_mcp_qlip_recovery_signal"
        / "_raw_run"
        / "execution"
        / "step_002_spp_package_for_qlip"
        / "qlip_request.json"
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = server.validate_request_tool(request)
    assert result["valid"] is False
    assert {"pot_root_missing", "invalid_guidance_params"}.issubset(
        set(result["validation_error_codes"])
    )
    assert result["invalid_guidance_params"]
    assert all(item["offending_keys"] for item in result["invalid_guidance_params"])
    assert server._validate_tool_output_errors("qlip.validate_request", result) == []


def test_valid_and_failed_solve_outputs_have_schema_valid_result_objects():
    failed = server.solve_tool({})
    assert server._validate_tool_output_errors("qlip.solve", failed) == []

    synthetic_success = {
        "run_id": "ok",
        "result": SolveResult(
            status="OPTIMAL",
            summary=SolveSummary(solver="gurobi", timing_ms=1, termination="optimal"),
            outputs=SolveOutputs(cif="data_x\n_cell_length_a 1\n_cell_length_b 1\n_cell_length_c 1\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n"),
        ).to_dict(),
    }
    assert server._validate_tool_output_errors("qlip.solve", synthetic_success) == []
