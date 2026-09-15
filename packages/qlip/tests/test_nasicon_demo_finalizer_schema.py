from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.finalize_nasicon_demo import SchemaContractError, extract_sca_fields


def valid_sca_fixture() -> dict:
    return {
        "parse_ok": True,
        "geometry": {"geometry_ok": True},
        "bonds": {"num_bad_contacts": 0, "bond_lengths_reasonable": True},
        "detected_space_groups": {"0.01": "C2"},
        "status": "PASS",
    }


def test_optional_minimum_distance_absent_still_finalizes() -> None:
    fields = extract_sca_fields(valid_sca_fixture())
    assert fields.contact_screen_pass is True
    assert fields.severe_contact_count == 0
    assert fields.minimum_distance_angstrom is None
    assert fields.minimum_distance_status == "OPTIONAL_FIELD_NOT_REPORTED"


def test_required_contact_information_missing_fails_descriptively() -> None:
    record = valid_sca_fixture()
    del record["bonds"]["num_bad_contacts"]
    with pytest.raises(SchemaContractError, match="REQUIRED_FIELD_MISSING: bonds.num_bad_contacts"):
        extract_sca_fields(record)


def test_optional_minimum_distance_present_is_recorded() -> None:
    record = valid_sca_fixture()
    record["bonds"]["min_distance"] = 1.75
    fields = extract_sca_fields(record)
    assert fields.minimum_distance_angstrom == 1.75
    assert fields.minimum_distance_status == "REPORTED_BY_SCA"
    assert fields.minimum_distance_source == "bonds.min_distance"


def test_optional_minimum_distance_invalid_type_fails() -> None:
    record = valid_sca_fixture()
    record["bonds"]["min_distance"] = "1.75"
    with pytest.raises(SchemaContractError, match="INVALID_FIELD_TYPE: bonds.min_distance"):
        extract_sca_fields(record)


def test_all_three_archived_demo_sca_responses_finalize() -> None:
    out = Path(__file__).resolve().parents[2] / "Skill-Loop-CSP" / "artifacts" / "paper_diversity_v2" / "nasicon_demo"
    for task_id in ("E4_A2", "E4_C2", "E4_F1"):
        record = json.loads((out / "tasks" / task_id / "sca_response.json").read_text(encoding="utf-8"))
        fields = extract_sca_fields(record)
        assert fields.contact_screen_pass is True
        assert fields.severe_contact_count == 0
