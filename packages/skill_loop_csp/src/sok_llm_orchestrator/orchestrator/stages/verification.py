from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.verification.presets import get_verification_preset
from sok_llm_orchestrator.verification.qlip_outputs import validate_qlip_outputs


def run_verification_stage(
    solve_payload: dict[str, Any],
    guidance_expected: bool,
    preset_name: str,
) -> dict[str, Any]:
    preset = get_verification_preset(preset_name)
    qlip_report = validate_qlip_outputs(solve_payload, guidance_expected=guidance_expected)
    return {
        "schema_version": "verification_report.v1",
        "preset": preset_name,
        "checks": preset["checks"],
        "qlip_outputs": qlip_report,
        "ok": qlip_report["ok"],
    }
