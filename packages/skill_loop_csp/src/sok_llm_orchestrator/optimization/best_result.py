from __future__ import annotations

from typing import Any


def promote_best_result(
    current_best: dict[str, Any] | None,
    candidate: dict[str, Any],
    *,
    epsilon: float = 1e-12,
) -> tuple[dict[str, Any], bool]:
    if current_best is None:
        return candidate, True
    curr_score = current_best.get("score")
    cand_score = candidate.get("score")
    if not isinstance(cand_score, (int, float)):
        return current_best, False
    if not isinstance(curr_score, (int, float)) or float(cand_score) > float(curr_score) + epsilon:
        return candidate, True
    return current_best, False

