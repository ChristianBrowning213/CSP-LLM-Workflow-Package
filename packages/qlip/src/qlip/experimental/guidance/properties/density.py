# qlip/experimental/guidance/properties/density.py
from __future__ import annotations
import json, pathlib
import pyomo.environ as pyo
from qlip.experimental.guidance.properties.base import Property

class DensityProperty(Property):
    def __init__(self, per_type_volume_path: str, cell_path: str):
        self.name = "density"
        with open(per_type_volume_path, "r", encoding="utf-8") as f:
            self.vt = json.load(f)  # {"Sr": float, "Ti": float, "O": float}
        with open(cell_path, "r", encoding="utf-8") as f:
            c = json.load(f)
            self.V_cell = float(c.get("V_cell", c.get("volume", 1.0)))

    def expr(self, allocation):
        m = allocation.m
        terms = []
        X = getattr(m, "X", None)
        if X is None:
            return 0.0
        # X[i,t] binary; sum v_t * X[i,t] / V_cell
        for (i,t) in X:
            v = self.vt.get(str(t))
            if v is not None:
                terms.append(v * X[i,t])
        return (1.0/self.V_cell) * pyo.quicksum(terms) if terms else 0.0
