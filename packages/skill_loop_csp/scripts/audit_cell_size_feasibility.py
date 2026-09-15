"""Pre-solve, diagnostic-only proximity feasibility sanity check.

For each (formula, cell_mode) row in the frozen NASICON_CELL_SIZE.csv
manifest, resolves the exact cubic cell QLIP will search (reusing the
production retrieve() + assemble_spp_evidence() stages for
retrieval_derived, so it consumes the SAME leakage-safe evidence cohort
the real solve will use -- no second hidden retrieval, no solve/CIF
generation) and reports whether the previously-diagnosed same-species
packing bottleneck (see docs/audits and the 2026-08-19 SPP-only
diagnostic) is now geometrically possible at that cell size.

This script does NOT tune cell parameters based on its own output -- it
is read before freeze, to confirm the frozen cell rules are sane, and its
numbers are recorded in the frozen package unchanged regardless of what
they show.
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from qlip.data.registry import default_registry
from sok_llm_orchestrator.workflow.cell_strategy import evidence_vpa_records, resolve_native_cell
from sok_llm_orchestrator.workflow.evidence import assemble_spp_evidence
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

GRID_DENSITY = 8


def _fractional_grid(density: int = GRID_DENSITY) -> np.ndarray:
    return np.asarray(list(np.ndindex(density, density, density)), dtype=float) / float(density)


def _minimum_image_distance_matrix(a: float, density: int = GRID_DENSITY) -> np.ndarray:
    frac = _fractional_grid(density)
    delta = frac[:, None, :] - frac[None, :, :]
    delta -= np.rint(delta)
    return np.linalg.norm(delta * a, axis=2)


def max_same_species_positions(species: str, a: float, density: int = GRID_DENSITY) -> dict[str, Any]:
    """Exact max independent set under proximity.atomic_radii(scale=1.0) at cell edge `a`."""
    import gurobipy as gp

    radius = float(default_registry().atomic_radius_map()[species])
    threshold = 2.0 * radius
    distances = _minimum_image_distance_matrix(a, density)
    n = density ** 3
    model = gp.Model(f"cell_size_audit_{species}")
    model.Params.OutputFlag = 0
    values = model.addVars(n, vtype=gp.GRB.BINARY, name="occupied")
    conflicts = 0
    for i in range(n):
        for j in range(i + 1, n):
            if float(distances[i, j]) < threshold:
                model.addConstr(values[i] + values[j] <= 1)
                conflicts += 1
    model.setObjective(gp.quicksum(values[i] for i in range(n)), gp.GRB.MAXIMIZE)
    model.optimize()
    return {
        "species": species, "atomic_radius_A": radius, "same_species_exclusion_A": threshold,
        "cell_edge_A": a, "grid_density": density,
        "conflict_edge_count": conflicts, "maximum_compatible_sites": int(round(model.ObjVal)),
        "solver_status": int(model.Status),
    }


def _culprit_species(formula: str) -> tuple[str, int]:
    from pymatgen.core import Composition

    counts = {str(k): int(v) for k, v in Composition(formula).get_el_amt_dict().items()}
    if counts.get("Na", 0) >= 3:
        return "Na", counts["Na"]
    return "Zr", counts["Zr"]


def resolve_row_cell(formula: str, request: str, cell_mode: str) -> dict[str, Any]:
    stages = ProductionWorkflowStages()
    task = stages.normalise(formula)
    if cell_mode == "retrieval_derived":
        with tempfile.TemporaryDirectory(prefix="cell_size_audit_") as tmp:
            run_root = Path(tmp)
            retrieval = stages.retrieve(request, task, _StubConfig(), run_root)
            required_pairs = stages.required_pairs(task, _StubConfig(native_qlip=True))
            evidence = assemble_spp_evidence(
                retrieval=retrieval, required_pairs=required_pairs, allow_partial_pair_coverage=True,
            )
            records = evidence_vpa_records(evidence.selected)
        resolved = resolve_native_cell(formula, cell_mode="retrieval_derived", evidence_vpa_records=records)
        return {"resolved": resolved, "evidence_structure_count": len(records)}
    resolved = resolve_native_cell(formula, cell_mode=cell_mode)
    return {"resolved": resolved, "evidence_structure_count": None}


class _StubConfig:
    """Minimal duck-typed stand-in so retrieve()/required_pairs() need no full WorkflowConfig."""

    def __init__(self, native_qlip: bool = False) -> None:
        self.retrieval_depth = 40
        self.embedding_model = "text-embedding-bge-m3"
        self.embedding_version = "lmstudio_v1"
        self.retrieval_demo_export = True
        self.registry_path = None
        self.native_qlip = native_qlip
        self.cutoff = 11.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    with args.manifest.open(encoding="utf-8-sig") as handle:
        text = "\n".join(line for line in handle if not line.lstrip().startswith("#"))
    rows = list(csv.DictReader(text.splitlines()))

    results: list[dict[str, Any]] = []
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        formula, cell_mode, request = row["formula"], row["cell_mode"], row["request"]
        key = (formula, cell_mode)
        if key not in cache:
            cache[key] = resolve_row_cell(formula, request, cell_mode)
        info = cache[key]
        resolved = info["resolved"]
        species, required = _culprit_species(formula)
        capacity = max_same_species_positions(species, resolved.a, resolved.grid_density)
        results.append({
            "row_id": row["row_id"], "formula": formula, "cell_mode": cell_mode,
            "cell_edge_A": resolved.a, "cell_volume_A3": resolved.cell_volume_A3,
            "grid_density": resolved.grid_density, "grid_spacing_A": resolved.grid_spacing_A,
            "vpa_source": resolved.vpa_source, "vpa_value_A3_per_atom": resolved.vpa_value,
            "evidence_structure_count": info["evidence_structure_count"],
            "culprit_species": species, "required_count": required,
            "maximum_compatible_sites": capacity["maximum_compatible_sites"],
            "same_species_exclusion_A": capacity["same_species_exclusion_A"],
            "geometrically_possible": "YES" if required <= capacity["maximum_compatible_sites"] else "NO",
        })
        print(f"{row['row_id']}: a={resolved.a:.4f}A {species} required={required} max_compatible={capacity['maximum_compatible_sites']} -> {'YES' if required <= capacity['maximum_compatible_sites'] else 'NO'}")

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    lines = ["# CELL_SIZE_FEASIBILITY (pre-solve diagnostic only; not used to tune cells)", "",
             "| row_id | formula | cell_mode | a (A) | grid spacing (A) | culprit | required | max compatible | possible |",
             "|---|---|---|---:|---:|---|---:|---:|---|"]
    for r in results:
        lines.append(
            f"| {r['row_id']} | {r['formula']} | {r['cell_mode']} | {r['cell_edge_A']:.4f} | "
            f"{r['grid_spacing_A']:.4f} | {r['culprit_species']} | {r['required_count']} | "
            f"{r['maximum_compatible_sites']} | {r['geometrically_possible']} |"
        )
    args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(results)} rows to {args.out_csv} and {args.out_md}")


if __name__ == "__main__":
    main()
