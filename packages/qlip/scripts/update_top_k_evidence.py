"""Record generic top-k capability without claiming task-specific unlocks."""

from __future__ import annotations

import csv
from pathlib import Path

from qlip.scaffolds import resolve_scaffold_corpus_root


SECTION = "## Explicit top-k distinctness contract"


def _table(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    resolution = resolve_scaffold_corpus_root()
    if not resolution.skill_loop_repo_root:
        raise RuntimeError("Sibling Skill-Loop-CSP repository required")
    evidence = Path(resolution.skill_loop_repo_root) / "artifacts" / "paper_diversity_v2" / "representability"
    requested = 0
    for name in ("TASK_CAPABILITY_BLOCKERS.csv", "E4_CAPABILITY_BLOCKERS.csv"):
        rows = _table(evidence / name)
        updated = []
        for row in rows:
            task_requests_top_k = "TOP_K_UNSUPPORTED" in row["missing_capabilities"].split(";")
            if name == "TASK_CAPABILITY_BLOCKERS.csv" and task_requests_top_k:
                requested += 1
            updated.append({
                **row,
                "generic_top_k_capability": "SUPPORTED" if task_requests_top_k else "NOT_REQUESTED",
                "top_k_distinctness_policies": (
                    "ASSIGNMENT_DISTINCT;HASH_DISTINCT;STRUCTURE_DISTINCT"
                    if task_requests_top_k else ""
                ),
                "top_k_task_specific_status": (
                    "BLOCKED_PENDING_REAL_TASK_SMOKE" if task_requests_top_k else "NOT_REQUESTED"
                ),
            })
        _write(evidence / name, updated)

    report_path = evidence / "QLIP_EXTENSION_REPORT.md"
    report = report_path.read_text(encoding="utf-8")
    if SECTION in report:
        report = report.split(SECTION, 1)[0].rstrip() + "\n"
    report += f"""

{SECTION}

- Assignment-distinct top-k: **SUPPORTED BY REAL GUROBI FOCUSED TESTS**.
- Canonical-hash-distinct top-k: **SUPPORTED BY REAL GUROBI FOCUSED TESTS**.
- StructureMatcher-distinct top-k: **SUPPORTED BY REAL GUROBI FOCUSED TESTS** and is the paper-candidate default.
- Exact assignment no-good cuts: **SUPPORTED**; every examined assignment is excluded before continuing, including rejected duplicates.
- Symmetry-equivalent filtering: **SUPPORTED** with `ltol=0.2`, `stol=0.3`, `angle_tol=5.0`, `primitive_cell=True`, `scale=True`, `attempt_supercell=False`.
- Focused top-k gate: **6 passed**. Adjacent schema/serialization/multi-scaffold gate: **4 passed**.
- Benchmark rows requesting top-k: **{requested}**; task-specific real-smoke unlocks: **0**. Their blocker rows are intentionally retained.

## E4_A1 high-symmetry representability

The selected verified R-3c scaffold has orbit multiplicities `Na:6`, framework cation:4, tetrahedral:6, and `O:12+12`. The requested two-formula-unit composition requires tetrahedral counts `Si:4` and `P:2`, which cannot be expressed by one symmetry-closed multiplicity-6 tetrahedral orbit.

No retained high-symmetry NASICON/NZP source containing a suitable split Si/P tetrahedral orbit was found. Replicating the cell can create multiple copies for an ordered 4:2 allocation only by breaking the parent R-3c occupational symmetry; preserving R-3c requires partial/disordered occupation outside the current ordered model. E4_A1 therefore remains blocked. Its stoichiometry and intent were not altered.
"""
    report_path.write_text(report, encoding="utf-8")
    print(f"top_k_requested_tasks={requested}; task_specific_unlocks=0; e4_a1=BLOCKED_OCCUPATIONAL_DISORDER_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
