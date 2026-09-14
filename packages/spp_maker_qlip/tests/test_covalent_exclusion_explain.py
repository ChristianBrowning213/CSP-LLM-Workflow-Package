"""Explainability tests for covalent-like structure exclusion."""

from __future__ import annotations

from pathlib import Path

from ase import Atoms

from spp_maker.covalent_filter import has_covalent_like_contact, load_covalent_rules


def test_covalent_exclusion_reports_rule_pair_distance_and_indices(tmp_path: Path) -> None:
    rules_yaml = tmp_path / "rules.yaml"
    rules_yaml.write_text(
        "rules:\n"
        "  - elem1: Br\n"
        "    elem2: O\n"
        "    min_dist: 1.8\n"
        "  - elem1: S\n"
        "    elem2: O\n"
        "    min_dist: 1.6\n",
        encoding="utf-8",
    )
    rules = load_covalent_rules(rules_yaml)

    atoms = Atoms(
        symbols=["Br", "O", "Li"],
        positions=[[0.0, 0.0, 0.0], [1.7, 0.0, 0.0], [5.0, 5.0, 5.0]],
        cell=[10.0, 10.0, 10.0],
        pbc=True,
    )
    hit, info = has_covalent_like_contact(atoms, rules)

    assert hit
    assert info["pair_key"] == "Br-O"
    assert info["threshold"] == 1.8
    assert info["observed_min_distance"] < info["threshold"]
    assert info["atom_indices"] == [0, 1]
    matched_rule = info["matched_rule"]
    assert matched_rule["elem1"] == "Br"
    assert matched_rule["elem2"] == "O"
    assert matched_rule["min_dist"] == 1.8
    assert str(matched_rule["source_id"]).startswith(str(rules_yaml))
