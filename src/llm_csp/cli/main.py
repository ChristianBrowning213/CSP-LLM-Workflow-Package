"""Command-line interface for the deterministic packaged workflow."""

from __future__ import annotations

import argparse
from contextlib import nullcontext, redirect_stdout
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from llm_csp.retrieval import EvidenceRecord, RetrievalStageResult
from llm_csp.schemas.workflow import (
    CSPWorkflowRequest,
    GenerationConfig,
    SPPConfig,
    WorkflowConfig,
)
from llm_csp.workflow import run_csp_workflow

EXIT_SUCCESS = 0
EXIT_INVALID_INPUT = 2
EXIT_BACKEND_UNAVAILABLE = 3
EXIT_SCIENTIFIC_FAILURE = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-csp",
        description="Run the deterministic Crystal-DB -> SPP -> QLIP -> validation workflow.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run from a validated JSON request/configuration")
    run.add_argument("--config", required=True, type=Path, help="workflow JSON configuration")
    run.add_argument("--output", type=Path, help="override config.output_root")
    run.add_argument("--json", action="store_true", dest="json_output", help="emit only JSON")
    demo = commands.add_parser("demo", help="run the bundled offline SrTiO3 workflow")
    demo.add_argument("--output", required=True, type=Path, help="new parent directory for demo results")
    demo.add_argument("--json", action="store_true", dest="json_output", help="emit only JSON")
    return parser


def _offline_request() -> CSPWorkflowRequest:
    return CSPWorkflowRequest(
        query="cubic strontium titanate perovskite",
        formula="SrTiO3",
        target_space_group="Pm-3m",
        topology_family="PEROVSKITE_3D",
        design_space={
            "template": {
                "name": "cubic",
                "lattice": {
                    "a": 3.9, "b": 3.9, "c": 3.9,
                    "alpha": 90.0, "beta": 90.0, "gamma": 90.0,
                    "units": "angstrom",
                },
            },
            "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
        },
    )


def _offline_provider(**kwargs: Any) -> RetrievalStageResult:
    from ase import Atoms
    from ase.io import write

    export_dir = Path(kwargs["export_dir"])
    evidence = export_dir / "synthetic_srtio3_evidence.cif"
    atoms = Atoms(
        ["Sr", "Ti", "O", "O", "O"],
        scaled_positions=[[0, 0, 0], [.5, .5, .5], [.5, .5, 0], [.5, 0, .5], [0, .5, .5]],
        cell=[3.9, 3.9, 3.9],
        pbc=True,
    )
    write(evidence, atoms, format="cif")
    return RetrievalStageResult(
        "retrieval_success",
        "offline_deterministic_fixture",
        (
            EvidenceRecord(
                "synthetic-srtio3-evidence",
                1.0,
                str(evidence),
                {"source": "bundled_synthetic_fixture", "allow_export": True},
                {"formula": "SrTiO3"},
            ),
        ),
        {"network": False, "production_database": False},
    )


def _offline_config(output: Path) -> WorkflowConfig:
    from qlip.resources import bundled_spp_root

    return WorkflowConfig(
        output_root=output,
        spp=SPPConfig(
            request_mode="disabled",
            regulator_root=bundled_spp_root(),
            request_coefficient=1.0,
            regulator_coefficient=1.0,
            outer_objective_scale=1.0,
        ),
        generation=GenerationConfig(time_limit_s=30),
        retrieval_provider=_offline_provider,
        run_id="offline-srtio3",
    )


def _error(message: str, *, json_output: bool, error_type: str = "invalid_input") -> None:
    if json_output:
        print(json.dumps({"status": "error", "error": {"code": error_type, "message": message}}))
    else:
        print(f"error: {message}", file=sys.stderr)


def _exit_code(result: Any) -> int:
    if result.status == "completed":
        return EXIT_SUCCESS
    codes = {str(item.get("code", "")) for item in result.errors}
    if result.status == "completed_with_validation_failure" or any(
        code in {"retrieval_backend_unavailable", "qlip_backend_unavailable"} for code in codes
    ):
        return EXIT_BACKEND_UNAVAILABLE
    return EXIT_SCIENTIFIC_FAILURE


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "demo":
            request = _offline_request()
            config = _offline_config(args.output)
        else:
            payload = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or "request" not in payload or "config" not in payload:
                raise ValueError("config must contain top-level request and config objects")
            request = CSPWorkflowRequest.from_dict(payload["request"])
            config_payload = dict(payload["config"])
            if args.output is not None:
                config_payload["output_root"] = str(args.output)
            config = WorkflowConfig.from_dict(config_payload)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        _error(str(exc), json_output=args.json_output)
        return EXIT_INVALID_INPUT

    try:
        output_context = redirect_stdout(sys.stderr) if args.json_output else nullcontext()
        with output_context:
            result = run_csp_workflow(request, config)
    except (OSError, RuntimeError) as exc:
        _error(str(exc), json_output=args.json_output, error_type="runtime_unavailable")
        return EXIT_BACKEND_UNAVAILABLE

    rendered = json.dumps(result.to_dict(), indent=2, sort_keys=True)
    if args.json_output:
        print(rendered)
    else:
        print(f"{result.status}: {result.run_id}")
        print(f"manifest: {result.artifacts['run_manifest']}")
    return _exit_code(result)
