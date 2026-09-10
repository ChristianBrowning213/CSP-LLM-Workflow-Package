from llm_csp.spp import derive_required_pairs, parse_formula_elements
from llm_csp.spp.library import canonical_pair_label


def test_formula_species_and_unordered_self_cross_pairs():
    assert parse_formula_elements("A2BC3") == ["A", "B", "C"]
    assert derive_required_pairs(["A", "B", "C", "A"]) == [
        "A-A", "A-B", "A-C", "B-B", "B-C", "C-C"
    ]


def test_pair_canonicalization_is_case_insensitive_and_unordered():
    assert canonical_pair_label("Sr", "O") == "O-Sr"
    assert canonical_pair_label("O", "Sr") == "O-Sr"
    assert canonical_pair_label("Ti", "Ti") == "Ti-Ti"
