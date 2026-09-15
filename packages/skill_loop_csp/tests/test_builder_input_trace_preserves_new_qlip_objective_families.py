from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_builder_input_trace_preserves_new_qlip_objective_families(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    objective = {
        "type": "threshold_tradeoff",
        "linear_property": {
            "kind": "occupancy_linear",
            "terms": [{"species": "Ti", "coefficient": 1.0}],
        },
        "threshold": {"operator": ">=", "value": 0.1},
        "base": {"type": "none"},
        "property_weight": 0.25,
    }
    run = run_csp_pipeline(
        query="TiO2 optimize threshold tradeoff",
        with_spp=False,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={"guidance_mode": "none", "qlip_objective": objective},
    )
    assert run.status == "SUCCEEDED"
    meta = json.loads((run.run_dir / "artifacts" / "qlip_builder_meta.json").read_text(encoding="utf-8"))
    trace = meta["builder_input_trace"]
    assert trace["builder_inputs"]["qlip_objective_family"] == "threshold_tradeoff"
    assert trace["builder_inputs"]["qlip_objective"] == objective
    assert "qlip_objective" in trace["consumed_override_keys"]
    request = json.loads((run.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    assert request["problem"]["objective"] == objective
