from __future__ import annotations

from typing import Any


def summarize_action_families(iteration_history: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    for item in iteration_history:
        family = str(item.get("action_family", "unknown"))
        reward = item.get("score")
        feasible = bool(item.get("feasible", False))
        bucket = out.setdefault(
            family,
            {"count": 0, "feasible_count": 0, "reward_sum": 0.0, "mean_reward": 0.0},
        )
        bucket["count"] = int(bucket["count"]) + 1
        if feasible:
            bucket["feasible_count"] = int(bucket["feasible_count"]) + 1
        if isinstance(reward, (int, float)):
            bucket["reward_sum"] = float(bucket["reward_sum"]) + float(reward)
        count = max(1, int(bucket["count"]))
        bucket["mean_reward"] = float(bucket["reward_sum"]) / float(count)
    return out

