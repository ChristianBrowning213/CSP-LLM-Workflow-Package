"""Build the pre-extension paper_diversity_v2 capability-blocker audit.

The frozen task manifests are read-only inputs.  This audit deliberately
separates an existing preflight label from the Ticket 2 real-smoke gate.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "paper_diversity_v2"
OUT = ROOT / "artifacts" / "paper_diversity_v2" / "representability"

TASK_FILES = (
    "EXP1_BASIC_TASKS.csv",
    "EXP2_COMMON_DESIRES_TASKS.csv",
    "EXP3_HALIDE_TASKS.csv",
    "EXP4_NASICON_32_TASKS.csv",
)

ALLOWED_BLOCKERS = {
    "MISSING_SCAFFOLD",
    "MISSING_LATTICE_CANDIDATE",
    "MISSING_ORBIT_TEMPLATE",
    "STOICHIOMETRY_NOT_REPRESENTABLE",
    "VACANCY_STATE_UNSUPPORTED",
    "MIXED_SPECIES_ALLOCATION_UNSUPPORTED",
    "COUPLED_ALLOCATION_UNSUPPORTED",
    "MULTIPLE_SCAFFOLDS_UNSUPPORTED",
    "TOP_K_UNSUPPORTED",
    "REFERENCE_ASSIGNMENT_EXCLUSION_UNSUPPORTED",
    "SYMMETRY_EQUIVALENCE_DEDUP_UNSUPPORTED",
    "CHARGE_BALANCE_POLICY_UNSUPPORTED",
    "TOPOLOGY_VALIDATOR_MISSING",
    "OTHER",
}

# These are the fixed or narrowly variable prototype-scaffold paths observed
# in the current integration before Ticket 2.  They are not the new versioned
# QLIP scaffold registry requested by this ticket.
OBSERVED_SCAFFOLDS = {
    "rocksalt",
    "fluorite",
    "spinel_mgal2o4",
    "perovskite",
    "pyrite",
    "layered_oxide",
    "olivine_phosphate",
    "nitride",
    "argyrodite",
    "halide_perovskite",
    "halide_perovskite_cspbcl3",
    "halide_perovskite_cspbi3",
    "halide_perovskite_cssnbr3",
}


def read_tasks() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name in TASK_FILES:
        with (BENCH / name).open(encoding="utf-8", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    if len(rows) != 82:
        raise AssertionError(f"expected 82 frozen tasks, found {len(rows)}")
    return rows


def _structured_substitution(row: dict[str, str]) -> bool:
    try:
        axes = json.loads(row.get("intent_axes") or "{}")
        operation = json.loads(row.get("substitution") or "{}")
    except json.JSONDecodeError:
        return False
    required = ("from_species", "to_species", "target_orbit", "charge_compensation_policy")
    return axes.get("substitution_site") is True and all(operation.get(key) for key in required)


def blockers_for(row: dict[str, str]) -> list[str]:
    blockers: set[str] = set()
    scaffold = row["scaffold_hypotheses"].strip()
    variable = row["variable_species_orbits"].strip().lower()
    vacancy = row["vacancy_ordering_requirement"].strip().lower()
    mixed_anion = row["mixed_anion_ordering_requirement"].strip().lower()
    ordering = row["site_ordering_requirement"].strip().lower()
    lattice = row["lattice_candidate_policy"].strip().lower()
    task_id = row["task_id"]
    requested_k = int(row["requested_distinct_solutions"])

    if scaffold not in OBSERVED_SCAFFOLDS:
        blockers.add("MISSING_SCAFFOLD")
    if "new " in lattice or "candidate" in lattice and scaffold not in OBSERVED_SCAFFOLDS:
        blockers.add("MISSING_LATTICE_CANDIDATE")
    if variable != "none" and scaffold not in OBSERVED_SCAFFOLDS:
        blockers.add("MISSING_ORBIT_TEMPLATE")
    if variable != "none" or mixed_anion != "none":
        blockers.add("MIXED_SPECIES_ALLOCATION_UNSUPPORTED")
    if vacancy != "none" or "vacancy" in variable:
        blockers.add("VACANCY_STATE_UNSUPPORTED")
    if ";" in variable or "coupled" in ordering or task_id.startswith("E4_G"):
        blockers.add("COUPLED_ALLOCATION_UNSUPPORTED")
    if "multiple" in scaffold or task_id == "E4_H4":
        blockers.add("MULTIPLE_SCAFFOLDS_UNSUPPORTED")
    if requested_k > 1:
        blockers.update({"TOP_K_UNSUPPORTED", "SYMMETRY_EQUIVALENCE_DEDUP_UNSUPPORTED"})
    if "exclude" in scaffold or "exclude" in ordering or task_id == "E4_H3":
        blockers.add("REFERENCE_ASSIGNMENT_EXCLUSION_UNSUPPORTED")
    if _structured_substitution(row) or "charge" in ordering or "charge" in vacancy:
        blockers.add("CHARGE_BALANCE_POLICY_UNSUPPORTED")
    if row["experiment_id"] == "EXP4_NASICON":
        blockers.add("TOPOLOGY_VALIDATOR_MISSING")

    # Existing fixed prototypes require no new allocation capability, but a
    # task is still not Ticket-2 supported until its real smoke row exists.
    if row["qlip_representability_status"] != "SUPPORTED_NOW" and not blockers:
        blockers.add("OTHER")

    if not blockers and row["qlip_representability_status"] == "SUPPORTED_NOW":
        return []
    if not blockers.issubset(ALLOWED_BLOCKERS):
        raise AssertionError(sorted(blockers - ALLOWED_BLOCKERS))
    return sorted(blockers)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    tasks = read_tasks()
    audit: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in tasks:
        blockers = blockers_for(row)
        counts.update(blockers)
        audit.append(
            {
                "task_id": row["task_id"],
                "experiment_id": row["experiment_id"],
                "target_formula": row["target_formula"],
                "scaffold_hypotheses": row["scaffold_hypotheses"],
                "preflight_representability_label": row["qlip_representability_status"],
                "blocker_count": len(blockers),
                "missing_capabilities": ";".join(blockers),
                "real_smoke_gate": "NOT_RUN",
                "ticket2_support_status": "NOT_YET_SUPPORTED_REAL_SOLVE",
            }
        )
    fields = list(audit[0])
    write_csv(OUT / "TASK_CAPABILITY_BLOCKERS.csv", audit, fields)
    write_csv(OUT / "E4_CAPABILITY_BLOCKERS.csv", [r for r in audit if r["experiment_id"] == "EXP4_NASICON"], fields)

    (OUT / "CAPABILITY_DEPENDENCY_GRAPH.md").write_text(
        """# Ticket 2 capability dependency graph

