from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import regenerate_first_crystal_summary, run_first_crystal_experiment


def test_case_focused_protocol_metadata_and_regeneration(workdir: Path) -> None:
    case_file = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "branch"
        / "benchmarks"
        / "hard_structure_moving_focus_cases.json"
    )

    def _executor_factory(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case.get("case_id", "unknown"))

        def _executor(_: str, __: dict[str, Any]) -> dict[str, Any]:
            structure = workdir / "focused_protocol" / f"{case_id}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}\n_cell_length_a 4.0\n", encoding="utf-8")
            return {
                "feasible": True,
                "primary_objective": -1.53,
                "property_estimate": 0.72,
                "objective_audit": {
                    "objective_total": -1.53,
                    "objective_terms": [{"term": "baseline", "value": -1.53}, {"term": "spp", "value": -0.2}],
                    "objective_terms_signature": f"obj-{case_id}",
                    "spp_term": -0.2,
                    "guidance_terms": [{"term": "objective.energy_spp", "value": -0.2}],
                    "solver_summary": {"property_x": 0.72},
                },
                "guided_request_trace": {
                    "effective_overrides": {},
                    "request_guidance_ids": ["objective.energy_spp"],
                    "guidance_structure_signature": f"g-{case_id}",
                },
                "baseline_request_trace": {"effective_overrides": {}, "request_guidance_ids": []},
                "valid_for_learning": True,
                "solver_calls": 1,
                "retrieval_calls": 1,
                "run_reference": {"structure_artifact_path": str(structure)},
            }

        return _executor

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    settings.optimization_max_iterations = 2
    result = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=2,
        action_profile="hard_structure_probe",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory,
    )

    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pack_meta = manifest.get("case_pack_metadata", {})
    assert isinstance(pack_meta, dict)
    assert pack_meta.get("pack_id") == "hard_structure_moving_focus_v1"
    focused_ids = pack_meta.get("focused_case_ids", [])
    assert isinstance(focused_ids, list)
    assert set(focused_ids) == {
        "hard_srtio3_polymorph",
        "hard_na3zr2si2po12_framework",
        "hard_sr2femoo6_ordering",
    }

    regen = regenerate_first_crystal_summary(manifest_path)
    regen_meta = regen.get("case_pack_metadata", {})
    assert isinstance(regen_meta, dict)
    assert regen_meta.get("pack_id") == "hard_structure_moving_focus_v1"
    row_ids = {str(item.get("case_id")) for item in regen.get("rows", []) if isinstance(item, dict)}
    assert row_ids == set(focused_ids)
