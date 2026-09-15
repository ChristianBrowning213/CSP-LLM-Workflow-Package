# qlip/experimental/guidance/presets/sto.py
from __future__ import annotations
from qlip.experimental.guidance.modes import GuidanceMode, WeightedTerm, EpsilonBound

def dielectric_mode(kappa_min: float) -> GuidanceMode:
    # Minimize energy subject to kappa >= floor
    return GuidanceMode(
        name=f"sto_dielectric_floor_{kappa_min}",
        base_objective="energy",
        weights=[],  # no extra penalties
        epsilons=[EpsilonBound(name="kappa", sense=">=", rhs=float(kappa_min))]
    )

def transparent_conductor_mode(eg_min: float, mass_weight: float=0.5) -> GuidanceMode:
    # Minimize [energy - Eg + (mass_weight * m*)]
    # Implemented as energy + (-1.0)*Eg + (mass_weight)*mstar
    return GuidanceMode(
        name=f"sto_tc_eg{eg_min}_mw{mass_weight}",
        base_objective="energy",
        weights=[
            WeightedTerm(name="Eg",    weight=-1.0),
            WeightedTerm(name="mstar", weight= float(mass_weight)),
        ],
        epsilons=[EpsilonBound(name="Eg", sense=">=", rhs=float(eg_min))]
    )

def memristor_mode(vo_floor: float, c11_floor: float) -> GuidanceMode:
    # Minimize energy, with floors on VO_robust and C11
    return GuidanceMode(
        name=f"sto_memristor_vo{vo_floor}_c11{c11_floor}",
        base_objective="energy",
        weights=[],
        epsilons=[
            EpsilonBound(name="VO_robust", sense=">=", rhs=float(vo_floor)),
            EpsilonBound(name="C11",       sense=">=", rhs=float(c11_floor)),
        ]
    )
