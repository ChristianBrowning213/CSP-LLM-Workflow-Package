# qlip/experimental/guidance/properties/hardness_index.py
from __future__ import annotations
import pyomo.environ as pyo
from qlip.experimental.guidance.properties.base import Property

class HardnessIndex(Property):
    """
    Simple composite: lambda1*C11 + lambda2*density - lambda3*mstar
    You pass in the already-created property expressions via allocation model attributes.
    """
    def __init__(self, lambda_c11=1.0, lambda_rho=1.0, lambda_mstar=1.0):
        self.name = "hardness_index"
        self.lc = float(lambda_c11)
        self.lr = float(lambda_rho)
        self.lm = float(lambda_mstar)

    def expr(self, allocation):
        m = allocation.m
        C11 = getattr(m, "gprop_C11", None)
        rho = getattr(m, "gprop_density", None)
        ms  = getattr(m, "gprop_mstar", None)
        pieces = []
        if C11 is not None: pieces.append(self.lc * C11)
        if rho is not None: pieces.append(self.lr * rho)
        if ms  is not None: pieces.append(-self.lm * ms)
        return pyo.quicksum(pieces) if pieces else 0.0
