from __future__ import annotations

from ase import Atoms
from ase.io import write

import llm_csp.workflow.runner as runner
from llm_csp.retrieval import EvidenceRecord, RetrievalStageResult
from llm_csp.schemas import CSPWorkflowRequest, ValidationConfig, WorkflowConfig
from llm_csp.validation import ValidationError, ValidationResult
from qlip.core.models import SolveOutputs, SolveResult, SolveSummary, ValidationIssue, ValidationReport


REQUEST = CSPWorkflowRequest(
    "SrTiO3", "SrTiO3",
    {
        "template": {"name": "cubic", "lattice": {"a": 3.9, "b": 3.9, "c": 3.9, "alpha": 90, "beta": 90, "gamma": 90, "units": "angstrom"}},
        "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
    },
)


def _cif(path):
    write(path, Atoms("SrTiO3", scaled_positions=[[0, 0, 0], [.5, .5, .5], [.5, .5, 0], [.5, 0, .5], [0, .5, .5]], cell=[3.9] * 3, pbc=True))
    return path


def _success_retrieval(path, events=None):
    def provider(**kwargs):
        if events is not None:
            events.append("retrieval")
        return RetrievalStageResult(
            "retrieval_success", "fixture", (EvidenceRecord("evidence", 1.0, str(path)),)
        )
    return provider


def _ready_spp(root):
    return {
        "status": "complete", "ready": True, "required_pairs": ["O-O"],
        "request_supported_pairs": [], "regulator_fallback_pairs": ["O-O"],
        "request_root": str(root / "request"), "regulator_root": str(root / "regulator"),
        "pair_decisions": [],
    }


def test_retrieval_unavailable_stops_before_spp(tmp_path, monkeypatch) -> None:
    called = False
    def forbidden(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("SPP must not run")
    monkeypatch.setattr(runner, "prepare_spp_guidance", forbidden)
    config = WorkflowConfig(
        output_root=tmp_path / "runs", run_id="retrieval-down",
        retrieval_provider=lambda **kwargs: RetrievalStageResult("retrieval_backend_unavailable", "fixture"),
    )
    result = runner.run_csp_workflow(REQUEST, config)
    assert result.status == "blocked"
    assert result.errors[0]["code"] == "retrieval_backend_unavailable"
    assert called is False
    assert "spp" not in result.stages


def test_no_exportable_cif_stops_before_spp(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "prepare_spp_guidance", lambda **kwargs: (_ for _ in ()).throw(AssertionError("SPP must not run")))
    config = WorkflowConfig(
        output_root=tmp_path / "runs", run_id="no-cif",
        retrieval_provider=lambda **kwargs: RetrievalStageResult(
            "retrieval_success", "fixture", (EvidenceRecord("redacted", 1.0, None),)
        ),
    )
    result = runner.run_csp_workflow(REQUEST, config)
    assert result.status == "blocked"
    assert result.errors[0]["code"] == "retrieval_no_exportable_cifs"
    assert "spp" not in result.stages


def test_incomplete_spp_stops_before_qlip(tmp_path, monkeypatch) -> None:
    cif = _cif(tmp_path / "evidence.cif")
    monkeypatch.setattr(runner, "prepare_spp_guidance", lambda **kwargs: {"status": "spp_incomplete", "ready": False, "reason": "regulator_pair_coverage_incomplete", "missing_pairs": ["Ti-Ti"]})
    monkeypatch.setattr(runner, "compile_qlip_request", lambda **kwargs: (_ for _ in ()).throw(AssertionError("QLIP compilation must not run")))
    result = runner.run_csp_workflow(
        REQUEST,
        WorkflowConfig(output_root=tmp_path / "runs", run_id="spp-incomplete", retrieval_provider=_success_retrieval(cif)),
    )
    assert result.status == "blocked"
    assert result.stages["spp"]["missing_pairs"] == ["Ti-Ti"]
    assert "qlip" not in result.stages


def test_qlip_infeasible_retains_solver_status_and_skips_validation(tmp_path, monkeypatch) -> None:
    import qlip
    import qlip.core.validate

    cif = _cif(tmp_path / "evidence.cif")
    monkeypatch.setattr(runner, "prepare_spp_guidance", lambda **kwargs: _ready_spp(tmp_path))
    monkeypatch.setattr(runner, "compile_qlip_request", lambda **kwargs: {"request": "fake"})
    monkeypatch.setattr(qlip.core.validate, "validate_request", lambda *args, **kwargs: ValidationReport(True, normalized_request={"request": "fake"}))
    monkeypatch.setattr(qlip, "solve", lambda request: SolveResult("INFEASIBLE", SolveSummary("gurobi", 1), SolveOutputs()))
    monkeypatch.setattr(runner, "validate_cif", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("validation must not run")))
    result = runner.run_csp_workflow(
        REQUEST,
        WorkflowConfig(output_root=tmp_path / "runs", run_id="infeasible", retrieval_provider=_success_retrieval(cif)),
    )
    assert result.status == "failed"
    assert result.stages["qlip"]["status"] == "INFEASIBLE"
    assert "candidate" not in result.stages
    assert "validation" not in result.stages


