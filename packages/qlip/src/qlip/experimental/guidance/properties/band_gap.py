# qlip/experimental/guidance/properties/band_gap.py
from __future__ import annotations
import pyomo.environ as pyo
from typing import Dict, Tuple
from qlip.experimental.guidance.properties.base import Property
from qlip.experimental.guidance.properties._io import load_pair_beta
from qlip.experimental.guidance.properties._y_index import iter_Y_with_shell

class EgProperty(Property):
    def __init__(self, table_path: str):
        self.name = "Eg"
        self.beta: Dict[Tuple[str,str,int], float] = load_pair_beta(table_path)

    def expr(self, allocation):
        terms = []
        for (i,j,t,u,sh), var in iter_Y_with_shell(allocation):
            b = self.beta.get((t,u,sh))
            if b is not None:
                terms.append(b * var)
        return pyo.quicksum(terms) if terms else 0.0
