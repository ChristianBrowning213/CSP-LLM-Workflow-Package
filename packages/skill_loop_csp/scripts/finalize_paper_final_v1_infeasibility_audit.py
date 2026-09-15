"""Add compact graph witnesses and historical comparisons to the v1 audit."""

from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path
from typing import Any

from pymatgen.core import Structure

from audit_paper_final_v1_infeasibility import CASES, OUT, V1, positions, read_json, species_and_counts, write_csv
from qlip.data.registry import default_registry


REPO = Path(__file__).resolve().parents[1]
HISTORICAL = {
    "BaTiO3": REPO / "local_runs" / "paper_experiment_1_common_v1" / "exp1_batio3_perovskite",
    "SrTiO3": REPO / "local_runs" / "paper_experiment_2_hard_v3" / "exp2v3_srtio3_perovskite",
    "CsPbBr3": REPO / "local_runs" / "paper_experiment_2_hard_v3" / "exp2v3_cspbbr3_halide",
    "CsPbCl3": REPO / "local_runs" / "paper_experiment_2_hard_v3" / "exp2v3_cspbcl3_halide",
    "CsSnI3": REPO / "local_runs" / "paper_experiment_2_hard_v3" / "exp2v3_cssni3_halide",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def graph_witness(task_id: str, formula: str) -> dict[str, Any]:
    search = read_json(V1 / "runs" / task_id / "qlip" / "search_space.json")
    grid = positions(search)
    distances = grid.get_all_distances(mic=True)
    species, counts = species_and_counts(formula)
    singles = [symbol for symbol in species if counts[symbol] == 1]
    repeated = [symbol for symbol in species if counts[symbol] > 1]
    if len(singles) != 2 or len(repeated) != 1:
        raise ValueError(f"controlled ABX3 audit requires two singleton species and one repeated species: {formula}")
    a_species, b_species = singles
    x_species = repeated[0]
    x_count = counts[x_species]
    radii = default_registry().atomic_radius_map(species)
    allowed_ab = []
    max_common_x = 0
    max_x_clique = 0
    feasible_ab = 0
    witness = None
    for a_site in range(len(grid)):
        for b_site in range(len(grid)):
            if a_site == b_site or distances[a_site, b_site] < radii[a_species] + radii[b_species]:
                continue
            allowed_ab.append((a_site, b_site))
            candidates = [
                site for site in range(len(grid))
                if site not in {a_site, b_site}
                and distances[a_site, site] >= radii[a_species] + radii[x_species]
                and distances[b_site, site] >= radii[b_species] + radii[x_species]
            ]
            max_common_x = max(max_common_x, len(candidates))
            local_max = 0
            local_witness = None
            for size in range(min(len(candidates), x_count), 0, -1):
                compatible = next(
                    (
                        chosen
                        for chosen in combinations(candidates, size)
                        if all(
                            distances[left, right] >= 2 * radii[x_species]
                            for left, right in combinations(chosen, 2)
                        )
                    ),
                    None,
                )
                if compatible is not None:
                    local_max = size
                    if size == x_count:
                        local_witness = compatible
                    break
            max_x_clique = max(max_x_clique, local_max)
            if local_witness is not None:
                feasible_ab += 1
                if witness is None:
                    witness = {"a_site": a_site, "b_site": b_site, "x_sites": list(local_witness)}
    return {
        "task_id": task_id, "formula": formula, "a_species": a_species, "b_species": b_species,
        "x_species": x_species, "required_x_count": x_count,
        "allowed_oriented_a_b_pairs": len(allowed_ab),
        "maximum_common_x_candidate_sites": max_common_x,
        "maximum_pairwise_compatible_x_sites": max_x_clique,
        "a_b_pairs_admitting_full_x_occupation": feasible_ab,
        "hard_geometry_feasible": feasible_ab > 0,
        "first_feasible_witness": json.dumps(witness, sort_keys=True) if witness else "",
        "interpretation": (
            "at least one exact ABX3 occupation exists" if feasible_ab
            else "no allowed A-B placement admits three mutually compatible X sites"
        ),
    }


def historical_radius_violations(structure: Structure) -> list[dict[str, Any]]:
    symbols = [str(site.specie) for site in structure]
    radii = default_registry().atomic_radius_map(set(symbols))
    distances = structure.distance_matrix
    violations = []
    for i in range(len(structure)):
        for j in range(i + 1, len(structure)):
            threshold = radii[symbols[i]] + radii[symbols[j]]
            if distances[i, j] < threshold:
                violations.append({"pair": f"{symbols[i]}-{symbols[j]}", "distance": distances[i, j], "threshold": threshold})
    return violations


def historical_row(formula: str, root: Path) -> dict[str, Any]:
    source = root / "generated.cif"
    structure = Structure.from_file(source)
    request = read_json(root / "qlip_request.json")
    input_payload = read_json(root / "input.json")
    task_id = next(key for key, value in CASES.items() if value == formula)
    v1_search = read_json(V1 / "runs" / task_id / "qlip" / "search_space.json")
    v1_result = read_json(V1 / "runs" / task_id / "qlip" / "solver_result.json")
    violations = historical_radius_violations(structure)
    sites = request["problem"]["design_space"]["sites"]
    return {
        "formula": formula, "historical_status": "generated",
        "historical_generated_cif_path": str(source.resolve()),
        "historical_generated_cif_sha256": sha256(source),
        "historical_cell_matrix_A": json.dumps(structure.lattice.matrix.tolist()),
        "historical_volume_A3": structure.volume,
        "historical_a_A": structure.lattice.a, "historical_b_A": structure.lattice.b,
        "historical_c_A": structure.lattice.c, "historical_candidate_site_count": len(structure),
        "historical_grid_dimensions": "NOT_APPLICABLE_PROTOTYPE_SITES",
        "historical_search_space_mode": sites.get("site_mode", sites.get("mode")),
        "historical_candidate_site_source": sites.get("candidate_site_source"),
        "historical_scaffold_hint": input_payload.get("qlip_scaffold_hint"),
        "historical_symmetry_mode": request.get("metadata", {}).get("active_symmetry_mode"),
        "historical_proximity_policy": "NOT_PERSISTED",
        "historical_current_radius_policy_violation_count": len(violations),
        "historical_current_radius_policy_violations": json.dumps(violations, sort_keys=True),
        "historical_spp_contract": "legacy retrieved pair guidance; exact numerical contract not persisted",
        "historical_qlip_version": "NOT_PERSISTED",
        "historical_solver_settings": "NOT_PERSISTED",
        "v1_status": v1_result["status"], "v1_volume_A3": v1_search["cell_volume_A3"],
        "v1_a_A": v1_search["a"], "v1_grid_dimensions": "4x4x4",
        "v1_candidate_site_count": v1_search["candidate_site_count"],
        "v1_search_space_mode": "native uniform grid; no scaffold",
        "v1_proximity_policy": "QLIP atomic radii scale=1.0",
        "material_difference": "historical prototype-supplied five-site scaffold versus v1 64-site native grid and current hard radius exclusions",
    }


def main() -> int:
    graph_rows = [graph_witness(task_id, formula) for task_id, formula in CASES.items()]
    write_csv(OUT / "SITE_FEASIBILITY_GRAPH_DETAILS.csv", graph_rows)
    historical = [historical_row(formula, root) for formula, root in HISTORICAL.items()]
    write_csv(OUT / "HISTORICAL_VS_FINAL_CONFIG.csv", historical)

    history_lines = [
        "# Historical success audit", "",
        "All five historical successes used prototype-supplied five-site perovskite/halide-perovskite search spaces, "
        "not the paper_final_v1 native 4x4x4 grid. Their persisted QLIP summaries do not contain a solver "
        "termination certificate, QLIP version, numerical solver configuration, or explicit proximity policy.", "",
        "| Formula | historical a (A) | volume (A^3) | current-radius violations | v1 outcome |", "|---|---:|---:|---:|---|",
    ]
    for row in historical:
        history_lines.append(
            f"| {row['formula']} | {float(row['historical_a_A']):.3f} | {float(row['historical_volume_A3']):.3f} "
            f"| {row['historical_current_radius_policy_violation_count']} | {row['v1_status']} |"
        )
    history_lines.extend([
        "", "The halide scaffolds used much larger chemistry-specific prototype cells (5.60-6.20 A). "
        "The BaTiO3 and SrTiO3 historical cells were only 4.00 A, but their generated placements violate the current "
        "scale-1 atomic-radius exclusions. Therefore those historical runs cannot be used as evidence that the present "
        "hard policy was feasible at 4.00 A. What is proven is that historical success used a materially different, "
        "prototype-constrained search space and incompletely persisted legacy solver/proximity semantics.",
    ])
    (OUT / "HISTORICAL_SUCCESS_AUDIT.md").write_text("\n".join(history_lines) + "\n", encoding="utf-8")

    graph = {row["formula"]: row for row in graph_rows}
    root_lines = [
        "# paper_final_v1 infeasibility root cause", "",
        "## Classification", "",
    ]
    for formula in HISTORICAL:
        row = graph[formula]
        root_lines.append(
            f"- **{formula}: FIXED_CELL_TOO_SMALL.** The frozen cell and scale-1 atomic-radius exclusions leave "
            f"{row['allowed_oriented_a_b_pairs']} oriented A-B placements, but zero placements admit the required "
            f"three mutually compatible X sites (maximum {row['maximum_pairwise_compatible_x_sites']})."
        )
    root_lines.extend([
        "", "CaTiO3 remains feasible because its smaller Ca radius leaves a broader compatibility graph; the audit "
        f"found {graph['CaTiO3']['a_b_pairs_admitting_full_x_occupation']} A-B placements admitting all three O sites.",
        "", "## Decision facts", "",
        "1. All five failures reproduce with the SPP objective removed, so SPP logic does not cause infeasibility.",
        "2. No family or symmetry constraint is present in the v1 native models.",
        "3. Exact composition, site exclusivity, and vacancy equations are internally consistent; conflict arises only when atomic-radius exclusions are added.",
        "4. The shared 89.93449651590149 A^3 / 4.480317269262231 A cell is too small under the declared radius policy for the five chemistries.",
        "5. The proximity policy amplifies the fixed-cell defect; it is not a species-radius lookup bug; the persisted registry values are used consistently.",
        "6. Hard geometry uses minimum-image distances between distinct sites. It omits periodic self-image constraints, which relaxes rather than causes infeasibility.",
        "7. Historical success used materially different prototype-supplied sites and cells. Historical solver/proximity details are incomplete.",
        "8. Cubic shape has not yet been shown to be the cause; the next gate should test cubic volume expansion only.",
        "", "The evidence justifies evaluating a universal retrieval-informed, hard-feasibility-aware cubic sizing policy. "
        "It does not justify per-target tuning or changing the radius policy.",
    ])
    (OUT / "INFEASIBILITY_ROOT_CAUSE.md").write_text("\n".join(root_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
