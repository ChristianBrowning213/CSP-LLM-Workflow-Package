# qlip/experimental/guidance/presets/generic.py
from __future__ import annotations
from qlip.experimental.guidance.modes import GuidanceMode, WeightedTerm, EpsilonBound

def maximize(property_name: str, base: str="energy", weight: float=1.0) -> GuidanceMode:
    return GuidanceMode(
        name=f"maximize_{property_name}",
        base_objective=base,
        weights=[WeightedTerm(name=property_name, weight=-abs(weight))],  # -P => maximize
        epsilons=[]
    )

def minimize(property_name: str, base: str="energy", weight: float=1.0) -> GuidanceMode:
    return GuidanceMode(
        name=f"minimize_{property_name}",
        base_objective=base,
        weights=[WeightedTerm(name=property_name, weight=+abs(weight))],  # +P => minimize
        epsilons=[]
    )

def epsilon_floor(property_name: str, rhs: float, base: str="energy") -> GuidanceMode:
    return GuidanceMode(
        name=f"epsilon_floor_{property_name}_{rhs}",
        base_objective=base,
        weights=[],
        epsilons=[EpsilonBound(name=property_name, sense=">=", rhs=float(rhs))]
    )
