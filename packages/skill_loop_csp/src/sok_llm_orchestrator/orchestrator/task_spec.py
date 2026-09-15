from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from sok_llm_orchestrator.contracts.phase1_properties import (
    Phase1PropertyResolutionError,
    list_phase1_property_entries,
    qlip_objective_for_phase1_entry,
    qlip_objective_for_phase1_request,
    resolve_phase1_property_request,
    resolve_property_bias_key,
)
from sok_llm_orchestrator.contracts.phase2_external_predictors import (
    Phase2ExternalPredictorResolutionError,
    normalize_phase2_external_predictor_request,
)
from sok_llm_orchestrator.contracts.phase3_external_predictors import (
    Phase3ExternalPredictorResolutionError,
    normalize_phase3_external_predictor_request,
)
from sok_llm_orchestrator.contracts.qlip_schema import QLIP_OBJECTIVE_SCHEMA

TASK_SPEC_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "query_text",
        "composition_target",
        "composition_strictness",
        "symmetry_request",
        "motif_prior",
        "property_bias",
        "qlip_objective",
        "target_space_group",
        "target_space_group_number",
        "target_crystal_system",
        "target_structure_family",
        "prototype",
        "external_predictor_targets",
        "solve_mode",
        "retrieval_strictness",
        "iteration_budget",
        "defaults_used",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "task_spec.v1"},
        "query_text": {"type": "string", "minLength": 1},
        "composition_target": {"type": ["string", "null"]},
        "composition_strictness": {"type": "string", "enum": ["fixed", "approximate"]},
        "symmetry_request": {
            "type": "object",
            "additionalProperties": False,
            "required": ["space_group", "hardness"],
            "properties": {
                "space_group": {"type": ["string", "null"]},
                "hardness": {"type": "string", "enum": ["hard", "soft", "none"]},
            },
        },
        "motif_prior": {"type": ["string", "null"]},
        "property_bias": {"type": ["string", "null"]},
        "qlip_objective": {"anyOf": [QLIP_OBJECTIVE_SCHEMA, {"type": "null"}]},
        "target_space_group": {"type": ["string", "null"]},
        "target_space_group_number": {"type": ["string", "integer", "null"]},
        "target_crystal_system": {"type": ["string", "null"]},
        "target_structure_family": {"type": ["string", "null"]},
        "prototype": {"type": ["string", "null"]},
        "external_predictor_targets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "predictor_id", "target", "use", "value_state"],
                "properties": {
                    "schema_version": {
                        "type": "string",
                        "enum": [
                            "phase2.external_predictor_request.v1",
                            "phase3.external_predictor_request.v1",
                        ],
                    },
                    "predictor_id": {"type": "string", "minLength": 1},
                    "target": {"type": "string", "minLength": 1},
                    "use": {"type": "string", "enum": ["reporting", "selection_metric", "ranking"]},
                    "value_state": {"type": "string", "enum": ["raw", "raw_log10"]},
                },
            },
        },
        "solve_mode": {"type": "string", "enum": ["feasibility", "optimize", "rediscovery"]},
        "retrieval_strictness": {"type": "string", "enum": ["composition_tight", "prototype_tight", "broad"]},
        "iteration_budget": {"type": "integer", "minimum": 0, "maximum": 5},
        "defaults_used": {"type": "array", "items": {"type": "string"}},
    },
}

_FORMULA_RE = re.compile(r"\b([A-Z][a-z]?\d*)+\b")
_SG_RE = re.compile(r"\bP\d[\w/]*\b", flags=re.IGNORECASE)
_PROPERTY_TOKEN_RE = re.compile(r"\b(?:property|high)\s+([A-Za-z][A-Za-z0-9_\- ]{0,40})", flags=re.IGNORECASE)
_OBJECTIVE_ASSIGNMENT_RE = re.compile(
    r"\b(?:primary\s+objective|objective)\s*[:=]\s*([A-Za-z0-9_.-]+)",
    flags=re.IGNORECASE,
)
_EXPLICIT_FEASIBILITY_RE = re.compile(r"\bfeasib(?:le|ility)\b", flags=re.IGNORECASE)


@dataclass(slots=True)
class SymmetryRequest:
    space_group: str | None
    hardness: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {"space_group": self.space_group, "hardness": self.hardness}


