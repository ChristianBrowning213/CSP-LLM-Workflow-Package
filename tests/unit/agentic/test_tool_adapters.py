from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from llm_csp.agentic.contracts import TOOL_CONTRACTS
from llm_csp.agentic.models import (
    ActorRole,
    AgentPlan,
    ArtifactReference,
    ParsedIntent,
    PlanStep,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    WorkflowRunReference,
)
from llm_csp.agentic.state import AgentRunState
from llm_csp.agentic.tools import (
    ADAPTER_REGISTRY,
    ApprovalRequiredError,
    ToolDependencies,
    ToolExecutionContext,
    apply_execution_to_state,
    execute_tool,
)
from llm_csp.agentic.tools._utils import sha256_file
from llm_csp.schemas import (
    CSPWorkflowRequest,
    RetrievalConfig,
    WorkflowConfig,
    WorkflowResult,
)
from llm_csp.validation import BackendProvenance, TopologyValidationResult, ValidationError, ValidationResult


DESIGN_SPACE = {
    "template": {"name": "cubic", "lattice": {"a": 3.9}},
    "sites": {"mode": "uniform_grid"},
}
REQUEST = CSPWorkflowRequest("SrTiO3", "SrTiO3", DESIGN_SPACE)


class IDs:
    def __init__(self) -> None:
        self.number = 0

    def __call__(self, prefix: str) -> str:
        self.number += 1
        return f"{prefix}_{self.number}"


class Clock:
    def __init__(self) -> None:
        self.seconds = 0

    def __call__(self) -> datetime:
        value = datetime(2026, 1, 1, 0, 0, self.seconds, tzinfo=timezone.utc)
        self.seconds += 2
        return value


def _context(tmp_path: Path, **updates) -> ToolExecutionContext:
    values = {
        "agent_run_id": "agent_1",
        "run_root": str(tmp_path / "agent"),
        "retrieval_configs": {"retrieval": RetrievalConfig(db_path=tmp_path / "fixture.db", embed_engine="hash")},
        "workflow_configs": {"workflow": WorkflowConfig(output_root=tmp_path / "ignored")},
        "id_factory": IDs(),
        "clock": Clock(),
    }
    values.update(updates)
    return ToolExecutionContext(**values)


def _call(name: str, arguments: dict, status=ToolCallStatus.PROPOSED) -> ToolCall:
    return ToolCall("call_1", name, arguments, ActorRole.ORCHESTRATOR, status=status)


def _fake_workflow(solver_status: str = "OPTIMAL", *, spp_incomplete: bool = False, gurobi_missing: bool = False):
    def execute(request, config):
        root = Path(config.output_root) / config.run_id
        root.mkdir(parents=True)
        stages = {"retrieval": {"status": "retrieval_success"}}
        errors = []
        status = "completed"
        artifacts = {"run_root": str(root), "run_manifest": str(root / "run.json")}
        if spp_incomplete:
            stages["spp"] = {"status": "spp_incomplete", "ready": False, "missing_pairs": ["Ti-Ti"]}
            errors.append({"stage": "spp", "code": "regulator_pair_coverage_incomplete", "details": stages["spp"]})
            status = "blocked"
        elif gurobi_missing:
            stages["spp"] = {"status": "complete", "ready": True}
            stages["qlip_request_validation"] = {"valid": False, "errors": [{"code": "gurobi_unavailable"}]}
            errors.append({"stage": "qlip_validate", "code": "qlip_backend_unavailable", "details": stages["qlip_request_validation"]})
            status = "blocked"
        else:
            stages["spp"] = {"status": "complete", "ready": True}
            stages["qlip"] = {"status": solver_status, "summary": {"objective_value": 1.25}}
            if solver_status == "INFEASIBLE":
                status = "failed"
                errors.append({"stage": "qlip_solve", "code": "qlip_infeasible", "solver_status": solver_status})
            else:
                candidate = root / "final" / "candidate.cif"
                candidate.parent.mkdir()
                candidate.write_text("data_fixture\n", encoding="utf-8")
                stages["candidate"] = {"path": str(candidate), "solver_status": solver_status, "solver_objective": 1.25}
                stages["validation"] = {"status": "disabled"}
                artifacts["candidate_cif"] = str(candidate)
        result = WorkflowResult(config.run_id, status, request.to_dict(), stages, artifacts, {"fixture": True}, errors=tuple(errors))
        (root / "run.json").write_text(json.dumps(result.to_dict()), encoding="utf-8")
        return result
    return execute


