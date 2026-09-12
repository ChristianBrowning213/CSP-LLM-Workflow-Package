"""Deterministic in-memory QLIP chemistry tables.

The implementation is the runtime form of QLIP's MIT-licensed
``scripts/build_base_data.py``. It reads data from pinned Python dependencies;
it does not download data or write into the package or source tree.
"""

from __future__ import annotations

import importlib.metadata as metadata
import math
import warnings
from functools import lru_cache
from typing import Any


EXPECTED_VERSIONS = {
    "ase": "3.27.0",
    "mendeleev": "1.1.0",
    "pymatgen": "2026.5.4",
    "pymatgen-core": "2026.8.30",
    "smact": "4.0.0",
}
SCHEMA_VERSION = "1.1"


def _verify_versions() -> None:
    mismatches = []
    for package, expected in EXPECTED_VERSIONS.items():
        try:
            actual = metadata.version(package)
        except metadata.PackageNotFoundError:
            actual = "not installed"
        if actual != expected:
            mismatches.append(f"{package}=={expected} required; found {actual}")
    if mismatches:
        raise RuntimeError(
            "QLIP chemistry data requires its pinned source packages: "
            + "; ".join(mismatches)
        )


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None
    if not math.isfinite(result) or result <= 0:
        return None
    return round(result, 6)


def _pm_to_angstrom(value: Any) -> float | None:
    value = _finite(value)
    return round(value / 100.0, 6) if value is not None else None


