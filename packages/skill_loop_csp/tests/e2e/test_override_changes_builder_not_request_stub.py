from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.sensitivity import run_per_key_ablation_experiment
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text


def _sig(obj: object) -> str:
    return sha256_text(canonical_json(obj))


def test_override_changes_builder_not_request_stub(workdir: Path) -> None:
    constant_request_structure = {
        "top_level_keys": ["constraints", "guidance", "problem", "solver", "version"],
        "guidance_entries": [],
        "constraint_entries": [],
        "objective_structure": {"guidance_ids": [], "constraint_ids": []},
    }

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        overrides = dict(compiled.get("guided_overrides", {}))
        retrieval_mode = overrides.get("retrieval_mode")
        trace = {
            "effective_overrides": overrides,
            "builder_input_trace": {
                "override_key_projection": {"retrieval_mode": retrieval_mode},
                "dropped_override_keys": [],
            },
            "request_structure": constant_request_structure,
            "request_structure_signature": _sig(constant_request_structure),
            "guidance_structure_signature": _sig(constant_request_structure["guidance_entries"]),
            "constraint_structure_signature": _sig(constant_request_structure["constraint_entries"]),
            "objective_structure_signature": _sig(constant_request_structure["objective_structure"]),
            "request_guidance_ids": [],
            "request_constraint_ids": [],
        }
        return {
            "feasible": True,
            "primary_objective": 0.33,
            "objective_total": 0.33,
            "objective_terms": [{"term": "baseline", "value": 0.33}],
            "guided_request_trace": trace,
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_per_key_ablation_experiment(
        query="TiO2 optimize high property x",
        mode="stub",
        workspace=workdir,
        settings=settings,
        dimensions=["retrieval_policy"],
        executor=_executor,
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    row = report["comparisons"][0]
    assert row["propagation_classification"] == "changes_request_metadata_only"

