"""Run non-benchmark compatibility smokes for the canonical CSP workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.retrieval.corpus_router import route_corpus
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    _qlip_runtime_root,
    _request_spp_run_id,
    _workflow_run_id,
    run_csp_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "canonical_workflow_compatibility_smokes"
SUMMARY = OUT / "COMPATIBILITY_SMOKE_RESULTS.json"


def _write(payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _config(name: str, *, scaffold_mode: str, request_spp_mode: str) -> WorkflowConfig:
    run_root = OUT / "runs" / name
    return WorkflowConfig(
        output_root=run_root,
        trace_path=run_root / "workflow_trace.json",
        scaffold_mode=scaffold_mode,
        request_spp_mode=request_spp_mode,
    )


def _adopt_legacy_interrupted_attempt(config: WorkflowConfig, request: str) -> dict[str, Any] | None:
    """Attach lifecycle provenance to the pre-attempt-layout interrupted smoke."""
    if config.trace_path is None or not Path(config.trace_path).is_file():
        return None
    trace = json.loads(Path(config.trace_path).read_text(encoding="utf-8"))
    if trace.get("failure_stage") != "request_spp_fit" or "out_root already exists" not in str(trace.get("failure_message")):
        return None
    evidence = trace.get("evidence_bundle") or {}
    bundle_hash = str(evidence.get("bundle_hash") or "")
    if not bundle_hash:
        return None
    legacy_id = _request_spp_run_id(bundle_hash, Path(config.output_root).resolve())
    workspace = _qlip_runtime_root(config) / "runs" / legacy_id
    if not (workspace / "request_spp" / "scaled_all_pairs").is_dir():
        raise RuntimeError(f"legacy collision trace does not match an interrupted request-SPP workspace: {workspace}")
    manifest_path = workspace / "attempt_manifest.json"
    payload = {
        "schema_version": "canonical_workflow_attempt.v1",
        "run_id": _workflow_run_id(request, config),
        "attempt_id": f"legacy-{legacy_id[:12]}",
        "legacy_request_spp_run_id": legacy_id,
        "request": request,
        "status": "INTERRUPTED_OR_INCOMPLETE",
        "workspace": str(workspace),
        "evidence_hash": bundle_hash,
        "evidence_ids": list(trace.get("SPP_evidence_ids") or []),
        "recognition_source": str(Path(config.trace_path).resolve()),
        "preservation_policy": "files_preserved_in_place; no overwrite; no deletion",
    }
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != payload:
            raise RuntimeError(f"refusing to overwrite differing legacy attempt manifest: {manifest_path}")
    else:
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _live_result(request: str, name: str, *, scaffold_mode: str, request_spp_mode: str) -> dict[str, Any]:
    config = _config(name, scaffold_mode=scaffold_mode, request_spp_mode=request_spp_mode)
    legacy_attempt = _adopt_legacy_interrupted_attempt(config, request)
    result = run_csp_workflow(request, config)
    return {
        "status": "PASS",
        "canonical_entrypoint": "sok_llm_orchestrator.workflow.runner.run_csp_workflow",
        "run_id": result.run_id,
        "attempt_id": result.attempt_id,
        "attempt_workspace": result.attempt_workspace,
        "prior_incomplete_attempts": list(result.prior_incomplete_attempts),
        "legacy_interrupted_attempt": legacy_attempt,
        "request": request,
        "scaffold_mode": result.scaffold_mode,
        "scaffold_id": result.scaffold_id,
        "feasible_state_count": result.feasible_state_count,
        "request_spp_mode": request_spp_mode,
        "request_component": result.request_component,
        "request_supported_pair_count": result.request_supported_pair_count,
        "regulator_fallback_pair_count": result.regulator_fallback_pair_count,
        "unsupported_pair_count": result.unsupported_pair_count,
        "pair_modes": {
            row["species_pair"]: row["guidance_mode"]
            for row in result.request_spp_quality["request_pair_results"]
        },
        "solver_status": result.solver_status,
        "objective_difference": result.objective_difference,
        "generated_cif_path": result.generated_cif_path,
        "sca_parse_ok": bool(result.sca_result.get("parse_ok")),
    }


def smoke_halide() -> dict[str, Any]:
    row = _live_result(
        "COMPATIBILITY-SMOKE: generate cubic CsPbBr3 halide perovskite.",
        "halide_fallback_cspbbr3",
        scaffold_mode="tight",
        request_spp_mode="enabled",
    )
    assert row["regulator_fallback_pair_count"] > 0
    assert any(str(mode).startswith("REGULATOR_ONLY_LOCAL_") for mode in row["pair_modes"].values())
    assert row["unsupported_pair_count"] == 0
    assert row["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    return row


def smoke_factorial() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scaffold_mode in ("tight", "loose"):
        for request_spp_mode in ("disabled", "enabled"):
            name = f"factorial_batio3_{scaffold_mode}_{request_spp_mode}"
            row = _live_result(
                "COMPATIBILITY-SMOKE: generate cubic BaTiO3 perovskite.",
                name,
                scaffold_mode=scaffold_mode,
                request_spp_mode=request_spp_mode,
            )
            assert row["feasible_state_count"] == (1 if scaffold_mode == "tight" else 2)
            assert row["unsupported_pair_count"] == 0
            modes = set(row["pair_modes"].values())
            if request_spp_mode == "disabled":
                assert row["request_component"] == 0.0
                assert row["request_supported_pair_count"] == 0
                assert modes == {"REGULATOR_ONLY_REQUEST_DISABLED"}
            else:
                assert row["request_supported_pair_count"] > 0
                assert "REQUEST_PLUS_REGULATOR" in modes
            rows.append(row)
    return {"status": "PASS", "runs": rows}


def smoke_roles() -> dict[str, Any]:
    stages = ProductionWorkflowStages()
    rows: list[dict[str, Any]] = []
    for formula in ("BaTiO3", "CsPbBr3", "CsPbCl3", "CsPbI3", "CsSnI3"):
        task = stages.normalise(f"COMPATIBILITY-SMOKE: {formula}")
        scaffold_id, structure, orbits = stages._scaffold(task, WorkflowConfig(output_root=OUT / "dry_run"))
        roles = task["roles"]
        present = {str(site.specie) for site in structure}
        assert present == set(roles.values())
        if task["family"] == "halide perovskite":
            assert roles["X"] != "O" and "O" not in present
        assert all(
            roles["X"] in orbit["allowed_species"]
            for index, orbit in enumerate(orbits)
            if str(structure[index].specie) == roles["X"]
        )
        rows.append({"formula": formula, "roles": roles, "scaffold_id": scaffold_id, "species": sorted(present)})
    return {"status": "PASS", "cases": rows}


def smoke_nasicon() -> dict[str, Any]:
    stages = ProductionWorkflowStages()
    requests = (
        ("RDX-E4-A2 Na3Zr2Si2PO12 C2", True),
        ("RDX-E4-C2 Na3Ti2(PO4)3 R-3", True),
        ("RDX-E4-F1 LiZr2(PO4)3 R-3c", True),
        ("RDX-NEG-E4-A1 Na3Zr2Si2PO12 R-3c", False),
        ("RDX-NEG-E4-A3 Na3Ti2Si2PO12 R-3", False),
        ("RDX-NEG-E4-A4 Na3Hf2Si2PO12 R-3", False),
    )
    rows: list[dict[str, Any]] = []
    for request, positive in requests:
        task = stages.normalise(request)
        route = route_corpus(request, formula=task["formula"])
        assert route.corpus_id == "nasicon_specialist_v3"
        row: dict[str, Any] = {
            "request": request,
            "formula": task["formula"],
            "classification": "positive" if positive else "negative",
            "corpus_id": route.corpus_id,
            "prototype": task["prototype"],
        }
        try:
            scaffold_id, _, _ = stages._scaffold(task, WorkflowConfig(output_root=OUT / "dry_run"))
            assert positive
            row.update({"representability": "PASS", "scaffold_id": scaffold_id})
        except WorkflowStageError as exc:
            assert not positive and exc.stage == "representability"
            row.update({"representability": "EXPECTED_ABSTENTION", "failure_code": exc.code})
        rows.append(row)
    return {"status": "PASS", "cases": rows}


SMOKES = {
    "halide": smoke_halide,
    "factorial": smoke_factorial,
    "roles": smoke_roles,
    "nasicon": smoke_nasicon,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("smoke", choices=tuple(SMOKES))
    args = parser.parse_args()
    payload = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.is_file() else {
        "schema_version": "canonical_workflow_compatibility_smokes.v1",
        "paper_benchmark_execution": False,
        "held_out_recovery_scoring": False,
        "smokes": {},
    }
    payload["smokes"][args.smoke] = SMOKES[args.smoke]()
    _write(payload)
    print(json.dumps(payload["smokes"][args.smoke], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
