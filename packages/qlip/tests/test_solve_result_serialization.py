from qlip.core.models import SolveError, SolveOutputs, SolveResult, SolveSummary


def test_solve_result_details_not_null():
    result = SolveResult(
        status="ERROR",
        summary=SolveSummary(solver="gurobi", timing_ms=0, termination="error"),
        outputs=SolveOutputs(),
        errors=[SolveError(code="bad", message="fail")],
    )
    payload = result.to_dict()
    assert payload["errors"][0]["details"] == {}
