from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.guided_sweep import (
    regenerate_guided_variant_sweep_report,
    run_guided_variant_sweep,
)


def test_regenerated_guided_variant_report(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_guided_variant_sweep(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=1,
        variant_action_ids=["baseline_control", "guided_hybrid_balanced"],
        metric_view="property_aware",
    )
    original = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    regenerated = regenerate_guided_variant_sweep_report(Path(out["results_path"]))
    assert regenerated["schema_version"] == "guided_variant_sweep.report.v1"
    assert regenerated["aggregate"]["best_variant_action_id"] == original["aggregate"]["best_variant_action_id"]
    assert regenerated["classification_counts"] == original["classification_counts"]
    assert regenerated["recommendations"] == original["recommendations"]
