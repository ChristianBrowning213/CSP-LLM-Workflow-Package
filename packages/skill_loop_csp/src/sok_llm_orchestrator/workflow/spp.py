"""Shared request/regulator SPP compilation and independent decomposition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from qlip.interactions.spp import SPPCollection, canonical_pair_key, periodic_spp_sum


REQUEST_USABLE = "REQUEST_USABLE"
REQUEST_INSUFFICIENT = "REQUEST_INSUFFICIENT_LOCAL_EVIDENCE"
REQUEST_MISSING = "REQUEST_MISSING"
REQUEST_DISABLED = "REQUEST_DISABLED"


def classify_request_pair_quality(required_pairs: Iterable[str], quality: dict[str, Any], missing_pairs: Iterable[str] = ()) -> dict[str, str]:
    by_pair = {str(row["pair"]): row for row in quality.get("pairs", [])}
    missing = {str(pair) for pair in missing_pairs}
    return {
        pair: (
            REQUEST_MISSING if pair in missing or pair not in by_pair
            else REQUEST_USABLE if by_pair[pair].get("pot_quality") == "usable"
            else REQUEST_INSUFFICIENT
        )
        for pair in required_pairs
    }


def guidance_mode_for_pair(request_status: str, regulator_available: bool) -> str:
    if not regulator_available:
        raise ValueError("GUIDANCE_PAIR_UNSUPPORTED")
    if request_status == REQUEST_USABLE:
        return "REQUEST_PLUS_REGULATOR"
    if request_status == REQUEST_MISSING:
        return "REGULATOR_ONLY_LOCAL_MISSING"
    if request_status == REQUEST_DISABLED:
        return "REGULATOR_ONLY_REQUEST_DISABLED"
    return "REGULATOR_ONLY_LOCAL_INSUFFICIENT"


def request_support_status(statuses: Iterable[str]) -> str:
    values = list(statuses)
    supported = sum(value == REQUEST_USABLE for value in values)
    if supported == len(values):
        return "FULL_LOCAL_SUPPORT"
    if supported == 0:
        return "NO_LOCAL_SUPPORT_REGULATOR_ONLY"
    return "PARTIAL_LOCAL_SUPPORT_WITH_REGULATOR_FALLBACK"


@dataclass(frozen=True, slots=True)
class SPPObjectiveComponents:
    request_spp_score: float
    regulator_spp_score: float
    regulator_weight: float
    request_guidance_weight: float
    combined_spp_score: float
    solver_objective: float
    pair_components: tuple[dict[str, Any], ...] = ()
    request_supported_pair_score_total: float = 0.0
    regulator_score_total: float = 0.0
    number_required_pairs: int = 0
    number_request_supported_pairs: int = 0
    number_regulator_fallback_pairs: int = 0
    number_unsupported_pairs: int = 0


def score_collection_by_pair(
    collection: SPPCollection | None,
    *,
    symbols: Sequence[str],
    positions: np.ndarray,
    cell: np.ndarray,
    pairs: Iterable[tuple[str, str]],
    pbc: bool = True,
) -> dict[str, float]:
    """Score exact periodic pair contributions without cross-pair leakage."""
    if collection is None:
        return {"-".join(sorted(pair, key=str.lower)): 0.0 for pair in pairs}
    matrix = np.asarray(cell, dtype=float)
    frac = np.asarray(positions, dtype=float) @ np.linalg.inv(matrix)
    result: dict[str, float] = {}
    for left, right in pairs:
        key = canonical_pair_key(left, right)
        spp = collection.spps.get(key)
        total = 0.0
        if spp is not None:
            for i, symbol_i in enumerate(symbols):
                if canonical_pair_key(symbol_i, symbol_i) == key and left.lower() == right.lower():
                    total += periodic_spp_sum(frac[i], frac[i], matrix, spp, cutoff=collection.cutoff) if pbc else 0.0
            for i in range(len(symbols)):
                for j in range(i + 1, len(symbols)):
                    if canonical_pair_key(symbols[i], symbols[j]) != key:
                        continue
                    if pbc:
                        total += periodic_spp_sum(frac[i], frac[j], matrix, spp, cutoff=collection.cutoff)
                    else:
                        distance = float(np.linalg.norm(np.asarray(positions[j]) - np.asarray(positions[i])))
                        if 0.0 < distance <= collection.cutoff:
                            total += float(spp(distance))
        result["-".join(sorted((left, right), key=str.lower))] = float(total)
    return result


def compile_spp_components(
    *,
    request_pot_root: Path,
    regulator_pot_root: Path,
    pairs: Iterable[tuple[str, str]],
    cutoff: float = 11.0,
    regulator_weight: float = 2.0,
    allow_request_fallback: bool = False,
) -> tuple[SPPCollection, SPPCollection, SPPCollection]:
    """Load request-only, regulator-only, and solver-combined collections."""
    canonical_pairs = list(pairs)
    request_policy = "fallback" if allow_request_fallback else "block"
    request = SPPCollection(request_pot_root, cutoff=cutoff, missing_pair_policy=request_policy)
    request.load(canonical_pairs)
    regulator = SPPCollection(regulator_pot_root, cutoff=cutoff, missing_pair_policy="block")
    regulator.load(canonical_pairs)
    combined = SPPCollection(
        request_pot_root,
        cutoff=cutoff,
        missing_pair_policy=request_policy,
        regularisation_spp_dir=regulator_pot_root,
        regularisation_weight=regulator_weight,
    )
    combined.load(canonical_pairs)
    return request, regulator, combined


def score_spp_components(
    *,
    symbols: Sequence[str],
    positions: np.ndarray,
    cell: np.ndarray,
    request: SPPCollection | None,
    regulator: SPPCollection | None,
    regulator_weight: float = 2.0,
    request_guidance_weight: float = 10.0,
    pbc: bool = True,
    pairs: Iterable[tuple[str, str]] | None = None,
    request_pair_statuses: dict[str, str] | None = None,
) -> SPPObjectiveComponents:
    """Recompute the exact deployed QLIP weighting convention explicitly."""
    request_score = (
        float(request.score(symbols, positions, cell, pbc=pbc))
        if request is not None
        else 0.0
    )
    regulator_score = (
        float(regulator.score(symbols, positions, cell, pbc=pbc))
        if regulator is not None
        else 0.0
    )
    combined = request_score + float(regulator_weight) * regulator_score
    pair_rows: list[dict[str, Any]] = []
    pair_list = list(pairs or [])
    if pair_list:
        request_by_pair = score_collection_by_pair(request, symbols=symbols, positions=positions, cell=cell, pairs=pair_list, pbc=pbc)
        regulator_by_pair = score_collection_by_pair(regulator, symbols=symbols, positions=positions, cell=cell, pairs=pair_list, pbc=pbc)
        for pair in pair_list:
            name = "-".join(sorted(pair, key=str.lower))
            status = (request_pair_statuses or {}).get(name, "REQUEST_USABLE" if request_by_pair[name] != 0.0 else "REQUEST_MISSING")
            mode = "REQUEST_PLUS_REGULATOR" if status == "REQUEST_USABLE" else (
                "REGULATOR_ONLY_REQUEST_DISABLED" if status == REQUEST_DISABLED else
                "REGULATOR_ONLY_LOCAL_MISSING" if status == "REQUEST_MISSING" else "REGULATOR_ONLY_LOCAL_INSUFFICIENT"
            )
            request_value = request_by_pair[name] if status == "REQUEST_USABLE" else 0.0
            regulator_value = regulator_by_pair[name]
            pair_rows.append({
                "species_pair": name,
                "request_pair_status": status,
                "request_pair_score": float(request_value),
                "regulator_pair_available": True,
                "regulator_pair_score": float(regulator_value),
                "guidance_mode": mode,
                "combined_pair_score": float(request_guidance_weight) * (float(request_value) + float(regulator_weight) * float(regulator_value)),
            })
    return SPPObjectiveComponents(
        request_spp_score=request_score,
        regulator_spp_score=regulator_score,
        regulator_weight=float(regulator_weight),
        request_guidance_weight=float(request_guidance_weight),
        combined_spp_score=combined,
        solver_objective=float(request_guidance_weight) * combined,
        pair_components=tuple(pair_rows),
        request_supported_pair_score_total=sum(float(row["request_pair_score"]) for row in pair_rows),
        regulator_score_total=sum(float(row["regulator_pair_score"]) for row in pair_rows),
        number_required_pairs=len(pair_rows),
        number_request_supported_pairs=sum(row["request_pair_status"] == "REQUEST_USABLE" for row in pair_rows),
        number_regulator_fallback_pairs=sum(row["guidance_mode"].startswith("REGULATOR_ONLY") for row in pair_rows),
        number_unsupported_pairs=sum(not row["regulator_pair_available"] for row in pair_rows),
    )
