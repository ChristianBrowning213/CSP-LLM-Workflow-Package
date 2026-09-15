from __future__ import annotations

import json

from scripts import run_full_100_skill_loop_benchmark as runner


def test_full_100_manifest_row_builds_structured_symmetry_task_spec() -> None:
    row = {
        "input_text": "Generate a plausible BaTiO3 oxide perovskites candidate.",
        "target_formula": "BaTiO3",
        "target_structure_family": "perovskite",
        "target_space_group": "Pm-3m or subgroup",
        "target_crystal_system": "cubic/tetragonal",
        "intent_constraints_json": json.dumps(
            {
                "formula": "BaTiO3",
                "structure_family": "perovskite",
                "space_group": "Pm-3m or subgroup",
                "crystal_system": "cubic/tetragonal",
                "required_motifs": ["corner-sharing TiO6 octahedra"],
            }
        ),
    }

    payload = runner._task_spec_payload_from_manifest_row(row)

    assert payload["composition_target"] == "BaTiO3"
    assert payload["symmetry_request"] == {"space_group": "Pm-3m or subgroup", "hardness": "hard"}
    assert payload["target_crystal_system"] == "cubic/tetragonal"
    assert payload["target_structure_family"] == "perovskite"
    assert payload["prototype"] == "perovskite"
    assert payload["motif_prior"] == "corner-sharing TiO6 octahedra"
