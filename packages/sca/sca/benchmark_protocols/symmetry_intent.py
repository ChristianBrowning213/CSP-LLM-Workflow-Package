"""Dedicated symmetry and space-group intent benchmark."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.symmetry.groups import SpaceGroup

from sca.evaluators.cif_parse import parse_cif
from sca.io import load_manifest_frame


RESULT_COLUMNS = [
    "prompt_id",
    "benchmark_id",
    "target_formula",
    "target_family",
    "target_space_group",
    "target_space_group_number",
    "target_crystal_system",
    "declared_space_group",
    "declared_space_group_number",
    "analyzed_space_group",
    "analyzed_space_group_number",
    "analyzed_crystal_system",
    "space_group_exact_match",
    "space_group_number_match",
    "crystal_system_match",
    "family_symmetry_compatible",
    "symmetry_match_level",
    "symmetry_score",
    "symmetry_status",
    "symmetry_error",
    "symprec",
    "angle_tolerance",
    "cif_path",
]

DECLARED_SYMBOL_FIELDS = (
    "_symmetry_space_group_name_H-M",
    "_space_group_name_H-M_alt",
)
DECLARED_NUMBER_FIELDS = ("_space_group_IT_number", "_symmetry_Int_Tables_number")

FAMILY_CRYSTAL_SYSTEMS = {
    "perovskite": ("cubic", "tetragonal", "orthorhombic"),
    "oxide perovskite": ("cubic", "tetragonal", "orthorhombic"),
    "halide perovskite": ("cubic", "tetragonal", "orthorhombic"),
    "spinel": ("cubic",),
    "rocksalt": ("cubic",),
    "fluorite": ("cubic",),
    "pyrite": ("cubic",),
    "layered oxide": ("rhombohedral", "hexagonal", "trigonal"),
    "olivine phosphate": ("orthorhombic",),
    "argyrodite": ("cubic",),
    "nitride": ("cubic",),
    "rocksalt-like nitride": ("cubic",),
}


def run_symmetry_intent_benchmark(
    *,
    manifest: str | Path,
    out_dir: str | Path,
    symprec: str = "0.01",
    angle_tolerance: float = 5.0,
    path_col: str = "cif_path",
) -> dict[str, Any]:
    """Run symmetry intent checks over a generated-CIF manifest."""

    manifest_path = Path(manifest)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = load_manifest_frame(manifest_path, path_col).fillna("")
    symprec_values = _parse_symprec_values(symprec)
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        row_data = {str(key): value for key, value in row.to_dict().items()}
        for symprec_value in symprec_values:
            rows.append(evaluate_symmetry_intent_row(row_data, symprec=symprec_value, angle_tolerance=angle_tolerance, path_col=path_col))
    summary = summarize_symmetry_rows(rows, symprec_values=symprec_values, angle_tolerance=angle_tolerance)

    results_csv = out / "symmetry_results.csv"
    summary_json = out / "symmetry_summary.json"
    report_md = out / "symmetry_report.md"
    pd.DataFrame(rows, columns=RESULT_COLUMNS).to_csv(results_csv, index=False)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report_md.write_text(render_symmetry_report(summary, rows), encoding="utf-8")
    return {
        "rows": len(rows),
        "results_csv": str(results_csv),
        "summary_json": str(summary_json),
        "report_md": str(report_md),
    }


def evaluate_symmetry_intent_row(
    row: dict[str, Any],
    *,
    symprec: float = 0.01,
    angle_tolerance: float = 5.0,
    path_col: str = "cif_path",
) -> dict[str, Any]:
    constraints = _constraints(row)
    cif_path = str(row.get(path_col) or row.get("cif_path") or "")
    target_space_group = _target(row, constraints, "space_group", "target_space_group")
    target_space_group_number = _target(row, constraints, "space_group_number", "target_space_group_number")
    target_crystal_system = _target(row, constraints, "crystal_system", "target_crystal_system")
    target_family = _target(row, constraints, "structure_family", "target_structure_family")

    base = {
        "prompt_id": _cell(row, "prompt_id"),
        "benchmark_id": _cell(row, "benchmark_id") or _cell(row, "prompt_id"),
        "target_formula": _target(row, constraints, "formula", "target_formula"),
        "target_family": target_family,
        "target_space_group": target_space_group,
        "target_space_group_number": target_space_group_number,
        "target_crystal_system": target_crystal_system,
        "declared_space_group": None,
        "declared_space_group_number": None,
        "analyzed_space_group": None,
        "analyzed_space_group_number": None,
        "analyzed_crystal_system": None,
        "space_group_exact_match": None,
        "space_group_number_match": None,
        "crystal_system_match": None,
        "family_symmetry_compatible": None,
        "symmetry_match_level": "not_computable",
        "symmetry_score": None,
        "symmetry_status": "not_computable",
        "symmetry_error": None,
        "symprec": symprec,
        "angle_tolerance": angle_tolerance,
        "cif_path": cif_path,
    }
    try:
        cif_text = Path(cif_path).read_text(encoding="utf-8")
    except Exception as exc:
        base["symmetry_error"] = f"{type(exc).__name__}: {exc}"
        return base

    declared_symbol, declared_number = _extract_declared_space_group(cif_text)
    base["declared_space_group"] = declared_symbol
    base["declared_space_group_number"] = declared_number
    structure, parsed = parse_cif(cif_path)
    if structure is None:
        base["symmetry_error"] = parsed.error_message or parsed.error_type or "parse_failed"
        return base
    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=symprec, angle_tolerance=angle_tolerance)
        analyzed_symbol = analyzer.get_space_group_symbol()
        analyzed_number = analyzer.get_space_group_number()
        analyzed_system = analyzer.get_crystal_system()
    except Exception as exc:
        base["symmetry_error"] = f"{type(exc).__name__}: {exc}"
        return base

    target_number = _space_group_number(target_space_group_number) or _space_group_number(target_space_group)
    target_symbol = _space_group_symbol(target_space_group)
    number_match = target_number == analyzed_number if target_number is not None else None
    symbol_match = _normalize_sg_symbol(target_symbol) == _normalize_sg_symbol(analyzed_symbol) if target_symbol else None
    exact_match = bool(number_match or symbol_match) if target_number is not None or target_symbol else None
    crystal_system_match = _crystal_system_match(target_crystal_system, analyzed_system)
    family_compatible = _family_compatible(target_family, row.get("chemistry_family"), analyzed_system)
    match_level, score = _match_level_and_score(
        exact_match=exact_match,
        crystal_system_match=crystal_system_match,
        family_compatible=family_compatible,
        has_target=bool(target_number or target_symbol or target_crystal_system or target_family),
    )
    base.update(
        {
            "analyzed_space_group": analyzed_symbol,
            "analyzed_space_group_number": analyzed_number,
            "analyzed_crystal_system": analyzed_system,
            "space_group_exact_match": exact_match,
            "space_group_number_match": number_match,
            "crystal_system_match": crystal_system_match,
            "family_symmetry_compatible": family_compatible,
            "symmetry_match_level": match_level,
            "symmetry_score": score,
            "symmetry_status": "ok" if match_level != "not_computable" else "not_computable",
        }
    )
    return base


def summarize_symmetry_rows(rows: list[dict[str, Any]], *, symprec_values: list[float], angle_tolerance: float) -> dict[str, Any]:
    total = len(rows)
    parseable = [row for row in rows if row.get("analyzed_space_group")]
    summary = {
        "benchmark_name": "symmetry_intent",
        "symprec_values": symprec_values,
        "angle_tolerance": angle_tolerance,
        "total_rows": total,
        "parseable_rows": len(parseable),
        "declared_p1_rate": _rate(sum(1 for row in rows if _is_p1(row.get("declared_space_group"), row.get("declared_space_group_number"))), total),
        "analyzed_p1_rate": _rate(sum(1 for row in rows if _is_p1(row.get("analyzed_space_group"), row.get("analyzed_space_group_number"))), len(parseable)),
        "space_group_exact_match_rate": _bool_rate(rows, "space_group_exact_match"),
        "space_group_number_match_rate": _bool_rate(rows, "space_group_number_match"),
        "crystal_system_match_rate": _bool_rate(rows, "crystal_system_match"),
        "family_symmetry_compatible_rate": _bool_rate(rows, "family_symmetry_compatible"),
        "symmetry_not_computable_rate": _rate(sum(1 for row in rows if row.get("symmetry_match_level") == "not_computable"), total),
        "symmetry_mismatch_rate": _rate(sum(1 for row in rows if row.get("symmetry_match_level") == "mismatch"), total),
        "mean_symmetry_score": _mean(row.get("symmetry_score") for row in rows),
        "counts_by_target_family": _counts(rows, "target_family"),
        "counts_by_symmetry_match_level": _counts(rows, "symmetry_match_level"),
        "family_compatibility_mapping": FAMILY_CRYSTAL_SYSTEMS,
    }
    return summary


def render_symmetry_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Symmetry Intent Benchmark Report",
        "",
        "This report checks whether generated CIFs have the requested space group, crystal system, or prototype-compatible symmetry. It is evaluation-only and does not rerun generation.",
        "",
        "## Summary",
        "",
        f"- Total rows: {summary['total_rows']}",
        f"- Parseable rows: {summary['parseable_rows']}",
        f"- Declared P1 rate: {_fmt(summary['declared_p1_rate'])}",
        f"- Analyzed P1 rate: {_fmt(summary['analyzed_p1_rate'])}",
        f"- Space-group exact match rate: {_fmt(summary['space_group_exact_match_rate'])}",
        f"- Crystal-system match rate: {_fmt(summary['crystal_system_match_rate'])}",
        f"- Family symmetry-compatible rate: {_fmt(summary['family_symmetry_compatible_rate'])}",
        f"- Not-computable rate: {_fmt(summary['symmetry_not_computable_rate'])}",
        f"- Mismatch rate: {_fmt(summary['symmetry_mismatch_rate'])}",
        f"- Mean symmetry score: {_fmt(summary['mean_symmetry_score'])}",
        "",
        "## Match-Level Counts",
        "",
    ]
    lines.extend(_markdown_table(_dict_rows(summary["counts_by_symmetry_match_level"], "match_level"), ["match_level", "count"]))
    lines.extend(["", "## Counts By Target Family", ""])
    lines.extend(_markdown_table(_dict_rows(summary["counts_by_target_family"], "target_family"), ["target_family", "count"]))
    lines.extend(["", "## Family Compatibility Heuristic", ""])
    mapping_rows = [{"target_family": key, "accepted_crystal_systems": ", ".join(value)} for key, value in FAMILY_CRYSTAL_SYSTEMS.items()]
    lines.extend(_markdown_table(mapping_rows, ["target_family", "accepted_crystal_systems"]))
    lines.extend(["", "## Example Rows", ""])
    lines.extend(
        _markdown_table(
            rows[:20],
            [
                "prompt_id",
                "target_family",
                "target_space_group",
                "target_crystal_system",
                "declared_space_group",
                "analyzed_space_group",
                "analyzed_crystal_system",
                "symmetry_match_level",
                "symmetry_score",
            ],
        )
    )
    return "\n".join(lines) + "\n"


def _parse_symprec_values(raw: str) -> list[float]:
    values = [float(item.strip()) for item in str(raw).split(",") if item.strip()]
    if not values:
        raise ValueError("At least one symprec value is required")
    return values


def _constraints(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("intent_constraints_json")
    if isinstance(raw, dict):
        return raw
    if raw is None or str(raw).strip() == "":
        return {}
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _target(row: dict[str, Any], constraints: dict[str, Any], constraint_key: str, row_key: str) -> str:
    return _cell({"value": constraints.get(constraint_key) or row.get(row_key)}, "value")


def _cell(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _extract_declared_space_group(cif_text: str) -> tuple[str | None, int | None]:
    symbol = None
    number = None
    for field in DECLARED_SYMBOL_FIELDS:
        match = re.search(rf"^{re.escape(field)}\s+(.+)$", cif_text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            symbol = match.group(1).strip().strip("'\"")
            break
    for field in DECLARED_NUMBER_FIELDS:
        match = re.search(rf"^{re.escape(field)}\s+([0-9]+)", cif_text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            number = int(match.group(1))
            break
    return symbol, number


def _space_group_number(value: Any) -> int | None:
    text = _cell({"value": value}, "value")
    if not text:
        return None
    first_int = re.search(r"\b([0-9]{1,3})\b", text)
    if first_int:
        number = int(first_int.group(1))
        return number if 1 <= number <= 230 else None
    symbol = _space_group_symbol(text)
    if not symbol:
        return None
    try:
        return int(SpaceGroup(symbol).int_number)
    except Exception:
        return None


def _space_group_symbol(value: Any) -> str:
    text = _cell({"value": value}, "value")
    if not text:
        return ""
    text = re.split(r"\bor\b|/", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.sub(r"\b(subgroup|space group|sg)\b", "", text, flags=re.IGNORECASE).strip()
    return text


def _normalize_sg_symbol(value: Any) -> str:
    return _cell({"value": value}, "value").replace(" ", "").replace("_", "").replace("'", "").replace('"', "").lower()


def _crystal_system_match(target: str, analyzed: str | None) -> bool | None:
    systems = _target_systems(target)
    if not systems or not analyzed:
        return None
    return analyzed.lower().strip() in systems


def _target_systems(target: str) -> set[str]:
    text = _cell({"value": target}, "value").lower()
    if not text:
        return set()
    parts = re.split(r"[/,;]|\bor\b", text)
    return {part.strip() for part in parts if part.strip()}


def _family_compatible(target_family: str, chemistry_family: Any, analyzed_system: str | None) -> bool | None:
    if not analyzed_system:
        return None
    text = " ".join([target_family, _cell({"value": chemistry_family}, "value")]).lower()
    for family, systems in FAMILY_CRYSTAL_SYSTEMS.items():
        if family in text:
            return analyzed_system.lower() in systems
    return None


def _match_level_and_score(
    *,
    exact_match: bool | None,
    crystal_system_match: bool | None,
    family_compatible: bool | None,
    has_target: bool,
) -> tuple[str, float | None]:
    if not has_target:
        return "not_computable", None
    if exact_match is True:
        return "exact_space_group", 1.0
    if crystal_system_match is True:
        return "same_crystal_system", 0.75
    if exact_match is None and crystal_system_match is None and family_compatible is True:
        return "family_compatible", 0.5
    if family_compatible is True and exact_match is None:
        return "family_compatible", 0.5
    if exact_match is False or crystal_system_match is False or family_compatible is False:
        return "mismatch", 0.0
    return "not_computable", None


def _is_p1(symbol: Any, number: Any) -> bool:
    number_int = _space_group_number(number)
    if number_int is not None:
        return number_int == 1
    return _normalize_sg_symbol(symbol) == "p1"


def _bool_rate(rows: list[dict[str, Any]], column: str) -> float | None:
    values = [_as_bool(row.get(column)) for row in rows]
    values = [value for value in values if value is not None]
    return _rate(sum(values), len(values)) if values else None


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _mean(values: Any) -> float | None:
    numbers = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        numbers.append(number)
    return sum(numbers) / len(numbers) if numbers else None


def _counts(rows: list[dict[str, Any]], column: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = _cell(row, column) or "missing"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "1.0", "yes"}:
        return True
    if normalized in {"false", "0", "0.0", "no"}:
        return False
    return None


def _fmt(value: Any) -> str:
    if value is None:
        return "not_computable"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _dict_rows(data: dict[str, int], key_name: str) -> list[dict[str, Any]]:
    return [{key_name: key, "count": value} for key, value in data.items()]


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["No rows."]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |")
    return lines


def _markdown_cell(value: Any) -> str:
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")
