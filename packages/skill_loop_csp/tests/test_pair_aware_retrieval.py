from __future__ import annotations

from sok_llm_orchestrator.workflow.pair_aware_retrieval import select_pair_augmentation


def _candidate(structure_id: str, pairs: list[str], observations: int, rank: int | None = None):
    return {
        "structure_id": structure_id, "supported_pairs": pairs,
        "observation_counts": {pair: observations for pair in pairs}, "semantic_rank": rank,
    }


def test_target_and_equivalent_ids_cannot_enter_augmentation() -> None:
    candidates = [_candidate("target", ["Cl-Na"], 100, 1), _candidate("analogue", ["Cl-Na"], 10, 2)]
    chosen = select_pair_augmentation(
        candidates=candidates, selected_structure_ids=("target",), priority_pairs=("Cl-Na",),
        maximum_additions=2, coverage_only=True,
    )
    assert [row["structure_id"] for row in chosen] == ["analogue"]


def test_partial_support_is_improved_by_smallest_multicoverage_candidate() -> None:
    candidates = [
        _candidate("one", ["Cl-Na"], 20, 1),
        _candidate("both", ["Cl-Na", "Na-Na"], 10, 2),
    ]
    chosen = select_pair_augmentation(
        candidates=candidates, selected_structure_ids=(), priority_pairs=("Cl-Na", "Na-Na"),
        maximum_additions=3, coverage_only=True,
    )
    assert [row["structure_id"] for row in chosen] == ["both"]


def test_no_real_support_returns_empty_augmentation() -> None:
    chosen = select_pair_augmentation(
        candidates=[_candidate("unrelated", ["K-O"], 100, 1)], selected_structure_ids=(),
        priority_pairs=("Cl-Na",), maximum_additions=5, coverage_only=True,
    )
    assert chosen == []


def test_selection_is_deterministic_and_uses_observation_count_then_rank() -> None:
    candidates = [
        _candidate("low", ["Cl-Na"], 10, 1),
        _candidate("high-late", ["Cl-Na"], 20, 3),
        _candidate("high-early", ["Cl-Na"], 20, 2),
    ]
    first = select_pair_augmentation(
        candidates=candidates, selected_structure_ids=(), priority_pairs=("Cl-Na",),
        maximum_additions=2, coverage_only=False,
    )
    second = select_pair_augmentation(
        candidates=reversed(candidates), selected_structure_ids=(), priority_pairs=("Cl-Na",),
        maximum_additions=2, coverage_only=False,
    )
    assert [row["structure_id"] for row in first] == ["high-early", "high-late"]
    assert [row["structure_id"] for row in second] == ["high-early", "high-late"]