def test_validation_failure_keeps_successful_candidate_and_stage_order(tmp_path, monkeypatch) -> None:
    import qlip
    import qlip.core.validate

    events = []
    cif_path = _cif(tmp_path / "evidence.cif")
    cif_text = cif_path.read_text(encoding="utf-8")

    def spp(**kwargs):
        events.append("spp")
        return _ready_spp(tmp_path)
    def compile_request(**kwargs):
        events.append("compile")
        return {"request": "fake"}
    def validate_request(*args, **kwargs):
        events.append("qlip_validate")
        return ValidationReport(True, normalized_request={"request": "fake"})
    def solve(request):
        events.append("qlip_solve")
        return SolveResult("OPTIMAL", SolveSummary("gurobi", 1, objective_value=1.5), SolveOutputs(cif=cif_text))
    def validate(*args, **kwargs):
        events.append("validation")
        return ValidationResult(
            "backend_unavailable", False, None,
            errors=(ValidationError("backend_unavailable", "SCA missing"),),
        )

    monkeypatch.setattr(runner, "prepare_spp_guidance", spp)
    monkeypatch.setattr(runner, "compile_qlip_request", compile_request)
    monkeypatch.setattr(runner, "score_compiled_spp_objective", lambda **kwargs: 1.5)
    monkeypatch.setattr(runner, "validate_cif", validate)
    monkeypatch.setattr(qlip.core.validate, "validate_request", validate_request)
    monkeypatch.setattr(qlip, "solve", solve)
    result = runner.run_csp_workflow(
        REQUEST,
        WorkflowConfig(
            output_root=tmp_path / "runs", run_id="validation-failure",
            retrieval_provider=_success_retrieval(cif_path, events),
            validation=ValidationConfig(topology=False),
        ),
    )
    assert events == ["retrieval", "spp", "compile", "qlip_validate", "qlip_solve", "validation"]
    assert result.status == "completed_with_validation_failure"
    assert result.stages["qlip"]["status"] == "OPTIMAL"
    assert result.stages["candidate"]["path"]
    assert result.stages["validation"]["general"]["status"] == "backend_unavailable"


