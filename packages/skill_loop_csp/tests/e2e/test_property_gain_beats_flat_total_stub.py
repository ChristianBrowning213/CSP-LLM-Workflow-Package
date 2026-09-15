from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.guided_sweep import run_guided_variant_sweep


def test_property_gain_beats_flat_total_stub(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    root = Path(__file__).resolve().parents[2]
    case_file = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_guided_variant_sweep(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=1,
        variant_action_ids=["baseline_control", "guided_hybrid_balanced", "guided_property_push"],
        metric_view="property_aware",
    )
    report = json.loads(Path(out["report_path"]).read_text(encoding="utf-8"))
    # In stub MCP, guided variants raise property_x while total objective can remain flat.
    assert report["aggregate"]["best_variant_action_id"] != "baseline_control"
    best = report["ranked_variants"][0]
    assert float(best.get("property_gain_vs_baseline_rate", 0.0)) > 0.0
