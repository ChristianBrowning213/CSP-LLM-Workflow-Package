from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from spp_maker.export import export_spp_root
from spp_maker.fit_hist import accumulate_histograms, canonical_pair
from spp_maker.fit_phi import build_phi_from_hist
from spp_maker.io_cif import LoadedCIF, load_cifs_from_dir
from spp_maker_qlip.qlip_package import parse_formula_elements, read_pot_root_pairs, required_pairs_from_formula


def _pair_label(pair: tuple[str, str]) -> str:
    return f"{pair[0]}-{pair[1]}"


def _elements_from_loaded(item: LoadedCIF) -> list[str]:
    seen: set[str] = set()
    elements: list[str] = []
    for symbol in item.symbols:
        if symbol not in seen:
            seen.add(symbol)
            elements.append(symbol)
    return elements


def _periodic_pair_distances(atoms: Any, cutoff: float, supercell: int) -> dict[str, dict[str, float | int]]:
    symbols = tuple(str(symbol) for symbol in atoms.get_chemical_symbols())
    positions = np.asarray(atoms.get_positions(), dtype=np.float64)
    cell = np.asarray(atoms.cell.array, dtype=np.float64)
    span = range(-int(supercell), int(supercell) + 1)
    by_pair: dict[tuple[str, str], list[float]] = {}

    for i, symbol_i in enumerate(symbols):
        pos_i = positions[i]
        for j, symbol_j in enumerate(symbols):
            pos_j = positions[j]
            for tx in span:
                for ty in span:
                    for tz in span:
                        if i == j and tx == 0 and ty == 0 and tz == 0:
                            continue
                        image_pos = pos_j + tx * cell[0] + ty * cell[1] + tz * cell[2]
                        distance = float(np.linalg.norm(image_pos - pos_i))
                        if distance <= cutoff + 1e-12:
                            by_pair.setdefault(canonical_pair(symbol_i, symbol_j), []).append(distance)

    out: dict[str, dict[str, float | int]] = {}
    for pair, distances in sorted(by_pair.items()):
        out[_pair_label(pair)] = {
            "count": int(len(distances)),
            "min_distance": float(min(distances)),
        }
    return out


def _selected_pairs_by_current_extractor(loaded: list[LoadedCIF], cutoff: float) -> list[str]:
    hist = accumulate_histograms(
        [item.atoms for item in loaded],
        r_cut=float(cutoff),
        d_min=0.5,
        d_max=max(8.0, float(cutoff)),
        bin_width=0.05,
        bandpass=None,
    )
    return [_pair_label(pair) for pair in sorted(hist.counts)]


def _export_current_spp_root(loaded: list[LoadedCIF], cutoff: float, out_json: Path) -> list[str]:
    hist = accumulate_histograms(
        [item.atoms for item in loaded],
        r_cut=float(cutoff),
        d_min=0.5,
        d_max=max(8.0, float(cutoff)),
        bin_width=0.05,
        bandpass=None,
    )
    phi_res = build_phi_from_hist(hist, alpha=1e-3, shifted=True)
    out_root = out_json.parent / f"{out_json.stem}_spp_root"
    export_spp_root(
        out_root,
        phi_res,
        name=f"{out_json.stem}_diagnostic",
        manifest_extra={
            "diagnostic": "pair_extraction",
            "r_cut": float(cutoff),
            "pair_policy": "neighbors_r_cut_unit_cell_edges",
        },
    )
    return sorted(read_pot_root_pairs(out_root), key=str.lower)


def build_diagnostic(*, cif_dir: Path, formula: str, out_json: Path, cutoff: float, supercell: int) -> dict[str, Any]:
    loaded = load_cifs_from_dir(cif_dir)
    required_pairs = required_pairs_from_formula(formula)
    formula_elements = set(parse_formula_elements(formula))
    cifs: list[dict[str, Any]] = []
    corpus_detected_formulas: list[str] = []
    for item in loaded:
        detected_formula = str(item.atoms.get_chemical_formula())
        corpus_detected_formulas.append(detected_formula)
        cifs.append(
            {
                "file": str(Path(item.path)),
                "detected_formula": detected_formula,
                "elements": _elements_from_loaded(item),
                "geometric_pairs_within_cutoff": _periodic_pair_distances(
                    item.atoms,
                    cutoff=float(cutoff),
                    supercell=int(supercell),
                ),
            }
        )

    spp_selected_pairs_all = _selected_pairs_by_current_extractor(loaded, cutoff=float(cutoff))
    spp_selected_pairs = [
        pair for pair in spp_selected_pairs_all if set(pair.split("-", 1)).issubset(formula_elements)
    ]
    pot_pairs_all = _export_current_spp_root(loaded, cutoff=float(cutoff), out_json=out_json)
    pot_pairs = [
        pair for pair in pot_pairs_all if set(pair.split("-", 1)).issubset(formula_elements)
    ]
    missing_after_spp = [pair for pair in required_pairs if pair not in set(pot_pairs)]
    geometric_detected = sorted(
        {
            pair
            for item in cifs
            for pair, detail in item["geometric_pairs_within_cutoff"].items()
            if isinstance(detail, dict) and int(detail.get("count", 0)) > 0
        },
        key=str.lower,
    )
    likely_reason = (
        "same-element periodic image pairs are geometrically present, but the current "
        "neighbors/r_cut SPP extraction policy only selects unit-cell contact edges; "
        "for this corpus that selected a subset of QLIP-required pairs"
        if missing_after_spp
        else "current SPP extraction produced all QLIP-required pairs"
    )

    return {
        "formula": formula,
        "required_pairs": required_pairs,
        "cutoff": float(cutoff),
        "supercell": int(supercell),
        "pair_policy": "neighbors_r_cut_unit_cell_edges",
        "corpus_cif_files": [str(Path(item.path)) for item in loaded],
        "corpus_detected_formulas": corpus_detected_formulas,
        "cifs": cifs,
        "geometric_pairs_detected": geometric_detected,
        "spp_selected_pairs": spp_selected_pairs,
        "pot_pairs": pot_pairs,
        "missing_after_spp": missing_after_spp,
        "likely_reason": likely_reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose SPP pair extraction versus formula pair requirements.")
    parser.add_argument("--cif_dir", required=True, type=Path)
    parser.add_argument("--formula", required=True)
    parser.add_argument("--out_json", required=True, type=Path)
    parser.add_argument("--cutoff", type=float, default=6.0)
    parser.add_argument("--supercell", type=int, default=1)
    args = parser.parse_args()

    if args.cutoff <= 0:
        raise SystemExit("--cutoff must be > 0")
    if args.supercell <= 0:
        raise SystemExit("--supercell must be > 0")

    out_json = args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = build_diagnostic(
        cif_dir=args.cif_dir,
        formula=args.formula,
        out_json=out_json,
        cutoff=float(args.cutoff),
        supercell=int(args.supercell),
    )
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
