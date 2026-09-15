from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def test_deep_spp_exploration_stub(workdir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    settings.optimization_max_iterations = 6
    settings.optimization_exploration_rate = 0.0
    settings.optimization_action_allowlist = [
        "guided_property_push",
        "guided_hybrid_balanced",
        "guided_corpus_branch",
        "guided_payload_probe",
    ]
    settings.optimization_action_family_limits = {
        "guided_exploit": 6,
        "guided_explore": 6,
        "retrieval_explore": 0,
        "cell_policy": 0,
        "baseline_control": 0,
    }
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub")
    result = engine.start(query="Na3Zr2Si2PO12 hard framework case", auto_run=True)
    assert result.status in {"READY", "STOPPED"}
    report_path = Path(result.session_path).parent / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    spp = report["spp_exploration_summary"]
    assert int(spp["unique_corpus_strategy_count"]) >= 2
    assert int(spp["unique_spp_package_variant_count"]) >= 2
    assert int(spp["unique_spp_payload_signature_count"]) >= 2
    assert bool(spp["richer_exploration_detected"])
