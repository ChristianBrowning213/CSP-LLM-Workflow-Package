from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_per_key_ablation_experiment
from sok_llm_orchestrator.optimization.backend_sensitivity import normalize_qlip_request_structure
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text


def _sig(obj: object) -> str:
    return sha256_text(canonical_json(obj))


def test_override_changes_request_structure_stub(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        overrides = dict(compiled.get("guided_overrides", {}))
        guidance_mode = str(overrides.get("guidance_mode"))
        guidance = []
        if guidance_mode != "none":
            guidance = [{"id": "objective.energy_spp", "params": {"spp_package_path": "SPPs/A"}}]
        request_payload = {
            "version": "1.0",
            "problem": {"chemistry": {"formula": "TiO2"}, "design_space": {"template": {"lattice": {"a": 4.6}}}},
            "constraints": [],
            "guidance": guidance,
            "solver": {"name": "gurobi"},
        }
        norm = normalize_qlip_request_structure(request_payload)
        value = 0.2 if guidance_mode == "none" else 0.6
        trace = {
            "effective_overrides": overrides,
            "builder_input_trace": {
                "override_key_projection": {"guidance_mode": guidance_mode},
                "dropped_override_keys": [],
            },
            "request_structure": norm,
            "request_structure_signature": _sig(norm),
            "guidance_structure_signature": _sig(norm["guidance_entries"]),
            "constraint_structure_signature": _sig(norm["constraint_entries"]),
            "objective_structure_signature": _sig(norm["objective_structure"]),
            "request_guidance_ids": [item["id"] for item in norm["guidance_entries"]],
            "request_constraint_ids": [],
        }
        return {
            "feasible": True,
            "primary_objective": value,
            "objective_total": value,
            "objective_terms": [{"term": "baseline", "value": value}],
            "guided_request_trace": trace,
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_per_key_ablation_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
        dimensions=["qlip_guidance"],
        executor=_executor,
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    row = report["comparisons"][0]
    assert row["propagation_classification"] == "propagates_to_request_structure"

