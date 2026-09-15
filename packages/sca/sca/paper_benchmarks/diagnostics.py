"""Per-target diagnostics for paper-target benchmark outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sca.evaluators.cif_parse import parse_cif


DIAGNOSTIC_COLUMNS = [
    "benchmark_id",
    "file_name",
    "cif_path",
    "reference_id",
    "reference_cif_path",
    "relaxed_cif_path",
    "target_formula",
    "generated_reduced_formula",
    "reference_formula",
    "target_structure_family",
    "reference_prototype",
    "structure_match",
    "structure_match_after",
    "rms_dist",
    "rms_dist_before",
    "rms_dist_after",
    "relax_ok",
    "energy_drop_per_atom",
    "max_force_before",
    "max_force_after",
    "mlip_consensus_stable_flag",
    "geometry_ok",
    "bond_lengths_reasonable",
    "num_bad_contacts",
    "generated_space_group",
    "reference_space_group",
    "relaxed_space_group",
    "generated_volume",
    "reference_volume",
    "relaxed_volume",
    "relaxed_volume_ratio",
    "primary_category",
    "category_flags",
    "failure_modes",
    "relaxation_effect",
    "reference_risk",
    "diagnostic_confidence",
    "diagnostic_reason",
]


def build_paper_target_diagnostics(
    results_csv: str | Path,
    manifest_csv: str | Path,
    references_csv: str | Path,
) -> list[dict[str, Any]]:
    results = pd.read_csv(results_csv, dtype=str).fillna("")
    manifest = pd.read_csv(manifest_csv, dtype=str).fillna("")
    references = pd.read_csv(references_csv, dtype=str).fillna("")
    manifest_by_id = _by_key(manifest, "benchmark_id")
    reference_by_id = _by_key(references, "benchmark_id")
    manifest_base = Path(manifest_csv).parent
    reference_base = Path(references_csv).parent

    rows = []
    for _, result in results.iterrows():
        benchmark_id = _cell(result, "benchmark_id")
        manifest_row = manifest_by_id.get(benchmark_id, {})
        reference_row = reference_by_id.get(benchmark_id, {})
        generated_path = _resolve_path(_cell(result, "cif_path") or _cell(result, "input_path"), manifest_base)
        reference_path = _resolve_path(
            _cell(result, "reference_cif_path")
            or _cell(manifest_row, "reference_cif_path")
            or _cell(reference_row, "reference_cif_path"),
            reference_base,
        )
        relaxed_path = _resolve_path(_cell(result, "relaxed_cif_path"), Path.cwd())

        generated_info = _structure_info(generated_path)
        reference_info = _structure_info(reference_path)
        relaxed_info = _structure_info(relaxed_path)
        classification = _classify(result, manifest_row, reference_row, generated_info, reference_info, relaxed_info)

        row = {
            "benchmark_id": benchmark_id,
            "file_name": _cell(result, "file_name"),
            "cif_path": str(generated_path) if generated_path else "",
            "reference_id": _cell(result, "reference_id") or _cell(reference_row, "reference_id"),
            "reference_cif_path": str(reference_path) if reference_path else "",
            "relaxed_cif_path": str(relaxed_path) if relaxed_path else "",
            "target_formula": _cell(result, "target_formula") or _cell(manifest_row, "target_formula"),
            "generated_reduced_formula": _cell(result, "generated_reduced_formula") or _cell(result, "reduced_formula"),
            "reference_formula": _cell(reference_row, "reference_formula") or reference_info["reduced_formula"],
            "target_structure_family": _cell(result, "target_structure_family") or _cell(manifest_row, "target_structure_family"),
            "reference_prototype": _cell(reference_row, "reference_prototype"),
            "structure_match": _cell(result, "structure_match"),
            "structure_match_after": _cell(result, "structure_match_after"),
            "rms_dist": _cell(result, "rms_dist"),
            "rms_dist_before": _cell(result, "rms_dist_before"),
            "rms_dist_after": _cell(result, "rms_dist_after"),
            "relax_ok": _cell(result, "relax_ok"),
            "energy_drop_per_atom": _cell(result, "energy_drop_per_atom"),
            "max_force_before": _cell(result, "max_force_before"),
            "max_force_after": _cell(result, "max_force_after"),
            "mlip_consensus_stable_flag": _cell(result, "mlip_consensus_stable_flag"),
            "geometry_ok": _cell(result, "geometry_ok"),
            "bond_lengths_reasonable": _cell(result, "bond_lengths_reasonable"),
            "num_bad_contacts": _cell(result, "num_bad_contacts"),
            "generated_space_group": generated_info["space_group"],
            "reference_space_group": reference_info["space_group"],
            "relaxed_space_group": relaxed_info["space_group"],
            "generated_volume": generated_info["volume"],
            "reference_volume": reference_info["volume"],
            "relaxed_volume": relaxed_info["volume"],
            "relaxed_volume_ratio": _volume_ratio(generated_info["volume"], relaxed_info["volume"]),
            **classification,
        }
        rows.append({column: row.get(column, "") for column in DIAGNOSTIC_COLUMNS})
    return rows


def write_diagnostics_outputs(
    rows: list[dict[str, Any]],
    out_csv: str | Path,
    out_json: str | Path,
    markdown: str | Path | None = None,
) -> None:
    out_csv = Path(out_csv)
    out_json = Path(out_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=DIAGNOSTIC_COLUMNS).to_csv(out_csv, index=False)
    out_json.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    if markdown:
        markdown_path = Path(markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_diagnostics_markdown(rows), encoding="utf-8")


def render_diagnostics_markdown(rows: list[dict[str, Any]]) -> str:
    frame = pd.DataFrame(rows)
    lines = [
        "# Paper Target Diagnostics",
        "",
        f"- Targets: {len(rows)}",
        "- This report classifies failures from existing benchmark columns and parsed CIF/reference/relaxed structures.",
        "- It does not change benchmark metrics.",
        "",
        "## Category Counts",
        "",
    ]
    if frame.empty:
        lines.append("No diagnostics rows.")
        return "\n".join(lines) + "\n"
    counts = frame["primary_category"].value_counts(dropna=False)
    lines.extend(["| category | count |", "|---|---:|"])
    lines.extend(f"| {category} | {count} |" for category, count in counts.items())
    lines.extend(["", "## Per Target", ""])
    cols = [
        "benchmark_id",
        "primary_category",
        "relaxation_effect",
        "reference_risk",
        "diagnostic_reason",
    ]
    lines.extend(_markdown_table(frame[cols].to_dict(orient="records")))
    return "\n".join(lines) + "\n"


def _classify(
    result: pd.Series,
    manifest_row: dict | pd.Series,
    reference_row: dict | pd.Series,
    generated_info: dict[str, Any],
    reference_info: dict[str, Any],
    relaxed_info: dict[str, Any],
) -> dict[str, str]:
    flags: list[str] = []
    reasons: list[str] = []

    structure_match = _bool(_cell(result, "structure_match"))
    structure_match_after = _bool(_cell(result, "structure_match_after"))
    relax_ok = _bool(_cell(result, "relax_ok"))
    geometry_ok = _bool(_cell(result, "geometry_ok"))
    bonds_ok = _bool(_cell(result, "bond_lengths_reasonable"))
    mlip_stable = _bool(_cell(result, "mlip_consensus_stable_flag"))
    bad_contacts = _float(_cell(result, "num_bad_contacts")) or 0
    force_before = _float(_cell(result, "max_force_before"))
    force_after = _float(_cell(result, "max_force_after"))
    energy_drop = _float(_cell(result, "energy_drop_per_atom"))
    rms_before = _float(_cell(result, "rms_dist_before"))
    rms_after = _float(_cell(result, "rms_dist_after"))
    volume_ratio = _volume_ratio(generated_info["volume"], relaxed_info["volume"])

    if structure_match is True:
        flags.append("exact_reference_match")
        reasons.append("StructureMatcher matched the generated CIF to the reference.")
    elif structure_match_after is True:
        flags.append("near_match")
        reasons.append("Generated CIF did not match, but the relaxed CIF matches the reference.")

    if geometry_ok is False or bonds_ok is False or bad_contacts > 0:
        flags.append("bad_contacts_or_invalid_geometry")
        reasons.append("Pre-DFT geometry/contact checks flagged the generated CIF.")

    if relax_ok is False:
        flags.append("relaxation_failed")
        reasons.append("CHGNet relaxation did not satisfy the configured force threshold.")

    relaxation_effect = _relaxation_effect(
        force_before=force_before,
        force_after=force_after,
        energy_drop=energy_drop,
        rms_before=rms_before,
        rms_after=rms_after,
    )
    if relaxation_effect:
        flags.append(relaxation_effect)
    if _collapsed(volume_ratio, _cell(result, "relax_error")):
        flags.append("relaxed_structure_collapsed")
        reasons.append("Relaxed volume ratio or relaxation error indicates possible collapse.")

    if structure_match is not True and geometry_ok is True and bonds_ok is True:
        flags.append("wrong_prototype_or_symmetry")
        reasons.append("Generated CIF is geometrically plausible but does not match the reference prototype.")
    if mlip_stable is True and structure_match is not True:
        flags.append("mlip_stable_but_wrong_prototype")
        reasons.append("MLIP consensus marks the structure stable while StructureMatcher does not match the reference.")

    reference_risk = _reference_risk(manifest_row, reference_row, generated_info, reference_info)
    if reference_risk != "none":
        flags.append("reference_prototype_mismatch_risk")

    primary = _primary_category(flags)
    if primary == "uncertain":
        reasons.append("Available columns do not support a more specific classification.")
    return {
        "primary_category": primary,
        "category_flags": ";".join(dict.fromkeys(flags)) or "uncertain",
        "failure_modes": ";".join(flag for flag in flags if flag not in {"relaxation_improved", "relaxation_worsened"}),
        "relaxation_effect": relaxation_effect or "uncertain",
        "reference_risk": reference_risk,
        "diagnostic_confidence": _confidence(primary, reference_risk),
        "diagnostic_reason": " ".join(reasons),
    }


def _primary_category(flags: list[str]) -> str:
    priority = [
        "exact_reference_match",
        "bad_contacts_or_invalid_geometry",
        "relaxed_structure_collapsed",
        "relaxation_failed",
        "near_match",
        "mlip_stable_but_wrong_prototype",
        "wrong_prototype_or_symmetry",
        "reference_prototype_mismatch_risk",
    ]
    for category in priority:
        if category in flags:
            return category
    return "uncertain"


def _relaxation_effect(
    force_before: float | None,
    force_after: float | None,
    energy_drop: float | None,
    rms_before: float | None,
    rms_after: float | None,
) -> str | None:
    if rms_before is not None and rms_after is not None:
        if rms_after < rms_before - 1e-6:
            return "relaxation_improved"
        if rms_after > rms_before + 1e-6:
            return "relaxation_worsened"
    if force_before is not None and force_after is not None:
        force_improved = force_after < force_before
        energy_improved = energy_drop is None or energy_drop >= -1e-6
        if force_improved and energy_improved:
            return "relaxation_improved"
        if force_after > force_before:
            return "relaxation_worsened"
    if energy_drop is not None:
        return "relaxation_improved" if energy_drop >= 0 else "relaxation_worsened"
    return None


def _reference_risk(
    manifest_row: dict | pd.Series,
    reference_row: dict | pd.Series,
    generated_info: dict[str, Any],
    reference_info: dict[str, Any],
) -> str:
    reasons = []
    notes = " ".join(
        filter(
            None,
            [
                _cell(reference_row, "notes"),
                _cell(manifest_row, "notes"),
                _cell(manifest_row, "target_structure_family"),
            ],
        )
    ).lower()
    risk_terms = ("prototype", "ideal", "distorted", "proxy", "monoclinic", "not the")
    if any(term in notes for term in risk_terms):
        reasons.append("prototype_or_polymorph_note")
    target_family = (_cell(manifest_row, "target_structure_family") or "").lower()
    reference_family = (_cell(reference_row, "reference_family") or "").lower()
    if "/" in target_family or (reference_family and reference_family not in target_family and target_family not in reference_family):
        reasons.append("family_alias_or_proxy")
    generated_formula = generated_info["reduced_formula"]
    reference_formula = reference_info["reduced_formula"] or _cell(reference_row, "reference_formula")
    if generated_formula and reference_formula and generated_formula != reference_formula:
        reasons.append("formula_notation_or_composition_difference")
    return ";".join(dict.fromkeys(reasons)) if reasons else "none"


def _structure_info(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"parse_ok": False, "space_group": "", "reduced_formula": "", "volume": None}
    structure, parsed = parse_cif(path)
    if structure is None:
        return {
            "parse_ok": False,
            "space_group": "",
            "reduced_formula": "",
            "volume": None,
            "error": parsed.error_message,
        }
    try:
        space_group = SpacegroupAnalyzer(structure, symprec=0.1).get_space_group_symbol()
    except Exception:
        space_group = ""
    return {
        "parse_ok": True,
        "space_group": space_group,
        "reduced_formula": structure.composition.reduced_formula,
        "volume": float(structure.volume),
    }


def _volume_ratio(before: float | None, after: float | None) -> float | None:
    if before in {None, 0} or after is None:
        return None
    return float(after) / float(before)


def _collapsed(volume_ratio: float | None, relax_error: str | None) -> bool:
    if relax_error and "collapse" in relax_error.lower():
        return True
    return volume_ratio is not None and volume_ratio < 0.5


def _by_key(frame: pd.DataFrame, key: str) -> dict[str, pd.Series]:
    if key not in frame.columns:
        return {}
    return {str(row[key]): row for _, row in frame.iterrows() if str(row[key]).strip()}


def _resolve_path(value: str | None, base: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = base / path
    if candidate.exists():
        return candidate.resolve()
    return path


def _cell(row: dict | pd.Series, key: str) -> str:
    if key not in row:
        return ""
    value = row[key]
    if value is None or str(value).lower() == "nan":
        return ""
    return str(value).strip()


def _bool(value: str | None) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _confidence(primary: str, reference_risk: str) -> str:
    if primary == "uncertain":
        return "low"
    if reference_risk != "none" and primary in {"wrong_prototype_or_symmetry", "mlip_stable_but_wrong_prototype"}:
        return "medium"
    return "high"


def _markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No rows."]
    columns = list(rows[0])
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = [str(row.get(column, "")).replace("|", "\\|") for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return lines
