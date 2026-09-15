from __future__ import annotations

import csv
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from qlip.scaffolds import get_scaffold
from qlip.scaffolds.occupation import preflight_ordered_occupation
from scripts.run_nasicon_qlip_smoke import build_request


def test_nasicon_runner_builds_schema_valid_representable_species_only_request(tmp_path: Path) -> None:
    scaffold = get_scaffold("nasicon_na3zr2si2po12_c2_ordered")
    orbit_table = tmp_path / "orbits.csv"
    with orbit_table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["orbit_id", "site_indices", "species", "fixed or variable in QLIP"],
        )
        writer.writeheader()
        for orbit in scaffold.symmetry_orbits:
            writer.writerow(
                {
                    "orbit_id": orbit["orbit_id"],
                    "site_indices": " ".join(str(index) for index in orbit["site_indices"]),
                    "species": orbit["source_species"],
                    "fixed or variable in QLIP": "variable" if len(orbit["allowed_species"]) > 1 else "fixed",
                }
            )
    request = build_request(Path(scaffold.source_cif_path), orbit_table, tmp_path, 11.0)
    schema = json.loads((Path(__file__).resolve().parents[1] / "docs" / "mcp" / "MCP_SCHEMA.json").read_text(encoding="utf-8"))["solve_request"]
    assert list(Draft202012Validator(schema).iter_errors(request)) == []
    sites = request["problem"]["design_space"]["sites"]
    assert "vacancy_count" not in sites
    assert all("VACANCY" not in orbit["allowed_species"] for orbit in sites["ordered_orbits"])
    result = preflight_ordered_occupation(
        request["problem"]["chemistry"]["formula"],
        len(sites["explicit_fractional_sites"]),
        sites["ordered_orbits"],
    )
    assert result.stoichiometry_representable
    assert result.vacancy_count == 0
