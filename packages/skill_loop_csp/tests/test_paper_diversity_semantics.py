from scripts.paper_diversity_semantics import is_substitution_sensitive, substitution_operation


def _task(prompt: str, *, structured: bool = True) -> dict:
    return {
        "natural_language_request": prompt,
        "intent_axes": {"substitution_site": structured},
        "substitution": {
            "from_species": "Mg",
            "to_species": "Li",
            "target_orbit": "Mg cation orbit",
            "charge_compensation_policy": "composition fixed; compensation validation required",
        } if structured else {},
    }


def test_substitute_li_for_mg_counts_from_structured_operation() -> None:
    assert is_substitution_sensitive(_task("substitute Li for Mg"))


def test_replace_mg_with_li_counts_from_structured_operation() -> None:
    assert is_substitution_sensitive(_task("replace Mg with Li"))


def test_li_occupies_mg_orbit_counts_from_structured_operation() -> None:
    operation = substitution_operation(_task("Li occupies the Mg orbit"))
    assert operation is not None
    assert operation["from_species"] == "Mg"
    assert operation["to_species"] == "Li"
    assert operation["target_orbit"] == "Mg cation orbit"


def test_doped_word_without_structured_operation_does_not_count() -> None:
    assert not is_substitution_sensitive(_task("Generate a doped oxide", structured=False))


def test_non_substitution_task_does_not_count() -> None:
    assert not is_substitution_sensitive({
        "natural_language_request": "Generate rocksalt NiO",
        "intent_axes": {"substitution_site": False},
        "substitution": {},
    })

