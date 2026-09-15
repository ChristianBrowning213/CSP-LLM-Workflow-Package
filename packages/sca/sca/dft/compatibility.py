"""Strict compatibility checks for energies used in formation/hull analysis."""

from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from sca.dft.schema import CompatibilityStatus, DFTCompatibilityFingerprint


class CompatibilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    status: CompatibilityStatus
    reasons: list[str] = Field(default_factory=list)


_FIELDS = (
    "engine_family",
    "energy_convention",
    "xc_functional",
    "pseudopotential_family",
    "hubbard_u",
    "dispersion",
    "correction_scheme",
)
_REQUIRED_FIELDS = {"engine_family", "energy_convention", "xc_functional", "pseudopotential_family"}


def compare_fingerprints(
    candidate: DFTCompatibilityFingerprint,
    reference: DFTCompatibilityFingerprint,
) -> CompatibilityResult:
    unknown: list[str] = []
    mismatches: list[str] = []
    for field in _FIELDS:
        left = getattr(candidate, field)
        right = getattr(reference, field)
        if left == right:
            if left is None and field in _REQUIRED_FIELDS:
                unknown.append(f"{field} is unspecified")
            continue
        mismatches.append(f"{field} mismatch: candidate={left!r}, reference={right!r}")
    if mismatches:
        return CompatibilityResult(status=CompatibilityStatus.INCOMPATIBLE, reasons=mismatches)
    if unknown:
        return CompatibilityResult(status=CompatibilityStatus.UNKNOWN, reasons=unknown)
    return CompatibilityResult(status=CompatibilityStatus.COMPATIBLE)


def compare_energy_set(
    candidate: DFTCompatibilityFingerprint,
    references: Iterable[DFTCompatibilityFingerprint],
) -> CompatibilityResult:
    reasons: list[str] = []
    saw_unknown = False
    for index, reference in enumerate(references):
        result = compare_fingerprints(candidate, reference)
        reasons.extend(f"reference[{index}]: {reason}" for reason in result.reasons)
        if result.status == CompatibilityStatus.INCOMPATIBLE:
            return CompatibilityResult(status=CompatibilityStatus.INCOMPATIBLE, reasons=reasons)
        saw_unknown = saw_unknown or result.status == CompatibilityStatus.UNKNOWN
    if saw_unknown:
        return CompatibilityResult(status=CompatibilityStatus.UNKNOWN, reasons=reasons)
    return CompatibilityResult(status=CompatibilityStatus.COMPATIBLE)
