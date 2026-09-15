"""Pre-DFT validity and ranking utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sca.schemas import CrystalEvalRecord


def compute_pre_dft_valid(record: "CrystalEvalRecord", require_spacegroup: bool = False) -> bool:
    valid = (
        record.parse_ok
        and record.target_formula_match is not False
        and record.multiplicity_consistent is not False
        and record.bond_lengths_reasonable is True
        and record.geometry_ok is True
    )
    if require_spacegroup:
        valid = valid and record.space_group_consistent is True
    return bool(valid)


def compute_rank_score(record: "CrystalEvalRecord") -> float:
    score = 0.0
    if not record.parse_ok:
        score += 1_000_000
    if record.target_formula_match is False:
        score += 100_000
    if record.bond_lengths_reasonable is not True:
        score += 50_000
    if record.geometry_ok is not True:
        score += 25_000
    if record.multiplicity_consistent is False:
        score += 25_000
    if record.space_group_consistent is False:
        score += 10_000
    if record.is_duplicate is True and record.is_unique_representative is False:
        score += 5_000
    score += record.num_bad_contacts * 100
    score += record.geometry_warning_count * 10
    if record.formation_energy_per_atom is not None:
        score += float(record.formation_energy_per_atom)
    elif record.pre_dft_valid:
        score += 1_000
    return float(score)
