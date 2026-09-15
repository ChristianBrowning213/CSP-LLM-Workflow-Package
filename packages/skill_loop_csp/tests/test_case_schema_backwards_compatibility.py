from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.bench.cases import load_case_set, validate_case


def test_case_schema_backwards_compatibility_for_existing_packs() -> None:
    root = Path(__file__).resolve().parents[1]
    packs = [
        "internal_rediscovery_cases.json",
        "internal_optimization_behavior_cases.json",
        "first_crystal_cases.json",
        "complex_first_crystal_cases.json",
        "hard_structural_guidance_cases.json",
        "hard_structure_moving_focus_cases.json",
        "multi_hypothesis_complex_cases.json",
        "adversarial_hard_crystal_cases.json",
    ]
    for name in packs:
        case_file = root / "docs" / "branch" / "benchmarks" / name
        cases = load_case_set(case_file)
        assert cases
        for case in cases:
            validate_case(case)