def test_feasible_time_limit_is_not_relabelled_optimal(tmp_path, monkeypatch) -> None:
    import qlip
    import qlip.core.validate

    cif_path = _cif(tmp_path / "evidence.cif")
    monkeypatch.setattr(runner, "prepare_spp_guidance", lambda **kwargs: _ready_spp(tmp_path))
    monkeypatch.setattr(runner, "compile_qlip_request", lambda **kwargs: {"request": "fake"})
    monkeypatch.setattr(runner, "score_compiled_spp_objective", lambda **kwargs: 2.0)
    monkeypatch.setattr(qlip.core.validate, "validate_request", lambda *args, **kwargs: ValidationReport(True, normalized_request={"request": "fake"}))
    monkeypatch.setattr(qlip, "solve", lambda request: SolveResult("FEASIBLE_TIME_LIMIT", SolveSummary("gurobi", 1, objective_value=2.0), SolveOutputs(cif=cif_path.read_text(encoding="utf-8"))))

    result = runner.run_csp_workflow(
        REQUEST,
        WorkflowConfig(
            output_root=tmp_path / "runs", run_id="time-limit",
            retrieval_provider=_success_retrieval(cif_path),
            validation=ValidationConfig(enabled=False),
        ),
    )

    assert result.status == "completed"
    assert result.stages["qlip"]["status"] == "FEASIBLE_TIME_LIMIT"
    assert result.stages["candidate"]["solver_status"] == "FEASIBLE_TIME_LIMIT"


def test_gurobi_license_failure_is_normalized(tmp_path, monkeypatch) -> None:
    import qlip
    import qlip.core.validate

    cif = _cif(tmp_path / "evidence.cif")
    monkeypatch.setattr(runner, "prepare_spp_guidance", lambda **kwargs: _ready_spp(tmp_path))
    monkeypatch.setattr(runner, "compile_qlip_request", lambda **kwargs: {"request": "fake"})
    monkeypatch.setattr(
        qlip.core.validate,
        "validate_request",
        lambda *args, **kwargs: ValidationReport(True, normalized_request={"request": "fake"}),
    )
    monkeypatch.setattr(qlip, "solve", lambda request: (_ for _ in ()).throw(RuntimeError("Gurobi license unavailable")))

    result = runner.run_csp_workflow(
        REQUEST,
        WorkflowConfig(output_root=tmp_path / "runs", run_id="no-license", retrieval_provider=_success_retrieval(cif)),
    )

    assert result.status == "failed"
    assert result.errors[0]["code"] == "qlip_backend_unavailable"
    assert result.errors[0]["type"] == "RuntimeError"
    assert "license unavailable" in result.errors[0]["message"]


def test_missing_gurobi_preflight_is_backend_unavailable(tmp_path, monkeypatch) -> None:
    import qlip.core.validate

    cif = _cif(tmp_path / "evidence.cif")
    monkeypatch.setattr(runner, "prepare_spp_guidance", lambda **kwargs: _ready_spp(tmp_path))
    monkeypatch.setattr(runner, "compile_qlip_request", lambda **kwargs: {"request": "fake"})
    monkeypatch.setattr(
        qlip.core.validate,
        "validate_request",
        lambda *args, **kwargs: ValidationReport(
            False,
            errors=[ValidationIssue("gurobi_unavailable", "Gurobi is unavailable", "/solver/name")],
        ),
    )

    result = runner.run_csp_workflow(
        REQUEST,
        WorkflowConfig(output_root=tmp_path / "runs", run_id="missing-gurobi", retrieval_provider=_success_retrieval(cif)),
    )

    assert result.status == "blocked"
    assert result.errors[0]["code"] == "qlip_backend_unavailable"


def test_spp_permission_failure_is_structured_and_stops_qlip(tmp_path, monkeypatch) -> None:
    cif = _cif(tmp_path / "evidence.cif")
    monkeypatch.setattr(
        runner,
        "prepare_spp_guidance",
        lambda **kwargs: (_ for _ in ()).throw(PermissionError("SPP output is not writable")),
    )
    monkeypatch.setattr(
        runner,
        "compile_qlip_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("QLIP must not run")),
    )

    result = runner.run_csp_workflow(
        REQUEST,
        WorkflowConfig(output_root=tmp_path / "runs", run_id="spp-permission", retrieval_provider=_success_retrieval(cif)),
    )

    assert result.status == "blocked"
    assert result.errors[0]["code"] == "spp_error"
    assert result.errors[0]["type"] == "PermissionError"
    assert "qlip" not in result.stages
