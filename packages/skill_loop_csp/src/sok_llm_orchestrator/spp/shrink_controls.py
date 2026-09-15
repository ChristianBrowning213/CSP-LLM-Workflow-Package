from __future__ import annotations

from typing import Any


def apply_shrink_controls(
    pair_rows: list[dict[str, Any]],
    min_distance: float = 1.2,
    max_distance: float = 6.5,
    neighbor_shell_limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    short_suppressed = 0
    long_suppressed = 0
    shell_count = 0
    for row in pair_rows:
        distance = float(row.get("distance", 0.0))
        if distance < min_distance:
            short_suppressed += 1
            continue
        if distance > max_distance:
            long_suppressed += 1
            continue
        if neighbor_shell_limit is not None and shell_count >= neighbor_shell_limit:
            continue
        shell_count += 1
        filtered.append(row)
    return filtered, {
        "schema_version": "spp.shrink_controls.v1",
        "min_distance": min_distance,
        "max_distance": max_distance,
        "neighbor_shell_limit": neighbor_shell_limit,
        "short_suppressed": short_suppressed,
        "long_suppressed": long_suppressed,
    }
