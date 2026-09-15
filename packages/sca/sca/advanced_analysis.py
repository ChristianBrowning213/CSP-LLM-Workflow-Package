"""Unified advanced crystal analysis with explicit independent evidence dimensions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sca.benchmark import benchmark_one


class AdvancedAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "sca.advanced_analysis.v1"
    input_provenance: dict[str, Any]
    crystallographic_validity: dict[str, Any]
    intent_satisfaction: dict[str, Any]
    pair_geometry: dict[str, Any]
    topology: dict[str, Any]
    spp_plausibility: dict[str, Any]
    mlip_static_analysis: dict[str, Any]
    mlip_agreement: dict[str, Any]
    mlip_relaxation: dict[str, Any]
    post_mlip_validation: dict[str, Any]
    dft_status: dict[str, Any]
    dft_relaxation: dict[str, Any]
    formation_energy: dict[str, Any]
    energy_above_hull: dict[str, Any]
    decomposition: dict[str, Any]
    scientific_quality_dimensions: dict[str, Any]
    limitations: list[str] = Field(default_factory=list)


def analyse_crystal_advanced(
    cif_path: str | Path,
    *,
    intent: dict[str, Any] | None = None,
    layers: dict[str, Any] | None = None,
) -> AdvancedAnalysisResult:
    path = Path(cif_path)
    intent = intent or {}
    layers = layers or {}
    record = benchmark_one(
        path,
        evaluator_names=["pre_dft_validity"],
        target_formula=intent.get("target_formula") or intent.get("formula"),
        target_space_group=intent.get("target_space_group") or intent.get("space_group"),
        require_spacegroup=bool(intent.get("require_space_group", False)),
    )
    raw = record.flattened
    missing = []

    def layer(name: str, unavailable: str = "NOT_RUN") -> dict[str, Any]:
        value = layers.get(name)
        if value is None:
            missing.append(f"{name}: {unavailable}")
            return {"status": unavailable}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return dict(value)

    crystallographic_valid = bool(raw.get("pre_dft_valid"))
    intent_compliant = _intent_compliant(raw, intent)
    mlip_retention = layer("post_mlip_validation")
    mlip_agreement = layer("mlip_agreement", "NOT_AVAILABLE")
    dft_relaxation = layer("dft_relaxation")
    formation = layer("formation_energy", "NOT_COMPUTABLE")
    hull = layer("energy_above_hull", "NOT_COMPUTABLE")
    return AdvancedAnalysisResult(
        input_provenance={"cif_path": str(path), "cif_sha256": _sha256(path)},
        crystallographic_validity={"status": "VALID" if crystallographic_valid else "INVALID", "pre_dft_valid": crystallographic_valid, "parse_ok": raw.get("parse_ok")},
        intent_satisfaction={"status": "COMPLIANT" if intent_compliant else "NOT_COMPLIANT" if intent else "NOT_AVAILABLE", "target_formula_match": raw.get("target_formula_match"), "space_group_consistent": raw.get("space_group_consistent")},
        pair_geometry={"status": "AVAILABLE", "minimum_distance": raw.get("min_distance"), "bad_contacts": raw.get("num_bad_contacts"), "geometry_ok": raw.get("geometry_ok")},
        topology=layer("topology", "NOT_AVAILABLE"),
        spp_plausibility=layer("spp_plausibility", "NOT_AVAILABLE"),
        mlip_static_analysis=layer("mlip_static_analysis"),
        mlip_agreement=mlip_agreement,
        mlip_relaxation=layer("mlip_relaxation"),
        post_mlip_validation=mlip_retention,
        dft_status=layer("dft_status"),
        dft_relaxation=dft_relaxation,
        formation_energy=formation,
        energy_above_hull=hull,
        decomposition=layer("decomposition", "NOT_COMPUTABLE"),
        scientific_quality_dimensions={
            "crystallographically_valid": crystallographic_valid,
            "intent_compliant": intent_compliant if intent else None,
            "mlip_relaxation_robust": _status_is(mlip_retention, {"ROBUST"}),
            "mlip_model_agreement": mlip_agreement.get("consensus_label"),
            "dft_relaxation_robust": _status_is(dft_relaxation, {"DFT_ROBUST", "DFT_VALID_SYMMETRY_LOWERED"}),
            "formation_energy_available": formation.get("formation_energy_eV_atom") is not None,
            "energy_above_hull": hull.get("energy_above_hull_eV_atom"),
            "thermodynamic_context_available": hull.get("energy_above_hull_eV_atom") is not None,
        },
        limitations=missing,
    )


def write_advanced_report(result: AdvancedAnalysisResult, out_dir: str | Path) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    row = result.model_dump(mode="json")
    json_path = out / "advanced_analysis.jsonl"
    json_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "advanced_analysis_summary.json").write_text(json.dumps(row["scientific_quality_dimensions"], indent=2) + "\n", encoding="utf-8")
    import pandas as pd

    pd.json_normalize(row, sep=".").to_csv(out / "advanced_analysis.csv", index=False)
    sections = (
        ("Input / provenance", "input_provenance"),
        ("Crystallographic validity", "crystallographic_validity"),
        ("Intent satisfaction", "intent_satisfaction"),
        ("Topology", "topology"),
        ("SPP plausibility", "spp_plausibility"),
        ("MLIP static analysis", "mlip_static_analysis"),
        ("MLIP agreement", "mlip_agreement"),
        ("MLIP relaxation", "mlip_relaxation"),
        ("Post-MLIP validation", "post_mlip_validation"),
        ("DFT status", "dft_status"),
        ("DFT relaxation", "dft_relaxation"),
        ("Formation energy", "formation_energy"),
        ("Energy above hull", "energy_above_hull"),
        ("Decomposition", "decomposition"),
    )
    lines = ["# Advanced Crystal Analysis", ""]
    for title, key in sections:
        lines.extend([f"## {title}", "", "```json", json.dumps(row[key], indent=2), "```", ""])
    lines.extend(["## Limitations / unavailable analyses", ""] + [f"- {item}" for item in result.limitations])
    report = out / "advanced_analysis_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv": str(out / "advanced_analysis.csv"), "jsonl": str(json_path), "summary": str(out / "advanced_analysis_summary.json"), "markdown": str(report)}


def _intent_compliant(row: dict[str, Any], intent: dict[str, Any]) -> bool:
    if not intent:
        return False
    checks = []
    if intent.get("target_formula") or intent.get("formula"):
        checks.append(row.get("target_formula_match") is True)
    if (intent.get("target_space_group") or intent.get("space_group")) and intent.get("require_space_group", False):
        checks.append(row.get("space_group_consistent") is True)
    return bool(checks) and all(checks)


def _status_is(value: dict[str, Any], statuses: set[str]) -> bool | None:
    status = value.get("overall_relaxation_status") or value.get("dft_relaxation_status") or value.get("status")
    return status in statuses if status not in {None, "NOT_RUN", "NOT_AVAILABLE"} else None


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