This graph records pre-extension dependencies. A schema-valid request is not a supported task.

```text
verified source CIF + immutable hash
  -> versioned scaffold registry
     -> lattice + fractional sites + symmetry-orbit decomposition
        -> composition/orbit-multiplicity preflight
           -> ordered occupation MILP
              -> explicit chemistry/charge preflight
                 -> real solve + decoded CIF
                    -> topology/formula validation
                       -> real-smoke support status

multi-scaffold request
  -> per-scaffold compatibility and independent solve
  -> explicit scale-safe selection policy

top-k request
  -> feasible assignment
  -> canonical CIF/hash/StructureMatcher deduplication
  -> no-good cut
  -> next assignment or exhaustion

known-assignment exclusion
  -> resolved reference occupation
  -> exact assignment no-good cut
```

The 24-task pilot depends on 24 successful real-smoke rows; it does not depend on preflight labels alone.
""",
        encoding="utf-8",
    )

    count_lines = "\n".join(f"- {key}: **{value} tasks**" for key, value in sorted(counts.items()))
    (OUT / "IMPLEMENTATION_WAVES.md").write_text(
        f"""# Ticket 2 implementation waves

## Pre-extension blocker counts

{count_lines}

## Wave 1 — generic scaffold and occupation core

- Tasks targeted first: E4_A1, E4_A2, E4_A3, E4_A4, E4_C1, E4_C2, E4_C4, E4_F2.
- Modules: `qlip.scaffolds.schema`, `qlip.scaffolds.registry`, generic occupation/chemistry preflight, and the QLIP allocation model.
- Semantics: immutable source-CIF provenance; exact orbit multiplicities; fixed/variable/full/empty orbit states; exact composition; explicit charge policy.
- Model impact: one binary per allowed species/site; orbit-closure equalities; exact species-count equalities; fixed/empty-orbit equalities.
- Tests: registry provenance, binary Si/P, phosphate-only, three species, vacancies, allowlists, impossible stoichiometry, fixed-plus-variable, explicit charge.
- Scope: generic; composition-specific solver branches are rejected.

## Wave 2 — multi-hypothesis and diversity controls

- Tasks unlocked: multi-scaffold and requested-k rows whose scaffolds are otherwise representable, including known-assignment exclusion cases.
- Modules: generic multi-scaffold coordinator, top-k enumerator, assignment canonicalizer, and reference-exclusion compiler.
- Semantics: independently validated scaffold attempts; no cross-SPP raw-objective comparison without a common scale; exact no-good cuts; hash and StructureMatcher deduplication.
- Model impact: one independent model per scaffold; one no-good constraint per accepted/excluded assignment.
- Tests: k reachable, hash duplicate, symmetry equivalent, exhausted space, and reference exclusion.
- Scope: generic.

## Wave 3 — coupled NASICON allocation (after a frozen 24-task pilot)

- Tasks targeted: E4 groups B, D, G, and H not unlocked by Waves 1–2.
- Semantics: ordered sodium vacancies, mixed framework cations, coupled Na/framework/tetrahedral allocation, and multi-orbit charge compensation.
- Model impact: additional allowed-state binaries and coupled count/charge equalities; top-3/top-5 enumeration may add multiple no-good cuts.
- Scope: generic; explicitly deferred by Ticket 2 until the pilot is frozen.
""",
        encoding="utf-8",
    )
    print(json.dumps({"tasks": len(audit), "e4": sum(r["experiment_id"] == "EXP4_NASICON" for r in audit), "blockers": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
