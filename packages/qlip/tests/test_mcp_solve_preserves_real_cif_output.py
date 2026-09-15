from qlip.core.models import SolveOutputs, SolveResult, SolveSummary
from qlip.mcp import server
from tests.helpers.solve_test_support import base_request, make_real_cif_text


def test_mcp_solve_preserves_real_cif_output(monkeypatch):
    real_cif = make_real_cif_text()

    def _fake_core_solve(payload):
        return SolveResult(
            status="OPTIMAL",
            summary=SolveSummary(solver="gurobi", timing_ms=1, termination="optimal"),
            outputs=SolveOutputs(cif=real_cif),
        )

    request = base_request("SrTiO3")
    request["context"] = {"run_id": "run-123"}
    monkeypatch.setattr(server, "core_solve", _fake_core_solve)

    result = server.solve_tool(request)

    assert result["run_id"] == "run-123"
    assert result["result"]["status"] == "OPTIMAL"
    assert result["result"]["outputs"]["cif"] == real_cif
