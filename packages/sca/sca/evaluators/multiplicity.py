"""Atom-site multiplicity checks."""

from __future__ import annotations

import re

from pymatgen.core import Structure

from sca.schemas import MultiplicityResult


def evaluate_multiplicity(structure: Structure, cif_text: str | None) -> MultiplicityResult:
    site_count = len(structure)
    if not cif_text or "_atom_site_symmetry_multiplicity" not in cif_text:
        return MultiplicityResult(
            multiplicity_checked=False,
            multiplicity_consistent=None,
            site_count=site_count,
        )

    try:
        values = _extract_multiplicity_values(cif_text)
        if not values:
            return MultiplicityResult(
                multiplicity_checked=False,
                multiplicity_consistent=None,
                site_count=site_count,
            )
        declared = sum(values)
        return MultiplicityResult(
            multiplicity_checked=True,
            multiplicity_consistent=declared == site_count,
            declared_atom_count=declared,
            expanded_atom_count=declared,
            site_count=site_count,
        )
    except Exception as exc:
        return MultiplicityResult(
            multiplicity_checked=True,
            multiplicity_consistent=None,
            site_count=site_count,
            multiplicity_error=f"{type(exc).__name__}: {exc}",
        )


def _extract_multiplicity_values(cif_text: str) -> list[int]:
    lines = cif_text.splitlines()
    values: list[int] = []
    cursor = 0
    while cursor < len(lines):
        if lines[cursor].strip().lower() != "loop_":
            cursor += 1
            continue
        cursor += 1
        headers: list[str] = []
        while cursor < len(lines) and lines[cursor].strip().startswith("_"):
            headers.append(lines[cursor].strip())
            cursor += 1
        lower_headers = [header.lower() for header in headers]
        if "_atom_site_symmetry_multiplicity" not in lower_headers:
            continue
        multiplicity_index = lower_headers.index("_atom_site_symmetry_multiplicity")
        while cursor < len(lines):
            row = lines[cursor].strip()
            if not row or row.startswith("_") or row.lower().startswith("loop_"):
                break
            tokens = re.findall(r"'[^']*'|\"[^\"]*\"|\S+", row)
            if len(tokens) > multiplicity_index:
                values.append(int(float(tokens[multiplicity_index].strip("'\""))))
            cursor += 1
    return values
