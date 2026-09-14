"""Tests for chemistry-dependent covalent-like contact exclusion."""

from __future__ import annotations

from pathlib import Path

from ase import Atoms

from spp_maker.covalent_filter import has_covalent_like_contact, load_covalent_rules


def test_covalent_exclusion_triggers_for_forbidden_short_pair(tmp_path: Path) -> None:
    rules_csv = tmp_path / "rules.csv"
    rules_csv.write_text(
        "elem1,elem2,min_dist\n"
        "O,H,1.30\n",
        encoding="utf-8",
    )
    rules = load_covalent_rules(rules_csv)

    atoms_short = Atoms(
        symbols=["H", "O"],
        positions=[[0.0, 0.0, 0.0], [1.10, 0.0, 0.0]],
        cell=[10.0, 10.0, 10.0],
        pbc=True,
    )
    atoms_safe = Atoms(
        symbols=["H", "O"],
        positions=[[0.0, 0.0, 0.0], [1.60, 0.0, 0.0]],
        cell=[10.0, 10.0, 10.0],
        pbc=True,
    )

    hit_short, info_short = has_covalent_like_contact(atoms_short, rules)
    hit_safe, info_safe = has_covalent_like_contact(atoms_safe, rules)

    assert hit_short
    assert info_short["pair_key"] == "H-O"
    assert info_short["threshold"] == 1.3
    assert info_short["atom_indices"] == [0, 1]
    assert info_short["matched_rule"]["source_id"].endswith(":2")

    assert not hit_safe
    assert info_safe == {}