def _run_arguments() -> dict:
    return {"request": REQUEST.to_dict(), "config_ref": "workflow", "parent_decision_id": "decision_1"}


def test_execution_registry_matches_contract_registry_exactly() -> None:
    assert set(ADAPTER_REGISTRY) == set(TOOL_CONTRACTS)
    assert len(ADAPTER_REGISTRY) == 4


def test_search_adapter_is_read_only_and_preserves_ranked_payload(tmp_path) -> None:
    seen = {}

    def retrieval(**kwargs):
        seen.update(kwargs)
        return {
            "status": "ok", "query": {"text": kwargs["query_text"]},
            "neighbors": [{"rank": 1, "structure_id": "mp-1", "score": 0.9,
                           "metadata": {"formula": "SrTiO3"}, "provenance": {"allow_export": 1}}],
            "backend_status": {"ready": True}, "errors": None,
        }

    result = execute_tool(
        _call("search_crystal_db", {"query": "perovskite", "k": 3, "retrieval_ref": "retrieval"}),
        _context(tmp_path), dependencies=ToolDependencies(retrieval=retrieval),
    )
    assert result.result.status == "retrieval_success"
    assert result.result.data["ranked_results"][0]["structure_id"] == "mp-1"
    assert result.budget_impact.retrieval_calls == 1
    assert seen["export_dir"] is None
    assert not (tmp_path / "agent").exists()
    assert result.duration_seconds == 2.0
    assert result.result.provenance["input_schema"].endswith("input.v1")
    assert result.result.provenance["input_payload"]["query"] == "perovskite"
    assert ToolResult.from_dict(result.result.to_dict()) == result.result


@pytest.mark.parametrize(("payload", "expected"), [
    ({"status": "ok", "neighbors": [], "errors": None}, "no_results"),
    ({"status": "error", "neighbors": [], "errors": {"code": "database_missing"}}, "missing_db"),
    ({"status": "error", "neighbors": [], "errors": {"code": "candidate_vectors_unusable"}}, "embedding_incompatible"),
    ({"status": "error", "neighbors": [], "errors": {"code": "timeout"}}, "retrieval_transient_error"),
    ({"status": "ok", "neighbors": [{"structure_id": "x", "provenance": {"allow_export": 0}}]}, "no_exportable_cifs"),
])
def test_search_failure_statuses(payload, expected, tmp_path) -> None:
    execution = execute_tool(
        _call("search_crystal_db", {"query": "q", "retrieval_ref": "retrieval"}),
        _context(tmp_path), dependencies=ToolDependencies(retrieval=lambda **kwargs: payload),
    )
    assert execution.result.status == expected
    assert execution.result.error.subsystem_status == expected
    assert execution.terminal_call.status is ToolCallStatus.FAILED
    assert execution.terminal_call.error == execution.result.error


def test_search_rejects_unexpressible_formula_filter(tmp_path) -> None:
    with pytest.raises(ValueError, match="formula filtering"):
        execute_tool(
            _call("search_crystal_db", {"query": "q", "formula": "SrTiO3", "retrieval_ref": "retrieval"}),
            _context(tmp_path), dependencies=ToolDependencies(retrieval=lambda **kwargs: {}),
        )


@pytest.mark.parametrize("solver_status", ["OPTIMAL", "FEASIBLE", "FEASIBLE_TIME_LIMIT", "INFEASIBLE"])
def test_run_csp_preserves_solver_status_and_safe_artifacts(tmp_path, solver_status) -> None:
    execution = execute_tool(
        _call("run_csp", _run_arguments(), ToolCallStatus.APPROVED),
        _context(tmp_path), dependencies=ToolDependencies(workflow=_fake_workflow(solver_status)),
    )
    assert execution.result.data["subsystem_statuses"]["solver"] == solver_status
    assert execution.workflow_run.result_ref.path.startswith("workflow_runs/")
    assert execution.workflow_run.result_ref.sha256
    if solver_status == "INFEASIBLE":
        assert execution.workflow_run.candidate_ref is None
        assert execution.terminal_call.status is ToolCallStatus.SUCCEEDED
    else:
        assert execution.workflow_run.candidate_ref.kind == "candidate_cif"
        assert execution.workflow_run.candidate_ref.sha256 == sha256_file(
            _context(tmp_path).write_scope.resolve(execution.workflow_run.candidate_ref.path)
        )