@dataclass(slots=True)
class TaskSpec:
    query_text: str
    composition_target: str | None = None
    composition_strictness: str = "fixed"
    symmetry_request: SymmetryRequest = field(default_factory=lambda: SymmetryRequest(space_group=None))
    motif_prior: str | None = None
    property_bias: str | None = None
    qlip_objective: dict[str, Any] | None = None
    target_space_group: str | None = None
    target_space_group_number: str | None = None
    target_crystal_system: str | None = None
    target_structure_family: str | None = None
    prototype: str | None = None
    external_predictor_targets: list[dict[str, Any]] = field(default_factory=list)
    solve_mode: str = "feasibility"
    retrieval_strictness: str = "composition_tight"
    iteration_budget: int = 1
    defaults_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "task_spec.v1",
            "query_text": self.query_text,
            "composition_target": self.composition_target,
            "composition_strictness": self.composition_strictness,
            "symmetry_request": self.symmetry_request.to_dict(),
            "motif_prior": self.motif_prior,
            "property_bias": self.property_bias,
            "qlip_objective": self.qlip_objective,
            "target_space_group": self.target_space_group,
            "target_space_group_number": self.target_space_group_number,
            "target_crystal_system": self.target_crystal_system,
            "target_structure_family": self.target_structure_family,
            "prototype": self.prototype,
            "external_predictor_targets": list(self.external_predictor_targets),
            "solve_mode": self.solve_mode,
            "retrieval_strictness": self.retrieval_strictness,
            "iteration_budget": self.iteration_budget,
            "defaults_used": list(self.defaults_used),
        }


