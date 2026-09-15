"""Verify cubic-compatible final CIFs in a paper evidence pack.

This is an evidence/reporting helper. It does not assert physical validity; it
only checks whether generated CIF lattice geometry or symmetry analysis is
cubic-compatible enough for a cubic-only showcase bundle.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any


def _load_manifest(out_root: Path) -> list[dict[str, Any]]:
    manifest_path = out_root / "manifests" / "paper_evidence_pack_v2_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest missing: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"manifest rows missing or invalid: {manifest_path}")
    return rows


def _resolve_path(repo_root: Path, path_text: str | None) -> Path | None:
    if not path_text:
        return None
    path = Path(path_text)
    if path.is_absolute():
        return path
    return repo_root / path


def _safe_fractional_spread(values: list[float]) -> float | None:
    if not values:
        return None
    avg = mean(values)
    if avg == 0:
        return None
    return (max(values) - min(values)) / avg


def _check_cif(
    cif_path: Path,
    length_tol_frac: float,
    angle_tol_deg: float,
    symprec: float,
) -> dict[str, Any]:
    try:
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    except Exception as exc:  # pragma: no cover - depends on optional env
        return {
            "parseable": False,
            "cubic_compatible": False,
            "cubic_geometry_pass": False,
            "spacegroup_cubic_pass": False,
            "error": f"pymatgen_unavailable: {exc}",
        }

    if not cif_path.exists():
        return {
            "parseable": False,
            "cubic_compatible": False,
            "cubic_geometry_pass": False,
            "spacegroup_cubic_pass": False,
            "error": "cif_missing",
        }

    try:
        structure = Structure.from_file(str(cif_path))
        lattice = structure.lattice
        lengths = [float(lattice.a), float(lattice.b), float(lattice.c)]
        angles = [float(lattice.alpha), float(lattice.beta), float(lattice.gamma)]
        length_spread = _safe_fractional_spread(lengths)
        max_angle_deviation = max(abs(angle - 90.0) for angle in angles)
        cubic_geometry_pass = (
            length_spread is not None
            and length_spread <= length_tol_frac
            and max_angle_deviation <= angle_tol_deg
        )

        crystal_system = None
        space_group_symbol = None
        space_group_number = None
        spacegroup_cubic_pass = False
        try:
            analyzer = SpacegroupAnalyzer(structure, symprec=symprec)
            crystal_system = analyzer.get_crystal_system()
            space_group_symbol = analyzer.get_space_group_symbol()
            space_group_number = analyzer.get_space_group_number()
            spacegroup_cubic_pass = crystal_system == "cubic"
        except Exception as exc:
            crystal_system = f"analysis_failed: {exc}"

        return {
            "parseable": True,
            "cubic_compatible": bool(cubic_geometry_pass or spacegroup_cubic_pass),
            "cubic_geometry_pass": bool(cubic_geometry_pass),
            "spacegroup_cubic_pass": bool(spacegroup_cubic_pass),
            "a": lengths[0],
            "b": lengths[1],
            "c": lengths[2],
            "alpha": angles[0],
            "beta": angles[1],
            "gamma": angles[2],
            "length_spread_frac": length_spread,
            "max_angle_deviation_deg": max_angle_deviation,
            "crystal_system": crystal_system,
            "space_group_symbol": space_group_symbol,
            "space_group_number": space_group_number,
            "error": "",
        }
    except Exception as exc:
        return {
            "parseable": False,
            "cubic_compatible": False,
            "cubic_geometry_pass": False,
            "spacegroup_cubic_pass": False,
            "error": f"parse_failed: {exc}",
        }


def verify_pack(
    out_root: Path,
    repo_root: Path,
    length_tol_frac: float,
    angle_tol_deg: float,
    symprec: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _load_manifest(out_root)
    records: list[dict[str, Any]] = []
    for row in rows:
        cif_path = _resolve_path(repo_root, row.get("solution_cif_path"))
        check = _check_cif(cif_path, length_tol_frac, angle_tol_deg, symprec) if cif_path else {
            "parseable": False,
            "cubic_compatible": False,
            "cubic_geometry_pass": False,
            "spacegroup_cubic_pass": False,
            "error": "solution_cif_path_missing",
        }
        records.append(
            {
                "case_id": row.get("case_id", ""),
                "short_name": row.get("short_name", ""),
                "target_formula": row.get("target_formula", ""),
                "chemistry_family": row.get("chemistry_family", ""),
                "status": row.get("status", ""),
                "failure_category": row.get("failure_category", ""),
                "solution_cif_path": row.get("solution_cif_path", ""),
                "solution_cif_produced": row.get("solution_cif_produced", False),
                **check,
            }
        )

    summary = {
        "out_root": str(out_root),
        "total_rows": len(records),
        "success_rows": sum(1 for r in records if r.get("status") == "success"),
        "solution_cifs": sum(1 for r in records if r.get("solution_cif_produced")),
        "parseable_cifs": sum(1 for r in records if r.get("parseable")),
        "cubic_compatible_cifs": sum(1 for r in records if r.get("cubic_compatible")),
        "cubic_geometry_pass": sum(1 for r in records if r.get("cubic_geometry_pass")),
        "spacegroup_cubic_pass": sum(1 for r in records if r.get("spacegroup_cubic_pass")),
        "length_tol_frac": length_tol_frac,
        "angle_tol_deg": angle_tol_deg,
        "symprec": symprec,
        "note": "Cubic compatibility is a lattice/symmetry screen only; it is not physical validation.",
    }
    return records, summary


def write_outputs(out_root: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    reports = out_root / "reports"
    manifests = out_root / "manifests"
    reports.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)

    (reports / "CUBIC_VERIFICATION_SUMMARY.json").write_text(
        json.dumps({"summary": summary, "rows": records}, indent=2),
        encoding="utf-8",
    )
    fieldnames = list(records[0].keys()) if records else [
        "case_id",
        "short_name",
        "target_formula",
        "cubic_compatible",
    ]
    with (manifests / "cubic_generated_cifs.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    lines = [
        "# Cubic Verification Summary",
        "",
        "This report checks generated CIF lattice/symmetry compatibility for a cubic-only showcase. It is not a physical stability or experimental validation report.",
        "",
        f"- Total rows: {summary['total_rows']}",
        f"- Successful workflow rows: {summary['success_rows']}",
        f"- Solution CIFs: {summary['solution_cifs']}",
        f"- Parseable CIFs: {summary['parseable_cifs']}",
        f"- Cubic-compatible CIFs: {summary['cubic_compatible_cifs']}",
        f"- Geometry cubic pass: {summary['cubic_geometry_pass']}",
        f"- Space-group cubic pass: {summary['spacegroup_cubic_pass']}",
        f"- Length tolerance fraction: {summary['length_tol_frac']}",
        f"- Angle tolerance degrees: {summary['angle_tol_deg']}",
        "",
        "## Non-Cubic Or Failed Rows",
        "",
    ]
    failures = [r for r in records if not r.get("cubic_compatible")]
    if not failures:
        lines.append("All parseable solution CIFs in this pack passed the cubic-compatible screen.")
    else:
        lines.append("| case_id | short_name | status | failure_category | parseable | error |")
        lines.append("|---|---|---|---|---:|---|")
        for r in failures:
            lines.append(
                f"| {r.get('case_id','')} | {r.get('short_name','')} | {r.get('status','')} | "
                f"{r.get('failure_category','')} | {r.get('parseable')} | {str(r.get('error','')).replace('|', '/')} |"
            )
    (reports / "CUBIC_VERIFICATION_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path.cwd(), type=Path)
    parser.add_argument("--length-tol-frac", default=0.02, type=float)
    parser.add_argument("--angle-tol-deg", default=2.0, type=float)
    parser.add_argument("--symprec", default=0.1, type=float)
    args = parser.parse_args()

    records, summary = verify_pack(
        out_root=args.out_root,
        repo_root=args.repo_root,
        length_tol_frac=args.length_tol_frac,
        angle_tol_deg=args.angle_tol_deg,
        symprec=args.symprec,
    )
    write_outputs(args.out_root, records, summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
