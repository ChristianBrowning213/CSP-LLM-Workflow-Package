#!/usr/bin/env python3
from __future__ import annotations

import itertools
import json
import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    from pymatgen.core import Structure
    from pymatgen.analysis.local_env import CrystalNN
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    HAVE_PMG = True
except Exception:
    HAVE_PMG = False


# ---------------------------------------------------------------------------
# Tunables
MAX_DEN = 24          # cap for rationalisation denominators (keeps grids sane)
MIN_A = 0.5           # Angstrom; smallest motif cell edge allowed for CIF export
HASH_N = 10           # number of hex digits to retain from hashes (file names)


@dataclass(frozen=True)
class MotifTemplate:
    name: str
    anchor: str
    geom: str
    footprint_size: int
    fingerprint: str
    neighbors: List[Tuple[str, List[float]]]                 # canonical fractional offsets (wrapped)
    local_grid_m: int                                        # minimal local grid after clamp
    local_offsets_ijk: List[Tuple[str, Tuple[int, int, int]]]
    species_key: str
    notes: str = ""


@dataclass(frozen=True)
class MotifInstance:
    anchor_index: int
    neighbors: List[Tuple[str, int]]


def _wrap_min(v: np.ndarray) -> np.ndarray:
    """Wrap a vector into (-0.5, 0.5] while preserving the sign of exact half-steps."""
    wrapped = (v + 0.5) % 1.0 - 0.5
    near_neg_half = np.isclose(wrapped, -0.5, atol=1e-8)
    wrapped = np.where(near_neg_half & (v > 0), 0.5, wrapped)
    near_pos_half = np.isclose(wrapped, 0.5, atol=1e-8)
    wrapped = np.where(near_pos_half & (v < 0), -0.5, wrapped)
    return wrapped.astype(float)


def _cube_rotations() -> List[np.ndarray]:
    """Generate the 24 proper rotations of the cube."""
    mats: List[np.ndarray] = []
    basis = np.eye(3)
    for perm in itertools.permutations(range(3)):
        permuted = basis[:, perm]
        for signs in itertools.product((-1, 1), repeat=3):
            R = permuted * np.array(signs, dtype=float)
            if np.isclose(np.linalg.det(R), 1.0, atol=1e-8):
                mats.append(R.astype(float))
    # Deduplicate any accidental repeats (e.g. due to permutations with repeated axes)
    unique: Dict[str, np.ndarray] = {}
    for R in mats:
        key = json.dumps(R.round(6).tolist())
        unique[key] = R
    return list(unique.values())


_ROT24 = _cube_rotations()


def _species_multiset_key(anchor: str, neigh_species: Iterable[str]) -> str:
    counts = Counter(neigh_species)
    parts = [f"{el}{counts[el]}" for el in sorted(counts)]
    return f"{anchor}-" + "".join(parts)


def _canon_neighbors(rel_disp: List[Tuple[str, np.ndarray]]) -> List[Tuple[str, List[float]]]:
    """Rotation-canonical (species-aware) ordering of wrapped displacements."""
    if not rel_disp:
        return []
    species = [s for s, _ in rel_disp]
    P = np.stack([_wrap_min(np.array(p, dtype=float)) for _, p in rel_disp], axis=0)
    best_sig: Optional[str] = None
    best_rows: Optional[List[Tuple[str, List[float]]]] = None
    for R in _ROT24:
        rotated = _wrap_min(P @ R.T)
        rows = []
        for idx, sp in enumerate(species):
            xyz = rotated[idx].tolist()
            rows.append((sp, [round(v, 6) for v in xyz]))
        rows.sort(key=lambda x: (x[0], x[1][0], x[1][1], x[1][2]))
        sig = json.dumps(rows, sort_keys=True)
        if best_sig is None or sig < best_sig:
            best_sig = sig
            best_rows = rows
    return best_rows or []


def _lcm(a: int, b: int) -> int:
    return abs(a * b) // math.gcd(a, b) if a and b else max(a, b)


def _minimal_grid_m(canon_rows: List[Tuple[str, List[float]]], max_den: int = MAX_DEN) -> int:
    """Smallest m such that all components are multiples of 1/m under rational clamp."""
    m = 1
    for _, xyz in canon_rows:
        for v in xyz:
            frac = Fraction(str(v)).limit_denominator(max_den)
            m = _lcm(m, frac.denominator)
    return max(1, m)


