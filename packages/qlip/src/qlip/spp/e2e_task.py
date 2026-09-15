from __future__ import annotations

import numpy as np
from qlip.spp.baseline_tasks import (
    BaselineDistanceCost,
    available_task_keys as available_baseline_task_keys,
    make_baseline_task,
)


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((str(a).strip().capitalize(), str(b).strip().capitalize())))


class CombinedBaselineSPPCost:
    """
    Objective adapter for fair e2e comparison:
    SPP-enabled run optimizes baseline + SPP term together.
    """

    objective_term_name = "total"
    term_names = ("SPP", "baseline")

    def __init__(self, baseline_cost: BaselineDistanceCost, spp_cost):
        self._baseline_cost = baseline_cost
        self._spp_cost = spp_cost
        self.include_diagonal_pair_terms = bool(getattr(spp_cost, "include_diagonal_pair_terms", False))

    def term_components(self, pair, distances):
        baseline = np.asarray(self._baseline_cost(pair, distances), dtype=float)
        spp = np.asarray(self._spp_cost(pair, distances), dtype=float)
        return {"baseline": baseline, "SPP": spp}

    def __call__(self, pair, distances):
        components = self.term_components(pair, distances)
        return components["baseline"] + components["SPP"]

    def pair_cost_matrix(self, pair, positions):
        # Baseline terms remain minimum-image distance costs. Periodic SPP
        # terms bypass this matrix when the wrapped SPP cost exposes
        # pair_cost_matrix.
        distances = positions.get_all_distances(mic=True)
        baseline = np.asarray(self._baseline_cost(pair, distances), dtype=float)
        if hasattr(self._spp_cost, "pair_cost_matrix"):
            spp = np.asarray(self._spp_cost.pair_cost_matrix(pair, positions), dtype=float)
        else:
            spp = np.asarray(self._spp_cost(pair, distances), dtype=float)
        return baseline + spp


def available_task_keys() -> list[str]:
    return available_baseline_task_keys()


def make_task(*, task_key: str = "sto_small", spp_guidance=None, seed: int | None = None):
    task = make_baseline_task(task_key=task_key, seed=seed)
    baseline_cost = task.cost
    if spp_guidance is None:
        return task
    else:
        spp_guidance.ensure_pairs(task.pairs)
        task.cost = CombinedBaselineSPPCost(baseline_cost=baseline_cost, spp_cost=spp_guidance.as_cost())
    return task
