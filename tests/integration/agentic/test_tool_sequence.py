from __future__ import annotations

import json
from pathlib import Path

from ase.build import bulk
from ase.io import write
import pytest

from llm_csp.agentic.models import ActorRole, ArtifactReference, ToolCall, ToolCallStatus
from llm_csp.agentic.tools import ToolDependencies, ToolExecutionContext, execute_tool
from llm_csp.retrieval import EvidenceRecord, RetrievalStageResult
from llm_csp.schemas import (
    CSPWorkflowRequest,
    RetrievalConfig,
    SPPConfig,
    ValidationConfig,
    WorkflowConfig,
    WorkflowResult,
)
from llm_csp.validation import ValidationResult


DESIGN_SPACE = {
    "template": {"name": "cubic", "lattice": {"a": 3.9}},
    "sites": {"mode": "uniform_grid"},
}
REQUEST = CSPWorkflowRequest("SrTiO3", "SrTiO3", DESIGN_SPACE)
FIXTURE = Path(__file__).parents[2] / "fixtures" / "agentic" / "canonical_tool_sequence.v1.json"


class IDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value}"


def _call(identifier, name, arguments, status=ToolCallStatus.PROPOSED):
    return ToolCall(identifier, name, arguments, ActorRole.ORCHESTRATOR, status=status)


def _fixture_workflow(request, config):
    root = Path(config.output_root) / config.run_id
    root.mkdir(parents=True)
    candidate = root / "final" / "candidate.cif"
    candidate.parent.mkdir()
    candidate.write_text("data_fixture\n", encoding="utf-8")
    artifacts = {
        "run_root": str(root), "run_manifest": str(root / "run.json"), "candidate_cif": str(candidate),
    }
    stages = {
        "retrieval": {"status": "retrieval_success"}, "spp": {"status": "complete", "ready": True},
        "qlip": {"status": "OPTIMAL"},
        "candidate": {"path": str(candidate), "solver_status": "OPTIMAL", "solver_objective": 1.0},
        "validation": {"status": "disabled"},
    }
    result = WorkflowResult(config.run_id, "completed", request.to_dict(), stages, artifacts, {"fixture": True})
    (root / "run.json").write_text(json.dumps(result.to_dict()), encoding="utf-8")
    return result


def test_four_tool_no_llm_sequence_is_context_coherent(tmp_path) -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ids = IDs()
    base = ToolExecutionContext(
        "agent_sequence", str(tmp_path / "agent"),
        retrieval_configs={"retrieval": RetrievalConfig(db_path=tmp_path / "fixture.db", embed_engine="hash")},
        workflow_configs={"workflow": WorkflowConfig(output_root=tmp_path / "ignored")},
        id_factory=ids,
    )
    search = execute_tool(
        _call("search", "search_crystal_db", {"query": "perovskite", "retrieval_ref": "retrieval"}), base,
        dependencies=ToolDependencies(retrieval=lambda **kwargs: {
            "status": "ok", "query": {"text": kwargs["query_text"]}, "errors": None,
            "backend_status": {"ready": True},
            "neighbors": [{"rank": 1, "structure_id": "fixture", "score": 1.0,
                           "provenance": {"allow_export": 1}}],
        }),
    )
    run = execute_tool(
        _call("run", "run_csp", {
            "request": REQUEST.to_dict(), "config_ref": "workflow", "parent_decision_id": "decision",
        }, ToolCallStatus.APPROVED),
        base, dependencies=ToolDependencies(workflow=_fixture_workflow),
    )
    artifacts = {item.artifact_id: item for item in run.result.artifact_refs}
    enriched = ToolExecutionContext(
        "agent_sequence", base.run_root,
        retrieval_configs=base.retrieval_configs,
        workflow_configs=base.workflow_configs,
        workflow_runs={run.workflow_run.run_id: run.workflow_run},
        artifact_index=artifacts,
        id_factory=ids,
    )
    validate = execute_tool(
        _call("validate", "validate_candidate", {"candidate_ref": run.workflow_run.candidate_ref.to_dict()}),
        enriched,
        dependencies=ToolDependencies(validate_general=lambda *args, **kwargs: ValidationResult("evaluated", True, True)),
    )
    inspect = execute_tool(
        _call("inspect", "inspect_run", {"workflow_run_id": run.workflow_run.run_id, "include": ["summary", "solver"]}),
        enriched,
    )
    actual = {
        "search_crystal_db": search.result.status,
        "run_csp": run.result.status,
        "validate_candidate": validate.result.status,
        "inspect_run": inspect.result.status,
    }
    assert actual == expected["expected_results"]
    assert {item.kind for item in run.result.artifact_refs} == set(expected["expected_artifacts"])
    assert inspect.result.data["workflow_run_id"] == run.workflow_run.run_id


