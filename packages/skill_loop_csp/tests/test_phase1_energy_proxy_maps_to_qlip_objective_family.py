from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_phase1_energy_proxy_from_query_binds_request_and_trace(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    run = run_csp_pipeline(
        query=(
            "Find a feasible TiO2 crystal. Composition fixed to TiO2. Keep symmetry unconstrained. "
            "Use retrieval and SPP guidance. Primary objective: qlip.objective.energy_proxy. "
            "Secondary preference: rutile-like."
        ),
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
    )
    assert run.status == "SUCCEEDED"

    task_spec = json.loads((run.run_dir / "artifacts" / "task_spec.json").read_text(encoding="utf-8"))
    assert task_spec["composition_target"] == "TiO2"
    assert task_spec["solve_mode"] == "feasibility"
    assert task_spec["qlip_objective"] == {"type": "spp_energy"}

    meta = json.loads((run.run_dir / "artifacts" / "qlip_builder_meta.json").read_text(encoding="utf-8"))
    trace = meta["builder_input_trace"]
    assert trace["builder_inputs"]["qlip_objective"] == {"type": "spp_energy"}
    assert trace["builder_inputs"]["qlip_objective_family"] == "spp_energy"

    request = json.loads((run.run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    assert request["problem"]["objective"] == {"type": "spp_energy"}
    assert request["problem"]["chemistry"]["formula"] == "TiO2"
    assert request["problem"]["design_space"]
    assert request["solver"] == {"name": "gurobi"}
