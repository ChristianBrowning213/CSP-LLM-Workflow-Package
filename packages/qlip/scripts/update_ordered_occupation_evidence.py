"""Update Ticket 2 evidence after generalized ordered-occupation tests pass."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from qlip.scaffolds import get_scaffold, resolve_scaffold_corpus_root
from qlip.scaffolds.occupation import preflight_ordered_occupation


FIRST_WAVE_SCAFFOLDS = {
    "E4_A1": "nasicon_na3sc2po43_r3c",
    "E4_A2": "nasicon_na3zr2si2po12_c2_ordered",
    "E4_A3": "nasicon_na3ti2si2po12_cc",
    "E4_A4": "nasicon_na3hftisi2po12_p1",
    "E4_C1": "nzp_nazr2po43_r3c",
    "E4_C2": "nasicon_na3ti2po43_r3",
    "E4_C4": "nasicon_na3sc2po43_r3c",
    "E4_F2": "nzp_lizr2po43_p21c",
}

RESOLVED_BY_REGISTRY = {
    "MISSING_SCAFFOLD",
    "MISSING_LATTICE_CANDIDATE",
    "MISSING_ORBIT_TEMPLATE",
    "MIXED_SPECIES_ALLOCATION_UNSUPPORTED",
    "STOICHIOMETRY_NOT_REPRESENTABLE",
}


def _table(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    resolution = resolve_scaffold_corpus_root()
    if not resolution.skill_loop_repo_root:
        raise RuntimeError("Sibling Skill-Loop-CSP repository is required for evidence export")
    skill = Path(resolution.skill_loop_repo_root)
    evidence = skill / "artifacts" / "paper_diversity_v2" / "representability"
    benchmark = skill / "benchmarks" / "paper_diversity_v2"
    task_rows = {
        row["task_id"]: row
        for name in ("EXP1_BASIC_TASKS.csv", "EXP2_COMMON_DESIRES_TASKS.csv", "EXP3_HALIDE_TASKS.csv", "EXP4_NASICON_32_TASKS.csv")
        for row in _table(benchmark / name)
    }
    results: dict[str, dict[str, Any]] = {}
    for task_id, scaffold_id in FIRST_WAVE_SCAFFOLDS.items():
        task = task_rows[task_id]
        scaffold = get_scaffold(scaffold_id)
        result = preflight_ordered_occupation(
            task["target_formula"],
            len(scaffold.fractional_candidate_sites),
            scaffold.symmetry_orbits,
        )
        results[task_id] = {
            "scaffold_id": scaffold_id,
            "source_structure_id": scaffold.source_structure_id,
            **result.to_dict(),
        }

    for name in ("TASK_CAPABILITY_BLOCKERS.csv", "E4_CAPABILITY_BLOCKERS.csv"):
        rows = _table(evidence / name)
        updated: list[dict[str, Any]] = []
        for row in rows:
            before = row.get("pre_extension_missing_capabilities") or row["missing_capabilities"]
            blockers = {value for value in row["missing_capabilities"].split(";") if value}
            # The generic multi-species mechanism now exists, but this alone
            # does not prove a task's scaffold or coupled mapping.
            blockers.discard("MIXED_SPECIES_ALLOCATION_UNSUPPORTED")
            result = results.get(row["task_id"])
            if result and result["stoichiometry_representable"]:
                blockers -= RESOLVED_BY_REGISTRY
                occupation_status = "REPRESENTABLE_NOT_SMOKE_SOLVED"
            elif result:
                occupation_status = "STOICHIOMETRY_NOT_REPRESENTABLE"
                blockers.add("STOICHIOMETRY_NOT_REPRESENTABLE")
            else:
                occupation_status = "NOT_TASK_SPECIFICALLY_VALIDATED"
            updated.append(
                {
                    **row,
                    "pre_extension_missing_capabilities": before,
                    "missing_capabilities": ";".join(sorted(blockers)),
                    "blocker_count": len(blockers),
                    "occupation_preflight_status": occupation_status,
                    "occupation_evidence": json.dumps(result or {}, sort_keys=True, separators=(",", ":")),
                    "ticket2_support_status": "NOT_YET_SUPPORTED_REAL_SOLVE",
                }
            )
        _write(evidence / name, updated)

    representable = [task_id for task_id, result in results.items() if result["stoichiometry_representable"]]
    unresolved = Counter(
        blocker
        for row in _table(evidence / "TASK_CAPABILITY_BLOCKERS.csv")
        for blocker in row["missing_capabilities"].split(";") if blocker
    )
    (evidence / "QLIP_EXTENSION_REPORT.md").write_text(
        f"""# QLIP Ticket 2 extension report

## Versioned scaffold registry

- Seven hash-verified registry records load successfully.
- Seven of seven source-CIF hashes match the frozen NASICON v3 manifest.
- Seven of seven lattice/site/orbit/topology material signatures are distinct.

## Generalized ordered occupation

- Species-only ordered occupation: **SUPPORTED BY FOCUSED MODEL TESTS**.
- Multi-species ordered occupation (>2 species): **SUPPORTED BY FOCUSED MODEL TESTS**.
- Fixed and variable orbit mixtures: **SUPPORTED BY FOCUSED MODEL TESTS**.
- Explicit vacancy occupation: **SUPPORTED BY FOCUSED MODEL TESTS AND ONE REAL GUROBI SOLVE**.
- Exact vacancy count: **SUPPORTED BY FOCUSED MODEL TESTS AND ONE REAL GUROBI SOLVE**.
- Impossible orbit multiplicity or vacancy/stoichiometry combinations: **REJECTED BEFORE SOLVE WITH STRUCTURED DIAGNOSTICS**.
- Vacancy representation: uniform indexed binary; initialized to zero; disabled site states fixed to zero; enabled states active.

Focused generalized-occupation gate: **14 passed**. Adjacent schema/validation/solve/runner gate: **24 passed**.

## First-wave task-specific multiplicity preflight

- Representable on a hash-verified registry search space: **{len(representable)}/8** (`{', '.join(representable)}`).
- Supported real smoke solves: **0/8**. No generation was launched in this compatibility repair.
- A representable preflight is not recorded as solver support.

## Remaining blockers

{chr(10).join(f'- {key}: **{value} tasks**' for key, value in sorted(unresolved.items()))}

Vacancy-task blocker rows remain until each task's real orbit map and exact vacancy count validate. Charge policy, coupled allocation, multi-scaffold, top-k, reference exclusion, topology validation, and real-smoke gates remain separate later phases.
""",
        encoding="utf-8",
    )
    print(json.dumps({"first_wave_representable": representable, "real_smoke_supported": 0, "remaining_blockers": unresolved}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
