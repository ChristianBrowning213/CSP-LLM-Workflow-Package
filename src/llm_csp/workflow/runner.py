"""Packaged Crystal-DB -> SPP -> QLIP -> validation orchestration."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from typing import Any

from llm_csp.generation import compile_qlip_request, score_compiled_spp_objective
from llm_csp.retrieval import retrieve_evidence
from llm_csp.schemas.workflow import CSPWorkflowRequest, WorkflowConfig, WorkflowResult
from llm_csp.validation import validate_cif, validate_family_topology
from .spp_policy import prepare_spp_guidance


SUCCESSFUL_QLIP_STATUSES = {"OPTIMAL", "FEASIBLE", "FEASIBLE_TIME_LIMIT"}
WORKFLOW_SCHEMA = "llm_csp.workflow.v1"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _run_id(request: CSPWorkflowRequest, config: WorkflowConfig) -> str:
    if config.run_id:
        return config.run_id
    scientific = config.to_dict()
    scientific.pop("output_root", None)
    payload = {"schema": WORKFLOW_SCHEMA, "request": request.to_dict(), "config": scientific}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


@contextmanager
def _authorize_qlip(root: Path):
    previous = os.environ.get("QLIP_ALLOWED_PATH_ROOTS")
    os.environ["QLIP_ALLOWED_PATH_ROOTS"] = str(root.resolve())
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("QLIP_ALLOWED_PATH_ROOTS", None)
        else:
            os.environ["QLIP_ALLOWED_PATH_ROOTS"] = previous


def _provenance() -> dict[str, Any]:
    return {
        "schema_version": "llm_csp.workflow.provenance.v1",
        "source_contract": {
            "entry_point": "sok_llm_orchestrator.workflow.runner.run_csp_workflow",
            "commit": "b2130661b4690623877e852dc03132506aa720dd",
        },
        "packages": {
            "llm-csp": _package_version("llm-csp"),
            "crystal-db": _package_version("crystal-db"),
            "qlip": _package_version("qlip"),
            "sca": _package_version("sca"),
        },
        "stage_order": ["retrieval", "spp", "qlip_validate", "qlip_solve", "validation"],
    }


def _result(
    *, run_id: str, status: str, request: CSPWorkflowRequest, stages: dict[str, Any],
    workspace: Path, warnings: list[str], errors: list[dict[str, Any]],
) -> WorkflowResult:
    artifacts = {
        "run_root": str(workspace),
        "request": str(workspace / "request.json"),
        "run_manifest": str(workspace / "run.json"),
    }
    candidate = workspace / "final" / "candidate.cif"
    if candidate.is_file():
        artifacts["candidate_cif"] = str(candidate)
    for name, relative in (
        ("retrieval_result", "retrieval/result.json"),
        ("spp_manifest", "spp/workflow_manifest.json"),
        ("qlip_request", "qlip/request.json"),
        ("qlip_result", "qlip/result.json"),
        ("validation_result", "validation/result.json"),
    ):
        path = workspace / relative
        if path.is_file():
            artifacts[name] = str(path)
    result = WorkflowResult(
        run_id=run_id,
        status=status,
        request=request.to_dict(),
        stages=stages,
        artifacts=artifacts,
        provenance=_provenance(),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    _write_json(workspace / "run.json", result.to_dict())
    return result


def run_csp_workflow(request: CSPWorkflowRequest, config: WorkflowConfig) -> WorkflowResult:
    """Execute the deterministic packaged workflow once in a caller-owned root."""

    if not isinstance(request, CSPWorkflowRequest):
        raise TypeError("request must be CSPWorkflowRequest")
    run_id = _run_id(request, config)
    workspace = Path(config.output_root).expanduser().resolve() / run_id
    if workspace.exists():
        raise FileExistsError(f"refusing to overwrite existing workflow run: {workspace}")
    workspace.mkdir(parents=True)
    _write_json(
        workspace / "request.json",
        {"schema_version": WORKFLOW_SCHEMA, "request": request.to_dict(), "config": config.to_dict()},
    )
    stages: dict[str, Any] = {}
    warnings: list[str] = []
    errors: list[dict[str, Any]] = []

    retrieval = retrieve_evidence(
        request,
        config.retrieval,
        workspace / "retrieval" / "cifs",
        provider=config.retrieval_provider,
    )
    stages["retrieval"] = retrieval.to_dict()
    _write_json(workspace / "retrieval" / "result.json", stages["retrieval"])
    if retrieval.status != "retrieval_success":
        errors.append({"stage": "retrieval", "code": retrieval.status, "details": retrieval.diagnostics})
        return _result(
            run_id=run_id, status="blocked", request=request, stages=stages,
            workspace=workspace, warnings=warnings, errors=errors,
        )

    try:
        spp = prepare_spp_guidance(
            formula=request.formula,
            evidence=retrieval.records,
            config=config.spp,
            output_root=workspace / "spp",
        )
    except Exception as exc:
        errors.append(
            {"stage": "spp", "code": "spp_error", "type": type(exc).__name__, "message": str(exc)}
        )
        return _result(
            run_id=run_id, status="blocked", request=request, stages=stages,
            workspace=workspace, warnings=warnings, errors=errors,
        )
    stages["spp"] = spp
    _write_json(workspace / "spp" / "workflow_manifest.json", spp)
    if not spp.get("ready"):
        errors.append({"stage": "spp", "code": str(spp.get("reason", "spp_incomplete")), "details": spp})
        return _result(
            run_id=run_id, status="blocked", request=request, stages=stages,
            workspace=workspace, warnings=warnings, errors=errors,
        )

    try:
        qlip_request = compile_qlip_request(
            request=request,
            spp=spp,
            spp_config=config.spp,
            generation=config.generation,
            run_id=run_id,
        )
    except Exception as exc:
        errors.append(
            {"stage": "qlip_compile", "code": "qlip_compile_error", "type": type(exc).__name__, "message": str(exc)}
        )
        return _result(
            run_id=run_id, status="blocked", request=request, stages=stages,
            workspace=workspace, warnings=warnings, errors=errors,
        )
    _write_json(workspace / "qlip" / "request.json", qlip_request)
    try:
        from qlip import solve
        from qlip.core.validate import validate_request

        with _authorize_qlip(workspace):
            validation_report = validate_request(qlip_request, strict=True)
            stages["qlip_request_validation"] = validation_report.to_dict()
            _write_json(workspace / "qlip" / "request_validation.json", validation_report.to_dict())
            if not validation_report.valid:
                errors.append(
                    {
                        "stage": "qlip_validate",
                        "code": "qlip_request_invalid",
                        "details": validation_report.to_dict(),
                    }
                )
                return _result(
                    run_id=run_id, status="blocked", request=request, stages=stages,
                    workspace=workspace, warnings=warnings, errors=errors,
                )
            solved = solve(validation_report.normalized_request or qlip_request)
    except Exception as exc:
        errors.append(
            {"stage": "qlip_solve", "code": "qlip_error", "type": type(exc).__name__, "message": str(exc)}
        )
        return _result(
            run_id=run_id, status="failed", request=request, stages=stages,
            workspace=workspace, warnings=warnings, errors=errors,
        )

    qlip_result = solved.to_dict()
    stages["qlip"] = qlip_result
    _write_json(workspace / "qlip" / "result.json", qlip_result)
    cif = solved.outputs.cif
    if solved.status not in SUCCESSFUL_QLIP_STATUSES or not cif:
        errors.append(
            {
                "stage": "qlip_solve",
                "code": f"qlip_{str(solved.status).lower()}",
                "solver_status": solved.status,
                "details": qlip_result.get("errors", []),
            }
        )
        return _result(
            run_id=run_id, status="failed", request=request, stages=stages,
            workspace=workspace, warnings=warnings, errors=errors,
        )

    candidate = workspace / "final" / "candidate.cif"
    candidate.parent.mkdir()
    candidate.write_text(cif, encoding="utf-8")
    objective = solved.summary.objective_value
    try:
        independent = score_compiled_spp_objective(cif=cif, spp=spp, spp_config=config.spp)
    except Exception as exc:
        independent = None
        errors.append(
            {"stage": "objective_parity", "code": "objective_parity_error", "type": type(exc).__name__, "message": str(exc)}
        )
    stages["candidate"] = {
        "path": str(candidate),
        "sha256": _sha256_bytes(candidate.read_bytes()),
        "solver_status": solved.status,
        "solver_objective": objective,
        "independent_objective": independent,
        "objective_difference": (
            None if objective is None or independent is None else abs(float(objective) - independent)
        ),
    }

    if not config.validation.enabled:
        stages["validation"] = {"status": "disabled"}
        return _result(
            run_id=run_id, status="completed", request=request, stages=stages,
            workspace=workspace, warnings=warnings, errors=errors,
        )
    try:
        general = validate_cif(
            candidate,
            target_formula=request.formula,
            target_space_group=request.target_space_group,
            method="llm_csp.workflow",
            run_id=run_id,
        )
    except Exception as exc:
        from llm_csp.validation import ValidationError, ValidationResult

        general = ValidationResult(
            status="evaluation_failure",
            parseable=False,
            valid=None,
            errors=(ValidationError(type(exc).__name__, str(exc)),),
        )
    validation_stage: dict[str, Any] = {"general": general.to_dict(), "topology": None}
    if config.validation.topology and request.topology_family and general.parseable:
        try:
            from pymatgen.core import Structure

            topology = validate_family_topology(
                Structure.from_file(candidate), request.topology_family
            )
            validation_stage["topology"] = topology.to_dict()
        except Exception as exc:
            validation_stage["topology"] = {
                "status": "evaluation_failure",
                "errors": [{"kind": type(exc).__name__, "message": str(exc)}],
            }
    stages["validation"] = validation_stage
    _write_json(workspace / "validation" / "result.json", validation_stage)
    validation_failed = general.status != "evaluated" or (
        validation_stage["topology"] is not None
        and validation_stage["topology"].get("status") not in {"evaluated"}
    )
    if validation_failed:
        errors.append(
            {"stage": "validation", "code": "validation_failed", "details": validation_stage}
        )
    return _result(
        run_id=run_id,
        status="completed_with_validation_failure" if validation_failed else "completed",
        request=request,
        stages=stages,
        workspace=workspace,
        warnings=warnings,
        errors=errors,
    )
