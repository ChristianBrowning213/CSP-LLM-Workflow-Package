"""Explicit, policy-controlled chemistry and charge preflight."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from ase.formula import Formula


CHARGE_POLICIES = {"EXPLICIT_REQUIRED", "EXPLICIT_INFORMATIONAL", "NOT_ENFORCED"}


@dataclass(frozen=True)
class ChargePreflight:
    charge_policy: str
    oxidation_states_used: dict[str, int]
    charge_sum: int | None
    charge_neutral: bool | None
    compensation_operation: str | None
    assumptions_source: str | None
    accepted: bool
    rejection_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def preflight_charge(chemistry: Mapping[str, Any]) -> ChargePreflight:
    formula = str(chemistry.get("formula") or "")
    counts = {str(key): int(value) for key, value in Formula(formula).count().items()}
    policy = str(chemistry.get("charge_policy") or "NOT_ENFORCED").upper()
    if policy not in CHARGE_POLICIES:
        return ChargePreflight(policy, {}, None, None, None, None, False, f"unknown charge policy: {policy}")
    raw_states = chemistry.get("oxidation_states")
    states = {str(key): int(value) for key, value in raw_states.items()} if isinstance(raw_states, Mapping) else {}
    compensation = str(chemistry.get("compensation_operation")) if chemistry.get("compensation_operation") else None
    source = str(chemistry.get("assumptions_source")) if chemistry.get("assumptions_source") else None
    missing = sorted(set(counts) - set(states))
    extra = sorted(set(states) - set(counts))
    if extra:
        return ChargePreflight(policy, states, None, None, compensation, source, False, f"oxidation states supplied for species absent from formula: {extra}")
    if policy == "EXPLICIT_REQUIRED" and missing:
        return ChargePreflight(policy, states, None, None, compensation, source, False, f"explicit oxidation states missing for: {missing}")
    if not states or missing:
        return ChargePreflight(policy, states, None, None, compensation, source, True, None)
    charge_sum = sum(counts[species] * states[species] for species in counts)
    neutral = charge_sum == 0
    if policy == "EXPLICIT_REQUIRED" and not neutral:
        return ChargePreflight(
            policy, states, charge_sum, False, compensation, source, False,
            f"explicit hard charge-neutrality requirement violated: charge_sum={charge_sum}",
        )
    return ChargePreflight(policy, states, charge_sum, neutral, compensation, source, True, None)
