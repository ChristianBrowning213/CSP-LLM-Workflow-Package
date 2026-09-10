"""Minimal CLI over :func:`llm_csp.workflow.run_csp_workflow`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from llm_csp.schemas.workflow import CSPWorkflowRequest, WorkflowConfig
from llm_csp.workflow import run_csp_workflow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-csp")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the deterministic packaged workflow")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--output", type=Path)
    run.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.config.read_text(encoding="utf-8"))
    request = CSPWorkflowRequest.from_dict(payload["request"])
    config_payload = dict(payload["config"])
    if args.output is not None:
        config_payload["output_root"] = str(args.output)
    config = WorkflowConfig.from_dict(config_payload)
    result = run_csp_workflow(request, config)
    rendered = json.dumps(result.to_dict(), indent=2, sort_keys=True)
    if args.json_output:
        print(rendered)
    else:
        print(f"{result.status}: {result.run_id}")
        print(f"manifest: {result.artifacts['run_manifest']}")
    return 0 if result.status == "completed" else 2
