from crystal_db.benchmark_freeze import build_target_evidence_pools, select_diverse_targets


def row(key, formula, hull=0):
    return {
        "candidate_key": key,
        "formula": formula,
        "summary": {"is_stable": hull == 0, "energy_above_hull": hull},
    }


def test_selection_is_diverse_deterministic_and_removes_equivalent_aliases():
    rows = [
        row("a1", "LiCoO2"),
        row("a2", "LiCoO2", 0.1),
        row("b1", "NaFeO2"),
        row("b2", "NaFeO2", 0.2),
        row("alias", "LiCoO2"),
    ]
    groups = [{"candidate_keys": ["a1", "alias"]}]

    selected = select_diverse_targets(rows, count=4, equivalent_groups=groups)

    assert [item["candidate_key"] for item in selected] == ["a1", "b1", "a2", "b2"]


def test_target_and_all_equivalents_are_excluded_from_evidence():
    rows = [row("target", "LiNiO2"), row("equivalent", "LiNiO2"), row("evidence", "NaCoO2")]
    groups = [{"candidate_keys": ["target", "equivalent"]}]

    pools = build_target_evidence_pools([rows[0]], rows, groups)

    assert pools[0]["excluded_candidate_keys"] == ["equivalent", "target"]
    assert pools[0]["eligible_evidence_candidate_keys"] == ["evidence"]
    assert pools[0]["no_target_leakage"]


def test_selection_excludes_engineering_keys_and_their_representatives():
    rows = [row("engineering", "LiCoO2"), row("alias", "LiCoO2"), row("new", "NaFeO2")]
    groups = [{"candidate_keys": ["engineering", "alias"]}]

    selected = select_diverse_targets(
        rows, count=1, equivalent_groups=groups, excluded_candidate_keys={"engineering", "alias"},
    )

    assert [item["candidate_key"] for item in selected] == ["new"]
