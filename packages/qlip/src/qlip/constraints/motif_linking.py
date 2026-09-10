from __future__ import annotations
from typing import Dict, Iterable, List, Tuple

import numpy as np
from pyomo.core import Constraint, Var
import pyomo.environ as pyo

from qlip.motifs import MotifRecord, MotifInstance

class MotifLinking:
    def __init__(self, motif_name, anchor, instances):
        self.name = motif_name
        self.anchor = anchor
        self.instances = instances

    def attach(self, allocation):
        m = allocation.m
        y = pyo.Var(range(len(self.instances)), domain=pyo.Binary)
        setattr(m, f"y_{self.name}", y)

        m.add_component(f"{self.name}_cons", pyo.ConstraintList())
        cons = getattr(m, f"{self.name}_cons")
        by_site = {}
        for k, (i_anchor, neighs) in enumerate(self.instances):
            cons.add(y[k] <= m.x[self.anchor, i_anchor])
            by_site.setdefault((self.anchor, i_anchor), []).append(k)
            for (s_req, j) in neighs:
                cons.add(y[k] <= m.x[s_req, j])
                by_site.setdefault((s_req, j), []).append(k)

        # Example coverage: for each anchor site, <= 1 motif
        by_anchor = {}
        for k, (i_anchor, _) in enumerate(self.instances):
            by_anchor.setdefault(i_anchor, []).append(k)
        for i, ks in by_anchor.items():
            cons.add(sum(y[k] for k in ks) <= 1)

        for (spec, site), ks in by_site.items():
            if len(ks) > 1:
                cons.add(sum(y[k] for k in ks) <= 1)

        try:
            allocation.motif_vars[self.name] = y
        except AttributeError:
            allocation.motif_vars = {self.name: y}
