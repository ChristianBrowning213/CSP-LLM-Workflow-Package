from __future__ import annotations

import argparse
import importlib
import importlib.metadata as md
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "base"
SCHEMA_VERSION = "1.1"
REQUIRED_SOURCES = ("ase", "mendeleev", "pymatgen", "smact")


def _load_sources(allow_missing: bool) -> Dict[str, Any]:
    modules: Dict[str, Any] = {}
    missing = []
    for name in REQUIRED_SOURCES:
        try:
            modules[name] = importlib.import_module(name)
        except Exception as exc:
            missing.append(f"{name}: {exc}")
            modules[name] = None
    if missing and not allow_missing:
        joined = "\n  - ".join(missing)
        raise RuntimeError(
            "Missing required base-data source package(s):\n"
            f"  - {joined}\n"
            "Install ASE, mendeleev, pymatgen, and SMACT, or pass --allow-missing-source."
        )
    return modules


def _version(package: str) -> Optional[str]:
    try:
        return md.version(package)
    except Exception:
        return None


def _finite(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out) or out <= 0:
        return None
    return round(out, 6)


def _pm_to_angstrom(value: Any) -> Optional[float]:
    finite = _finite(value)
    return round(finite / 100.0, 6) if finite is not None else None


def _unit_to_angstrom(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if hasattr(value, "to"):
            converted = value.to("ang")
            return _finite(float(converted))
    except Exception:
        pass
    return _finite(value)


def _unit_to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return _finite(float(value))
    except Exception:
        return _finite(value)


def _array_value(values: Any, z: int) -> Optional[float]:
    if values is None or z >= len(values):
        return None
    return _finite(values[z])


def _symbols_from_ase(ase_module: Any) -> list[str]:
    from ase.data import chemical_symbols

    return [symbol for symbol in chemical_symbols if symbol != "X"]


def _ase_element_data(symbol: str) -> Dict[str, Any]:
    from ase.data import atomic_masses, atomic_names, atomic_numbers

    z = int(atomic_numbers[symbol])
    return {
        "symbol": symbol,
        "atomic_number": z,
        "name": atomic_names[z],
        "atomic_mass": _array_value(atomic_masses, z),
        "source_id": "ase_elements_iupac2016",
    }


def _mendeleev_element(symbol: str, modules: Dict[str, Any]) -> Any:
    if modules.get("mendeleev") is None:
        return None
    try:
        return importlib.import_module("mendeleev").element(symbol)
    except Exception:
        return None


def _pymatgen_element(symbol: str, modules: Dict[str, Any]) -> Any:
    if modules.get("pymatgen") is None:
        return None
    try:
        from pymatgen.core import Element

        return Element(symbol)
    except Exception:
        return None


def build_elements(symbols: Iterable[str], modules: Dict[str, Any]) -> Dict[str, Any]:
    records = []
    for symbol in symbols:
        ase_record = _ase_element_data(symbol)
        pmg_el = _pymatgen_element(symbol, modules)
        if pmg_el is not None:
            records.append(
                {
                    "symbol": symbol,
                    "atomic_number": int(pmg_el.Z),
                    "name": str(getattr(pmg_el, "long_name", None) or ase_record["name"]),
                    "atomic_mass": _unit_to_float(getattr(pmg_el, "atomic_mass", None)),
                    "source_id": "pymatgen_element",
                }
            )
            continue

        mend_el = _mendeleev_element(symbol, modules)
        if mend_el is not None:
            records.append(
                {
                    "symbol": symbol,
                    "atomic_number": int(mend_el.atomic_number),
                    "name": str(mend_el.name),
                    "atomic_mass": _finite(getattr(mend_el, "atomic_weight", None)),
                    "source_id": "mendeleev_element",
                }
            )
            continue

        records.append(ase_record)

    return {"schema_version": SCHEMA_VERSION, "records": records}


def _ase_radii(symbol: str) -> Dict[str, Optional[float]]:
    from ase.data import atomic_numbers, covalent_radii, vdw_radii

    z = int(atomic_numbers[symbol])
    return {
        "covalent_radius_ase_cordero_angstrom": _array_value(covalent_radii, z),
        "vdw_radius_ase_angstrom": _array_value(vdw_radii, z),
    }


def _mendeleev_radii(symbol: str, modules: Dict[str, Any]) -> Dict[str, Optional[float]]:
    el = _mendeleev_element(symbol, modules)
    if el is None:
        return {
            "covalent_radius_mendeleev_cordero_angstrom": None,
            "covalent_radius_mendeleev_pyykko_angstrom": None,
            "vdw_radius_mendeleev_angstrom": None,
        }
    return {
        "covalent_radius_mendeleev_cordero_angstrom": _pm_to_angstrom(
            getattr(el, "covalent_radius_cordero", None)
        ),
        "covalent_radius_mendeleev_pyykko_angstrom": _pm_to_angstrom(
            getattr(el, "covalent_radius_pyykko", None)
        ),
        "vdw_radius_mendeleev_angstrom": _pm_to_angstrom(getattr(el, "vdw_radius", None)),
    }


def _pymatgen_radii(symbol: str, modules: Dict[str, Any]) -> Dict[str, Optional[float]]:
    el = _pymatgen_element(symbol, modules)
    if el is None:
        return {
            "pymatgen_atomic_radius_angstrom": None,
            "pymatgen_atomic_radius_calculated_angstrom": None,
        }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        atomic_radius = getattr(el, "atomic_radius", None)
        atomic_radius_calculated = getattr(el, "atomic_radius_calculated", None)
    return {
        "pymatgen_atomic_radius_angstrom": _unit_to_angstrom(atomic_radius),
        "pymatgen_atomic_radius_calculated_angstrom": _unit_to_angstrom(atomic_radius_calculated),
    }


RADIUS_PRIORITY = [
    ("covalent_radius_mendeleev_cordero_angstrom", "mendeleev_covalent_radius_cordero"),
    ("covalent_radius_ase_cordero_angstrom", "ase_covalent_radii_cordero2008"),
    ("covalent_radius_mendeleev_pyykko_angstrom", "mendeleev_covalent_radius_pyykko"),
    ("vdw_radius_mendeleev_angstrom", "mendeleev_vdw_radius"),
    ("vdw_radius_ase_angstrom", "ase_vdw_radii"),
]


def _first_radius(record: Dict[str, Any], priority: list[tuple[str, str]]) -> tuple[Optional[float], Optional[str], Optional[str]]:
    for field, source_id in priority:
        value = record.get(field)
        if _finite(value) is not None:
            kind = "covalent" if field.startswith("covalent") else "vdw"
            return float(value), kind, source_id
    return None, None, None


def build_radii(symbols: Iterable[str], modules: Dict[str, Any]) -> Dict[str, Any]:
    from ase.data import atomic_numbers

    records = {}
    for symbol in symbols:
        record: Dict[str, Any] = {"atomic_number": int(atomic_numbers[symbol]), "notes": []}
        record.update(_mendeleev_radii(symbol, modules))
        record.update(_ase_radii(symbol))
        record.update(_pymatgen_radii(symbol, modules))

        covalent, _, covalent_source = _first_radius(
            record,
            [
                ("covalent_radius_mendeleev_cordero_angstrom", "mendeleev_covalent_radius_cordero"),
                ("covalent_radius_ase_cordero_angstrom", "ase_covalent_radii_cordero2008"),
                ("covalent_radius_mendeleev_pyykko_angstrom", "mendeleev_covalent_radius_pyykko"),
            ],
        )
        vdw, _, vdw_source = _first_radius(
            record,
            [
                ("vdw_radius_mendeleev_angstrom", "mendeleev_vdw_radius"),
                ("vdw_radius_ase_angstrom", "ase_vdw_radii"),
            ],
        )
        default_radius, default_kind, default_source = _first_radius(record, RADIUS_PRIORITY)

        record.update(
            {
                "covalent_radius_angstrom": covalent,
                "covalent_radius_source_id": covalent_source,
                "vdw_radius_angstrom": vdw,
                "vdw_radius_source_id": vdw_source,
                "qlip_default_radius_angstrom": default_radius,
                "qlip_default_radius_kind": default_kind,
                "qlip_default_radius_source_id": default_source,
            }
        )
        if default_radius is None:
            record["notes"].append("No supported default radius source is available; QLIP will report radii_data_missing.")
        records[symbol] = record
    return {"schema_version": SCHEMA_VERSION, "unit": "angstrom", "records": records}


def _smact_ionic_rows(symbol: str, modules: Dict[str, Any]) -> list[Dict[str, Any]]:
    if modules.get("smact") is None:
        return []
    try:
        from smact.data_loader import lookup_element_shannon_radius_data

        raw_rows = lookup_element_shannon_radius_data(symbol)
    except Exception:
        return []
    rows = []
    for raw in raw_rows or []:
        radius = _finite(raw.get("ionic_radius"))
        if radius is None:
            continue
        notes = []
        if raw.get("comment"):
            notes.append(str(raw["comment"]))
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
                "notes": notes,
            }
        )
    return rows


