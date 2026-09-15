from __future__ import annotations

from sok_llm_orchestrator.verification.presets import get_verification_preset


def test_verification_presets_lookup() -> None:
    preset = get_verification_preset("benchmark")
    assert "checks" in preset
    assert "reproducibility" in preset["checks"]