def _ijk_on_m_grid(canon_rows: List[Tuple[str, List[float]]], m: int) -> List[Tuple[str, Tuple[int, int, int]]]:
    """Map fractional displacements to centred integer offsets on Z_m^3."""
    ijk: List[Tuple[str, Tuple[int, int, int]]] = []
    for species, xyz in canon_rows:
        wrapped = _wrap_min(np.array(xyz, dtype=float))
        di, dj, dk = (int(round(coord * m)) for coord in wrapped)
        ijk.append((species, (di, dj, dk)))
    ijk.sort(key=lambda x: (x[0], x[1][0], x[1][1], x[1][2]))
    return ijk


def _tmpl_fingerprint(anchor: str, ijk_m: List[Tuple[str, Tuple[int, int, int]]], m: int) -> str:
    """Hash anchor + integer offsets + grid size (the geometry-in-use)."""
    payload = {"anchor": anchor, "m": m, "ijk": ijk_m}
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:HASH_N]


def _idx_to_frac(idx: int, g: int) -> np.ndarray:
    i = idx % g
    j = (idx // g) % g
    k = idx // (g * g)
    return np.array([i / g, j / g, k / g], dtype=float)


def _fetch_mp_structures(formula: str, mp_api_key: Optional[str], mp_max: int) -> List["Structure"]:
    structs: List["Structure"] = []
    if not mp_api_key:
        print("[miner] MP requested but no API key was supplied.")
        return structs

    # Try the v2 client first.
    try:
        from mp_api.client import MPRester as MP2  # type: ignore

        with MP2(mp_api_key) as mpr:
            docs = mpr.summary.search(formula=formula, fields=["structure"], chunk_size=mp_max)
            for doc in docs[:max(0, mp_max)]:
                struct = getattr(doc, "structure", None)
                if struct is not None:
                    structs.append(struct)
    except Exception as exc:  # pragma: no cover - MP client optional
        print(f"[miner] mp-api client failed: {exc}")

    if structs:
        return structs[:mp_max]

    # Fall back to the legacy pymatgen client.
    try:
        from pymatgen.ext.matproj import MPRester  # type: ignore

        with MPRester(mp_api_key) as mpr:
            query = mpr.query(
                criteria={"pretty_formula": formula},
                properties=["structure"],
                chunk_size=mp_max,
            )
            for entry in query[:max(0, mp_max)]:
                struct = entry.get("structure")
                if struct is not None:
                    structs.append(struct)
    except Exception as exc:  # pragma: no cover - legacy client optional
        print(f"[miner] legacy MPRester failed: {exc}")

    return structs[:mp_max]


def _read_local_structures(cif_paths: Sequence[str]) -> List["Structure"]:
    structs: List["Structure"] = []
    for raw in cif_paths:
        path = Path(raw)
        if not path.exists():
            print(f"[miner] local CIF not found: {raw}")
            continue
        try:
            struct = Structure.from_file(str(path))
            structs.append(struct)
        except Exception as exc:
            print(f"[miner] failed to read {raw}: {exc}")
    return structs


def _standardize_and_scale(struct: "Structure", target_volume: Optional[float]) -> "Structure":
    if not HAVE_PMG:
        raise RuntimeError("pymatgen is required to standardise structures.")
    try:
        std = SpacegroupAnalyzer(struct, symprec=1e-3).get_conventional_standard_structure()
    except Exception:
        std = struct.copy()
    if target_volume and target_volume > 1e-8:
        scale = (target_volume / std.volume) ** (1.0 / 3.0)
        if math.isfinite(scale) and scale > 0:
            return std.scale_lattice(std.volume * (scale**3))
    return std


def _detect_crystalnn(struct: "Structure") -> List[Tuple[str, np.ndarray, List[Tuple[str, np.ndarray]]]]:
    """Return (anchor species, anchor frac, neighbours as absolute frac coords)."""
    detector = CrystalNN()
    hits: List[Tuple[str, np.ndarray, List[Tuple[str, np.ndarray]]]] = []
    for index, site in enumerate(struct.sites):
        anchor_species = str(site.specie)
        anchor_frac = struct.lattice.get_fractional_coords(site.coords) % 1.0
        neighbours: List[Tuple[str, np.ndarray]] = []
        try:
            nn_info = detector.get_nn_info(struct, index)
        except Exception:
            continue
        for nn in nn_info:
            neigh_site = nn.get("site")
            if neigh_site is None:
                continue
            species = str(neigh_site.specie)
            frac = np.array(neigh_site.frac_coords, dtype=float)
            image = nn.get("image")
            if image is not None:
                frac = frac + np.array(image, dtype=float)
            neighbours.append((species, frac))
        if neighbours:
            hits.append((anchor_species, anchor_frac, neighbours))
    return hits


def mine(
    formula: str,
    grid_g: int,
    a: float,
    out_dir: str | Path,
    *,
    source: str = "mp",
    mp_api_key: Optional[str] = None,
    mp_max: int = 20,
    local_cifs: Optional[Sequence[str]] = None,
    snap_tol_frac: float = 0.08,
    emit_cifs: bool = False,
    emit_instances_limit: Optional[int] = None,
) -> Tuple[List[MotifTemplate], Dict[str, List[MotifInstance]], Dict[str, object]]:
    """
    Mine motif templates and grid instances.

    Returns (templates, instances_by_template_name, metadata).
    """
    if not HAVE_PMG:
        raise RuntimeError("pymatgen is not available; motif mining requires it.")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    src = (source or "").lower()
    target_volume = a**3 if a else None

    structs: List[Structure] = []
    if "mp" in src:
        mp_structs = _fetch_mp_structures(formula, mp_api_key, mp_max)
        if mp_structs:
            structs.extend(_standardize_and_scale(s, target_volume) for s in mp_structs)
        print(f"[miner] MP structures: {len(mp_structs)}")

    if "local" in src:
        local_structs = _read_local_structures(local_cifs or [])
        if local_structs:
            structs.extend(_standardize_and_scale(s, target_volume) for s in local_structs)
        print(f"[miner] local structures: {len(local_structs)}")
    elif local_cifs:
        print("[miner] local CIFs were provided but source does not include 'local'; they were ignored.")

    if not structs:
        meta = {
            "chem": formula,
            "grid": grid_g,
            "a": a,
            "source": source,
            "counts": {},
            "note": "no input structures",
        }
        _dump(out_path / "motifs.json", {"_meta": meta, "motifs": []})
        _dump(out_path / "instances.json", {"_meta": meta, "instances": {}})
        print("[miner] no structures available; wrote empty artifacts.")
        return [], {}, meta

    detections: List[Tuple[str, np.ndarray, List[Tuple[str, np.ndarray]]]] = []
    for idx, struct in enumerate(structs):
        hits = _detect_crystalnn(struct)
        detections.extend(hits)
        print(f"[miner] structure {idx} -> {len(hits)} CrystalNN motifs.")
    print(f"[miner] CrystalNN detections: {len(detections)} motifs (pre-dedup).")

    template_payloads: Dict[str, Dict[str, object]] = {}
    for anchor_species, anchor_frac, neighbours_abs in detections:
        rel = [
            (species, np.array(frac, dtype=float) - np.array(anchor_frac, dtype=float))
            for species, frac in neighbours_abs
        ]
        canon_rows = _canon_neighbors(rel)
        m_eff = _minimal_grid_m(canon_rows, max_den=MAX_DEN)
        ijk_m = _ijk_on_m_grid(canon_rows, m_eff)
        fp = _tmpl_fingerprint(anchor_species, ijk_m, m_eff)
        if fp in template_payloads:
            continue
        cn = len(canon_rows)
        template_payloads[fp] = {
            "anchor": anchor_species,
            "geom": f"CN{cn}",
            "footprint_size": 1 + cn,
            "neighbors": canon_rows,
            "local_grid_m": m_eff,
            "local_offsets_ijk": ijk_m,
            "species_key": _species_multiset_key(anchor_species, [s for s, _ in canon_rows]),
            "notes": "rotation canonical; denominators clamped; MILP-ready offsets",
        }

    def _base_template_name(anchor: str, neighbours: List[Tuple[str, List[float]]], m_value: int) -> str:
        counts = Counter(sp for sp, _ in neighbours)
        species_part = "".join(f"{el}{counts[el]}" for el in sorted(counts))
        return f"{anchor}_{species_part}_m{m_value}"

    templates: List[MotifTemplate] = []
    base_counts: Dict[str, int] = defaultdict(int)
    seen_integer_payloads: Dict[Tuple[Tuple[str, Tuple[int, int, int]], ...], str] = {}

    # Sort deterministically by anchor, coordination, grid, then fingerprint for stability.
    def _payload_sort_key(item: Tuple[str, Dict[str, object]]) -> Tuple:
        fp, payload = item
        return (
            payload["anchor"],
            payload["geom"],
            payload["local_grid_m"],
            fp,
        )

    for fp, payload in sorted(template_payloads.items(), key=_payload_sort_key):
        neighbours = payload["neighbors"]  # type: ignore[assignment]
        local_offsets = payload["local_offsets_ijk"]  # type: ignore[assignment]
        anchor = payload["anchor"]  # type: ignore[assignment]
        m_eff = payload["local_grid_m"]  # type: ignore[assignment]

        integer_key = tuple(local_offsets)  # type: ignore[arg-type]
        if integer_key in seen_integer_payloads:
            raise RuntimeError(
                f"duplicate motif payload detected for fingerprint {fp} "
                f"(matches {seen_integer_payloads[integer_key]})"
            )
        seen_integer_payloads[integer_key] = fp

        base = _base_template_name(anchor, neighbours, m_eff)  # type: ignore[arg-type]
        base_counts[base] += 1
        suffix = "" if base_counts[base] == 1 else f"_{base_counts[base]}"
        name = f"{base}{suffix}"
        if len(name) > 40:
            name = name[:40]

        templates.append(
            MotifTemplate(
                name=name,
                anchor=anchor,
                geom=payload["geom"],  # type: ignore[arg-type]
                footprint_size=payload["footprint_size"],  # type: ignore[arg-type]
                fingerprint=fp,
                neighbors=neighbours,  # type: ignore[arg-type]
                local_grid_m=m_eff,
                local_offsets_ijk=local_offsets,  # type: ignore[arg-type]
                species_key=payload["species_key"],  # type: ignore[arg-type]
                notes=payload["notes"],  # type: ignore[arg-type]
            )
        )

    template_by_fp: Dict[str, MotifTemplate] = {t.fingerprint: t for t in templates}
    template_by_name: Dict[str, MotifTemplate] = {t.name: t for t in templates}

    combo_counts = Counter((t.anchor, len(t.neighbors), t.local_grid_m) for t in templates)
    if templates:
        summary = ", ".join(
            f"{anchor}/CN{cn}/m{m}: {count}"
            for (anchor, cn, m), count in sorted(combo_counts.items())
        )
        print(f"[miner] motifs (unique): {len(templates)} -> {summary}")
    else:
        print("[miner] no motifs survived deduplication.")

    def _frac_to_idx(value: float, g: int) -> int:
        return int(round((value % 1.0) * g)) % g

    def _flat(i: int, j: int, k: int, g: int) -> int:
        return i + j * g + k * g * g

    def _snap_frac(point: Sequence[float], g: int, tol: float) -> Optional[Tuple[int, int, int]]:
        fx, fy, fz = (float(coord) % 1.0 for coord in point)
        ix, iy, iz = (_frac_to_idx(fx, g), _frac_to_idx(fy, g), _frac_to_idx(fz, g))

        def delta(u: float, iu: int) -> float:
            diff = abs(u - iu / g)
            return min(diff, 1.0 - diff)

        if max(delta(fx, ix), delta(fy, iy), delta(fz, iz)) > tol:
            return None
        return ix, iy, iz

    def _instance_fp(anchor_idx: int, neighbours: List[Tuple[str, int]], g: int) -> str:
        def idx_to_ijk(idx: int) -> Tuple[int, int, int]:
            i = idx % g
            j = (idx // g) % g
            k = idx // (g * g)
            return i, j, k

        ai, aj, ak = idx_to_ijk(anchor_idx)
        rel_offsets: List[Tuple[str, Tuple[int, int, int]]] = []
        for species, idx in neighbours:
            i, j, k = idx_to_ijk(idx)
            di, dj, dk = (i - ai) % g, (j - aj) % g, (k - ak) % g
            if di > g // 2:
                di -= g
            if dj > g // 2:
                dj -= g
            if dk > g // 2:
                dk -= g
            rel_offsets.append((species, (di, dj, dk)))

        best_sig: Optional[str] = None
        for R in _ROT24:
            rows: List[Tuple[str, Tuple[int, int, int]]] = []
            for species, (di, dj, dk) in rel_offsets:
                rotated = R @ np.array([di, dj, dk], dtype=float)
                rotated_int = tuple(int(round(val)) for val in rotated.tolist())
                rows.append((species, rotated_int))
            rows.sort(key=lambda x: (x[0], x[1][0], x[1][1], x[1][2]))
            sig = json.dumps(rows, sort_keys=True)
            if best_sig is None or sig < best_sig:
                best_sig = sig
        return hashlib.sha1((best_sig or "").encode("utf-8")).hexdigest()[:HASH_N]

    instances: Dict[str, List[MotifInstance]] = {template.name: [] for template in templates}
    seen_instance_fps: Dict[str, set] = {template.name: set() for template in templates}

    for anchor_species, anchor_frac, neighbours_abs in detections:
        rel = [
            (species, np.array(frac, dtype=float) - np.array(anchor_frac, dtype=float))
            for species, frac in neighbours_abs
        ]
        canon_rows = _canon_neighbors(rel)
        m_eff = _minimal_grid_m(canon_rows, max_den=MAX_DEN)
        ijk_m = _ijk_on_m_grid(canon_rows, m_eff)
        fp = _tmpl_fingerprint(anchor_species, ijk_m, m_eff)
        template = template_by_fp.get(fp)
        if template is None:
            continue

        anchor_snap = _snap_frac(anchor_frac, grid_g, snap_tol_frac)
        if anchor_snap is None:
            continue
        anchor_idx = _flat(*anchor_snap, grid_g)

        neighbour_indices: List[Tuple[str, int]] = []
        snap_fail = False
        for species, frac in neighbours_abs:
            ijk = _snap_frac(frac, grid_g, snap_tol_frac)
            if ijk is None:
                snap_fail = True
                break
            neighbour_indices.append((species, _flat(*ijk, grid_g)))
        if snap_fail:
            continue

        inst_fp = _instance_fp(anchor_idx, neighbour_indices, grid_g)
        seen = seen_instance_fps[template.name]
        if inst_fp in seen:
            continue
        seen.add(inst_fp)
        instances[template.name].append(MotifInstance(anchor_index=anchor_idx, neighbors=neighbour_indices))

    meta: Dict[str, object] = {
        "chem": formula,
        "grid": grid_g,
        "a": a,
        "source": source,
        "counts": {name: len(lst) for name, lst in instances.items()},
        "unique_anchor_cn_m": {
            f"{anchor}_CN{cn}_m{m}": count for (anchor, cn, m), count in sorted(combo_counts.items())
        },
    }

    _dump(out_path / "motifs.json", {"_meta": meta, "motifs": [asdict(t) for t in templates]})
    flat_instances = {
        name: [
            [inst.anchor_index, [[species, idx] for species, idx in inst.neighbors]]
            for inst in lst
        ]
        for name, lst in instances.items()
    }
    _dump(out_path / "instances.json", {"_meta": meta, "instances": flat_instances})

    if emit_cifs:
        tmpl_dir = out_path / "motifs_cif"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        for existing in tmpl_dir.glob("*.cif"):
            try:
                existing.unlink()
            except OSError:
                pass
        for template in templates:
            a_min = max(a / max(1, template.local_grid_m), MIN_A)
            coords = [np.array([0.0, 0.0, 0.0], dtype=float)]
            for _, disp in template.neighbors:
                coords.append(_wrap_min(np.array(disp, dtype=float)))
            symbols = [template.anchor] + [species for species, _ in template.neighbors]
            cif_text = _cif_from(symbols, np.asarray(coords, dtype=float), a_min)
            target = tmpl_dir / f"{template.name}.cif"
            if len(target.name) > 40:
                raise ValueError(f"Template filename too long: {target.name}")
            target.write_text(cif_text, encoding="utf-8")
            if a_min < MIN_A - 1e-6:
                raise ValueError(f"Template cell length below MIN_A for {template.name}: {a_min}")

        inst_dir = out_path / "instances_cif"
        inst_dir.mkdir(parents=True, exist_ok=True)
        for existing in inst_dir.glob("*.cif"):
            try:
                existing.unlink()
            except OSError:
                pass
        limit = emit_instances_limit if emit_instances_limit is not None else 16
        for name, placements in instances.items():
            template = template_by_name.get(name)
            anchor_species = template.anchor if template else "X"
            for idx, placement in enumerate(placements[:max(0, limit)]):
                symbols = [anchor_species] + [species for species, _ in placement.neighbors]
                coords = [_idx_to_frac(placement.anchor_index, grid_g)] + [
                    _idx_to_frac(idx, grid_g) for _, idx in placement.neighbors
                ]
                cif_text = _cif_from(symbols, np.asarray(coords, dtype=float), a)
                (inst_dir / f"{name}_{idx}.cif").write_text(cif_text, encoding="utf-8")

    print(f"[miner] motifs written: {len(templates)}")
    return templates, instances, meta


def _cif_from(symbols: List[str], frac: np.ndarray, a: float) -> str:
    """Write a simple cubic CIF with the provided fractional coordinates."""
    lines = [
        "data_motif",
        f"_cell_length_a {a:.6f}",
        f"_cell_length_b {a:.6f}",
        f"_cell_length_c {a:.6f}",
        "_cell_angle_alpha 90",
        "_cell_angle_beta 90",
        "_cell_angle_gamma 90",
        "loop_",
        "_atom_site_label",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
    ]
    for idx, (symbol, fcoords) in enumerate(zip(symbols, frac)):
        lines.append(f"{symbol}{idx + 1:03d}  {fcoords[0]:.6f}  {fcoords[1]:.6f}  {fcoords[2]:.6f}")
    return "\n".join(lines) + "\n"


def _dump(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