@pytest.mark.parametrize(("executor", "expected"), [
    (_fake_workflow(spp_incomplete=True), "spp_incomplete"),
    (_fake_workflow(gurobi_missing=True), "gurobi_unavailable"),
])
def test_run_csp_preserves_blocking_subsystem_failure(tmp_path, executor, expected) -> None:
    execution = execute_tool(
        _call("run_csp", _run_arguments(), ToolCallStatus.APPROVED),
        _context(tmp_path), dependencies=ToolDependencies(workflow=executor),
    )
    assert execution.result.error.subsystem_status == expected
    assert execution.terminal_call.status is ToolCallStatus.FAILED
    if expected == "spp_incomplete":
        assert execution.result.data["subsystem_statuses"]["solver"] is None


def test_run_csp_requires_approval_and_rejects_out_of_root_result(tmp_path) -> None:
    with pytest.raises(ApprovalRequiredError):
        execute_tool(_call("run_csp", _run_arguments()), _context(tmp_path), dependencies=ToolDependencies(workflow=_fake_workflow()))

    def outside(request, config):
        root = tmp_path / "outside"
        root.mkdir()
        manifest = root / "run.json"
        result = WorkflowResult(config.run_id, "blocked", request.to_dict(), {}, {"run_root": str(root), "run_manifest": str(manifest)}, {})
        manifest.write_text(json.dumps(result.to_dict()), encoding="utf-8")
        return result

    with pytest.raises(ValueError, match="allocated run directory"):
        execute_tool(
            _call("run_csp", _run_arguments(), ToolCallStatus.APPROVED),
            _context(tmp_path), dependencies=ToolDependencies(workflow=outside),
        )

    unsafe_context = _context(tmp_path / "unsafe", id_factory=lambda prefix: "../escape")
    with pytest.raises(ValueError, match="unsafe identifier"):
        execute_tool(
            _call("run_csp", _run_arguments(), ToolCallStatus.APPROVED),
            unsafe_context, dependencies=ToolDependencies(workflow=_fake_workflow()),
        )


def test_programming_errors_are_not_swallowed(tmp_path) -> None:
    with pytest.raises(TypeError, match="must return WorkflowResult"):
        execute_tool(
            _call("run_csp", _run_arguments(), ToolCallStatus.APPROVED),
            _context(tmp_path), dependencies=ToolDependencies(workflow=lambda request, config: {}),
        )


def test_artifact_hash_changes_with_content(tmp_path) -> None:
    path = tmp_path / "artifact"
    path.write_text("one", encoding="utf-8")
    first = sha256_file(path)
    assert sha256_file(path) == first
    path.write_text("two", encoding="utf-8")
    assert sha256_file(path) != first


def _candidate_context(tmp_path, *, exists=True):
    root = tmp_path / "agent"
    path = root / "workflow_runs" / "run" / "candidate.cif"
    if exists:
        path.parent.mkdir(parents=True)
        path.write_text("data_fixture\n", encoding="utf-8")
    ref = ArtifactReference("candidate", "candidate_cif", "workflow_runs/run/candidate.cif", "run")
    return _context(tmp_path, artifact_index={"candidate": ref}), ref


def test_validate_candidate_general_and_rocksault_topology(tmp_path) -> None:
    context, ref = _candidate_context(tmp_path)
    general = ValidationResult("evaluated", True, True, composition={"formula": "NaCl", "target_formula_match": True})
    topology = TopologyValidationResult("evaluated", "ROCKSALT", True, "PASS", True, metrics={"coordination": 6})
    execution = execute_tool(
        _call("validate_candidate", {"candidate_ref": ref.to_dict(), "target_formula": "NaCl", "topology_family": "ROCKSALT"}),
        context,
        dependencies=ToolDependencies(
            validate_general=lambda *args, **kwargs: general,
            structure_loader=lambda path: "structure",
            validate_topology=lambda structure, family: topology,
        ),
    )
    assert execution.result.status == "evaluated"
    assert execution.result.data["general"]["composition"]["formula"] == "NaCl"
    assert execution.result.data["topology"]["topology_status"] == "PASS"


@pytest.mark.parametrize("status", ["parse_failure", "backend_unavailable"])
def test_validate_candidate_normalizes_expected_failures(tmp_path, status) -> None:
    context, ref = _candidate_context(tmp_path)
    general = ValidationResult(status, False, None, errors=(ValidationError(status, "not available"),), backend=BackendProvenance())
    execution = execute_tool(
        _call("validate_candidate", {"candidate_ref": ref.to_dict()}), context,
        dependencies=ToolDependencies(validate_general=lambda *args, **kwargs: general),
    )
    assert execution.result.status == status
    assert execution.result.error.code == status