def _pymatgen_ionic_rows(symbol: str, modules: Dict[str, Any]) -> list[Dict[str, Any]]:
    el = _pymatgen_element(symbol, modules)
    if el is None:
        return []
    rows = []
    for ox, radius in sorted((getattr(el, "ionic_radii", None) or {}).items()):
        value = _unit_to_angstrom(radius)
        if value is None:
            continue
        rows.append(
            {
                "oxidation_state": int(ox),
                "coordination": "unspecified",
                "radius_angstrom": value,
                "radius_type": "ionic_radius",
                "source_label": "pymatgen Element.ionic_radii",
                "spin": None,
                "source_id": "pymatgen_ionic_radii",
                "method": "pymatgen_ionic_radii",
                "notes": ["Pymatgen ionic_radii does not expose coordination in this package version."],
            }
        )
    return rows


def _mendeleev_ionic_rows(symbol: str, modules: Dict[str, Any]) -> list[Dict[str, Any]]:
    el = _mendeleev_element(symbol, modules)
    if el is None:
        return []
    rows = []
    for raw in getattr(el, "ionic_radii", None) or []:
        radius = _pm_to_angstrom(getattr(raw, "ionic_radius", None))
        if radius is None:
            continue
        notes = []
        if getattr(raw, "origin", None):
            notes.append(str(raw.origin).strip())
        if getattr(raw, "most_reliable", None) is not None:
            notes.append(f"most_reliable={bool(raw.most_reliable)}")
        rows.append(
            {
                "oxidation_state": int(raw.charge),
                "coordination": str(raw.coordination or "unspecified"),
                "radius_angstrom": radius,
                "radius_type": "ionic_radius",
                "source_label": "mendeleev IonicRadius.ionic_radius",
                "spin": str(raw.spin) if getattr(raw, "spin", None) else None,
                "source_id": "mendeleev_ionic_radius",
                "method": "mendeleev_ionic_radius",
                "notes": notes,
            }
        )
    return rows


