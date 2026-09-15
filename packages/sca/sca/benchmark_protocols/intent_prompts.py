"""Seeded intent-prompt manifest generation for full E2E benchmarks."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pandas as pd


INTENT_COLUMNS = [
    "run_index",
    "prompt_id",
    "seed",
    "benchmark_mode",
    "input_text",
    "target_formula",
    "target_structure_family",
    "target_space_group",
    "target_crystal_system",
    "chemistry_family",
    "challenge_type",
    "intent_specificity",
    "expected_formula_terms",
    "expected_family_terms",
    "expected_coordination_terms",
    "expected_connectivity_terms",
    "expected_motifs_or_priors",
    "intent_constraints_json",
    "reference_cif_path",
    "num_attempts",
    "skill_loop_archive_dir",
    "notes",
]

MODE_COUNTS_100 = {
    "loose_design_intent": 30,
    "motif_specific": 25,
    "retrieval_evidence_grounded": 15,
    "solver_constraint_heavy": 15,
    "adversarial_or_infeasible": 10,
    "repair_or_diagnostic": 5,
}


_TEMPLATES = [
    {
        "formula": "BaTiO3",
        "family": "perovskite",
        "space_group": "Pm-3m or subgroup",
        "crystal_system": "cubic/tetragonal",
        "chemistry": "oxide perovskites",
        "coordination": "TiO6 octahedra",
        "connectivity": "corner-sharing octahedra",
        "motifs": ["corner-sharing TiO6 octahedra"],
    },
    {
        "formula": "CsPbBr3",
        "family": "halide perovskite",
        "space_group": "Pm-3m or subgroup",
        "crystal_system": "cubic/orthorhombic",
        "chemistry": "halide perovskites",
        "coordination": "PbBr6 octahedra",
        "connectivity": "corner-sharing octahedra",
        "motifs": ["PbBr6 octahedra"],
    },
    {
        "formula": "ZnFe2O4",
        "family": "spinel",
        "space_group": "Fd-3m",
        "crystal_system": "cubic",
        "chemistry": "spinels",
        "coordination": "ZnO4 tetrahedra and FeO6 octahedra",
        "connectivity": "spinel cation sublattices",
        "motifs": ["ZnO4 tetrahedra", "FeO6 octahedra"],
    },
    {
        "formula": "NiO",
        "family": "rocksalt",
        "space_group": "Fm-3m",
        "crystal_system": "cubic",
        "chemistry": "rocksalt/halides",
        "coordination": "NiO6 octahedra",
        "connectivity": "edge-sharing octahedral network",
        "motifs": ["octahedral Ni coordination"],
    },
    {
        "formula": "CeO2",
        "family": "fluorite",
        "space_group": "Fm-3m",
        "crystal_system": "cubic",
        "chemistry": "fluorites",
        "coordination": "CeO8 cubic coordination",
        "connectivity": "fluorite anion sublattice",
        "motifs": ["CeO8 coordination"],
    },
    {
        "formula": "FeS2",
        "family": "pyrite",
        "space_group": "Pa-3",
        "crystal_system": "cubic",
        "chemistry": "pyrites",
        "coordination": "FeS6 octahedra",
        "connectivity": "S-S dumbbell motifs",
        "motifs": ["FeS6 octahedra", "S-S dumbbells"],
    },
    {
        "formula": "LiCoO2",
        "family": "layered oxide",
        "space_group": "R-3m",
        "crystal_system": "trigonal",
        "chemistry": "layered oxides/chalcogenides",
        "coordination": "CoO6 octahedra",
        "connectivity": "layered edge-sharing slabs",
        "motifs": ["layered CoO2 slabs"],
    },
    {
        "formula": "LiFePO4",
        "family": "olivine phosphate",
        "space_group": "Pnma",
        "crystal_system": "orthorhombic",
        "chemistry": "phosphates/NASICON/olivines",
        "coordination": "FeO6 octahedra and PO4 tetrahedra",
        "connectivity": "olivine phosphate framework",
        "motifs": ["PO4 tetrahedra", "FeO6 octahedra"],
    },
    {
        "formula": "Li6PS5Cl",
        "family": "argyrodite",
        "space_group": "F-43m",
        "crystal_system": "cubic",
        "chemistry": "sulfide solid electrolytes",
        "coordination": "PS4 tetrahedra",
        "connectivity": "lithium conduction framework",
        "motifs": ["PS4 tetrahedra"],
    },
    {
        "formula": "TiN",
        "family": "nitride",
        "space_group": "Fm-3m",
        "crystal_system": "cubic",
        "chemistry": "borides/carbides/nitrides",
        "coordination": "TiN6 octahedra",
        "connectivity": "rocksalt-like nitride network",
        "motifs": ["TiN6 octahedra"],
    },
]


def build_intent_prompt_manifest(
    *,
    out_csv: str | Path,
    out_json: str | Path | None,
    seed: int,
    num_prompts: int,
) -> dict[str, Any]:
    rows = generate_intent_prompt_rows(seed=seed, num_prompts=num_prompts)
    csv_path = Path(out_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=INTENT_COLUMNS).to_csv(csv_path, index=False)
    json_path = Path(out_json) if out_json else None
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps({"seed": seed, "rows": rows}, indent=2), encoding="utf-8")
    return {"rows": len(rows), "csv": str(csv_path), "json": str(json_path) if json_path else None}


def generate_intent_prompt_rows(*, seed: int, num_prompts: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    modes = _mode_sequence(num_prompts)
    rows = []
    for index, mode in enumerate(modes, start=1):
        template = _TEMPLATES[(index - 1) % len(_TEMPLATES)]
        row = _row(index, seed, mode, template)
        rows.append(row)
    rng.shuffle(rows)
    rows.sort(key=lambda row: int(row["run_index"]))
    return rows


def _mode_sequence(num_prompts: int) -> list[str]:
    if num_prompts == 100:
        return [mode for mode, count in MODE_COUNTS_100.items() for _ in range(count)]
    base = list(MODE_COUNTS_100)
    return [base[index % len(base)] for index in range(num_prompts)]


def _row(index: int, seed: int, mode: str, template: dict[str, Any]) -> dict[str, Any]:
    constraints = {
        "formula": template["formula"],
        "structure_family": template["family"],
        "space_group": template["space_group"],
        "crystal_system": template["crystal_system"],
        "required_motifs": template["motifs"],
        "forbidden_contacts": [],
        "min_distance_rules": [],
        "expected_solver_status": _expected_status(mode),
    }
    if mode == "adversarial_or_infeasible":
        constraints["min_distance_rules"] = [{"pair": "*-*", "max_distance": 1.0}]
        prompt = (
            f"Generate {template['formula']} {template['family']} while forcing every cation-anion "
            "distance below 1.0 Angstrom; reject the request if it is physically infeasible."
        )
        challenge = "adversarial impossible request"
    elif mode == "solver_constraint_heavy":
        prompt = (
            f"Generate {template['family']} {template['formula']} with a solver-backed archive containing "
            "solver status, objective value, active constraints, and generated CIF."
        )
        challenge = "solver-backed constraints"
    elif mode == "retrieval_evidence_grounded":
        prompt = (
            f"Generate a {template['family']}-like {template['formula']} candidate using retrieved "
            f"{template['chemistry']} evidence. Record which retrieved structures informed the constraints."
        )
        challenge = "retrieval grounded"
    elif mode == "motif_specific":
        prompt = (
            f"Generate a {template['family']}-like {template['formula']} candidate that preserves "
            f"{', '.join(template['motifs'])}."
        )
        challenge = "motif preservation"
    elif mode == "repair_or_diagnostic":
        prompt = (
            f"Generate a {template['formula']} {template['family']} candidate and, if bad contacts are "
            "detected, emit diagnostics explaining which constraints should be tightened."
        )
        challenge = "repair diagnostics"
    else:
        prompt = (
            f"Generate a plausible {template['formula']} {template['chemistry']} candidate with the "
            f"requested chemistry and broad {template['family']}-like design intent."
        )
        challenge = "loose natural-language design"
    return {
        "run_index": index,
        "prompt_id": f"intent_{index:03d}_{_slug(template['formula'])}_{_slug(template['family'])}",
        "seed": seed,
        "benchmark_mode": mode,
        "input_text": prompt,
        "target_formula": template["formula"],
        "target_structure_family": template["family"],
        "target_space_group": template["space_group"],
        "target_crystal_system": template["crystal_system"],
        "chemistry_family": template["chemistry"],
        "challenge_type": challenge,
        "intent_specificity": _specificity(mode),
        "expected_formula_terms": template["formula"],
        "expected_family_terms": template["family"],
        "expected_coordination_terms": template["coordination"],
        "expected_connectivity_terms": template["connectivity"],
        "expected_motifs_or_priors": "; ".join(template["motifs"]),
        "intent_constraints_json": json.dumps(constraints, sort_keys=True),
        "reference_cif_path": "",
        "num_attempts": 1,
        "skill_loop_archive_dir": "",
        "notes": "",
    }


def _expected_status(mode: str) -> str:
    if mode == "adversarial_or_infeasible":
        return "infeasible_or_invalid"
    if mode == "solver_constraint_heavy":
        return "expected_solver_backed_candidate"
    return "expected_valid"


def _specificity(mode: str) -> str:
    return {
        "loose_design_intent": "low",
        "motif_specific": "medium",
        "retrieval_evidence_grounded": "medium",
        "solver_constraint_heavy": "high",
        "adversarial_or_infeasible": "high",
        "repair_or_diagnostic": "medium",
    }[mode]


def _slug(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())
