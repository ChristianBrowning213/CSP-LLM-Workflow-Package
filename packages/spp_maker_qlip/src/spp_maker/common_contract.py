"""Versioned common numerical contract for local and broad-prior SPP artifacts.

The v1 contract follows the historical Dmytro supercell-g(r) construction:
uniform 0.05 A bins on [0, 10], Gaussian deposition with sigma=0.1 A and
3-sigma truncation, followed by ``U(r) = -log(g(r) + 1e-12)``.  Values are
dimensionless and are never corpus-rescaled or minimum-shifted.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from spp_maker.fit_hist import make_uniform_binning
from spp_maker.io_cif import load_cifs_from_dir
from spp_maker.pot_io import read_pot_like_qlip, write_pot


CONTRACT_ID = "dmytro_gr_v1"
CONTRACT_VERSION = 1
R_MAX = 10.0
BIN_WIDTH = 0.05
SIGMA = 0.1
TRUNCATE_SIGMA = 3.0
SUPERCELL_TARGET_LEN = 20.0
EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class PairBlend:
    pair: str
    mode: str
    local_weight: float
    global_weight: float
    confidence: float
    structures_contributing: int
    observations: int


def contract_metadata() -> dict[str, Any]:
    return {
        "artifact_contract": CONTRACT_ID,
        "artifact_contract_version": CONTRACT_VERSION,
        "quantity": "dimensionless_negative_log_radial_distribution",
        "transform": "U(r)=-ln(g(r)+epsilon)",
        "grid": {"edge_min_A": 0.0, "edge_max_A": R_MAX, "bin_width_A": BIN_WIDTH,
                 "center_min_A": 0.025, "center_max_A": 9.975, "bin_count": 200},
        "gaussian_deposition": {"sigma_A": SIGMA, "truncate_sigma": TRUNCATE_SIGMA},
        "supercell_target_length_A": SUPERCELL_TARGET_LEN,
        "epsilon": EPSILON,
        "minimum_shifted": False,
        "corpus_scalar_applied": False,
        "short_distance_policy": "epsilon_plateau_only; no undocumented extrapolated wall",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _canonical_pair_label(pair: str) -> str:
    parts = [part.strip().title() for part in str(pair).split("-")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"invalid pair label: {pair!r}")
    return "-".join(sorted(parts))


def _pair_file(root: Path, pair: str, suffix: str) -> Path | None:
    wanted = _canonical_pair_label(pair).casefold()
    for directory in root.iterdir() if root.is_dir() else ():
        if directory.is_dir() and directory.name.casefold() == wanted:
            matches = sorted(directory.glob(f"*.{suffix}"))
            return matches[0] if matches else None
    return None


def build_local_supercell_artifact(*, cif_dir: Path, out_root: Path, name: str) -> dict[str, Any]:
    """Build a local artifact with the exact common Dmytro-compatible contract."""
    # This is the canonical implementation already exercised by the CLI; importing
    # it here prevents a second, subtly divergent g(r) implementation.
    from spp_maker.cli import _build_supercell_phi_result
    from spp_maker.export import export_spp_root

    loaded = load_cifs_from_dir(Path(cif_dir))
    if not loaded:
        raise ValueError(f"no CIF files found in {cif_dir}")
    weights = np.ones(len(loaded), dtype=np.float64)
    binning = make_uniform_binning(d_min=0.0, d_max=R_MAX, bin_width=BIN_WIDTH)
    phi, stats = _build_supercell_phi_result(
        loaded=loaded, weights=weights, binning=binning, species_whitelist=None,
        supercell_target_len=SUPERCELL_TARGET_LEN, r_max=R_MAX, sigma=SIGMA,
        truncate_sigma=TRUNCATE_SIGMA, max_pairs=None, eps=EPSILON,
    )
    metadata = contract_metadata() | {
        "name": name, "source_role": "local_request", "source_cif_count": len(loaded),
        "source_cif_files": [str(Path(item.path).resolve()) for item in loaded],
        "build_stats": stats,
        "pair_observations": {
            f"{a}-{b}": int(round(float(np.sum(phi.counts[index]))))
            for index, (a, b) in enumerate(phi.pairs)
        },
    }
    export_spp_root(Path(out_root), phi, name=name, manifest_extra=metadata,
                    oob_recommendation="max", missing_pair_recommendation="error")
    for index, (a, b) in enumerate(phi.pairs):
        pair = f"{a}-{b}"
        pair_metadata = metadata | {
            "pair": pair, "pair_support": {
                "corpus_structures": len(loaded),
                "effective_observations": int(round(float(np.sum(phi.counts[index])))),
            },
            "calibration_version": "none_common_contract_v1",
        }
        _write_json(Path(out_root) / pair / f"{pair}.metadata.json", pair_metadata)
    return metadata | {"pairs": [f"{a}-{b}" for a, b in phi.pairs]}


def rebuild_global_pair_from_rdf(*, regulator_root: Path, pair: str, out_root: Path) -> dict[str, Any]:
    """Convert a documented regulator RDF onto the common grid and transform."""
    rdf_path = _pair_file(Path(regulator_root), pair, "RDF")
    if rdf_path is None:
        raise FileNotFoundError(f"global RDF unavailable for {_canonical_pair_label(pair)}")
    data = np.loadtxt(rdf_path, dtype=np.float64)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(f"invalid RDF payload: {rdf_path}")
    source_r, source_g = data[:, 0], data[:, 1]
    centers = np.arange(BIN_WIDTH / 2.0, R_MAX, BIN_WIDTH, dtype=np.float64)
    if source_r.shape == centers.shape and np.allclose(source_r, centers, atol=1e-8, rtol=0.0):
        g = source_g.copy()
        interpolation = "identity"
    else:
        g = np.interp(centers, source_r, source_g, left=0.0, right=0.0)
        interpolation = "linear_to_contract_centers"
    if not np.all(np.isfinite(g)) or np.any(g < 0.0):
        raise ValueError(f"RDF must be finite and non-negative: {rdf_path}")
    u = -np.log(g + EPSILON)
    label = _canonical_pair_label(pair)
    pot_path = Path(out_root) / label / f"{label}.POT"
    write_pot(pot_path, centers, u, header_lines=[
        f"pair: {label}", f"artifact_contract: {CONTRACT_ID}", "source_role: global_weak_prior",
        f"source_rdf: {rdf_path.resolve()}", f"rdf_grid_conversion: {interpolation}",
        "transform: U(r)=-ln(g(r)+1e-12)", "corpus_scalar_applied: false",
    ])
    metadata = contract_metadata() | {
        "source_role": "global_weak_prior", "pair": label,
        "source_rdf": str(rdf_path.resolve()), "rdf_grid_conversion": interpolation,
        "pot_path": str(pot_path.resolve()),
    }
    _write_json(pot_path.with_suffix(".metadata.json"), metadata)
    return metadata


def pair_confidence(*, structures_contributing: int, observations: int) -> float:
    """Deterministic evidence confidence, fixed independently of benchmark outcomes."""
    if structures_contributing <= 0 or observations <= 0:
        return 0.0
    structure_term = min(1.0, float(structures_contributing) / 20.0)
    observation_term = min(1.0, math.log1p(float(observations)) / math.log1p(20000.0))
    return float(math.sqrt(structure_term * observation_term))


def choose_pair_blend(*, pair: str, local_valid: bool, global_valid: bool,
                      structures_contributing: int, observations: int) -> PairBlend:
    confidence = pair_confidence(structures_contributing=structures_contributing,
                                 observations=observations) if local_valid else 0.0
    if local_valid:
        # The local term is always primary.  The broad prior is bounded to 5--20%.
        global_weight = 0.05 + 0.15 * (1.0 - confidence) if global_valid else 0.0
        mode = "LOCAL_PRIMARY_GLOBAL_WEAK_PRIOR" if global_valid else "LOCAL_ONLY_GLOBAL_UNAVAILABLE"
        return PairBlend(_canonical_pair_label(pair), mode, 1.0, float(global_weight), confidence,
                         int(structures_contributing), int(observations))
    if global_valid:
        return PairBlend(_canonical_pair_label(pair), "GLOBAL_ONLY_LOCAL_ABSENT_OR_INVALID", 0.0, 1.0,
                         0.0, int(structures_contributing), int(observations))
    raise ValueError(f"neither local nor global contract artifact is valid for {pair}")


def _valid_pot(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    r, u = read_pot_like_qlip(path)
    return bool(r.size == 200 and u.size == 200 and np.all(np.isfinite(r)) and
                np.all(np.isfinite(u)) and np.all(np.diff(r) > 0.0))


def blend_contract_roots(*, local_root: Path, regulator_root: Path, out_root: Path,
                         required_pairs: Iterable[str], pair_evidence: dict[str, dict[str, int]],
                         name: str) -> dict[str, Any]:
    """Write a complete pair root using the fixed pair-level blending policy."""
    rows: list[dict[str, Any]] = []
    global_contract_root = Path(out_root).parent / "global_common_contract"
    for raw_pair in required_pairs:
        pair = _canonical_pair_label(raw_pair)
        local_path = _pair_file(Path(local_root), pair, "POT")
        global_path: Path | None = None
        try:
            rebuilt = rebuild_global_pair_from_rdf(regulator_root=Path(regulator_root), pair=pair,
                                                    out_root=global_contract_root)
            global_path = Path(str(rebuilt["pot_path"]))
        except (FileNotFoundError, ValueError):
            global_path = None
        local_valid, global_valid = _valid_pot(local_path), _valid_pot(global_path)
        evidence = pair_evidence.get(pair, pair_evidence.get(raw_pair, {}))
        blend = choose_pair_blend(pair=pair, local_valid=local_valid, global_valid=global_valid,
                                  structures_contributing=int(evidence.get("structures_contributing", 0)),
                                  observations=int(evidence.get("observations", 0)))
        source = local_path if local_valid else global_path
        assert source is not None
        r, local_u = read_pot_like_qlip(source)
        if local_valid and global_valid:
            global_r, global_u = read_pot_like_qlip(global_path)  # type: ignore[arg-type]
            if not np.allclose(r, global_r, atol=1e-8, rtol=0.0):
                raise ValueError(f"contract grids disagree for {pair}")
            final_u = blend.local_weight * local_u + blend.global_weight * global_u
        else:
            final_u = local_u
        destination = Path(out_root) / pair / f"{pair}.POT"
        write_pot(destination, r, final_u, header_lines=[
            f"pair: {pair}", f"artifact_contract: {CONTRACT_ID}", f"blend_mode: {blend.mode}",
            f"local_weight: {blend.local_weight:.12g}", f"global_weight: {blend.global_weight:.12g}",
            "outer_objective_scale_not_applied: true",
        ])
        row = blend.__dict__ if hasattr(blend, "__dict__") else {
            key: getattr(blend, key) for key in blend.__dataclass_fields__
        }
        rows.append(row | {"local_valid": local_valid, "global_valid": global_valid,
                           "output_pot": str(destination.resolve())})
        _write_json(destination.with_suffix(".metadata.json"), contract_metadata() | {
            "pair": pair, "source_role": "pair_level_blended_complete_root",
            "calibration_version": "evidence_blend_v1", "blend": rows[-1],
        })
    manifest = contract_metadata() | {
        "name": name, "source_role": "pair_level_blended_complete_root",
        "blend_policy": {
            "local_weight": 1.0, "global_weight_min": 0.05, "global_weight_max": 0.20,
            "confidence": "sqrt(min(n_structures/20,1)*min(log1p(n_observations)/log1p(20000),1))",
            "global_only_condition": "local artifact absent or invalid",
        },
        "outer_objective_scale_not_applied": True, "pairs": rows,
    }
    _write_json(Path(out_root) / "manifest.json", manifest)
    return manifest
