# qlip/experimental/guidance/builders.py
from __future__ import annotations
import pyomo.environ as pyo
from typing import Dict
from qlip.experimental.guidance.modes import GuidanceMode

def apply_guidence(allocation, mode: GuidanceMode, props: Dict[str, "Property"]) -> None:
    """
    Attach objective + epsilon side-constraints to allocation.m using the provided properties.
    Props is a dict name->Property (matching names referenced by the mode).
    """
    m = allocation.m

    # Build expressions
    exprs = {}
    for name, prop in props.items():
        exprs[name] = pyo.Expression(expr=prop.expr(allocation))
        # store on model for introspection: m.gprop_<name>
        setattr(m, f"gprop_{name}", exprs[name])

    # Epsilon side-constraints
    for k, eb in enumerate(mode.epsilons, start=1):
        if eb.name not in exprs:
            raise KeyError(f"epsilon references unknown property '{eb.name}'")
        e = exprs[eb.name]
        if eb.sense == ">=":
            con = pyo.Constraint(expr=(e >= eb.rhs))
        elif eb.sense == "<=":
            con = pyo.Constraint(expr=(e <= eb.rhs))
        else:
            raise ValueError(f"bad sense {eb.sense}")
        setattr(m, f"guid_eps_{k}_{eb.name}", con)

    # Objective: base +/- weighted terms
    if mode.base_objective is None:
        # Only side-constraints; do not set objective
        return

    if mode.base_objective not in exprs:
        raise KeyError(f"base_objective '{mode.base_objective}' not provided in props")

    obj_expr = exprs[mode.base_objective]

    # Convention: We *minimize* the total objective.
    # If you want to MAXIMIZE a property P, subtract it (weight > 0 => subtract).
    # If you want to MINIMIZE a property P, add it (weight > 0 => add).
    for term in mode.weights:
        if term.name not in exprs:
            raise KeyError(f"weighted term references unknown property '{term.name}'")
        # Positive weight => interpret as: objective += weight * expr_sign * expr
        # We follow a clear convention in presets; here we just add weight * expr
        obj_expr = obj_expr + term.weight * exprs[term.name]

    # Attach/replace model objective
    # Remove existing objective if present
    if hasattr(m, "guidence_objective"):
        m.del_component(m.guidence_objective)

    m.guidence_objective = pyo.Objective(expr=obj_expr, sense=pyo.minimize)
