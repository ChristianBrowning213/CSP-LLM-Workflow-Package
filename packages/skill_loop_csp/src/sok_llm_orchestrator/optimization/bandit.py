from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ArmStats:
    pulls: int = 0
    total_reward: float = 0.0

    @property
    def mean_reward(self) -> float:
        if self.pulls == 0:
            return 0.0
        return self.total_reward / float(self.pulls)


class EpsilonGreedyBandit:
    def __init__(self, *, epsilon: float, seed: int = 0, state: dict[str, Any] | None = None) -> None:
        self.epsilon = float(epsilon)
        self.seed = int(seed)
        self._rng = random.Random(self.seed)
        self._stats: dict[str, ArmStats] = {}
        self._steps = 0
        if state:
            self._steps = int(state.get("steps", 0))
            for aid, item in state.get("arms", {}).items():
                self._stats[aid] = ArmStats(pulls=int(item.get("pulls", 0)), total_reward=float(item.get("total_reward", 0.0)))

    def rank(self, candidates: list[str]) -> list[str]:
        uniq: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            uniq.append(candidate)
        position = {aid: idx for idx, aid in enumerate(uniq)}
        return sorted(
            uniq,
            key=lambda aid: (
                -self._stats.get(aid, ArmStats()).mean_reward,
                self._stats.get(aid, ArmStats()).pulls,
                position.get(aid, 0),
            ),
        )

    def select(self, candidates: list[str], *, epsilon_override: float | None = None) -> tuple[str, dict[str, Any]]:
        ranked = self.rank(candidates)
        self._steps += 1
        unpulled = [aid for aid in ranked if self._stats.get(aid, ArmStats()).pulls == 0]
        if unpulled:
            return unpulled[0], {"mode": "warm_start", "ranked": ranked}
        epsilon = self.epsilon if epsilon_override is None else float(epsilon_override)
        explore = self._rng.random() < epsilon
        if explore:
            # Explore the least-pulled candidate first, with deterministic tie-break.
            chosen = sorted(ranked, key=lambda aid: (self._stats.get(aid, ArmStats()).pulls, aid))[0]
            return chosen, {"mode": "explore", "ranked": ranked, "epsilon_used": epsilon}
        chosen = ranked[0]
        return chosen, {"mode": "exploit", "ranked": ranked, "epsilon_used": epsilon}

    def update(self, action_id: str, reward: float) -> None:
        arm = self._stats.setdefault(action_id, ArmStats())
        arm.pulls += 1
        arm.total_reward += float(reward)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": "epsilon_greedy",
            "epsilon": self.epsilon,
            "seed": self.seed,
            "steps": self._steps,
            "arms": {
                aid: {"pulls": item.pulls, "total_reward": item.total_reward}
                for aid, item in sorted(self._stats.items())
            },
        }
