"""Audit paper_final_v1 ABX3 infeasibility without modifying frozen results."""

from __future__ import annotations

import csv
import json
from collections import OrderedDict
from dataclasses import dataclass
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Any

import gurobipy as gp
from ase import Atoms
from gurobipy import GRB
from pymatgen.core import Composition

from qlip.core.solve import _build_positions
from qlip.data.registry import default_registry


REPO = Path(__file__).resolve().parents[1]
V1 = REPO / "artifacts" / "paper_final_v1"
OUT = V1 / "infeasibility_audit"
IIS = OUT / "iis"
CASES = OrderedDict([
    ("catio3", "CaTiO3"),
    ("batio3", "BaTiO3"),
    ("srtio3", "SrTiO3"),
    ("cspbbr3", "CsPbBr3"),
    ("cspbcl3", "CsPbCl3"),
    ("cssni3", "CsSnI3"),
])
INFEASIBLE = set(CASES) - {"catio3"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def species_and_counts(formula: str) -> tuple[list[str], dict[str, int]]:
    species = list(Atoms(symbols=formula).symbols.formula.count().keys())
    values = Composition(formula).get_el_amt_dict()
    return species, {symbol: int(values[symbol]) for symbol in species}


def positions(search: dict[str, Any]):
    lattice = {key: search[key] for key in ("a", "b", "c", "alpha", "beta", "gamma")}
    design = {
        "template": {"name": "cubic", "lattice": lattice},
        "sites": {"mode": "uniform_grid", "uniform_grid": {"density": int(search["grid_density"])}},
    }
    return _build_positions(design)


@dataclass(frozen=True)
class ConstraintMeta:
    name: str
    constraint_type: str
    species: str
    site_or_pair: str
    lower_bound: float | int | None
    upper_bound: float | int | None
    distance: float | None
    radius_or_threshold: float | None
    interpretation: str


def build_hard_model(formula: str, search: dict[str, Any]) -> tuple[gp.Model, dict[str, ConstraintMeta], Any, dict[str, float]]:
    grid = positions(search)
    distances = grid.get_all_distances(mic=True)
    species, counts = species_and_counts(formula)
    radii = default_registry().atomic_radius_map(species)
    site_count = len(grid)
    model = gp.Model(f"paper_final_v1_hard_feasibility__{formula}")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = 300
    model.Params.MIPGap = 0.0
    model.Params.Threads = 1
    model.Params.NonConvex = 2
    variables = {(symbol, site): model.addVar(vtype=GRB.BINARY, name=f"x__{symbol}__{site}")
                 for symbol in species for site in range(site_count)}
    vacancy = {site: model.addVar(vtype=GRB.BINARY, name=f"vacancy__{site}") for site in range(site_count)}
    metadata: dict[str, ConstraintMeta] = {}

    proximity_index = 0
    for left, right in combinations_with_replacement(species, 2):
        threshold = float(radii[left]) + float(radii[right])
        for i in range(site_count):
            for j in range(i + 1, site_count):
                distance = float(distances[i, j])
                if distance >= threshold:
                    continue
                for first, second in ((left, right), (right, left)):
                    name = f"atomic_radii__{proximity_index}"
                    model.addConstr(variables[first, i] + variables[second, j] <= 1, name=name)
                    metadata[name] = ConstraintMeta(
                        name, "ATOMIC_RADII_EXCLUSION", f"{first}-{second}", f"{i}-{j}", None, 1,
                        distance, threshold,
                        f"forbid {first}@{i} with {second}@{j}: MIC distance {distance:.12g} A < radius sum {threshold:.12g} A",
                    )
                    proximity_index += 1

    for symbol in species:
        name = f"stoic__{symbol}"
        target = counts[symbol]
        model.addConstr(gp.quicksum(variables[symbol, site] for site in range(site_count)) == target, name=name)
        metadata[name] = ConstraintMeta(
            name, "EXACT_STOICHIOMETRY", symbol, "all_sites", target, target, None, None,
            f"exactly {target} {symbol} atom(s) must occupy the candidate grid",
        )
    for site in range(site_count):
        name = f"excl__{site}"
        model.addConstr(gp.quicksum(variables[symbol, site] for symbol in species) + vacancy[site] == 1, name=name)
        metadata[name] = ConstraintMeta(
            name, "ONE_STATE_PER_SITE", "all", str(site), 1, 1, None, None,
            "candidate site contains exactly one species or vacancy state",
        )
    expected_vacancies = site_count - sum(counts.values())
    model.addConstr(gp.quicksum(vacancy.values()) == expected_vacancies, name="vacancy_count")
    metadata["vacancy_count"] = ConstraintMeta(
        "vacancy_count", "EXACT_VACANCY_COUNT", "VACANCY", "all_sites",
        expected_vacancies, expected_vacancies, None, None,
        f"exactly {expected_vacancies} of {site_count} candidate sites remain vacant",
    )
    model.setObjective(0.0, GRB.MINIMIZE)
    model.update()
    return model, metadata, grid, radii


def compatibility_rows(task_id: str, formula: str, search: dict[str, Any]) -> list[dict[str, Any]]:
    grid = positions(search)
    distances = grid.get_all_distances(mic=True)
    species, _ = species_and_counts(formula)
    radii = default_registry().atomic_radius_map(species)
    rows = []
    for left, right in combinations_with_replacement(species, 2):
        threshold = float(radii[left]) + float(radii[right])
        multiplier = 1 if left == right else 2
        total = allowed = 0
        for i in range(len(grid)):
            for j in range(i + 1, len(grid)):
                total += multiplier
                if float(distances[i, j]) >= threshold:
                    allowed += multiplier
        rows.append({
            "task_id": task_id, "formula": formula, "species_a": left, "species_b": right,
            "radius_a_A": radii[left], "radius_b_A": radii[right],
            "min_allowed_distance_A": threshold, "total_candidate_pairs": total,
            "allowed_candidate_pairs": allowed, "forbidden_candidate_pairs": total - allowed,
            "allowed_fraction": allowed / total,
        })
    return rows


def case_config(task_id: str, formula: str) -> dict[str, Any]:
    run = V1 / "runs" / task_id
    search = read_json(run / "qlip" / "search_space.json")
    solver = read_json(run / "qlip" / "solver_config.json")
    result = read_json(run / "qlip" / "solver_result.json")
    structured = read_json(run / "structured_task" / "structured_task.json")
    pairs = read_csv(run / "spp" / "pair_manifest.csv")
    species, counts = species_and_counts(formula)
    radii = default_registry().atomic_radius_map(species)
    thresholds = {f"{left}-{right}": radii[left] + radii[right]
                  for left, right in combinations_with_replacement(species, 2)}
    cell_matrix = [[search["a"], 0.0, 0.0], [0.0, search["b"], 0.0], [0.0, 0.0, search["c"]]]
    return {
        "task_id": task_id, "formula": formula, "v1_solver_status": result["status"],
        "composition_counts": json.dumps(counts, sort_keys=True), "atom_count": sum(counts.values()),
        "cell_matrix_A": json.dumps(cell_matrix), "cell_volume_A3": search["cell_volume_A3"],
        "a_A": search["a"], "b_A": search["b"], "c_A": search["c"],
        "alpha_deg": search["alpha"], "beta_deg": search["beta"], "gamma_deg": search["gamma"],
        "grid_dimensions": f"{search['grid_density']}x{search['grid_density']}x{search['grid_density']}",
        "grid_spacing_A": search["grid_spacing_A"], "candidate_site_count": search["candidate_site_count"],
        "species_radii_A": json.dumps(radii, sort_keys=True),
        "pair_minimum_distances_A": json.dumps(thresholds, sort_keys=True),
        "proximity_constraint": "proximity.atomic_radii(scale=1.0, allow_self_overlap=false)",
        "hard_distance_policy": "for every i<j, forbid species assignment when ASE MIC distance < radius sum",
        "hard_periodic_image_handling": "ASE minimum-image distance for distinct candidate sites only; i==i periodic self-images not constrained",
        "hard_composition_constraints": "exact species counts + exactly one species/vacancy per site + exact vacancy count",
        "family_constraints": "NONE", "symmetry_constraints": "NONE",
        "structured_family": structured.get("family_intent", ""),
        "spp_required_pairs": len(pairs),
        "spp_locally_usable_pairs": sum(row["request_evidence_status"] == "REQUEST_USABLE" for row in pairs),
        "spp_selected_sources": ";".join(f"{row['species_pair']}={row['selected_pot_source']}" for row in pairs),
        "spp_enters_feasibility": False,
        "solver_config": json.dumps(solver, sort_keys=True),
        "solver_result_path": str((run / "qlip" / "solver_result.json").resolve()),
    }


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"audit output already exists; refusing overwrite: {OUT}")
    IIS.mkdir(parents=True)
    configs = []
    compatibility = []
    feasibility = []
    iis_rows = []
    for task_id, formula in CASES.items():
        config = case_config(task_id, formula)
        configs.append(config)
        compatibility.extend(compatibility_rows(task_id, formula, read_json(V1 / "runs" / task_id / "qlip" / "search_space.json")))
        if task_id not in INFEASIBLE:
            feasibility.append({
                "task_id": task_id, "formula": formula, "hard_model_status": "FEASIBLE_PROVEN_BY_FROZEN_OPTIMAL_RUN",
                "v1_solver_status": config["v1_solver_status"], "iis_constraint_count": 0,
            })
            continue
        model, metadata, _, _ = build_hard_model(
            formula, read_json(V1 / "runs" / task_id / "qlip" / "search_space.json"),
        )
        model.optimize()
        if model.Status != GRB.INFEASIBLE:
            raise RuntimeError(f"hard-model reconstruction for {formula} was not infeasible: status={model.Status}")
        model.computeIIS()
        ilp_path = IIS / f"{formula}.ilp"
        model.write(str(ilp_path))
        selected = [constraint for constraint in model.getConstrs() if constraint.IISConstr]
        feasibility.append({
            "task_id": task_id, "formula": formula, "hard_model_status": "INFEASIBLE",
            "v1_solver_status": config["v1_solver_status"], "model_variables": model.NumVars,
            "model_constraints": model.NumConstrs, "iis_constraint_count": len(selected),
            "iis_path": str(ilp_path.resolve()),
        })
        for constraint in selected:
            item = metadata[constraint.ConstrName]
            iis_rows.append({
                "formula": formula, "constraint_name": item.name,
                "constraint_type": item.constraint_type, "species": item.species,
                "site_or_pair": item.site_or_pair, "lower_bound": item.lower_bound,
                "upper_bound": item.upper_bound, "distance": item.distance,
                "radius_or_threshold": item.radius_or_threshold,
                "interpretation": item.interpretation,
            })
        for variable in model.getVars():
            if variable.IISLB or variable.IISUB:
                iis_rows.append({
                    "formula": formula, "constraint_name": variable.VarName,
                    "constraint_type": "VARIABLE_BOUND", "species": variable.VarName.split("__")[1],
                    "site_or_pair": variable.VarName.split("__")[-1],
                    "lower_bound": variable.LB if variable.IISLB else None,
                    "upper_bound": variable.UB if variable.IISUB else None,
                    "distance": None, "radius_or_threshold": None,
                    "interpretation": "binary variable bound participates in the IIS",
                })
    write_csv(OUT / "CASE_CONFIG_COMPARISON.csv", configs)
    write_csv(OUT / "PAIR_COMPATIBILITY_COUNTS.csv", compatibility)
    write_csv(OUT / "SITE_FEASIBILITY_SUMMARY.csv", feasibility)
    write_csv(OUT / "IIS_SUMMARY.csv", iis_rows)

    by_formula = {formula: [row for row in compatibility if row["formula"] == formula] for formula in CASES.values()}
    ca = by_formula["CaTiO3"]
    ba = by_formula["BaTiO3"]
    comparison = [
        "# CaTiO3 vs BaTiO3 frozen hard-model comparison", "",
        "Both cases have the same 89.93449651590149 A^3 cubic cell, a=b=c=4.480317269262231 A, "
        "4x4x4 grid, 64 candidate sites, exact ABX3 counts, no family constraint, and no symmetry constraint.", "",
        "The first mathematical difference is the A-site radius: Ca=1.76 A versus Ba=2.15 A. "
        "This raises every Ba-containing exclusion threshold while leaving the grid unchanged.", "",
        "| Pair role | Ca case allowed/total | Ba case allowed/total |", "|---|---:|---:|",
    ]
    for ca_row, ba_row in zip(ca, ba, strict=True):
        comparison.append(
            f"| {ca_row['species_a']}-{ca_row['species_b']} / {ba_row['species_a']}-{ba_row['species_b']} "
            f"| {ca_row['allowed_candidate_pairs']}/{ca_row['total_candidate_pairs']} "
            f"| {ba_row['allowed_candidate_pairs']}/{ba_row['total_candidate_pairs']} |"
        )
    comparison.extend([
        "", "SPP values do not enter any hard constraint. Periodic hard geometry uses the minimum-image "
        "distance between distinct grid sites; SPP objective coefficients separately enumerate all images within 10 A.",
    ])
    (OUT / "CaTiO3_vs_BaTiO3.md").write_text("\n".join(comparison) + "\n", encoding="utf-8")
    (OUT / "AUDIT_METHOD.md").write_text(
        "# Infeasibility audit method\n\nThe reconstruction preserves the exact v1 discrete feasible region: "
        "same formula, cubic cell, uniform grid, QLIP radius registry, scale-1 atomic-radii exclusions, "
        "stoichiometry, site exclusivity, vacancy count, and minimum-image distances. The SPP quadratic "
        "objective is deliberately replaced by zero for IIS/feasibility because an objective cannot change "
        "the feasible set. Gurobi uses the frozen 300 s, gap 0, one-thread, NonConvex=2 settings.\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
