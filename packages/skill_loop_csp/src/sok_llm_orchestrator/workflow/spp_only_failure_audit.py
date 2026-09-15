"""Engineering-shakeout failure audit for the preliminary SPP-only 100."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.workflow.evidence import required_pairs_for_formula
from sok_llm_orchestrator.workflow.spp_only_benchmark import (
    normalize_pair_for_match,
    strict_spp_artifact_preflight,
)


AUDIT_COLUMNS = (
    "experiment_id", "family", "formula", "required_species", "required_pairs",
    "retrieved_cif_count", "retrieved_mp_ids", "pair_support_present", "pair_support_absent",
    "pair_structure_counts", "pair_observation_counts", "pair_distance_ranges",
    "curves_produced", "pot_files_produced", "strict_audit_result", "first_blocker",
    "diagnostic_reason",
)


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _material_ids_by_structure_id(crystal_root: Path) -> dict[str, str]:
    output: dict[str, str] = {}
    base = crystal_root / "artifacts" / "mp_oxide_families_v1"
    for dataset in ("MP_LAYERED_BATTERY_OXIDES_V1", "MP_SPINEL_OXIDES_V1"):
        payload = _read_json(base / dataset / "accepted.json", {})
        rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
        for row in rows:
            output[str(row["structure_id"])] = str(row["material_id"])
    return output


def _production_pair_diagnostics(selected: list[dict[str, Any]], formula: str, cutoff: float) -> dict[str, Any]:
    from spp_maker_qlip.required_pair_extraction import collect_required_pair_distances

    with tempfile.TemporaryDirectory(prefix="spp_only_failure_audit_") as temporary:
        corpus = Path(temporary)
        copied = 0
        for index, item in enumerate(selected):
            source = Path(str(item.get("cif_path", "")))
            if source.is_file():
                shutil.copy2(source, corpus / f"{index:04d}_{item.get('structure_id', 'unknown')}.cif")
                copied += 1
        if copied == 0:
            return {
                "required_pairs": required_pairs_for_formula(formula), "pair_stats": {},
                "missing_pairs": required_pairs_for_formula(formula), "corpus_cif_count": 0,
            }
        return collect_required_pair_distances(corpus, formula=formula, cutoff=float(cutoff))


def _request_spp_roots(run_dir: Path) -> tuple[Path | None, Path | None]:
    old = _read_json(run_dir / "spp" / "artifact_preflight.json", {})
    pot_root = old.get("pot_audit", {}).get("pot_root") if isinstance(old, dict) else None
    supported = Path(str(pot_root)) if pot_root else None
    if supported is None:
        return None, None
    return supported, supported.parent / "unscaled_spp_root"


def _recomputed_strict_audit(
    *, supported_root: Path | None, unscaled_root: Path | None, required_pairs: list[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if supported_root is None or unscaled_root is None:
        return {}, {}, {}
    manifest = _read_json(unscaled_root / "manifest.json", {})
    quality = _read_json(unscaled_root.parent / "spp_pot_quality.json", {})
    quality_by_key = {
        normalize_pair_for_match(str(row["pair"])): row for row in quality.get("pairs", [])
    }
    stats = manifest.get("pair_stats", {})
    request_rows = []
    for pair in required_pairs:
        quality_row = quality_by_key.get(normalize_pair_for_match(pair), {})
        request_rows.append({
            "species_pair": pair,
            "observations": int((stats.get(pair) or {}).get("count", 0)),
            "request_pair_status": "REQUEST_USABLE" if quality_row.get("pot_quality") == "usable" else "REQUEST_INSUFFICIENT_LOCAL_EVIDENCE",
        })
    request_spp = {"pot_root": supported_root, "quality": {"request_pair_results": request_rows}}
    strict = strict_spp_artifact_preflight(request_spp, required_pairs) if supported_root.is_dir() else {}
    return strict, manifest, quality


def audit_engineering_results(
    *, results_root: Path, crystal_root: Path, output_csv: Path, output_md: Path, cutoff: float = 11.0,
) -> list[dict[str, Any]]:
    results_root = Path(results_root)
    material_ids = _material_ids_by_structure_id(Path(crystal_root))
    rows: list[dict[str, Any]] = []
    for summary_path in sorted(results_root.glob("runs/*/*/run_summary.json")):
        run_dir = summary_path.parent
        summary = _read_json(summary_path, {})
        evidence = _read_json(run_dir / "spp" / "evidence_bundle.json", {})
        selected = list(evidence.get("selected", []))
        formula = str(summary["formula"])
        required = required_pairs_for_formula(formula)
        diagnostics = _production_pair_diagnostics(selected, formula, cutoff)
        stats = {str(pair): dict(value) for pair, value in diagnostics.get("pair_stats", {}).items()}
        present = [pair for pair in required if int((stats.get(pair) or {}).get("count", 0)) > 0]
        absent = [pair for pair in required if pair not in present]
        supported_root, unscaled_root = _request_spp_roots(run_dir)
        strict, manifest, quality = _recomputed_strict_audit(
            supported_root=supported_root, unscaled_root=unscaled_root, required_pairs=required,
        )
        unscaled_pots = sorted(unscaled_root.rglob("*.POT")) if unscaled_root and unscaled_root.is_dir() else []
        produced = [str(row.get("pair")) for row in manifest.get("pair_export_diagnostics", []) if row.get("pot_export_status") == "exported"]
        old_artifact_valid = bool(summary.get("SPP_ARTIFACT_VALID"))
        corrected_valid = bool(strict.get("SPP_ARTIFACT_VALID"))
        if not selected:
            blocker = "EMPTY_RETRIEVAL_CORPUS"
            reason = "No leakage-safe exportable CIFs entered the SPP corpus."
        elif absent:
            blocker = "NO_REQUIRED_PAIR_COVERAGE" if not present else "PARTIAL_REQUIRED_PAIR_COVERAGE"
            reason = "No real periodic observations for: " + ", ".join(absent)
        elif not manifest:
            blocker = "SPP_FITTER_FAILURE"
            reason = "Pair coverage was complete but no SPP build manifest exists."
        elif not unscaled_pots:
            blocker = "NO_REQUEST_CURVES"
            reason = "Pair coverage was complete but the fitter produced no POT files."
        elif corrected_valid and not old_artifact_valid:
            blocker = "CASE_NORMALIZATION_FALSE_FAILURE"
            reason = "All real request POTs are usable; the preliminary mixed-case inventory comparison rejected uppercase artifact names."
        elif not corrected_valid:
            blocker = "SPP_ARTIFACT_INVALID"
            unusable = [str(item["pair"]) for item in quality.get("pairs", []) if item.get("pot_quality") != "usable"]
            reason = "Generated request curves failed the frozen quality gate: " + ", ".join(unusable)
        else:
            blocker = "OTHER"
            reason = "No pre-solve blocker was identified by the engineering audit."
        retrieved_ids = [str(item.get("structure_id", "")) for item in selected]
        row = {
            "experiment_id": summary["experiment_id"], "family": summary["family"], "formula": formula,
            "required_species": json.dumps(sorted({token for pair in required for token in pair.split("-")}, key=str.lower)),
            "required_pairs": json.dumps(required), "retrieved_cif_count": len(selected),
            "retrieved_mp_ids": json.dumps([material_ids.get(value, value) for value in retrieved_ids]),
            "pair_support_present": json.dumps(present), "pair_support_absent": json.dumps(absent),
            "pair_structure_counts": json.dumps(evidence.get("pair_structure_counts", {}), sort_keys=True),
            "pair_observation_counts": json.dumps({pair: int((stats.get(pair) or {}).get("count", 0)) for pair in required}, sort_keys=True),
            "pair_distance_ranges": json.dumps({pair: {"minimum_A": (stats.get(pair) or {}).get("min_distance"), "maximum_A": (stats.get(pair) or {}).get("max_distance")} for pair in required}, sort_keys=True),
            "curves_produced": json.dumps(produced), "pot_files_produced": json.dumps([str(path) for path in unscaled_pots]),
            "strict_audit_result": json.dumps(strict, sort_keys=True, default=str), "first_blocker": blocker,
            "diagnostic_reason": reason,
        }
        rows.append(row)
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output_csv, rows)
    counts = Counter(str(row["first_blocker"]) for row in rows)
    lines = [
        "# SPP-Only 100 Engineering Failure Audit", "",
        "This is a development/shakeout audit, not a final benchmark result.", "",
        f"- Rows audited: {len(rows)}", "", "## First blocking stage", "",
    ] + [f"- {key}: {value}" for key, value in sorted(counts.items())]
    Path(output_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


__all__ = ["AUDIT_COLUMNS", "audit_engineering_results"]
