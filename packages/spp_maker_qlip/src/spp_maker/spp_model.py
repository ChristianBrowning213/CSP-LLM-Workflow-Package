"""In-memory loader and lookup utilities for exported SPP POT trees."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple

import numpy as np

from spp_maker.fit_hist import Binning, canonical_pair
from spp_maker.pot_io import read_pot_like_qlip

PairKey = Tuple[str, str]
OobPolicy = Literal["zero", "clamp", "max"]
MissingPairPolicy = Literal["zero", "max_global", "error"]

_VALID_OOB_POLICIES: set[str] = {"zero", "clamp", "max"}
_VALID_MISSING_PAIR_POLICIES: set[str] = {"zero", "max_global", "error"}


@dataclass(frozen=True)
class SPPModel:
    """Loaded SPP penalty model keyed by canonical species pair."""

    root: Path
    binning: Optional[Binning]
    pairs: tuple[PairKey, ...]
    phi: Dict[PairKey, np.ndarray]
    r: Dict[PairKey, np.ndarray]
    global_max_phi: float
    oob_policy: OobPolicy
    missing_pair_policy: MissingPairPolicy

    def _missing_pair_penalty(self, key: PairKey) -> float:
        if self.missing_pair_policy == "zero":
            return 0.0
        if self.missing_pair_policy == "max_global":
            return self.global_max_phi
        raise KeyError(
            f"Missing pair curve for {key[0]}-{key[1]} in SPP root {self.root}. "
            "Use --missing_pair_policy zero/max_global or provide that pair curve."
        )

    def _oob_penalty(self, key: PairKey, d: float) -> float:
        phi_vals = self.phi[key]
        if self.oob_policy == "zero":
            return 0.0
        if self.oob_policy == "max":
            return float(np.max(phi_vals))

        # clamp policy
        if self.binning is not None:
            edges = self.binning.edges
            return float(phi_vals[0] if d < edges[0] else phi_vals[-1])
        r_vals = self.r[key]
        return float(phi_vals[0] if d < r_vals[0] else phi_vals[-1])

    def penalty(self, a: str, b: str, d: float) -> float:
        """
        Return penalty for pair `(a, b)` at distance `d`.

        Behavior:
        - Missing pair follows `missing_pair_policy`
        - Out-of-range follows `oob_policy`
        - In-range uses direct bin lookup (manifest binning) or nearest-r fallback
        """
        if not np.isfinite(d):
            raise ValueError(f"Distance must be finite, got {d}.")

        key = canonical_pair(a, b)
        if key not in self.phi:
            return self._missing_pair_penalty(key)

        if self.binning is not None:
            idx = self.binning.bin_index(float(d))
            if idx < 0:
                return self._oob_penalty(key, float(d))
            return float(self.phi[key][idx])

        r_vals = self.r[key]
        d_float = float(d)
        if d_float < float(r_vals[0]) or d_float > float(r_vals[-1]):
            return self._oob_penalty(key, d_float)
        idx = int(np.argmin(np.abs(r_vals - float(d))))
        return float(self.phi[key][idx])


def _parse_pair_from_dirname(dirname: str) -> PairKey:
    if "-" not in dirname:
        raise ValueError(f"Cannot infer pair key from directory name: {dirname!r}")
    a, b = dirname.split("-", 1)
    if not a or not b:
        raise ValueError(f"Invalid pair directory name: {dirname!r}")
    return canonical_pair(a, b)


def _load_manifest(root: Path) -> tuple[Optional[Binning], dict]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return None, {}

    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    edges_raw = manifest.get("edges")
    if edges_raw is None:
        return None, manifest
    edges = np.asarray(edges_raw, dtype=np.float64)
    return Binning(edges=edges), manifest


def _load_pair_from_file(
    *,
    key: PairKey,
    pot_path: Path,
    binning: Optional[Binning],
) -> tuple[np.ndarray, np.ndarray]:
    if not pot_path.is_file():
        raise ValueError(f"POT file not found for pair {key}: {pot_path}")

    r_vals, u_vals = read_pot_like_qlip(pot_path)
    if r_vals.shape != u_vals.shape:
        raise ValueError(
            f"POT parse shape mismatch for pair {key}: {r_vals.shape} vs {u_vals.shape}."
        )
    if r_vals.ndim != 1:
        raise ValueError(f"POT values for pair {key} must be 1D.")
    if r_vals.size == 0:
        raise ValueError(f"POT file has no numeric rows for pair {key}: {pot_path}")
    if not np.all(np.isfinite(r_vals)) or not np.all(np.isfinite(u_vals)):
        raise ValueError(f"POT file contains non-finite values for pair {key}: {pot_path}")

    if binning is not None and r_vals.size != binning.nbins:
        raise ValueError(
            f"POT row count for pair {key} ({r_vals.size}) does not match "
            f"manifest nbins ({binning.nbins})."
        )

    return r_vals.astype(np.float64, copy=False), u_vals.astype(np.float64, copy=False)


def load_spp_model(
    root: Path,
    *,
    oob_policy: OobPolicy = "max",
    missing_pair_policy: MissingPairPolicy = "max_global",
) -> SPPModel:
    """
    Load an exported SPP root into memory.

    If `manifest.json` exists, it is used for binning and pair path enumeration.
    Otherwise, POT files are discovered recursively under `root`.
    """
    return load_spp_model_with_policies(
        root=root,
        oob_policy=oob_policy,
        missing_pair_policy=missing_pair_policy,
    )


def load_spp_model_with_policies(
    root: Path,
    *,
    oob_policy: OobPolicy = "max",
    missing_pair_policy: MissingPairPolicy = "max_global",
) -> SPPModel:
    """
    Load an exported SPP root into memory with explicit safety policies.

    Defaults are QLIP-safe:
    - out-of-range policy: max
    - missing-pair policy: max_global
    """
    if oob_policy not in _VALID_OOB_POLICIES:
        raise ValueError(
            f"Invalid oob_policy {oob_policy!r}. Expected one of {sorted(_VALID_OOB_POLICIES)}."
        )
    if missing_pair_policy not in _VALID_MISSING_PAIR_POLICIES:
        raise ValueError(
            "Invalid missing_pair_policy "
            f"{missing_pair_policy!r}. Expected one of {sorted(_VALID_MISSING_PAIR_POLICIES)}."
        )

    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"SPP root is not a directory: {root}")

    binning, manifest = _load_manifest(root)
    phi_by_pair: Dict[PairKey, np.ndarray] = {}
    r_by_pair: Dict[PairKey, np.ndarray] = {}

    manifest_pairs = manifest.get("pairs")
    if isinstance(manifest_pairs, list):
        entries = []
        for entry in manifest_pairs:
            if not isinstance(entry, dict):
                raise ValueError("manifest pairs entries must be objects.")
            a = entry.get("A")
            b = entry.get("B")
            rel = entry.get("path")
            if not isinstance(a, str) or not isinstance(b, str) or not isinstance(rel, str):
                raise ValueError("manifest pair entries must include string A, B, and path fields.")
            key = canonical_pair(a, b)
            pot_path = root / Path(rel)
            entries.append((key, pot_path))

        for key, pot_path in entries:
            if key in phi_by_pair:
                raise ValueError(f"Duplicate pair entry in manifest: {key}")
            r_vals, phi_vals = _load_pair_from_file(key=key, pot_path=pot_path, binning=binning)
            r_by_pair[key] = r_vals
            phi_by_pair[key] = phi_vals
    else:
        pot_files = sorted(root.rglob("*.POT"), key=lambda p: str(p.relative_to(root)))
        for pot_path in pot_files:
            key = _parse_pair_from_dirname(pot_path.parent.name)
            if key in phi_by_pair:
                raise ValueError(
                    f"Duplicate POT detected for pair {key}. "
                    f"Use a single canonical file per pair."
                )
            r_vals, phi_vals = _load_pair_from_file(key=key, pot_path=pot_path, binning=binning)
            r_by_pair[key] = r_vals
            phi_by_pair[key] = phi_vals

    ordered_pairs = tuple(sorted(phi_by_pair))
    if ordered_pairs:
        global_max_phi = float(
            max(float(np.max(phi_by_pair[key])) for key in ordered_pairs)
        )
    else:
        global_max_phi = 0.0
    return SPPModel(
        root=root,
        binning=binning,
        pairs=ordered_pairs,
        phi={key: phi_by_pair[key] for key in ordered_pairs},
        r={key: r_by_pair[key] for key in ordered_pairs},
        global_max_phi=global_max_phi,
        oob_policy=oob_policy,
        missing_pair_policy=missing_pair_policy,
    )
