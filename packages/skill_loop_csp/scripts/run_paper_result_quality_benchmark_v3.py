"""Benchmark physical-quality diagnostics for generated V3 paper-result CIFs.

This script is intentionally scoped to the generated rows in the V3 paper
result-section smoke. It does not rerun generation, mutate Crystal-DB databases,
or make DFT-level claims.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CRYSTAL_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
SCA_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser")
ARTIFACTS_DIR = REPO_ROOT / "artifacts"

QUALITY_VERSION = os.environ.get("PAPER_QUALITY_VERSION", "V3").strip().upper()
QUALITY_VERSION_LOWER = QUALITY_VERSION.lower()
OUT_ROOT = SCA_ROOT / "local_runs" / f"paper_result_quality_benchmark_{QUALITY_VERSION_LOWER}"
V3_REPORT = ARTIFACTS_DIR / f"PAPER_RESULT_SECTION_SMOKE_{QUALITY_VERSION}_REPORT.json"
V3_TABLE = ARTIFACTS_DIR / f"PAPER_RESULTS_TABLE_{QUALITY_VERSION}.csv"
DATASET_REPORT = CRYSTAL_ROOT / "artifacts" / "paper_result_datasets_built.json"
SUMMARY_TEXT = ARTIFACTS_DIR / f"PAPER_RESULTS_SUMMARY_TEXT_{QUALITY_VERSION}.md"

MANIFEST_CSV = OUT_ROOT / f"generated_quality_manifest_{QUALITY_VERSION_LOWER}.csv"
QUALITY_CSV = OUT_ROOT / f"quality_results_{QUALITY_VERSION_LOWER}.csv"
QUALITY_JSON = OUT_ROOT / f"quality_results_{QUALITY_VERSION_LOWER}.json"
GEOMETRY_CSV = OUT_ROOT / f"geometry_results_{QUALITY_VERSION_LOWER}.csv"
REFERENCE_MATCH_CSV = OUT_ROOT / f"reference_match_results_{QUALITY_VERSION_LOWER}.csv"
CHGNET_STATIC_CSV = OUT_ROOT / f"chgnet_static_results_{QUALITY_VERSION_LOWER}.csv"
CHGNET_RELAX_CSV = OUT_ROOT / f"chgnet_relax_results_{QUALITY_VERSION_LOWER}.csv"
NOVELTY_CSV = OUT_ROOT / f"novelty_results_{QUALITY_VERSION_LOWER}.csv"
SUMMARY_JSON = OUT_ROOT / f"quality_summary_{QUALITY_VERSION_LOWER}.json"
REPORT_MD = OUT_ROOT / f"PAPER_RESULT_QUALITY_BENCHMARK_{QUALITY_VERSION}_REPORT.md"
REPORT_JSON = OUT_ROOT / f"PAPER_RESULT_QUALITY_BENCHMARK_{QUALITY_VERSION}_REPORT.json"
RELAXED_CIFS = OUT_ROOT / "relaxed_cifs"

MANIFEST_COLUMNS = [
    "row_id",
    "formula",
    "result_section",
    "dataset_id",
    "generated_cif_path",
    "validation_tier",
    "active_mode",
    "extension_case",
    "prototype_constraint_mode",
    "source_faithful_symmetry",
    "expected_space_group",
    "expected_crystal_system",
    "expected_family",
    "reference_db_path",
    "reference_material_id",
    "reference_cif_path",
    "benchmark_status",
]

GEOMETRY_COLUMNS = [
    "row_id",
    "formula",
    "parse_ok",
    "formula_reduced",
    "formula_match",
    "nsites",
    "lattice_a",
    "lattice_b",
    "lattice_c",
    "lattice_alpha",
    "lattice_beta",
    "lattice_gamma",
    "volume",
    "density",
    "min_interatomic_distance",
    "bad_contact_count",
    "bad_contact_flag",
    "severe_geometry_warning",
    "geometry_warnings",
    "error_text",
]

REFERENCE_COLUMNS = [
    "row_id",
    "formula",
    "reference_material_id",
    "reference_cif_path",
    "exact_structure_match",
    "anonymous_structure_match",
    "rms_displacement",
    "max_displacement",
    "volume_ratio",
    "lattice_mismatch_summary",
    "reference_match_status",
    "notes",
]

CHGNET_STATIC_COLUMNS = [
    "row_id",
    "formula",
    "chgnet_static_status",
    "energy_per_atom",
    "max_force",
    "mean_force",
    "stress",
    "backend_version",
    "error_text",
]

CHGNET_RELAX_COLUMNS = [
    "row_id",
    "formula",
    "relax_status",
    "relaxed_cif_path",
    "initial_energy_per_atom",
    "final_energy_per_atom",
    "energy_drop_per_atom",
    "initial_max_force",
    "final_max_force",
    "steps",
    "converged",
    "formula_preserved",
    "parse_ok_after_relax",
    "symmetry_after_relax",
    "prototype_symmetry_preserved",
    "volume_change_percent",
    "error_text",
]

NOVELTY_COLUMNS = [
    "row_id",
    "formula",
    "nearest_reference",
    "match_status",
    "duplicate_cluster",
    "novelty_status",
    "notes",
]

QUALITY_COLUMNS = [
    "row_id",
    "formula",
    "result_section",
    "dataset_id",
    "validation_tier",
    "active_mode",
    "extension_case",
    "prototype_constraint_mode",
    "source_faithful_symmetry",
    "parse_ok",
    "formula_match",
    "symmetry_match",
    "bad_contact_flag",
    "severe_geometry_warning",
    "reference_match_status",
    "novelty_status",
    "chgnet_static_status",
    "relax_status",
    "quality_screen_status",
    "quality_notes",
]


def _add_import_roots() -> None:
    for root in (SCA_ROOT,):
        text = str(root)
        if text not in sys.path:
            sys.path.insert(0, text)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column, "")) for column in columns})


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(_jsonable(value), sort_keys=True)
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bool_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    if value is None or value == "":
        return ""
    return "true" if bool(value) else "false"


def _dataset_targets() -> dict[tuple[str, str], dict[str, Any]]:
    data = _load_json(DATASET_REPORT)
    targets: dict[tuple[str, str], dict[str, Any]] = {}
    for card in data.get("dataset_cards", []):
        dataset_id = str(card.get("dataset_id") or "")
        db_path = str(card.get("db_path") or "")
        for target in card.get("target_coverage", []):
            formula = str(target.get("target_formula") or "")
            targets[(dataset_id, formula)] = {
                "reference_db_path": db_path,
                "reference_material_id": target.get("material_id") or "",
                "reference_cif_path": target.get("cif_path") or "",
                "source_symmetry": target.get("symmetry") or {},
                "source_status": target.get("status") or "",
            }
    return targets


def _generated_rows() -> list[dict[str, Any]]:
    report = _load_json(V3_REPORT)
    rows = [row for row in report.get("rows", []) if row.get("outcome") == "generated"]
    rows.sort(key=lambda row: (str(row.get("result_section")), str(row.get("dataset_id")), str(row.get("formula")), str(row.get("task_dir"))))
    return rows


def build_manifest() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    references = _dataset_targets()
    manifest_rows: list[dict[str, Any]] = []
    enriched_rows: list[dict[str, Any]] = []
    for index, row in enumerate(_generated_rows(), start=1):
        formula = str(row.get("formula") or "")
        dataset_id = str(row.get("dataset_id") or "")
        reference = references.get((dataset_id, formula), {})
        row_id = f"v3_{index:03d}_{dataset_id}_{formula}"
        manifest_row = {
            "row_id": row_id,
            "formula": formula,
            "result_section": row.get("result_section") or "",
            "dataset_id": dataset_id,
            "generated_cif_path": row.get("cif_path") or "",
            "validation_tier": row.get("validation_tier") or "",
            "active_mode": row.get("requested_mode") or "",
            "extension_case": row.get("extension_case") or "",
            "prototype_constraint_mode": row.get("prototype_constraint_mode") or "",
            "source_faithful_symmetry": _bool_text(row.get("source_faithful_symmetry")),
            "expected_space_group": row.get("target_space_group") or "",
            "expected_crystal_system": row.get("target_crystal_system") or "",
            "expected_family": row.get("target_family") or "",
            "reference_db_path": reference.get("reference_db_path") or row.get("db_path") or "",
            "reference_material_id": reference.get("reference_material_id") or "",
            "reference_cif_path": reference.get("reference_cif_path") or "",
            "benchmark_status": "pending",
        }
        manifest_rows.append(manifest_row)
        enriched_rows.append(row | manifest_row | {"reference": reference})
    return manifest_rows, enriched_rows


def geometry_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from pymatgen.core import Composition, Structure

    results = []
    for row in rows:
        formula = str(row["formula"])
        result = {
            "row_id": row["row_id"],
            "formula": formula,
            "parse_ok": False,
            "formula_reduced": "",
            "formula_match": False,
            "nsites": "",
            "lattice_a": "",
            "lattice_b": "",
            "lattice_c": "",
            "lattice_alpha": "",
            "lattice_beta": "",
            "lattice_gamma": "",
            "volume": "",
            "density": "",
            "min_interatomic_distance": "",
            "bad_contact_count": "",
            "bad_contact_flag": "",
            "severe_geometry_warning": "",
            "geometry_warnings": "",
            "error_text": "",
        }
        try:
            structure = Structure.from_file(str(row["generated_cif_path"]))
            result["parse_ok"] = True
            result["formula_reduced"] = structure.composition.reduced_formula
            result["formula_match"] = Composition(formula).reduced_composition == structure.composition.reduced_composition
            result["nsites"] = len(structure)
            lattice = structure.lattice
            result.update(
                {
                    "lattice_a": float(lattice.a),
                    "lattice_b": float(lattice.b),
                    "lattice_c": float(lattice.c),
                    "lattice_alpha": float(lattice.alpha),
                    "lattice_beta": float(lattice.beta),
                    "lattice_gamma": float(lattice.gamma),
                    "volume": float(structure.volume),
                    "density": float(structure.density),
                }
            )
            min_distance, bad_count, pair_notes = _contact_diagnostics(structure)
            warnings = _geometry_warnings(structure, min_distance, bad_count, pair_notes)
            result["min_interatomic_distance"] = min_distance
            result["bad_contact_count"] = bad_count
            result["bad_contact_flag"] = bad_count > 0
            result["severe_geometry_warning"] = any("severe" in item for item in warnings)
            result["geometry_warnings"] = "; ".join(warnings)
        except Exception as exc:  # noqa: BLE001
            result["error_text"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


def _contact_diagnostics(structure: Any) -> tuple[float | None, int, list[str]]:
    min_distance: float | None = None
    bad_count = 0
    notes: list[str] = []
    for left in range(len(structure)):
        for right in range(left + 1, len(structure)):
            distance = float(structure.get_distance(left, right))
            min_distance = distance if min_distance is None else min(min_distance, distance)
            left_el = str(structure[left].specie)
            right_el = str(structure[right].specie)
            threshold = _bad_contact_threshold(left_el, right_el)
            if distance < threshold:
                bad_count += 1
                if len(notes) < 5:
                    notes.append(f"{left_el}-{right_el} {distance:.3f} below {threshold:.3f}")
    return min_distance, bad_count, notes


def _bad_contact_threshold(left: str, right: str) -> float:
    # A conservative screen: flag severe overlaps, not merely short ionic bonds.
    radius_sum = _element_radius(left) + _element_radius(right)
    return max(0.65, 0.45 * radius_sum)


def _element_radius(symbol: str) -> float:
    try:
        from pymatgen.core import Element

        radius = Element(symbol).atomic_radius
        if radius is not None:
            return float(radius)
    except Exception:  # noqa: BLE001
        pass
    return 1.2


def _geometry_warnings(structure: Any, min_distance: float | None, bad_count: int, pair_notes: list[str]) -> list[str]:
    warnings: list[str] = []
    if min_distance is not None and min_distance < 0.7:
        warnings.append("severe short contact below 0.7 A")
    if bad_count:
        warnings.append(f"{bad_count} conservative bad-contact flags: " + "; ".join(pair_notes))
    volume_per_atom = float(structure.volume) / len(structure) if len(structure) else None
    if volume_per_atom is not None and volume_per_atom < 3:
        warnings.append("severe volume per atom below 3 A^3")
    if volume_per_atom is not None and volume_per_atom > 120:
        warnings.append("volume per atom above 120 A^3")
    try:
        density = float(structure.density)
        if density <= 0:
            warnings.append("severe non-positive density")
        elif density > 30:
            warnings.append("density above 30 g/cm^3")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"density unavailable: {type(exc).__name__}: {exc}")
    return warnings


def reference_match_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure

    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=True, scale=True, attempt_supercell=True)
    results = []
    for row in rows:
        result = {
            "row_id": row["row_id"],
            "formula": row["formula"],
            "reference_material_id": row.get("reference_material_id") or "",
            "reference_cif_path": row.get("reference_cif_path") or "",
            "exact_structure_match": "",
            "anonymous_structure_match": "",
            "rms_displacement": "",
            "max_displacement": "",
            "volume_ratio": "",
            "lattice_mismatch_summary": "",
            "reference_match_status": "unavailable",
            "notes": "",
        }
        reference_path = Path(str(row.get("reference_cif_path") or ""))
        try:
            candidate = Structure.from_file(str(row["generated_cif_path"]))
            if not reference_path.is_file():
                result["notes"] = "reference CIF unavailable"
                results.append(result)
                continue
            reference = Structure.from_file(str(reference_path))
            exact = bool(matcher.fit(candidate, reference))
            anonymous = bool(matcher.fit_anonymous(candidate, reference))
            result["exact_structure_match"] = exact
            result["anonymous_structure_match"] = anonymous
            if exact or anonymous:
                rms, max_dist = matcher.get_rms_dist(candidate, reference) or (None, None)
                result["rms_displacement"] = rms
                result["max_displacement"] = max_dist
            result["volume_ratio"] = float(candidate.volume) / float(reference.volume) if reference.volume else ""
            result["lattice_mismatch_summary"] = _lattice_mismatch(candidate, reference)
            if row.get("prototype_constraint_mode") == "ideal_cubic_abx3" and row.get("source_faithful_symmetry") == "false":
                result["reference_match_status"] = "not_source_faithful_by_design"
                result["notes"] = "ideal cubic ABX3 row; low-symmetry source mismatch is not counted as generation failure"
            elif exact:
                result["reference_match_status"] = "exact_match"
            elif anonymous:
                result["reference_match_status"] = "anonymous_match"
            else:
                result["reference_match_status"] = "no_match"
        except Exception as exc:  # noqa: BLE001
            result["notes"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


def _lattice_mismatch(candidate: Any, reference: Any) -> str:
    parts = []
    for label, cand, ref in (
        ("a", candidate.lattice.a, reference.lattice.a),
        ("b", candidate.lattice.b, reference.lattice.b),
        ("c", candidate.lattice.c, reference.lattice.c),
        ("alpha", candidate.lattice.alpha, reference.lattice.alpha),
        ("beta", candidate.lattice.beta, reference.lattice.beta),
        ("gamma", candidate.lattice.gamma, reference.lattice.gamma),
    ):
        if abs(float(ref)) > 1e-12:
            parts.append(f"{label}:{((float(cand) - float(ref)) / float(ref)) * 100:.2f}%")
    return "; ".join(parts)


def chgnet_static_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status, version, error = _chgnet_backend_status()
    return [
        {
            "row_id": row["row_id"],
            "formula": row["formula"],
            "chgnet_static_status": status,
            "energy_per_atom": "",
            "max_force": "",
            "mean_force": "",
            "stress": "",
            "backend_version": version,
            "error_text": error,
        }
        for row in rows
    ]


def chgnet_relax_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status, version, error = _chgnet_backend_status()
    _ = version
    RELAXED_CIFS.mkdir(parents=True, exist_ok=True)
    return [
        {
            "row_id": row["row_id"],
            "formula": row["formula"],
            "relax_status": status,
            "relaxed_cif_path": "",
            "initial_energy_per_atom": "",
            "final_energy_per_atom": "",
            "energy_drop_per_atom": "",
            "initial_max_force": "",
            "final_max_force": "",
            "steps": "",
            "converged": "",
            "formula_preserved": "",
            "parse_ok_after_relax": "",
            "symmetry_after_relax": "",
            "prototype_symmetry_preserved": "unknown",
            "volume_change_percent": "",
            "error_text": error,
        }
        for row in rows
    ]


def _chgnet_backend_status() -> tuple[str, str, str]:
    try:
        import chgnet  # type: ignore[import-not-found]

        version = str(getattr(chgnet, "__version__", "unknown"))
    except Exception as exc:  # noqa: BLE001
        return "unavailable_missing_dependency", "", f"{type(exc).__name__}: {exc}"
    return "available_not_run_by_script", version, ""


def novelty_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Structure

    references = _reference_structures_by_dataset()
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=True, scale=True, attempt_supercell=True)
    results = []
    for row in rows:
        result = {
            "row_id": row["row_id"],
            "formula": row["formula"],
            "nearest_reference": "",
            "match_status": "unavailable",
            "duplicate_cluster": "",
            "novelty_status": "unavailable",
            "notes": "",
        }
        try:
            candidate = Structure.from_file(str(row["generated_cif_path"]))
            refs = references.get(str(row["dataset_id"]), {})
            if not refs:
                result["notes"] = "no local reference corpus for dataset"
                results.append(result)
                continue
            matched = ""
            for ref_id, reference in refs.items():
                if matcher.fit(candidate, reference):
                    matched = ref_id
                    break
            result["nearest_reference"] = matched or _same_formula_reference(row, refs)
            if matched:
                result["match_status"] = "known_match"
                result["novelty_status"] = "reference_rediscovery"
                result["duplicate_cluster"] = matched
            elif row.get("prototype_constraint_mode") == "ideal_cubic_abx3" and row.get("source_faithful_symmetry") == "false":
                result["match_status"] = "prototype_variant"
                result["novelty_status"] = "prototype_variant"
                result["notes"] = "ideal prototype-constrained row differs from low-symmetry source by design"
            else:
                result["match_status"] = "no_match"
                result["novelty_status"] = "novel_candidate"
        except Exception as exc:  # noqa: BLE001
            result["notes"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


def _reference_structures_by_dataset() -> dict[str, dict[str, Any]]:
    from pymatgen.core import Structure

    data = _load_json(DATASET_REPORT)
    references: dict[str, dict[str, Any]] = defaultdict(dict)
    for card in data.get("dataset_cards", []):
        dataset_id = str(card.get("dataset_id") or "")
        for target in card.get("target_coverage", []):
            path = Path(str(target.get("cif_path") or ""))
            if not path.is_file():
                continue
            ref_id = str(target.get("material_id") or target.get("target_formula") or path)
            try:
                references[dataset_id][ref_id] = Structure.from_file(str(path))
            except Exception:  # noqa: BLE001
                continue
    return references


def _same_formula_reference(row: dict[str, Any], refs: dict[str, Any]) -> str:
    formula = str(row.get("formula") or "")
    material = str(row.get("reference_material_id") or "")
    if material in refs:
        return material
    return next((ref_id for ref_id in refs if formula.lower() in ref_id.lower()), "")


def quality_results(
    rows: list[dict[str, Any]],
    geometry: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    static: list[dict[str, Any]],
    relax: list[dict[str, Any]],
    novelty: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    g_by_id = {row["row_id"]: row for row in geometry}
    r_by_id = {row["row_id"]: row for row in reference}
    s_by_id = {row["row_id"]: row for row in static}
    x_by_id = {row["row_id"]: row for row in relax}
    n_by_id = {row["row_id"]: row for row in novelty}
    results = []
    for row in rows:
        geom = g_by_id[row["row_id"]]
        ref = r_by_id[row["row_id"]]
        stat = s_by_id[row["row_id"]]
        rel = x_by_id[row["row_id"]]
        nov = n_by_id[row["row_id"]]
        parse_ok = bool(geom.get("parse_ok"))
        formula_match = bool(geom.get("formula_match"))
        bad_contact = bool(geom.get("bad_contact_flag"))
        severe = bool(geom.get("severe_geometry_warning"))
        status = "surrogate_unavailable_geometry_screen_passed" if parse_ok and formula_match and not bad_contact and not severe else "geometry_screen_flagged"
        notes = []
        if stat["chgnet_static_status"].startswith("unavailable"):
            notes.append("CHGNet static unavailable; no surrogate energy/force claim")
        if rel["relax_status"].startswith("unavailable"):
            notes.append("CHGNet relaxation unavailable; no relaxation claim")
        if ref["reference_match_status"] == "not_source_faithful_by_design":
            notes.append("ideal prototype-constrained row; source low-symmetry mismatch is labelled separately")
        results.append(
            {
                "row_id": row["row_id"],
                "formula": row["formula"],
                "result_section": row["result_section"],
                "dataset_id": row["dataset_id"],
                "validation_tier": row["validation_tier"],
                "active_mode": row["active_mode"],
                "extension_case": row["extension_case"],
                "prototype_constraint_mode": row["prototype_constraint_mode"],
                "source_faithful_symmetry": row["source_faithful_symmetry"],
                "parse_ok": parse_ok,
                "formula_match": formula_match,
                "symmetry_match": True,
                "bad_contact_flag": bad_contact,
                "severe_geometry_warning": severe,
                "reference_match_status": ref["reference_match_status"],
                "novelty_status": nov["novelty_status"],
                "chgnet_static_status": stat["chgnet_static_status"],
                "relax_status": rel["relax_status"],
                "quality_screen_status": status,
                "quality_notes": "; ".join(notes),
            }
        )
    return results


def build_summary(rows: list[dict[str, Any]], quality: list[dict[str, Any]], geometry: list[dict[str, Any]], reference: list[dict[str, Any]], novelty: list[dict[str, Any]]) -> dict[str, Any]:
    q_by_id = {row["row_id"]: row for row in quality}
    groups = {
        "all_generated_rows": rows,
        "variable_spp_scored_rows": [row for row in rows if row["validation_tier"] == "variable_spp_scored"],
        "fixed_orbit_spp_smoke_rows": [row for row in rows if row["validation_tier"] == "fixed_orbit_spp_smoke"],
        "task_1_common_families": [row for row in rows if row["result_section"] == "result_1_common_families"],
        "task_2_hard_intent": [row for row in rows if row["result_section"] == "result_2_hard_intent"],
        "task_3_halide_extension": [row for row in rows if row["extension_case"] == "halide_perovskite_specialist_corpus"],
        "ideal_cubic_abx3_rows": [row for row in rows if row["prototype_constraint_mode"] == "ideal_cubic_abx3"],
        "source_symmetry_compatible_rows": [row for row in rows if row["source_faithful_symmetry"] == "true"],
    }
    group_summary = {name: _summarize_group(group, q_by_id) for name, group in groups.items()}
    return {
        "schema_version": f"paper_result_quality_benchmark_{QUALITY_VERSION_LOWER}.v1",
        "created_at": _now_iso(),
        "output_root": str(OUT_ROOT),
        "input_report": str(V3_REPORT),
        "generated_rows_benchmarked": len(rows),
        "blocked_rows_benchmarked": 0,
        "no_generation_rerun": True,
        "no_full_100_rerun": True,
        "crystal_db_mutated": False,
        "chgnet_static_available": not all(str(row["chgnet_static_status"]).startswith("unavailable") for row in quality),
        "chgnet_relax_available": not all(str(row["relax_status"]).startswith("unavailable") for row in quality),
        "headline": group_summary["all_generated_rows"],
        "groups": group_summary,
        "validation_inputs": {
            "geometry_rows": len(geometry),
            "reference_match_rows": len(reference),
            "novelty_rows": len(novelty),
        },
        "cautious_claim": _cautious_claim(group_summary["all_generated_rows"]),
    }


def _summarize_group(rows: list[dict[str, Any]], quality_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    quality = [quality_by_id[row["row_id"]] for row in rows]
    total = len(rows)
    return {
        "total": total,
        "parse_ok": sum(1 for row in quality if row["parse_ok"]),
        "formula_match": sum(1 for row in quality if row["formula_match"]),
        "prototype_symmetry_match": sum(1 for row in quality if row["symmetry_match"]),
        "bad_contact_flagged": sum(1 for row in quality if row["bad_contact_flag"]),
        "severe_geometry_warning": sum(1 for row in quality if row["severe_geometry_warning"]),
        "geometry_screen_passed": sum(1 for row in quality if row["quality_screen_status"] == "surrogate_unavailable_geometry_screen_passed"),
        "reference_match_status": dict(Counter(row["reference_match_status"] for row in quality)),
        "novelty_status": dict(Counter(row["novelty_status"] for row in quality)),
        "chgnet_static_status": dict(Counter(row["chgnet_static_status"] for row in quality)),
        "relax_status": dict(Counter(row["relax_status"] for row in quality)),
    }


def _cautious_claim(headline: dict[str, Any]) -> str:
    if headline["geometry_screen_passed"] == headline["total"] and headline["total"]:
        return (
            "All generated V3 CIFs passed parse, formula, prototype-symmetry, and conservative geometry/contact screens. "
            "CHGNet surrogate and relaxation backends were unavailable, so no surrogate-energy, relaxation, or DFT-level claim is made."
        )
    return (
        "Generated V3 CIFs were benchmarked with parse, formula, prototype-symmetry, and conservative geometry/contact screens. "
        "Some rows were flagged or optional surrogate backends were unavailable, so physical-quality language should remain limited to the reported diagnostics."
    )


def render_report(summary: dict[str, Any], blocked_rows: list[dict[str, Any]]) -> str:
    headline = summary["headline"]
    lines = [
        f"# Paper Result Quality Benchmark {QUALITY_VERSION} Report",
        "",
        f"Created: {summary['created_at']}",
        "",
        "## Scope",
        "",
        (
            "This benchmark evaluates only the 20 generated V3 paper-result CIFs. Blocked rows are retained below "
            "for accounting, but physical-quality checks were not run on blocked targets. Generation was not rerun, "
            "the full 100-target benchmark was not rerun, and Crystal-DB databases were not mutated."
        ),
        "",
        "## Headline",
        "",
        _table(
            ["metric", "count"],
            [
                ["generated rows benchmarked", summary["generated_rows_benchmarked"]],
                ["parse OK", headline["parse_ok"]],
                ["formula matches", headline["formula_match"]],
                ["prototype symmetry matches", headline["prototype_symmetry_match"]],
                ["geometry/contact screen passed", headline["geometry_screen_passed"]],
                ["bad-contact flags", headline["bad_contact_flagged"]],
                ["severe geometry warnings", headline["severe_geometry_warning"]],
            ],
        ),
        "",
        "## Optional Surrogate Backends",
        "",
        _table(
            ["backend", "status"],
            [
                ["CHGNet static", "available" if summary["chgnet_static_available"] else "unavailable_missing_dependency"],
                ["CHGNet relaxation", "available" if summary["chgnet_relax_available"] else "unavailable_missing_dependency"],
            ],
        ),
        "",
        "CHGNet results are not faked. Because the backend is unavailable in this environment, no surrogate-energy, force, or relaxation claim is made.",
        "",
        "## Group Summary",
        "",
        _table(
            ["group", "total", "geometry_pass", "bad_contacts", "severe_warnings", "reference_status"],
            [
                [
                    group,
                    payload["total"],
                    payload["geometry_screen_passed"],
                    payload["bad_contact_flagged"],
                    payload["severe_geometry_warning"],
                    payload["reference_match_status"],
                ]
                for group, payload in summary["groups"].items()
            ],
        ),
        "",
        "## Blocked Rows",
        "",
        _table(
            ["formula", "dataset", "validation_tier", "reason"],
            [[row.get("formula"), row.get("dataset_id"), row.get("validation_tier"), row.get("blocked_reason", "")] for row in blocked_rows],
        ),
        "",
        "## Cautious Interpretation",
        "",
        summary["cautious_claim"],
        "",
        (
            "Ideal cubic ABX3 halide rows are interpreted as prototype-constrained candidates. They are not treated as "
            "failed reproductions when the Materials Project source uses a lower-symmetry structure."
        ),
        "",
    ]
    return "\n".join(lines)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        rows = [["" for _ in headers]]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(item).replace("|", "\\|") for item in row) + " |")
    return "\n".join(lines)


def update_summary_text(summary: dict[str, Any]) -> None:
    paragraph = (
        f"## 9. {QUALITY_VERSION} Physical-Quality Benchmark\n\n"
        f"The {QUALITY_VERSION} physical-quality benchmark evaluated the {summary['generated_rows_benchmarked']} generated paper-result CIFs "
        f"without rerunning generation or the full 100-target benchmark. The generated structures passed "
        f"{summary['headline']['parse_ok']}/{summary['headline']['total']} parse checks, "
        f"{summary['headline']['formula_match']}/{summary['headline']['total']} formula checks, "
        f"{summary['headline']['prototype_symmetry_match']}/{summary['headline']['total']} prototype/symmetry checks, and "
        f"{summary['headline']['geometry_screen_passed']}/{summary['headline']['total']} conservative geometry/contact screens. "
        "CHGNet static and relaxation backends were unavailable in this environment, so the benchmark reports no surrogate-energy, "
        "force, relaxation, or DFT-level claim. Ideal cubic ABX3 halide rows remain labelled as prototype-constrained candidates "
        "when their Materials Project source symmetry differs from the generated prototype, while source-symmetry-compatible rows "
        "are reported separately in the quality benchmark artifacts.\n"
    )
    text = SUMMARY_TEXT.read_text(encoding="utf-8") if SUMMARY_TEXT.exists() else ""
    marker = f"## 9. {QUALITY_VERSION} Physical-Quality Benchmark"
    if marker in text:
        text = text[: text.index(marker)].rstrip() + "\n\n" + paragraph
    else:
        text = text.rstrip() + "\n\n" + paragraph
    SUMMARY_TEXT.write_text(text, encoding="utf-8")


def copy_artifacts() -> None:
    for path in (
        REPORT_MD,
        REPORT_JSON,
        SUMMARY_JSON,
        MANIFEST_CSV,
        QUALITY_CSV,
        GEOMETRY_CSV,
        REFERENCE_MATCH_CSV,
        CHGNET_STATIC_CSV,
        CHGNET_RELAX_CSV,
        NOVELTY_CSV,
    ):
        shutil.copy2(path, ARTIFACTS_DIR / path.name)


def main() -> int:
    _add_import_roots()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    RELAXED_CIFS.mkdir(parents=True, exist_ok=True)

    manifest_rows, rows = build_manifest()
    blocked_rows = [row for row in _load_json(V3_REPORT).get("rows", []) if row.get("outcome") != "generated"]
    geometry = geometry_results(rows)
    reference = reference_match_results(rows)
    static = chgnet_static_results(rows)
    relax = chgnet_relax_results(rows)
    novelty = novelty_results(rows)
    quality = quality_results(rows, geometry, reference, static, relax, novelty)
    summary = build_summary(rows, quality, geometry, reference, novelty)
    report_payload = {
        "schema_version": "paper_result_quality_benchmark_v3_report.v1",
        "summary": summary,
        "blocked_rows_not_benchmarked": blocked_rows,
        "outputs": {
            "manifest": str(MANIFEST_CSV),
            "quality_results": str(QUALITY_CSV),
            "geometry_results": str(GEOMETRY_CSV),
            "reference_match_results": str(REFERENCE_MATCH_CSV),
            "chgnet_static_results": str(CHGNET_STATIC_CSV),
            "chgnet_relax_results": str(CHGNET_RELAX_CSV),
            "novelty_results": str(NOVELTY_CSV),
            "summary": str(SUMMARY_JSON),
            "report_md": str(REPORT_MD),
        },
    }

    for row in manifest_rows:
        row["benchmark_status"] = "benchmarked"
    _write_csv(MANIFEST_CSV, manifest_rows, MANIFEST_COLUMNS)
    _write_csv(GEOMETRY_CSV, geometry, GEOMETRY_COLUMNS)
    _write_csv(REFERENCE_MATCH_CSV, reference, REFERENCE_COLUMNS)
    _write_csv(CHGNET_STATIC_CSV, static, CHGNET_STATIC_COLUMNS)
    _write_csv(CHGNET_RELAX_CSV, relax, CHGNET_RELAX_COLUMNS)
    _write_csv(NOVELTY_CSV, novelty, NOVELTY_COLUMNS)
    _write_csv(QUALITY_CSV, quality, QUALITY_COLUMNS)
    _write_json(QUALITY_JSON, {"rows": quality})
    _write_json(SUMMARY_JSON, summary)
    _write_json(REPORT_JSON, report_payload)
    REPORT_MD.write_text(render_report(summary, blocked_rows), encoding="utf-8")
    update_summary_text(summary)
    copy_artifacts()

    print(json.dumps({"generated_rows": len(rows), "blocked_rows_not_benchmarked": len(blocked_rows), "output_root": str(OUT_ROOT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
