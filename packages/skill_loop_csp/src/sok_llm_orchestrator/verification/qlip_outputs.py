from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _objective_metadata(nested: dict[str, Any]) -> dict[str, Any]:
    outputs = nested.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}
    certificates = nested.get("certificates")
    if not isinstance(certificates, dict):
        certificates = {}
    diagnostics = certificates.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    spp_guidance = diagnostics.get("spp_guidance")
    if not isinstance(spp_guidance, dict):
        spp_guidance = {}
    return {
        "objective_terms": outputs.get("objective_terms"),
        "objective_value": outputs.get("objective_value"),
        "spp_score": outputs.get("spp_score"),
        "weighted_score": outputs.get("weighted_score"),
        "spp_guidance": spp_guidance,
    }


def validate_qlip_outputs(payload: dict[str, Any], guidance_expected: bool) -> dict[str, Any]:
    result = payload.get("result", payload)
    warnings: list[str] = []
    errors: list[str] = []
    if not isinstance(result, dict):
        primary_error = payload.get("primary_error") if isinstance(payload, dict) else None
        if isinstance(primary_error, dict):
            errors.append(str(primary_error.get("code") or "non_solution_result"))
        else:
            errors.append("non_solution_result")
        return {
            "schema_version": "verification.qlip_outputs.v1",
            "ok": False,
            "warnings": warnings,
            "errors": errors,
        }
    nested = result.get("result", result)
    if not isinstance(nested, dict):
        errors.append("non_solution_result")
        return {
            "schema_version": "verification.qlip_outputs.v1",
            "ok": False,
            "warnings": warnings,
            "errors": errors,
        }
    solver_status = nested.get("status")
    metadata = _objective_metadata(nested)
    if isinstance(solver_status, str) and solver_status.upper() not in {
        "SUCCESS",
        "SUCCEEDED",
        "SOLVED",
        "OPTIMAL",
        "FEASIBLE",
    }:
        errors.append(f"qlip_solver_status:{solver_status}")
        error_message = nested.get("error") or nested.get("message")
        if isinstance(error_message, str) and error_message:
            errors.append(f"qlip_solver_error:{error_message}")
        return {
            "schema_version": "verification.qlip_outputs.v1",
            "ok": False,
            "warnings": warnings,
            "errors": errors,
            "objective_metadata": metadata,
        }
    outputs = nested.get("outputs", {})
    if not isinstance(outputs, dict):
        outputs = {}
    terms = outputs.get("objective_terms")
    if not isinstance(terms, list):
        errors.append("objective_metadata_missing")
    else:
        if guidance_expected:
            has_spp = any(str(term.get("term", "")).lower() == "spp" for term in terms if isinstance(term, dict))
            if not has_spp:
                warnings.append("spp_term_missing")
    return {
        "schema_version": "verification.qlip_outputs.v1",
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
        "objective_metadata": metadata,
    }


def structure_signature_from_cif_path(cif_path: str | None) -> dict[str, Any]:
    """
    Build a stable structure identity proxy from CIF content when available.

    This keeps the implementation intentionally lightweight: content hash over
    normalized text plus optional formula/cell field snippets.
    """

    result: dict[str, Any] = {
        "structure_artifact_path": cif_path,
        "structure_signature": None,
        "structure_source": None,
        "structure_content_hash": None,
        "formula_signature": None,
        "lattice_signature": None,
        "path_exists": False,
    }
    if not isinstance(cif_path, str) or not cif_path.strip():
        return result
    path = Path(cif_path)
    result["path_exists"] = path.exists()
    if not path.exists():
        # Fallback to path-based signature to keep traceability explicit.
        path_sig = hashlib.sha256(path.as_posix().encode("utf-8")).hexdigest()
        result["structure_signature"] = f"path:{path_sig}"
        result["structure_source"] = "path"
        return result

    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        path_sig = hashlib.sha256(path.as_posix().encode("utf-8")).hexdigest()
        result["structure_signature"] = f"path:{path_sig}"
        result["structure_source"] = "path"
        return result

    # Normalize line whitespace while keeping order.
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    normalized = "\n".join(lines)
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    result["structure_content_hash"] = content_hash
    result["structure_signature"] = f"cif:{content_hash}"
    result["structure_source"] = "content"

    formula_line = next(
        (
            line
            for line in lines
            if line.lower().startswith("_chemical_formula_sum")
            or line.lower().startswith("_chemical_formula_structural")
        ),
        None,
    )
    if isinstance(formula_line, str):
        result["formula_signature"] = formula_line

    lattice_keys = (
        "_cell_length_a",
        "_cell_length_b",
        "_cell_length_c",
        "_cell_angle_alpha",
        "_cell_angle_beta",
        "_cell_angle_gamma",
    )
    lattice_lines = [line for line in lines if any(line.lower().startswith(key) for key in lattice_keys)]
    if lattice_lines:
        lattice_norm = "|".join(lattice_lines)
        result["lattice_signature"] = hashlib.sha256(lattice_norm.encode("utf-8")).hexdigest()

    return result
