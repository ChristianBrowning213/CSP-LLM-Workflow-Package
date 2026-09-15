# qlip/experimental/guidance/modes.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Literal

@dataclass
class WeightedTerm:
    name: str
    weight: float  # positive to maximize, negative to minimize if objective = base + sum(w*prop)
    # Convention we’ll use in builders: objective = base_energy - sum(maximize_props) + sum(minimize_props)
    # In presets we’ll set signs for you.

@dataclass
class EpsilonBound:
    name: str
    sense: Literal[">=", "<="]  # floor or ceiling
    rhs: float

@dataclass
class GuidanceMode:
    # Name for logging
    name: str
    # Which property provides the "base" objective (usually energy). If None, we add only side-constraints.
    base_objective: str | None = "energy"
    # Weighted combination terms (added to objective with signs chosen by presets)
    weights: List[WeightedTerm] = field(default_factory=list)
    # Epsilon constraints applied as side constraints
    epsilons: List[EpsilonBound] = field(default_factory=list)
    # Lexicographic not implemented here to keep this lightweight; add later if needed
