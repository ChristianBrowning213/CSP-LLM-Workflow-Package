"""Emit the comparable frozen-source/package SPP-to-QLIP adapter contract."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _normalized(value):
    text = json.dumps(value, sort_keys=True)
    return json.loads(text.replace(str(Path(os.environ["WORKFLOW_PARITY_POT_ROOT"]).resolve()), "<POT_ROOT>")
                     .replace(str(Path(tempfile.gettempdir()).resolve()), "<TEMP>"))


mode = os.environ["WORKFLOW_PARITY_IMPL"]
pot_root = Path(os.environ["WORKFLOW_PARITY_POT_ROOT"]).resolve()
pairs = ["O-O", "O-Sr", "O-Ti", "Sr-Sr", "Sr-Ti", "Ti-Ti"]

if mode == "source":
    from sok_llm_orchestrator.workflow.runner import (
        WorkflowConfig,
        _qlip_spp_request_adapter,
        _solver_pair_guidance,
    )

    pair_results = [
        {
            "species_pair": pair,
            "request_pair_status": "REQUEST_DISABLED",
            "guidance_mode": "REGULATOR_ONLY_REQUEST_DISABLED",
        }
        for pair in pairs
    ]
    guidance = _solver_pair_guidance(pairs, pair_results)
    with tempfile.TemporaryDirectory() as directory:
        request_root = Path(directory) / "request"
        request_root.mkdir()
        adapted = _qlip_spp_request_adapter(
            pair_guidance=guidance,
            request_spp={"pot_root": request_root, "regulator_root": pot_root},
            config=WorkflowConfig(
                output_root=Path(directory), regulator_root=pot_root,
                request_coefficient=1.0, regulator_coefficient=1.0,
                outer_objective_scale=1.0, run_id="parity",
            ),
        )
        result = {"required_pairs": pairs, "context": adapted["context"], "guidance": adapted["guidance"]}
elif mode == "package":
    from llm_csp.generation import compile_qlip_request
    from llm_csp.schemas import CSPWorkflowRequest, GenerationConfig, SPPConfig

    request = CSPWorkflowRequest(
        "SrTiO3", "SrTiO3",
        {"template": {"lattice": {}}, "sites": {"mode": "uniform_grid"}},
    )
    with tempfile.TemporaryDirectory() as directory:
        request_root = Path(directory) / "request"
        request_root.mkdir()
        spp = {
            "ready": True, "required_pairs": pairs, "request_supported_pairs": [],
            "regulator_fallback_pairs": pairs, "request_root": str(request_root),
            "regulator_root": str(pot_root),
        }
        compiled = compile_qlip_request(
            request=request, spp=spp,
            spp_config=SPPConfig(request_mode="disabled", regulator_root=pot_root,
                                 request_coefficient=1.0, regulator_coefficient=1.0,
                                 outer_objective_scale=1.0),
            generation=GenerationConfig(), run_id="parity",
        )
        result = {"required_pairs": pairs, "context": compiled["context"], "guidance": compiled["guidance"]}
else:
    raise ValueError(mode)

print(json.dumps(_normalized(result), sort_keys=True, separators=(",", ":")))
