"""Acquire and structurally screen missing Paper_scaffolds specialist families."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_crystaldb_corpus import load_mp_api_key  # noqa: E402


OUTPUT_ROOT = REPO_ROOT / "artifacts/Paper_scaffolds_september/specialist_corpora/families"
CLASSIFIER_VERSION = "paper_scaffolds.prototype_match.v1"
MATCHER = StructureMatcher(
    ltol=0.2,
    stol=0.3,
    angle_tol=5.0,
    primitive_cell=True,
    scale=True,
    attempt_supercell=False,
)
MOBILE = {"Li", "Na", "K", "Rb", "Cs", "Ag"}
HALOGENS = {"F", "Cl", "Br", "I"}
CHALCOGENS = {"S", "Se", "Te"}
ARGYRODITE_FRAMEWORK = {"P", "As", "Si", "Ge", "Sn"}
FAMILY_CONFIG: dict[str, dict[str, Any]] = {
    "ROCKSALT": {
        "query": {"spacegroup_number": 225, "num_elements": 2, "num_sites": (2, 16), "include_gnome": False},
        "templates": ["MgO"],
    },
    "OLIVINE": {
        "query": {"elements": ["Li", "P", "O"], "num_elements": 4, "spacegroup_number": 62, "num_sites": (4, 80), "include_gnome": False},
        "templates": ["LiFePO4"],
    },
    "ARGYRODITE": {
        "query": {"elements": ["Li", "P", "S"], "num_elements": (4, 5), "spacegroup_number": [216, 43], "num_sites": (10, 120), "include_gnome": False},
        "templates": ["Li6PS5Cl"],
    },
    "GARNET": {
        "query": {"elements": ["O"], "num_elements": (3, 5), "spacegroup_number": [230, 142], "num_sites": (10, 200), "include_gnome": False},
        "templates": ["Li7La3Zr2O12", "Y3Al5O12"],
    },
    "RUDDLESDEN_POPPER": {
        "query": {"elements": ["O"], "num_elements": (3, 5), "spacegroup_number": [139, 63, 64], "num_sites": (5, 150), "include_gnome": False},
        "templates": ["Sr2TiO4", "Sr3Ti2O7"],
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cif_text(structure: Structure) -> str:
    return str(CifWriter(structure, symprec=None)) + "\n"


def anonymous_prototype_fit(candidate: Structure, templates: list[Structure]) -> int | None:
    for index, template in enumerate(templates):
        if MATCHER.fit_anonymous(candidate, template):
            return index
    return None


def reduced_element_amounts(structure: Structure) -> dict[str, int]:
    composition = structure.composition.reduced_composition
    return {
        str(element): int(round(float(amount)))
        for element, amount in composition.items()
    }


def oxygen_stoichiometry_matches(family: str, structure: Structure) -> bool:
    amounts = reduced_element_amounts(structure)
    oxygen = amounts.pop("O", None)
    non_oxygen = sorted(amounts.values())
    if family == "OLIVINE":
        return oxygen == 4 and non_oxygen == [1, 1, 1]
    if family == "GARNET":
        return oxygen == 12 and non_oxygen in ([3, 5], [2, 3, 3], [2, 3, 7])
    if family == "RUDDLESDEN_POPPER":
        return (oxygen == 4 and non_oxygen == [1, 2]) or (
            oxygen == 7 and non_oxygen == [2, 3]
        )
    raise ValueError(f"No oxygen stoichiometry rule for {family}")


def classify_structure(
    family: str, structure: Structure, templates: list[Structure]
) -> tuple[bool, str, dict[str, Any]]:
    elements = {element.symbol for element in structure.composition.elements}
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
    space_group = analyzer.get_space_group_number()
    evidence: dict[str, Any] = {
        "space_group_number": space_group,
        "space_group_symbol": analyzer.get_space_group_symbol(),
        "primitive_sites": len(analyzer.get_primitive_standard_structure()),
        "conventional_sites": len(analyzer.get_conventional_standard_structure()),
    }
    if family == "ROCKSALT":
        conventional = analyzer.get_conventional_standard_structure()
        conventional_analyzer = SpacegroupAnalyzer(conventional, symprec=0.01, angle_tolerance=5.0)
        dataset = conventional_analyzer.get_symmetry_dataset()
        wyckoffs = sorted(set(str(value) for value in dataset.wyckoffs)) if dataset else []
        amounts = sorted(float(value) for value in structure.composition.get_el_amt_dict().values())
        evidence["wyckoff_letters"] = wyckoffs
        evidence["conventional_formula"] = conventional.composition.reduced_formula
        passed = bool(
            space_group == 225
            and len(elements) == 2
            and len(amounts) == 2
            and abs(amounts[0] - amounts[1]) < 1e-8
            and len(conventional) == 8
            and wyckoffs == ["a", "b"]
        )
        return passed, "B1_Fm-3m_4a_4b" if passed else "not_B1_Fm-3m_4a_4b", evidence

    template_index = anonymous_prototype_fit(structure, templates)
    evidence["anonymous_template_index"] = template_index
    if template_index is None:
        return False, "structurematcher_prototype_mismatch", evidence
    if family == "OLIVINE":
        passed = (
            {"Li", "P", "O"}.issubset(elements)
            and len(elements) == 4
            and space_group == 62
            and oxygen_stoichiometry_matches(family, structure)
        )
        evidence["scope"] = "LiMPO4-type polyanion olivine"
    elif family == "ARGYRODITE":
        passed = bool(
            elements & MOBILE
            and elements & HALOGENS
            and elements & CHALCOGENS
            and elements & ARGYRODITE_FRAMEWORK
            and space_group in {216, 43}
        )
    elif family == "GARNET":
        passed = (
            "O" in elements
            and space_group in {230, 142}
            and oxygen_stoichiometry_matches(family, structure)
        )
    elif family == "RUDDLESDEN_POPPER":
        passed = (
            "O" in elements
            and space_group in {139, 63, 64}
            and oxygen_stoichiometry_matches(family, structure)
        )
        amounts = reduced_element_amounts(structure)
        evidence["rp_n"] = 1 if amounts.get("O") == 4 else 2
    else:
        raise ValueError(f"Unsupported family: {family}")
    return passed, "prototype_match" if passed else "chemistry_or_symmetry_mismatch", evidence


def classify_task(
    task: tuple[str, Structure, list[Structure]],
) -> tuple[bool, str, dict[str, Any]]:
    return classify_structure(*task)


def safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "value"):
        return safe_value(value.value)
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value]
    if hasattr(value, "model_dump"):
        return safe_value(value.model_dump())
    return str(value)


def row_for_doc(doc: Any, query: dict[str, Any]) -> dict[str, Any]:
    symmetry = getattr(doc, "symmetry", None)
    return {
        "material_id": str(doc.material_id),
        "formula_pretty": str(doc.formula_pretty),
        "elements": ";".join(sorted(str(element) for element in doc.elements)),
        "space_group_number_source": getattr(symmetry, "number", None),
        "space_group_symbol_source": getattr(symmetry, "symbol", None),
        "energy_above_hull_eV_per_atom": safe_value(getattr(doc, "energy_above_hull", None)),
        "formation_energy_eV_per_atom": safe_value(getattr(doc, "formation_energy_per_atom", None)),
        "theoretical": safe_value(getattr(doc, "theoretical", None)),
        "deprecated": safe_value(getattr(doc, "deprecated", None)),
        "last_updated": safe_value(getattr(doc, "last_updated", None)),
        "density": safe_value(getattr(doc, "density", None)),
        "volume": safe_value(getattr(doc, "volume", None)),
        "band_gap_eV": safe_value(getattr(doc, "band_gap", None)),
        "source_query": json.dumps(query, sort_keys=True, separators=(",", ":")),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) if rows else ["material_id", "reason"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def acquire_family(
    mpr: Any,
    family: str,
    *,
    force: bool,
    workers: int = 1,
    database_version: str | None = None,
) -> dict[str, Any]:
    config = FAMILY_CONFIG[family]
    family_root = OUTPUT_ROOT / family
    dataset_id = f"PAPER_SCAFFOLDS_{family}_V1"
    dataset_root = family_root / dataset_id
    acquisition_root = dataset_root / "acquisition"
    if acquisition_root.exists():
        if not force:
            raise FileExistsError(f"Refusing to overwrite {acquisition_root}; pass --force")
        if dataset_root.resolve() not in acquisition_root.resolve().parents:
            raise ValueError(f"Unsafe acquisition target: {acquisition_root}")
        shutil.rmtree(acquisition_root)
    cif_root = acquisition_root / "accepted_cifs"
    cif_root.mkdir(parents=True)
    fields = [
        "material_id", "formula_pretty", "elements", "symmetry", "energy_above_hull",
        "formation_energy_per_atom", "theoretical", "deprecated", "last_updated", "density",
        "volume", "band_gap", "structure",
    ]
    templates = []
    template_ids = []
    for formula in config["templates"]:
        docs = mpr.materials.summary.search(formula=formula, fields=fields)
        docs = sorted(
            docs,
            key=lambda doc: (
                getattr(doc, "energy_above_hull", None) is None,
                getattr(doc, "energy_above_hull", None) or 0.0,
                str(doc.material_id),
            ),
        )
        if not docs:
            raise RuntimeError(f"No template returned for {family}: {formula}")
        templates.append(docs[0].structure)
        template_ids.append(str(docs[0].material_id))
    docs = mpr.materials.summary.search(**config["query"], fields=fields)
    ordered_docs = sorted(docs, key=lambda item: str(item.material_id))
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            classifications = list(
                executor.map(
                    classify_task,
                    ((family, doc.structure, templates) for doc in ordered_docs),
                    chunksize=1,
                )
            )
    else:
        classifications = [classify_structure(family, doc.structure, templates) for doc in ordered_docs]
    candidates: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for doc, classification in zip(ordered_docs, classifications, strict=True):
        row = row_for_doc(doc, config["query"])
        text = cif_text(doc.structure)
        cif_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        passed, reason, evidence = classification
        row.update(
            {
                "cif_sha256": cif_hash,
                "classifier_version": CLASSIFIER_VERSION,
                "classifier_reason": reason,
                "classifier_evidence": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
            }
        )
        candidates.append(row)
        if not passed:
            rejected.append({**row, "rejection_reason": reason})
            continue
        if cif_hash in seen_hashes:
            rejected.append({**row, "rejection_reason": "duplicate_cif_sha256"})
            continue
        seen_hashes.add(cif_hash)
        (cif_root / f"{doc.material_id}.cif").write_text(text, encoding="utf-8")
        accepted.append(row)
    write_csv(acquisition_root / "candidates.csv", candidates)
    write_csv(acquisition_root / "accepted.csv", accepted)
    write_csv(acquisition_root / "rejected.csv", rejected)
    manifest = {
        "dataset_id": dataset_id,
        "family": family,
        "acquired_at": now_iso(),
        "source": "Materials Project summary endpoint",
        "source_endpoint": "materials/summary",
        "mp_api_version": importlib.metadata.version("mp-api"),
        "materials_project_database_version": database_version,
        "query": config["query"],
        "template_formulas": config["templates"],
        "template_material_ids": template_ids,
        "classifier_version": CLASSIFIER_VERSION,
        "candidate_count": len(candidates),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "api_secret_persisted": False,
    }
    (acquisition_root / "query_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--families", nargs="+", choices=tuple(FAMILY_CONFIG), default=list(FAMILY_CONFIG))
    args = parser.parse_args()
    key = load_mp_api_key(REPO_ROOT)
    if not key:
        raise RuntimeError("Materials Project API key unavailable")
    import truststore
    from mp_api.client import MPRester

    truststore.inject_into_ssl()
    reports = []
    with MPRester(key) as mpr:
        database_version = str(mpr.get_database_version())
        for family in args.families:
            reports.append(
                acquire_family(
                    mpr,
                    family,
                    force=args.force,
                    workers=max(1, args.workers),
                    database_version=database_version,
                )
            )
    print(json.dumps({row["family"]: {"candidates": row["candidate_count"], "accepted": row["accepted_count"], "rejected": row["rejected_count"]} for row in reports}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