def build_ionic_radii(symbols: Iterable[str], modules: Dict[str, Any]) -> Dict[str, Any]:
    from ase.data import atomic_numbers

    records = {}
    for symbol in symbols:
        source_status = []
        rows = _smact_ionic_rows(symbol, modules)
        if rows:
            source_status.append("primary_source=smact_shannon")
        else:
            source_status.append("smact_shannon=no_rows")
            rows = _pymatgen_ionic_rows(symbol, modules)
            if rows:
                source_status.append("primary_source=pymatgen_ionic_radii")
            else:
                source_status.append("pymatgen_ionic_radii=no_rows")
                rows = _mendeleev_ionic_rows(symbol, modules)
                if rows:
                    source_status.append("primary_source=mendeleev_ionic_radius")
                else:
                    source_status.append("mendeleev_ionic_radius=no_rows")
        records[symbol] = {
            "atomic_number": int(atomic_numbers[symbol]),
            "ionic_radii": rows,
            "extended_ionic_radii": [],
            "source_status": source_status,
        }
    return {"schema_version": SCHEMA_VERSION, "unit": "angstrom", "records": records}


def build_radius_policy() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_id": "qlip_radius_policy_v1",
        "default_radius_field": "qlip_default_radius_angstrom",
        "priority": [field for field, _ in RADIUS_PRIORITY],
        "allow_synthetic_fallback": False,
        "missing_radius_code": "radii_data_missing",
        "source_id": "qlip_policy_v1",
        "notes": [
            "Neutral/current proximity.atomic_radii uses covalent data first.",
            "Fallbacks are real package data only; no synthetic radii are generated.",
        ],
    }