def _unit_to_angstrom(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if hasattr(value, "to"):
            return _finite(float(value.to("ang")))
    except Exception:
        pass
    return _finite(value)


def _array_value(values: Any, atomic_number: int) -> float | None:
    if values is None or atomic_number >= len(values):
        return None
    return _finite(values[atomic_number])


def _symbols() -> list[str]:
    from ase.data import chemical_symbols

    return [symbol for symbol in chemical_symbols if symbol != "X"]


def _elements() -> dict[str, Any]:
    from pymatgen.core import Element

    records = []
    for symbol in _symbols():
        element = Element(symbol)
        records.append(
            {
                "symbol": symbol,
                "atomic_number": int(element.Z),
                "name": str(element.long_name),
                "atomic_mass": _finite(float(element.atomic_mass)),
                "source_id": "pymatgen_element",
            }
        )
    return {"schema_version": SCHEMA_VERSION, "records": records}


def _mendeleev_radii(symbol: str) -> dict[str, float | None]:
    from mendeleev import element

    record = element(symbol)
    return {
        "covalent_radius_mendeleev_cordero_angstrom": _pm_to_angstrom(
            record.covalent_radius_cordero
        ),
        "covalent_radius_mendeleev_pyykko_angstrom": _pm_to_angstrom(
            record.covalent_radius_pyykko
        ),
        "vdw_radius_mendeleev_angstrom": _pm_to_angstrom(record.vdw_radius),
    }


def _ase_radii(symbol: str) -> dict[str, float | None]:
    from ase.data import atomic_numbers, covalent_radii, vdw_radii

    atomic_number = int(atomic_numbers[symbol])
    return {
        "covalent_radius_ase_cordero_angstrom": _array_value(covalent_radii, atomic_number),
        "vdw_radius_ase_angstrom": _array_value(vdw_radii, atomic_number),
    }


def _pymatgen_radii(symbol: str) -> dict[str, float | None]:
    from pymatgen.core import Element

    element = Element(symbol)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        atomic = element.atomic_radius
        calculated = element.atomic_radius_calculated
    return {
        "pymatgen_atomic_radius_angstrom": _unit_to_angstrom(atomic),
        "pymatgen_atomic_radius_calculated_angstrom": _unit_to_angstrom(calculated),
    }


def _first_radius(
    record: dict[str, Any], priority: list[tuple[str, str]]
) -> tuple[float | None, str | None, str | None]:
    for field, source_id in priority:
        if _finite(record.get(field)) is not None:
            kind = "covalent" if field.startswith("covalent") else "vdw"
            return float(record[field]), kind, source_id
    return None, None, None


def _radii() -> dict[str, Any]:
    from ase.data import atomic_numbers

    covalent_priority = [
        ("covalent_radius_mendeleev_cordero_angstrom", "mendeleev_covalent_radius_cordero"),
        ("covalent_radius_ase_cordero_angstrom", "ase_covalent_radii_cordero2008"),
        ("covalent_radius_mendeleev_pyykko_angstrom", "mendeleev_covalent_radius_pyykko"),
    ]
    vdw_priority = [
        ("vdw_radius_mendeleev_angstrom", "mendeleev_vdw_radius"),
        ("vdw_radius_ase_angstrom", "ase_vdw_radii"),
    ]
    records: dict[str, Any] = {}
    for symbol in _symbols():
        record: dict[str, Any] = {"atomic_number": int(atomic_numbers[symbol]), "notes": []}
        record.update(_mendeleev_radii(symbol))
        record.update(_ase_radii(symbol))
        record.update(_pymatgen_radii(symbol))
        covalent, _kind, covalent_source = _first_radius(record, covalent_priority)
        vdw, _kind, vdw_source = _first_radius(record, vdw_priority)
        default, default_kind, default_source = _first_radius(
            record, covalent_priority + vdw_priority
        )
        record.update(
            {
                "covalent_radius_angstrom": covalent,
                "covalent_radius_source_id": covalent_source,
                "vdw_radius_angstrom": vdw,
                "vdw_radius_source_id": vdw_source,
                "qlip_default_radius_angstrom": default,
                "qlip_default_radius_kind": default_kind,
                "qlip_default_radius_source_id": default_source,
            }
        )
        if default is None:
            record["notes"].append(
                "No supported default radius source is available; QLIP will report radii_data_missing."
            )
        records[symbol] = record
    return {"schema_version": SCHEMA_VERSION, "unit": "angstrom", "records": records}


def _smact_ionic_rows(symbol: str) -> list[dict[str, Any]]:
    from smact.data_loader import lookup_element_shannon_radius_data

    rows = []
    for raw in lookup_element_shannon_radius_data(symbol) or []:
        radius = _finite(raw.get("ionic_radius"))
        if radius is None:
            continue
        rows.append(
            {
                "oxidation_state": int(raw["charge"]),
                "coordination": str(raw["coordination"]),
                "radius_angstrom": radius,
                "radius_type": "ionic_radius",
                "source_label": "Shannon effective ionic radius",
                "spin": None,
                "source_id": "smact_shannon_radii",
                "method": "smact_shannon",
                "notes": [str(raw["comment"])] if raw.get("comment") else [],
            }
        )
    return rows


def _pymatgen_ionic_rows(symbol: str) -> list[dict[str, Any]]:
    from pymatgen.core import Element

    rows = []
    for oxidation, radius in sorted((Element(symbol).ionic_radii or {}).items()):
        value = _unit_to_angstrom(radius)
        if value is not None:
            rows.append(
                {
                    "oxidation_state": int(oxidation),
                    "coordination": "unspecified",
                    "radius_angstrom": value,
                    "radius_type": "ionic_radius",
                    "source_label": "pymatgen Element.ionic_radii",
                    "spin": None,
                    "source_id": "pymatgen_ionic_radii",
                    "method": "pymatgen_ionic_radii",
                    "notes": [
                        "Pymatgen ionic_radii does not expose coordination in this package version."
                    ],
                }
            )
    return rows


def _mendeleev_ionic_rows(symbol: str) -> list[dict[str, Any]]:
    from mendeleev import element

    rows = []
    for raw in element(symbol).ionic_radii or []:
        radius = _pm_to_angstrom(raw.ionic_radius)
        if radius is None:
            continue
        notes = []
        if raw.origin:
            notes.append(str(raw.origin).strip())
        if raw.most_reliable is not None:
            notes.append(f"most_reliable={bool(raw.most_reliable)}")
        rows.append(
            {
                "oxidation_state": int(raw.charge),
                "coordination": str(raw.coordination or "unspecified"),
                "radius_angstrom": radius,
                "radius_type": "ionic_radius",
                "source_label": "mendeleev IonicRadius.ionic_radius",
                "spin": str(raw.spin) if raw.spin else None,
                "source_id": "mendeleev_ionic_radius",
                "method": "mendeleev_ionic_radius",
                "notes": notes,
            }
        )
    return rows


def _ionic_radii() -> dict[str, Any]:
    from ase.data import atomic_numbers

    records: dict[str, Any] = {}
    for symbol in _symbols():
        status = []
        rows = _smact_ionic_rows(symbol)
        if rows:
            status.append("primary_source=smact_shannon")
        else:
            status.append("smact_shannon=no_rows")
            rows = _pymatgen_ionic_rows(symbol)
            if rows:
                status.append("primary_source=pymatgen_ionic_radii")
            else:
                status.append("pymatgen_ionic_radii=no_rows")
                rows = _mendeleev_ionic_rows(symbol)
                if rows:
                    status.append("primary_source=mendeleev_ionic_radius")
                else:
                    status.append("mendeleev_ionic_radius=no_rows")
        records[symbol] = {
            "atomic_number": int(atomic_numbers[symbol]),
            "ionic_radii": rows,
            "extended_ionic_radii": [],
            "source_status": status,
        }
    return {"schema_version": SCHEMA_VERSION, "unit": "angstrom", "records": records}


@lru_cache(maxsize=3)
def generated_resource(name: str) -> dict[str, Any]:
    """Build one canonical table on first explicit registry access."""

    _verify_versions()
    builders = {
        "elements.json": _elements,
        "radii.json": _radii,
        "ionic_radii.json": _ionic_radii,
    }
    try:
        return builders[name]()
    except KeyError as exc:
        raise KeyError(f"No generated QLIP base resource named {name!r}") from exc


__all__ = ["EXPECTED_VERSIONS", "generated_resource"]
