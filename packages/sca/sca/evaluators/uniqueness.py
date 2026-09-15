"""Duplicate grouping with pymatgen StructureMatcher."""

from __future__ import annotations

from pymatgen.core import Structure
from pymatgen.analysis.structure_matcher import StructureMatcher

from sca.schemas import CrystalEvalRecord
from sca.scoring import compute_rank_score


def assign_duplicate_groups(
    records: list[CrystalEvalRecord],
    structures: dict[str, Structure],
) -> list[CrystalEvalRecord]:
    matcher = StructureMatcher(
        ltol=0.2,
        stol=0.3,
        angle_tol=5,
        primitive_cell=True,
        scale=True,
        attempt_supercell=True,
    )
    groups: list[list[CrystalEvalRecord]] = []
    group_structures: list[Structure] = []

    for record in records:
        structure = structures.get(record.input_path)
        if not record.parse_ok or structure is None:
            continue
        placed = False
        for group_index, representative in enumerate(group_structures):
            if matcher.fit(structure, representative):
                groups[group_index].append(record)
                placed = True
                break
        if not placed:
            groups.append([record])
            group_structures.append(structure)

    updates: dict[str, CrystalEvalRecord] = {}
    for index, group in enumerate(groups, start=1):
        group_id = f"dup-{index:04d}"
        group_size = len(group)
        for member_index, record in enumerate(group):
            updated = record.model_copy(
                update={
                    "duplicate_group_id": group_id,
                    "is_duplicate": group_size > 1,
                    "is_unique_representative": member_index == 0,
                    "num_duplicates_in_group": group_size,
                }
            )
            updated = updated.model_copy(update={"pre_dft_rank_score": compute_rank_score(updated)})
            updates[record.input_path] = updated

    return [updates.get(record.input_path, record) for record in records]