def test_validate_candidate_rejects_unknown_or_missing_candidate(tmp_path) -> None:
    context, ref = _candidate_context(tmp_path, exists=False)
    missing = execute_tool(
        _call("validate_candidate", {"candidate_ref": ref.to_dict()}), context,
        dependencies=ToolDependencies(validate_general=lambda *args, **kwargs: pytest.fail("must not validate")),
    )
    assert missing.result.status == "candidate_missing"
    unknown = replace(ref, artifact_id="unknown")
    execution = execute_tool(_call("validate_candidate", {"candidate_ref": unknown.to_dict()}), context)
    assert execution.result.status == "candidate_unknown"


def _known_run_context(tmp_path, *, manifest_text=None, include_hash=True):
    root = tmp_path / "agent"
    manifest = root / "workflow_runs" / "run" / "run.json"
    manifest.parent.mkdir(parents=True)
    payload = {
        "run_id": "run", "status": "completed", "request": {"formula": "SrTiO3"},
        "stages": {"retrieval": {"status": "retrieval_success"}, "spp": {"status": "complete"},
                   "qlip": {"status": "OPTIMAL"}, "candidate": {"solver_status": "OPTIMAL"}},
        "artifacts": {"run_manifest": str(manifest)}, "provenance": {"fixture": True}, "warnings": [], "errors": [],
    }
    manifest.write_text(json.dumps(payload) if manifest_text is None else manifest_text, encoding="utf-8")
    digest = sha256_file(manifest) if include_hash else None
    result_ref = ArtifactReference("manifest", "workflow_manifest", "workflow_runs/run/run.json", "run", digest)
    run_ref = WorkflowRunReference("run", "completed", result_ref)
    return _context(tmp_path, workflow_runs={"run": run_ref}, artifact_index={"manifest": result_ref}), manifest, run_ref


def test_inspect_run_selects_sections_without_writing(tmp_path) -> None:
    context, manifest, _ = _known_run_context(tmp_path)
    before = manifest.read_bytes()
    execution = execute_tool(_call("inspect_run", {"workflow_run_id": "run", "include": ["summary", "solver"]}), context)
    assert set(execution.result.data["sections"]) == {"summary", "solver"}
    assert execution.result.data["sections"]["solver"]["result"]["status"] == "OPTIMAL"
    assert manifest.read_bytes() == before


def test_inspect_run_rejects_unknown_missing_corrupt_and_hash_mismatch(tmp_path) -> None:
    context = _context(tmp_path)
    assert execute_tool(_call("inspect_run", {"workflow_run_id": "unknown"}), context).result.status == "unknown_run"

    context, manifest, run_ref = _known_run_context(tmp_path)
    manifest.unlink()
    assert execute_tool(_call("inspect_run", {"workflow_run_id": "run"}), context).result.status == "missing_manifest"

    corrupt_context, _, _ = _known_run_context(tmp_path / "corrupt", manifest_text="not-json", include_hash=False)
    assert execute_tool(_call("inspect_run", {"workflow_run_id": "run"}), corrupt_context).result.status == "corrupt_manifest"

    mismatch_context, mismatch_manifest, mismatch_ref = _known_run_context(tmp_path / "mismatch")
    mismatch_manifest.write_text("{}", encoding="utf-8")
    assert execute_tool(_call("inspect_run", {"workflow_run_id": "run"}), mismatch_context).result.status == "hash_mismatch"


def test_completed_workflow_execution_applies_to_state(tmp_path) -> None:
    call = _call("run_csp", _run_arguments(), ToolCallStatus.APPROVED)
    execution = execute_tool(call, _context(tmp_path), dependencies=ToolDependencies(workflow=_fake_workflow()))
    state = AgentRunState(
        "agent_1", "find SrTiO3", ParsedIntent("find SrTiO3"),
        AgentPlan("plan", "find SrTiO3", (PlanStep("step", "run_csp", "run", _run_arguments()),)),
        tool_calls=(call,),
    )
    updated = apply_execution_to_state(state, execution)
    assert updated.workflow_runs == (execution.workflow_run,)
    assert updated.current_candidate == execution.workflow_run.candidate_ref
    assert updated.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert updated.tool_calls[0].result_ref == execution.workflow_run.run_id
    assert updated.budgets.usage.workflow_runs_used == 1
