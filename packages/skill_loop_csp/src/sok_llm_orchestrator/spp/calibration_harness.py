from __future__ import annotations

import statistics
from typing import Any


def run_calibration_harness(
    reference_scores: list[float],
    target_quantile: float = 0.8,
    guidance_weight_grid: list[float] | None = None,
) -> dict[str, Any]:
    if not reference_scores:
        raise ValueError("reference_scores must not be empty")
    guidance_weight_grid = guidance_weight_grid or [0.1, 0.3, 0.5, 1.0]
    ordered = sorted(reference_scores)
    q_index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * target_quantile))))
    threshold = ordered[q_index]
    spread = statistics.pstdev(ordered) if len(ordered) > 1 else 0.0
    recommended_weight = guidance_weight_grid[min(len(guidance_weight_grid) - 1, int(len(guidance_weight_grid) / 2))]
    return {
        "schema_version": "spp.calibration_report.v1",
        "target_quantile": target_quantile,
        "threshold": threshold,
        "recommended_weight": recommended_weight,
        "distribution": {
            "count": len(ordered),
            "min": ordered[0],
            "max": ordered[-1],
            "mean": statistics.mean(ordered),
            "std": spread,
        },
        "weight_grid": guidance_weight_grid,
    }
