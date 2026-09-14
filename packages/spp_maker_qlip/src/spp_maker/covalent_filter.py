"""Covalent-like short-contact exclusion rules."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, Tuple

import numpy as np
from ase import Atoms

from spp_maker.fit_hist import canonical_pair
from spp_maker.neighbors import pairwise_mic_distances

PairKey = Tuple[str, str]


@dataclass(frozen=True)
class CovalentRule:
    """One forbidden pair with minimum allowed separation (Angstrom)."""

    elem1: str
    elem2: str
    min_dist: float
    source_id: str

    @property
    def pair(self) -> PairKey:
        return canonical_pair(self.elem1, self.elem2)


def _normalize_rule_entry(entry: dict, *, source: str) -> CovalentRule:
    elem1 = str(entry.get("elem1", "")).strip()
    elem2 = str(entry.get("elem2", "")).strip()
    if not elem1 or not elem2:
        raise ValueError(f"{source}: rule must include non-empty elem1/elem2.")

    try:
        min_dist = float(entry.get("min_dist"))
    except Exception as exc:
        raise ValueError(f"{source}: rule min_dist must be numeric.") from exc

    if not np.isfinite(min_dist) or min_dist <= 0.0:
        raise ValueError(f"{source}: rule min_dist must be finite and > 0, got {min_dist}.")

    return CovalentRule(elem1=elem1, elem2=elem2, min_dist=min_dist, source_id=source)


def _load_rules_csv(path: Path) -> list[CovalentRule]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"elem1", "elem2", "min_dist"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError(
                f"CSV must include columns {sorted(required)}, got {reader.fieldnames}."
            )
        rules = [
            _normalize_rule_entry(row, source=f"{path}:{idx + 2}")
            for idx, row in enumerate(reader)
        ]
    return sorted(rules, key=lambda rule: (rule.pair, rule.min_dist, rule.elem1, rule.elem2))


def _load_rules_yaml(path: Path) -> list[CovalentRule]:
    try:
        import yaml
    except Exception as exc:  # pragma: no cover - import failure environment-dependent
        raise ValueError("YAML rules require PyYAML to be installed.") from exc

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)

    if isinstance(payload, dict) and "rules" in payload:
        payload = payload["rules"]
    if not isinstance(payload, list):
        raise ValueError("YAML rules must be a list of {elem1, elem2, min_dist} entries.")

    rules: list[CovalentRule] = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{idx + 1}: each YAML rule must be a mapping.")
        rules.append(_normalize_rule_entry(item, source=f"{path}:{idx + 1}"))
    return sorted(rules, key=lambda rule: (rule.pair, rule.min_dist, rule.elem1, rule.elem2))


def load_covalent_rules(path: str | Path) -> list[CovalentRule]:
    """Load covalent-like exclusion rules from `.csv`, `.yaml`, or `.yml`."""
    path_obj = Path(path)
    if not path_obj.is_file():
        raise ValueError(f"Rules path is not a file: {path_obj}")

    suffix = path_obj.suffix.lower()
    if suffix == ".csv":
        return _load_rules_csv(path_obj)
    if suffix in {".yaml", ".yml"}:
        return _load_rules_yaml(path_obj)
    raise ValueError(
        f"Unsupported rules format for {path_obj}. Use .csv, .yaml, or .yml."
    )


def _threshold_by_pair(rules: Sequence[CovalentRule]) -> dict[PairKey, float]:
    lookup: dict[PairKey, float] = {}
    for rule in rules:
        key = rule.pair
        previous = lookup.get(key)
        if previous is None or rule.min_dist > previous:
            lookup[key] = float(rule.min_dist)
    return lookup


def has_covalent_like_contact(
    atoms: Atoms,
    rules: Iterable[CovalentRule],
    r_check_max: float = 2.2,
) -> tuple[bool, dict]:
    """
    Return whether any listed pair has MIC distance below its forbidden threshold.

    On hit, info includes:
    - pair_key
    - threshold
    - observed_min_distance
    - atom_indices
    - matched_rule (with source entry id)
    """
    r_check_max = float(r_check_max)
    if not np.isfinite(r_check_max) or r_check_max <= 0.0:
        raise ValueError(f"r_check_max must be finite and > 0, got {r_check_max}.")

    rules_list = list(rules)
    if not rules_list:
        return False, {}
    threshold_lookup = _threshold_by_pair(rules_list)
    rules_by_pair: dict[PairKey, list[CovalentRule]] = {}
    for rule in sorted(
        rules_list,
        key=lambda item: (item.pair, item.min_dist, item.elem1, item.elem2, item.source_id),
    ):
        rules_by_pair.setdefault(rule.pair, []).append(rule)

    symbols = tuple(atoms.get_chemical_symbols())
    distances = np.asarray(pairwise_mic_distances(atoms), dtype=np.float64)
    n_atoms = len(symbols)

    best_info: dict | None = None
    best_margin = -np.inf
    for i in range(n_atoms):
        for j in range(i + 1, n_atoms):
            d = float(distances[i, j])
            if d <= 0.0 or d > r_check_max:
                continue
            key = canonical_pair(symbols[i], symbols[j])
            threshold = threshold_lookup.get(key)
            if threshold is None or d >= threshold:
                continue

            matching_rules = [
                rule for rule in rules_by_pair.get(key, []) if d < float(rule.min_dist)
            ]
            if not matching_rules:
                continue
            chosen_rule = sorted(
                matching_rules,
                key=lambda item: (
                    -(float(item.min_dist) - d),
                    item.min_dist,
                    item.source_id,
                ),
            )[0]
            margin = float(chosen_rule.min_dist) - d

            candidate = {
                "pair_key": f"{key[0]}-{key[1]}",
                "threshold": float(chosen_rule.min_dist),
                "observed_min_distance": d,
                "atom_indices": [int(i), int(j)],
                "matched_rule": {
                    "elem1": chosen_rule.elem1,
                    "elem2": chosen_rule.elem2,
                    "min_dist": float(chosen_rule.min_dist),
                    "source_id": chosen_rule.source_id,
                },
            }
            if (
                best_info is None
                or margin > best_margin
                or (
                    np.isclose(margin, best_margin, rtol=0.0, atol=1e-15)
                    and (
                        str(candidate["pair_key"]),
                        candidate["atom_indices"][0],
                        candidate["atom_indices"][1],
                    )
                    < (
                        str(best_info["pair_key"]),
                        best_info["atom_indices"][0],
                        best_info["atom_indices"][1],
                    )
                )
            ):
                best_margin = margin
                best_info = candidate

    if best_info is None:
        return False, {}
    return True, best_info