def test_run_adapter_calls_real_workflow_and_preserves_spp_gate(tmp_path) -> None:
    evidence = tmp_path / "evidence.cif"
    evidence.write_text("data_fixture\n", encoding="utf-8")
    regulator_root = tmp_path / "empty-pots"
    regulator_root.mkdir()

    def retrieval_provider(**kwargs):
        return RetrievalStageResult(
            "retrieval_success", "fixture", (EvidenceRecord("fixture", 1.0, str(evidence)),)
        )

    context = ToolExecutionContext(
        "agent_real_boundary", str(tmp_path / "agent"),
        workflow_configs={
            "workflow": WorkflowConfig(
                output_root=tmp_path / "ignored",
                retrieval_provider=retrieval_provider,
                spp=SPPConfig(request_mode="disabled", regulator_root=regulator_root),
                validation=ValidationConfig(enabled=False),
            )
        },
        id_factory=lambda prefix: f"{prefix}_real",
    )
    execution = execute_tool(
        _call("run", "run_csp", {
            "request": REQUEST.to_dict(), "config_ref": "workflow", "parent_decision_id": "decision",
        }, ToolCallStatus.APPROVED),
        context,
    )
    assert execution.result.provenance["underlying_api"] == "llm_csp.workflow.run_csp_workflow"
    assert execution.result.data["subsystem_statuses"]["spp"] == "spp_incomplete"
    assert execution.result.data["subsystem_statuses"]["solver"] is None
    assert execution.workflow_run.candidate_ref is None


def test_search_adapter_calls_real_crystal_db_missing_db_boundary_read_only(tmp_path) -> None:
    missing_db = tmp_path / "does-not-exist.db"
    context = ToolExecutionContext(
        "agent_retrieval", str(tmp_path / "agent"),
        retrieval_configs={"missing": RetrievalConfig(db_path=missing_db, embed_engine="hash")},
    )
    execution = execute_tool(
        _call("search", "search_crystal_db", {"query": "perovskite", "retrieval_ref": "missing"}),
        context,
    )
    assert execution.result.provenance["underlying_api"] == "crystal_db.retrieval.text_search"
    assert execution.result.status == "missing_db"
    assert not missing_db.exists()
    assert not (tmp_path / "agent").exists()


def test_validation_adapter_calls_real_sca_boundary_when_available(tmp_path) -> None:
    pytest.importorskip("sca", reason="install the validation extra to test the real SCA adapter boundary")
    root = tmp_path / "agent"
    candidate = root / "workflow_runs" / "run" / "candidate.cif"
    candidate.parent.mkdir(parents=True)
    write(candidate, bulk("NaCl", "rocksalt", a=5.64))
    reference = ArtifactReference(
        "candidate", "candidate_cif", "workflow_runs/run/candidate.cif", "run"
    )
    context = ToolExecutionContext(
        "agent_validation", str(root), artifact_index={"candidate": reference}
    )
    execution = execute_tool(
        _call("validate", "validate_candidate", {
            "candidate_ref": reference.to_dict(), "target_formula": "NaCl", "topology_family": "ROCKSALT",
        }),
        context,
    )
    assert execution.result.data["general"]["status"] == "evaluated"
    assert execution.result.data["general"]["composition"]["target_formula_match"] is True
    assert execution.result.data["topology"]["family"] == "ROCKSALT"
