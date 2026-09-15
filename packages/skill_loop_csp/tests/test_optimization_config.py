from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings


def test_optimization_config_overrides_from_yaml(workdir: Path) -> None:
    cfg = workdir / "opt_cfg.yaml"
    cfg.write_text(
        "\n".join(
            [
                "optimization_max_iterations: 9",
                "optimization_exploration_rate: 0.1",
                "optimization_allow_midloop_clarification: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings.from_sources(cfg)
    assert settings.optimization_max_iterations == 9
    assert abs(settings.optimization_exploration_rate - 0.1) < 1e-12
    assert settings.optimization_allow_midloop_clarification is False

