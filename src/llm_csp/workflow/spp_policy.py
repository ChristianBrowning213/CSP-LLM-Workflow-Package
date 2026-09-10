"""Request-SPP and complete-regulator policy for the deterministic workflow."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from llm_csp.retrieval import EvidenceRecord
from llm_csp.schemas.workflow import SPPConfig
from llm_csp.spp import export_required_pair_spp_root, export_required_pot_subset
from llm_csp.spp.quality import audit_pot_root
from llm_csp.spp.required_pairs import derive_required_pairs, parse_formula_elements


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "evidence"


def prepare_spp_guidance(
    *,
    formula: str,
    evidence: tuple[EvidenceRecord, ...],
    config: SPPConfig,
    output_root: Path,
) -> dict[str, Any]:
    """Prepare request POTs and enforce complete external regulator coverage."""

    output_root.mkdir(parents=True, exist_ok=False)
    required_pairs = derive_required_pairs(parse_formula_elements(formula))
    regulator_root = output_root / "regulator"
    regulator = export_required_pot_subset(
        formula=formula,
        source_pot_root=config.regulator_root,
        output_root=regulator_root,
    )
    if not regulator["complete"]:
        return {
            "status": "spp_incomplete",
            "ready": False,
            "required_pairs": required_pairs,
            "missing_pairs": regulator["missing_pairs"],
            "reason": "regulator_pair_coverage_incomplete",
            "regulator": regulator,
            "request": None,
            "pair_decisions": [],
        }
    regulator_quality = audit_pot_root(regulator_root, required_pairs=required_pairs)
    if regulator_quality["spp_pot_quality_status"] != "usable":
        return {
            "status": "spp_incomplete",
            "ready": False,
            "required_pairs": required_pairs,
            "missing_pairs": regulator_quality["missing_pairs"],
            "unusable_pairs": regulator_quality["unusable_pairs"],
            "reason": "regulator_pair_quality_failed",
            "regulator": regulator,
            "regulator_quality": regulator_quality,
            "request": None,
            "pair_decisions": [],
        }

    request_root = output_root / "request"
    request_manifest: dict[str, Any]
    usable_request_pairs: set[str]
    if config.request_mode == "disabled":
        request_root.mkdir()
        request_manifest = {
            "status": "disabled",
            "required_pairs": required_pairs,
            "fitted_pairs": [],
            "missing_pairs": required_pairs,
            "spp_root": str(request_root),
        }
        usable_request_pairs = set()
    else:
        cif_dir = output_root / "evidence_cifs"
        cif_dir.mkdir()
        inputs: list[dict[str, Any]] = []
        for index, item in enumerate(evidence, start=1):
            source = Path(str(item.cif_path)).resolve()
            destination = cif_dir / f"{index:03d}_{_safe_id(item.structure_id)}.cif"
            shutil.copyfile(source, destination)
            inputs.append(
                {
                    "structure_id": item.structure_id,
                    "source_path": str(source),
                    "copied_path": str(destination),
                    "sha256": _sha256(destination),
                }
            )
        request_manifest = export_required_pair_spp_root(
            cif_dir=cif_dir,
            formula=formula,
            out_root=request_root,
            name="retrieval_request_spp",
            cutoff=config.cutoff,
        )
        request_manifest["evidence_inputs"] = inputs
        quality_rows = {
            str(row["pair"]): row
            for row in request_manifest.get("spp_pot_quality", {}).get("pairs", [])
        }
        usable_request_pairs = {
            pair
            for pair in request_manifest.get("fitted_pairs", [])
            if quality_rows.get(pair, {}).get("pot_quality") == "usable"
        }

    decisions: list[dict[str, Any]] = []
    for pair in required_pairs:
        local = pair in usable_request_pairs
        request_path = request_root / pair / f"{pair}.POT"
        regulator_path = regulator_root / pair / f"{pair}.POT"
        decisions.append(
            {
                "pair": pair,
                "request_status": "REQUEST_USABLE" if local else (
                    "REQUEST_DISABLED" if config.request_mode == "disabled" else "REQUEST_MISSING_OR_UNUSABLE"
                ),
                "guidance_mode": "REQUEST_PLUS_REGULATOR" if local else (
                    "REGULATOR_ONLY_REQUEST_DISABLED"
                    if config.request_mode == "disabled"
                    else "REGULATOR_ONLY_LOCAL_MISSING_OR_INSUFFICIENT"
                ),
                "request_pot": str(request_path) if local else None,
                "request_sha256": _sha256(request_path) if local else None,
                "regulator_pot": str(regulator_path),
                "regulator_sha256": _sha256(regulator_path),
            }
        )
    fallback = [row["pair"] for row in decisions if row["guidance_mode"].startswith("REGULATOR_ONLY")]
    return {
        "status": "complete" if not fallback else "complete_with_regulator_fallback",
        "ready": True,
        "required_pairs": required_pairs,
        "missing_pairs": [],
        "request_supported_pairs": sorted(usable_request_pairs, key=str.lower),
        "regulator_fallback_pairs": fallback,
        "request_root": str(request_root),
        "regulator_root": str(regulator_root),
        "request": request_manifest,
        "regulator": regulator,
        "regulator_quality": regulator_quality,
        "pair_decisions": decisions,
        "weights": {
            "request_coefficient": config.request_coefficient,
            "regulator_coefficient": config.regulator_coefficient,
            "outer_objective_scale": config.outer_objective_scale,
        },
    }
