# qlip/experimental/guidance/properties/oxygen_vacancy.py
from __future__ import annotations
import pyomo.environ as pyo
from typing import Dict
from qlip.experimental.guidance.properties.base import Property
from qlip.experimental.guidance.properties._io import load_motif_beta

class OxygenVacancyProperty(Property):
    """
    Linear motif score: sum beta_m * M[m,p].
    You must have motif binaries (m.M[m,p]) already declared & linked to X.
    """
    def __init__(self, table_path: str):
        self.name = "VO_robust"
        self.beta: Dict[str, float] = load_motif_beta(table_path)

    def expr(self, allocation):
        m = allocation.m
        M = getattr(m, "M", None)
        if M is None:
            return 0.0
        terms = []
        for idx in M:
            # idx might be motif_id or (motif_id, placement)
            motif_id = idx if not isinstance(idx, tuple) else idx[0]
            b = self.beta.get(str(motif_id))
            if b is not None:
                terms.append(b * M[idx])
        return pyo.quicksum(terms) if terms else 0.0
