"""Deterministic held-out target selection and leakage exclusions."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Any

from pymatgen.core import Composition


FREEZE_VERSION = "spp_only_oxide_benchmark.freeze.v1"


def canonical_hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def equivalence_map(groups: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for group in groups:
        keys = {str(key) for key in group.get("candidate_keys") or []}
        for key in keys:
            result[key] = set(keys)
    return result


def _formula(row: dict[str, Any]) -> str:
    return Composition(str(row["formula"])).reduced_composition.alphabetical_formula


def _rank(row: dict[str, Any]) -> tuple[int, float, str]:
    summary = row.get("summary") or {}
    stable_rank = 0 if summary.get("is_stable") is True else 1
    hull = summary.get("energy_above_hull")
    try:
        hull_value = float(hull)
    except (TypeError, ValueError):
        hull_value = float("inf")
    return stable_rank, hull_value, str(row["candidate_key"])


def select_diverse_targets(
    rows: list[dict[str, Any]],
    *,
    count: int,
    equivalent_groups: list[dict[str, Any]],
    excluded_candidate_keys: set[str] | frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    equivalents = equivalence_map(equivalent_groups)
    representatives = {
        key: min(group) for key, group in equivalents.items() if group
    }
    eligible = [
        row
        for row in rows
        if str(row["candidate_key"]) not in excluded_candidate_keys
        and representatives.get(str(row["candidate_key"]), str(row["candidate_key"])) not in excluded_candidate_keys
        and representatives.get(str(row["candidate_key"]), str(row["candidate_key"]))
        == str(row["candidate_key"])
    ]
    by_formula: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        by_formula[_formula(row)].append(row)
    for formula_rows in by_formula.values():
        formula_rows.sort(key=_rank)
    selected: list[dict[str, Any]] = []
    formulas = sorted(by_formula)
    depth = 0
    while len(selected) < count:
        added = False
        for formula in formulas:
            values = by_formula[formula]
            if depth < len(values):
                selected.append(values[depth])
                added = True
                if len(selected) == count:
                    break
        if not added:
            break
        depth += 1
    if len(selected) != count:
        raise ValueError(f"Need {count} non-equivalent targets, found {len(selected)}")
    return selected


def build_target_evidence_pools(
    targets: list[dict[str, Any]],
    accepted_rows: list[dict[str, Any]],
    equivalent_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    equivalents = equivalence_map(equivalent_groups)
    all_keys = {str(row["candidate_key"]) for row in accepted_rows}
    pools = []
    for target in targets:
        target_key = str(target["candidate_key"])
        excluded = equivalents.get(target_key, {target_key}) | {target_key}
        evidence = sorted(all_keys - excluded)
        pools.append(
            {
                "target_key": target_key,
                "excluded_candidate_keys": sorted(excluded),
                "eligible_evidence_candidate_keys": evidence,
                "no_target_leakage": not bool(set(evidence) & excluded),
            }
        )
    return pools


__all__ = [
    "FREEZE_VERSION",
    "build_target_evidence_pools",
    "canonical_hash",
    "equivalence_map",
    "select_diverse_targets",
]