def build_pair_distance_policy() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_id": "qlip_pair_distance_policy_v1",
        "formula": "min_distance_angstrom = scale * (radius_a + radius_b)",
        "radius_policy_id": "qlip_radius_policy_v1",
        "default_scale": 1.0,
        "valid_scale_range": [0.0, None],
        "allow_synthetic_fallback": False,
        "source_id": "qlip_policy_v1",
        "notes": [
            "This is a QLIP operational proximity policy, not empirical bond-length data.",
            "The radius values come from radius_policy_id; scale is a user/request parameter.",
        ],
    }


def build_provenance(modules: Dict[str, Any]) -> Dict[str, Any]:
    package_versions = {name: _version(name) if modules.get(name) is not None else None for name in REQUIRED_SOURCES}
    sources = {
        "pymatgen_element": {
            "package": "pymatgen",
            "package_version": package_versions["pymatgen"],
            "description": "Element metadata from pymatgen.core.Element.",
            "url": "https://pymatgen.org/",
        },
        "mendeleev_element": {
            "package": "mendeleev",
            "package_version": package_versions["mendeleev"],
            "description": "Element metadata from mendeleev.element.",
            "url": "https://mendeleev.readthedocs.io/",
        },
        "ase_elements_iupac2016": {
            "package": "ase",
            "package_version": package_versions["ase"],
            "description": "Element symbols, names, and atomic masses exposed by ase.data.",
            "citation": "Meija et al. Atomic weights of the elements 2013, Pure and Applied Chemistry 88(3), 2016. DOI:10.1515/pac-2015-0305.",
            "url": "https://wiki.fysik.dtu.dk/ase/ase/data.html",
        },
        "mendeleev_covalent_radius_cordero": {
            "package": "mendeleev",
            "package_version": package_versions["mendeleev"],
            "description": "Cordero covalent radius exposed by mendeleev, normalized from pm to angstrom.",
            "citation": "Cordero et al. Covalent radii revisited, Dalton Trans., 2008, 2832-2838. DOI:10.1039/B801115J.",
        },
        "mendeleev_covalent_radius_pyykko": {
            "package": "mendeleev",
            "package_version": package_versions["mendeleev"],
            "description": "Pyykko covalent radius exposed by mendeleev, normalized from pm to angstrom.",
            "citation": "Pyykko and Atsumi, Molecular Single-Bond Covalent Radii for Elements 1-118, Chem. Eur. J. 2009. DOI:10.1002/chem.200901472.",
        },
        "ase_covalent_radii_cordero2008": {
            "package": "ase",
            "package_version": package_versions["ase"],
            "description": "Covalent radii exposed by ase.data.covalent_radii.",
            "citation": "Cordero et al. Covalent radii revisited, Dalton Trans., 2008, 2832-2838. DOI:10.1039/B801115J.",
        },
        "mendeleev_vdw_radius": {
            "package": "mendeleev",
            "package_version": package_versions["mendeleev"],
            "description": "Van der Waals radius exposed by mendeleev, normalized from pm to angstrom.",
        },
        "ase_vdw_radii": {
            "package": "ase",
            "package_version": package_versions["ase"],
            "description": "Van der Waals radii exposed by ase.data.vdw_radii.",
            "url": "https://wiki.fysik.dtu.dk/ase/ase/data.html",
        },
        "pymatgen_atomic_radius": {
            "package": "pymatgen",
            "package_version": package_versions["pymatgen"],
            "description": "Atomic radius fields exposed by pymatgen.core.Element.",
            "url": "https://pymatgen.org/",
        },
        "smact_shannon_radii": {
            "package": "smact",
            "package_version": package_versions["smact"],
            "description": "Shannon ionic radius lookup exposed by smact.data_loader.lookup_element_shannon_radius_data.",
            "citation": "Shannon, Revised effective ionic radii and systematic studies of interatomic distances in halides and chalcogenides, Acta Cryst. A32, 751-767 (1976).",
            "url": "https://smact.readthedocs.io/",
        },
        "pymatgen_ionic_radii": {
            "package": "pymatgen",
            "package_version": package_versions["pymatgen"],
            "description": "Element.ionic_radii fallback exposed by pymatgen.core.Element.",
        },
        "mendeleev_ionic_radius": {
            "package": "mendeleev",
            "package_version": package_versions["mendeleev"],
            "description": "IonicRadius rows exposed by mendeleev.element(...).ionic_radii, normalized from pm to angstrom.",
            "citation": "Shannon ionic radii as distributed by mendeleev.",
        },
        "qlip_policy_v1": {
            "kind": "qlip_policy",
            "description": "QLIP default radius and pair-distance policy for proximity constraints.",
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "generator": "scripts/build_base_data.py",
        "package_versions": package_versions,
        "sources": sources,
        "field_source_map": {
            "elements.source_id": ["pymatgen_element", "mendeleev_element", "ase_elements_iupac2016"],
            "radii.covalent_radius_mendeleev_cordero_angstrom": "mendeleev_covalent_radius_cordero",
            "radii.covalent_radius_mendeleev_pyykko_angstrom": "mendeleev_covalent_radius_pyykko",
            "radii.covalent_radius_ase_cordero_angstrom": "ase_covalent_radii_cordero2008",
            "radii.vdw_radius_mendeleev_angstrom": "mendeleev_vdw_radius",
            "radii.vdw_radius_ase_angstrom": "ase_vdw_radii",
            "radii.pymatgen_atomic_radius_angstrom": "pymatgen_atomic_radius",
            "radii.pymatgen_atomic_radius_calculated_angstrom": "pymatgen_atomic_radius",
            "ionic_radii.method=smact_shannon": "smact_shannon_radii",
            "ionic_radii.method=pymatgen_ionic_radii": "pymatgen_ionic_radii",
            "ionic_radii.method=mendeleev_ionic_radius": "mendeleev_ionic_radius",
        },
    }


def _write(name: str, payload: Dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _summarize(elements: Dict[str, Any], radii: Dict[str, Any], ionic: Dict[str, Any]) -> Dict[str, Any]:
    radius_records = radii["records"]
    ionic_records = ionic["records"]
    missing_default = [symbol for symbol, record in radius_records.items() if record["qlip_default_radius_angstrom"] is None]
    return {
        "element_count": len(elements["records"]),
        "radii_count": len(radius_records),
        "covalent_coverage": sum(1 for r in radius_records.values() if r["covalent_radius_angstrom"] is not None),
        "vdw_coverage": sum(1 for r in radius_records.values() if r["vdw_radius_angstrom"] is not None),
        "ionic_radii_row_count": sum(len(r["ionic_radii"]) for r in ionic_records.values()),
        "missing_default_radius_symbols": missing_default,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build QLIP source-tagged base element/radius data.")
    parser.add_argument("--allow-missing-source", action="store_true", help="Build with null fields for missing optional source packages.")
    args = parser.parse_args()

    modules = _load_sources(args.allow_missing_source)
    if modules.get("ase") is None:
        raise RuntimeError("ASE is required because it defines the 1..118 element symbol list.")

    symbols = _symbols_from_ase(modules["ase"])
    elements = build_elements(symbols, modules)
    radii = build_radii(symbols, modules)
    ionic = build_ionic_radii(symbols, modules)
    radius_policy = build_radius_policy()
    pair_policy = build_pair_distance_policy()
    provenance = build_provenance(modules)

    _write("elements.json", elements)
    _write("radii.json", radii)
    _write("ionic_radii.json", ionic)
    _write("radius_policy.json", radius_policy)
    _write("pair_distance_policy.json", pair_policy)
    _write("provenance.json", provenance)

    summary = _summarize(elements, radii, ionic)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