def validate_task_spec(spec: dict[str, Any]) -> None:
    validator = Draft202012Validator(TASK_SPEC_SCHEMA)
    errors = sorted(validator.iter_errors(spec), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{pointer}: {err.message}")


def _norm_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _text_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is not None and not isinstance(value, str):
        text = str(value).strip()
        if text:
            return text
    return None


def _phase1_objective_from_text(text: str, *, formula: str | None) -> dict[str, Any] | None:
    for match in _OBJECTIVE_ASSIGNMENT_RE.finditer(text):
        requested = match.group(1).strip().rstrip(".,;:")
        if not requested:
            continue
        try:
            entry = resolve_phase1_property_request(requested, allow_small_wiring=False)
        except Phase1PropertyResolutionError:
            continue
        objective = qlip_objective_for_phase1_entry(entry, formula=formula)
        if objective is not None:
            return objective

    norm_text = f"_{_norm_token(text)}_"
    for entry in list_phase1_property_entries(include_small_wiring=False):
        if not isinstance(entry.qlip_objective_family, str) or not entry.qlip_objective_family.strip():
            continue
        aliases = [entry.id, *(entry.request_aliases or [])]
        for alias in aliases:
            key = _norm_token(alias)
            if key and f"_{key}_" in norm_text:
                return qlip_objective_for_phase1_entry(entry, formula=formula)
    return None


def _canonical_phase1_objective_ids_in_text(text: str) -> list[str]:
    norm_text = f"_{_norm_token(text)}_"
    matches: list[str] = []
    for entry in list_phase1_property_entries(include_small_wiring=False):
        if not isinstance(entry.qlip_objective_family, str) or not entry.qlip_objective_family.strip():
            continue
        key = _norm_token(entry.id)
        if key and f"_{key}_" in norm_text and entry.id not in matches:
            matches.append(entry.id)
    return matches


def _normalize_external_predictor_request_from_text(payload: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, str):
        predictor_id: Any = payload
    elif isinstance(payload, dict):
        predictor_id = payload.get("predictor_id")
    else:
        predictor_id = None
    if isinstance(predictor_id, str) and predictor_id.startswith("phase3."):
        return normalize_phase3_external_predictor_request(payload)
    if isinstance(predictor_id, str) and predictor_id.startswith("phase2."):
        return normalize_phase2_external_predictor_request(payload)
    try:
        return normalize_phase2_external_predictor_request(payload)
    except Phase2ExternalPredictorResolutionError:
        return normalize_phase3_external_predictor_request(payload)


def _normalize_external_predictor_requests_from_text(
    requests: list[dict[str, Any] | str],
) -> list[dict[str, Any]]:
    return [_normalize_external_predictor_request_from_text(item) for item in requests]


def _external_predictors_from_text(
    text: str,
    *,
    strict_phase1_benchmark_mode: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    defaults_used: list[str] = []
    matches = re.findall(r"phase[23]\.external\.[A-Za-z0-9_\-.]+", text)
    requests: list[dict[str, Any] | str] = []
    seen: set[str] = set()
    for match in matches:
        token = match.strip().rstrip(".,;:")
        if token and token not in seen:
            seen.add(token)
            requests.append(token)
    lowered = text.lower()
    if not requests and "external predictor" in lowered:
        for alias in ("mean atomic number", "mean_atomic_number", "pymatgen composition descriptor"):
            if alias in lowered:
                requests.append(
                    {
                        "predictor_id": "phase2.external.pymatgen_composition_descriptor",
                        "target": "mean_atomic_number" if "number" in alias else "mean_atomic_number",
                        "use": "reporting",
                    }
                )
                break
        if not requests:
            phase3_aliases = (
                ("band gap", "phase3.external.megnet_band_gap"),
                ("band_gap", "phase3.external.megnet_band_gap"),
                ("bulk modulus", "phase3.external.megnet_bulk_modulus"),
                ("bulk_modulus", "phase3.external.megnet_bulk_modulus"),
                ("shear modulus", "phase3.external.megnet_shear_modulus"),
                ("shear_modulus", "phase3.external.megnet_shear_modulus"),
                ("formation energy", "phase3.external.megnet_formation_energy"),
                ("formation_energy", "phase3.external.megnet_formation_energy"),
            )
            for alias, predictor_id in phase3_aliases:
                if alias in lowered:
                    requests.append({"predictor_id": predictor_id, "use": "reporting"})
                    break
    try:
        return _normalize_external_predictor_requests_from_text(requests), defaults_used
    except (Phase2ExternalPredictorResolutionError, Phase3ExternalPredictorResolutionError) as exc:
        if strict_phase1_benchmark_mode:
            phase = "PHASE3" if str(exc.code).startswith("PHASE3") else "PHASE2"
            raise ValueError(f"{phase}_BENCHMARK_MODE_REJECTED:{exc.code}:{exc.detail}") from exc
        defaults_used.append(f"external_predictor_unresolved:{exc.code}")
        return [], defaults_used


def task_spec_from_query(query: str, *, strict_phase1_benchmark_mode: bool = False) -> TaskSpec:
    text = query.strip()
    defaults_used: list[str] = []
    mentioned_canonical_objective_ids = _canonical_phase1_objective_ids_in_text(text)

    formula_match = _FORMULA_RE.search(text)
    composition = formula_match.group(0) if formula_match else None
    if composition is None:
        defaults_used.append("composition_target:none")

    symmetry_match = _SG_RE.search(text)
    space_group = symmetry_match.group(0) if symmetry_match else None
    hardness = "soft" if space_group else "none"
    if space_group is None:
        defaults_used.append("symmetry_request:none")

    solve_mode = "rediscovery" if "rediscover" in text.lower() else "feasibility"
    if "optimiz" in text.lower():
        solve_mode = "optimize"

    property_bias: str | None = None
    qlip_objective: dict[str, Any] | None = None
    external_predictor_targets, external_defaults = _external_predictors_from_text(
        text,
        strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
    )
    defaults_used.extend(external_defaults)
    lowered = text.lower()
    if "property x" in lowered:
        property_bias = "property_x"
    else:
        qlip_objective = _phase1_objective_from_text(text, formula=composition)
        if qlip_objective is None:
            match = _PROPERTY_TOKEN_RE.search(text)
            if match:
                raw_prop = match.group(1).strip().lower()
                raw_prop = raw_prop.split(" and ")[0].split(",")[0].strip()
                property_bias = re.sub(r"[^a-z0-9]+", "_", raw_prop).strip("_")
                if property_bias in {"x", "property"}:
                    property_bias = "property_x"
    if property_bias and solve_mode == "feasibility":
        solve_mode = "optimize"
    if property_bias is not None:
        try:
            resolved = resolve_phase1_property_request(property_bias, allow_small_wiring=False)
            if isinstance(resolved.property_key, str) and resolved.property_key.strip():
                property_bias = resolve_property_bias_key(property_bias, allow_small_wiring=False)
            else:
                qlip_objective = qlip_objective_for_phase1_entry(resolved, formula=composition)
                property_bias = None
        except Phase1PropertyResolutionError as exc:
            if strict_phase1_benchmark_mode:
                raise ValueError(f"PHASE1_BENCHMARK_MODE_REJECTED:{exc.code}:{exc.detail}") from exc
            defaults_used.append(f"property_bias_unresolved:{exc.code}")
    if mentioned_canonical_objective_ids and qlip_objective is None:
        detail = ",".join(mentioned_canonical_objective_ids)
        if strict_phase1_benchmark_mode:
            raise ValueError(f"PHASE1_CANONICAL_OBJECTIVE_UNBOUND:{detail}")
        defaults_used.append(f"qlip_objective_unbound:{mentioned_canonical_objective_ids[0]}")
    if qlip_objective is not None and solve_mode == "feasibility" and not _EXPLICIT_FEASIBILITY_RE.search(text):
        solve_mode = "optimize"

    strictness = "broad" if "broad" in text.lower() else "composition_tight"
    if "prototype" in text.lower():
        strictness = "prototype_tight"

    spec = TaskSpec(
        query_text=text,
        composition_target=composition,
        symmetry_request=SymmetryRequest(space_group=space_group, hardness=hardness),
        target_space_group=space_group,
        property_bias=property_bias,
        qlip_objective=qlip_objective,
        external_predictor_targets=external_predictor_targets,
        solve_mode=solve_mode,
        retrieval_strictness=strictness,
        defaults_used=defaults_used,
    )
    validate_task_spec(spec.to_dict())
    return spec


def _normalize_structured_qlip_objective(
    value: Any,
    *,
    formula: str | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return json.loads(json.dumps(value))
    if isinstance(value, str) and value.strip():
        requested = value.strip()
        try:
            objective = qlip_objective_for_phase1_request(
                requested,
                formula=formula,
                allow_small_wiring=False,
            )
        except Phase1PropertyResolutionError as exc:
            raise ValueError(f"Structured qlip_objective '{requested}' is invalid: {exc.detail}") from exc
        if objective is None:
            raise ValueError(
                f"Structured qlip_objective '{requested}' did not resolve to a QLIP objective payload."
            )
        return objective
    raise ValueError("Structured qlip_objective must be null, a mapping, or a canonical Phase 1 objective id.")


def task_spec_from_payload(
    payload: dict[str, Any],
    *,
    strict_phase1_benchmark_mode: bool = False,
) -> TaskSpec:
    if not isinstance(payload, dict):
        raise ValueError("Structured task spec payload must be an object.")
    schema_version = payload.get("schema_version")
    if schema_version not in {None, "task_spec.v1"}:
        raise ValueError(f"Unsupported task spec schema_version: {schema_version}")

    defaults_used = [
        str(item).strip()
        for item in payload.get("defaults_used", [])
        if isinstance(item, str) and str(item).strip()
    ]
    composition = payload.get("composition_target")
    if composition is not None and not isinstance(composition, str):
        raise ValueError("composition_target must be a string or null.")
    composition_text = composition.strip() if isinstance(composition, str) and composition.strip() else None

    query_text = payload.get("query_text")
    if isinstance(query_text, str) and query_text.strip():
        normalized_query_text = query_text.strip()
    elif composition_text:
        normalized_query_text = composition_text
        defaults_used.append("query_text:derived_from_task_spec")
    else:
        raise ValueError("Structured task spec requires query_text or composition_target.")

    target_space_group = _text_or_none(payload.get("target_space_group") or payload.get("space_group"))
    target_space_group_number = _text_or_none(
        payload.get("target_space_group_number") or payload.get("space_group_number")
    )
    target_crystal_system = _text_or_none(payload.get("target_crystal_system") or payload.get("crystal_system"))
    target_structure_family = _text_or_none(
        payload.get("target_structure_family") or payload.get("structure_family") or payload.get("family")
    )
    prototype = _text_or_none(payload.get("prototype") or payload.get("prototype_family") or target_structure_family)

    symmetry_raw = payload.get("symmetry_request")
    if symmetry_raw is None:
        symmetry_request = SymmetryRequest(
            space_group=target_space_group,
            hardness="hard" if target_space_group else "none",
        )
    elif isinstance(symmetry_raw, dict):
        space_group = symmetry_raw.get("space_group") or target_space_group
        if space_group is not None and not isinstance(space_group, str):
            raise ValueError("symmetry_request.space_group must be a string or null.")
        hardness = str(symmetry_raw.get("hardness", "none")).strip().lower() or "none"
        if hardness == "none" and space_group:
            hardness = "hard"
        if hardness not in {"hard", "soft", "none"}:
            raise ValueError("symmetry_request.hardness must be one of hard, soft, none.")
        symmetry_request = SymmetryRequest(
            space_group=space_group.strip() if isinstance(space_group, str) and space_group.strip() else None,
            hardness=hardness,
        )
    else:
        raise ValueError("symmetry_request must be an object or null.")

    qlip_objective = _normalize_structured_qlip_objective(
        payload.get("qlip_objective"),
        formula=composition_text,
    )
    property_bias = payload.get("property_bias")
    if property_bias is not None and not isinstance(property_bias, str):
        raise ValueError("property_bias must be a string or null.")
    property_bias_text = property_bias.strip() if isinstance(property_bias, str) and property_bias.strip() else None

    external_targets_raw = payload.get("external_predictor_targets", [])
    if not isinstance(external_targets_raw, list):
        raise ValueError("external_predictor_targets must be an array.")
    try:
        external_predictor_targets = _normalize_external_predictor_requests_from_text(external_targets_raw)
    except (Phase2ExternalPredictorResolutionError, Phase3ExternalPredictorResolutionError) as exc:
        if strict_phase1_benchmark_mode:
            phase = "PHASE3" if str(exc.code).startswith("PHASE3") else "PHASE2"
            raise ValueError(f"{phase}_BENCHMARK_MODE_REJECTED:{exc.code}:{exc.detail}") from exc
        raise ValueError(f"Structured external_predictor_targets invalid: {exc.code}:{exc.detail}") from exc

    composition_strictness = str(payload.get("composition_strictness", "fixed")).strip().lower() or "fixed"
    if composition_strictness not in {"fixed", "approximate"}:
        raise ValueError("composition_strictness must be one of fixed, approximate.")
    solve_mode = str(payload.get("solve_mode", "optimize" if qlip_objective or property_bias_text else "feasibility"))
    solve_mode = solve_mode.strip().lower() or "feasibility"
    if solve_mode not in {"feasibility", "optimize", "rediscovery"}:
        raise ValueError("solve_mode must be one of feasibility, optimize, rediscovery.")
    retrieval_strictness = str(payload.get("retrieval_strictness", "composition_tight")).strip().lower()
    if retrieval_strictness not in {"composition_tight", "prototype_tight", "broad"}:
        raise ValueError("retrieval_strictness must be one of composition_tight, prototype_tight, broad.")
    iteration_budget = int(payload.get("iteration_budget", 1))

    spec = TaskSpec(
        query_text=normalized_query_text,
        composition_target=composition_text,
        composition_strictness=composition_strictness,
        symmetry_request=symmetry_request,
        motif_prior=(
            str(payload.get("motif_prior")).strip()
            if isinstance(payload.get("motif_prior"), str) and str(payload.get("motif_prior")).strip()
            else None
        ),
        property_bias=property_bias_text,
        qlip_objective=qlip_objective,
        target_space_group=target_space_group or symmetry_request.space_group,
        target_space_group_number=target_space_group_number,
        target_crystal_system=target_crystal_system,
        target_structure_family=target_structure_family,
        prototype=prototype,
        external_predictor_targets=external_predictor_targets,
        solve_mode=solve_mode,
        retrieval_strictness=retrieval_strictness,
        iteration_budget=iteration_budget,
        defaults_used=defaults_used,
    )
    validate_task_spec(spec.to_dict())
    return spec


def load_task_spec_file(
    path: str | Path,
    *,
    strict_phase1_benchmark_mode: bool = False,
) -> TaskSpec:
    task_spec_path = Path(path).resolve()
    text = task_spec_path.read_text(encoding="utf-8")
    suffix = task_spec_path.suffix.strip().lower()
    if suffix == ".json":
        payload = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"Structured task spec file must contain an object: {task_spec_path}")
    return task_spec_from_payload(
        payload,
        strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
    )
