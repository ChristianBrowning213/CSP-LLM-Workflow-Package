from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_SOURCE_SYSTEMS = {"qlip_native", "spp_native", "hybrid"}
_FORMULATION_TYPES = {"objective", "threshold", "constraint", "guidance"}
_OPTIMIZATION_DIRECTIONS = {"minimize", "maximize", "bounded", "feasibility"}
_IMPLEMENTATION_STATUS = {"implemented_now", "small_wiring_needed"}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _elements_from_formula(formula: str | None) -> list[str]:
    if not isinstance(formula, str):
        return []
    items: list[str] = []
    for match in re.finditer(r"([A-Z][a-z]?)(?:\d+(?:\.\d+)?)?", formula):
        element = match.group(1)
        if element and element not in items:
            items.append(element)
    return items


def _default_linear_property(formula: str | None) -> dict[str, Any]:
    elements = _elements_from_formula(formula)
    if not elements:
        elements = ["*"]
    return {
        "kind": "occupancy_linear",
        "intercept": 0.0,
        "terms": [
            {"species": element, "coefficient": 1.0}
            for element in elements
        ],
    }


class Phase1PropertyResolutionError(ValueError):
    def __init__(
        self,
        *,
        code: str,
        requested: str,
        detail: str,
        suggestions: list[str] | None = None,
    ) -> None:
        self.code = str(code)
        self.requested = str(requested)
        self.detail = str(detail)
        self.suggestions = [str(item) for item in (suggestions or []) if str(item).strip()]
        message = self.detail
        if self.suggestions:
            message = f"{self.detail} Supported: {', '.join(self.suggestions)}"
        super().__init__(message)


class Phase1BenchmarkModeError(ValueError):
    def __init__(self, *, requested: str, cause: Phase1PropertyResolutionError) -> None:
        self.requested = str(requested)
        self.cause = cause
        self.code = f"PHASE1_BENCHMARK_REJECTED_{cause.code}"
        super().__init__(f"{self.code}: {cause.detail}")


@dataclass(frozen=True, slots=True)
class Phase1PropertyEntry:
    id: str
    display_name: str
    source_system: str
    formulation_type: str
    optimization_direction: str
    implementation_status: str
    required_inputs: list[str]
    notes: str
    benchmark_ready_now: bool = False
    request_aliases: list[str] | None = None
    property_key: str | None = None
    qlip_objective_family: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "source_system": self.source_system,
            "formulation_type": self.formulation_type,
            "optimization_direction": self.optimization_direction,
            "implementation_status": self.implementation_status,
            "required_inputs": list(self.required_inputs),
            "notes": self.notes,
            "benchmark_ready_now": bool(self.benchmark_ready_now),
            "request_aliases": list(self.request_aliases or []),
            "property_key": self.property_key,
            "qlip_objective_family": self.qlip_objective_family,
        }


def _registry() -> list[Phase1PropertyEntry]:
    # NOTE: IDs are orchestrator-level canonical identifiers.
    return [
        Phase1PropertyEntry(
            id="qlip.objective.energy_proxy",
            display_name="QLIP Native Energy/Enthalpy Proxy Objective",
            source_system="qlip_native",
            formulation_type="objective",
            optimization_direction="maximize",
            implementation_status="implemented_now",
            benchmark_ready_now=True,
            qlip_objective_family="spp_energy",
            request_aliases=[
                "objective_total",
                "qlip_objective",
                "energy_proxy",
                "enthalpy_proxy",
                "energy",
                "enthalpy",
            ],
            required_inputs=[
                "qlip.solve.result.summary.objective_value",
                "optimization.reward.primary_objective",
            ],
            notes=(
                "Loop-CSP currently optimizes this scalar directly as primary objective. "
                "Direction follows current backend convention (higher score preferred by bandit scoring)."
            ),
        ),
        Phase1PropertyEntry(
            id="qlip.property.property_x_estimate",
            display_name="QLIP Property Estimate (property_x)",
            source_system="qlip_native",
            formulation_type="objective",
            optimization_direction="maximize",
            implementation_status="implemented_now",
            benchmark_ready_now=True,
            request_aliases=["property_x", "property x", "x"],
            property_key="property_x",
            required_inputs=[
                "task_spec.property_bias=property_x",
                "qlip.solve.result.outputs.property_estimates.property_x or summary.property_x",
            ],
            notes=(
                "This is the only explicitly wired property-bias key in current Loop-CSP selection/reporting flow. "
                "Used by property-aware and property-decomposition-aware views."
            ),
        ),
        Phase1PropertyEntry(
            id="spp.guidance.energy_spp_term",
            display_name="SPP Objective Shaping Term (objective.energy_spp)",
            source_system="hybrid",
            formulation_type="guidance",
            optimization_direction="bounded",
            implementation_status="implemented_now",
            benchmark_ready_now=True,
            request_aliases=["objective.energy_spp", "energy_spp", "spp_term"],
            required_inputs=[
                "guidance[].id=objective.energy_spp",
                "guidance.params.spp_package_path",
                "qlip.solve.result.outputs.objective_terms includes term SPP",
            ],
            notes=(
                "Fully wired through qlip_builders_v2 + pipeline guidance payload. "
                "Term is consumed in objective decomposition analysis and property_decomp_aware selection."
            ),
        ),
        Phase1PropertyEntry(
            id="spp.guidance.lambda_weight_override",
            display_name="SPP Guidance Weight Override (lambda_override)",
            source_system="hybrid",
            formulation_type="guidance",
            optimization_direction="bounded",
            implementation_status="implemented_now",
            benchmark_ready_now=True,
            request_aliases=["lambda_override", "spp_lambda", "spp_weight"],
            required_inputs=[
                "guidance.params.lambda_override",
                "objective.energy_spp guidance enabled",
            ],
            notes=(
                "Directly configurable today via action compile/pipeline overrides. "
                "This is a control surface for Phase 1 objective shaping, not a standalone property metric."
            ),
        ),
        Phase1PropertyEntry(
            id="spp.calibration.recommended_lambda",
            display_name="SPP Calibration Recommended Weight",
            source_system="spp_native",
            formulation_type="guidance",
            optimization_direction="bounded",
            implementation_status="implemented_now",
            benchmark_ready_now=True,
            request_aliases=["calibrated_lambda", "spp_calibrated_lambda"],
            required_inputs=[
                "spp.calibration_report.v1.recommended_weight",
                "pipeline lambda precedence wiring with source tracking",
            ],
            notes=(
                "Recommended weight is auto-applied when available and when no stronger override exists. "
                "Lambda precedence and source are written to run artifacts."
            ),
        ),
        Phase1PropertyEntry(
            id="qlip.native.density_packing_proxy",
            display_name="QLIP Native Density/Packing Proxy",
            source_system="qlip_native",
            formulation_type="objective",
            optimization_direction="maximize",
            implementation_status="implemented_now",
            benchmark_ready_now=True,
            qlip_objective_family="density_packing",
            request_aliases=[
                "density_packing",
                "density packing",
                "density",
                "packing",
                "density_proxy",
                "packing_proxy",
                "pair_distance_packing",
            ],
            required_inputs=[
                "task_spec.qlip_objective.type=density_packing",
                "task_spec.qlip_objective.proxy=pair_distance_packing",
                "qlip.solve.request.objective",
            ],
            notes=(
                "Maps to upstream QLIP objective {type: density_packing, proxy: pair_distance_packing}. "
                "This is a packing/contact proxy, not literal physical mass density."
            ),
        ),
        Phase1PropertyEntry(
            id="qlip.native.linear_property_proxy",
            display_name="QLIP Native Occupancy-Linear Property Proxy",
            source_system="qlip_native",
            formulation_type="objective",
            optimization_direction="maximize",
            implementation_status="implemented_now",
            benchmark_ready_now=True,
            qlip_objective_family="linear_property",
            request_aliases=[
                "linear_property",
                "linear property",
                "linear_property_proxy",
                "occupancy_linear",
                "occupancy_linear_property",
            ],
            required_inputs=[
                "task_spec.qlip_objective.type=linear_property",
                "task_spec.qlip_objective.linear_property.terms[].coefficient",
                "task_spec.qlip_objective.linear_property.terms[].species or .site_label",
                "qlip.solve.request.objective",
            ],
            notes=(
                "Maps to upstream QLIP objective {type: linear_property}. Exposes only native "
                "occupancy-linear terms supplied as coefficients over species/site occupancy; it does not imply "
                "external hardness, modulus, or pretrained property predictors."
            ),
        ),
        Phase1PropertyEntry(
            id="qlip.native.threshold_tradeoff",
            display_name="QLIP Native Threshold/Weighted Tradeoff Form",
            source_system="qlip_native",
            formulation_type="threshold",
            optimization_direction="bounded",
            implementation_status="implemented_now",
            benchmark_ready_now=True,
            qlip_objective_family="threshold_tradeoff",
            request_aliases=["threshold", "tradeoff", "weighted_tradeoff", "bounded_tradeoff"],
            required_inputs=[
                "task_spec.qlip_objective.type=threshold_tradeoff",
                "task_spec.qlip_objective.linear_property.terms[]",
                "task_spec.qlip_objective.threshold.operator/value",
                "optional task_spec.qlip_objective.base.type in {spp_energy, none}",
                "optional task_spec.qlip_objective.property_weight",
            ],
            notes=(
                "Maps to upstream QLIP objective {type: threshold_tradeoff}. The threshold is a hard bound "
                "over a native linear property; the optional weighted property term is separate from that bound."
            ),
        ),
    ]


def validate_phase1_property_registry() -> None:
    seen_ids: set[str] = set()
    for item in _registry():
        payload = item.to_dict()
        if payload["id"] in seen_ids:
            raise ValueError(f"Duplicate phase1 property id: {payload['id']}")
        seen_ids.add(payload["id"])
        if payload["source_system"] not in _SOURCE_SYSTEMS:
            raise ValueError(f"Invalid source_system for {payload['id']}: {payload['source_system']}")
        if payload["formulation_type"] not in _FORMULATION_TYPES:
            raise ValueError(f"Invalid formulation_type for {payload['id']}: {payload['formulation_type']}")
        if payload["optimization_direction"] not in _OPTIMIZATION_DIRECTIONS:
            raise ValueError(f"Invalid optimization_direction for {payload['id']}: {payload['optimization_direction']}")
        if payload["implementation_status"] not in _IMPLEMENTATION_STATUS:
            raise ValueError(f"Invalid implementation_status for {payload['id']}: {payload['implementation_status']}")
        if not payload["required_inputs"]:
            raise ValueError(f"required_inputs must be non-empty for {payload['id']}")


def list_phase1_property_entries(*, include_small_wiring: bool = True) -> list[Phase1PropertyEntry]:
    validate_phase1_property_registry()
    items = _registry()
    if include_small_wiring:
        return list(items)
    return [item for item in items if item.implementation_status == "implemented_now"]


def phase1_property_table(*, include_small_wiring: bool = True) -> list[dict[str, Any]]:
    return [item.to_dict() for item in list_phase1_property_entries(include_small_wiring=include_small_wiring)]


def phase1_property_report() -> dict[str, Any]:
    table = phase1_property_table(include_small_wiring=True)
    implemented = [row for row in table if row.get("implementation_status") == "implemented_now"]
    small_wiring = [row for row in table if row.get("implementation_status") == "small_wiring_needed"]
    return {
        "schema_version": "phase1.property_library.v1",
        "counts": {
            "total": len(table),
            "implemented_now": len(implemented),
            "small_wiring_needed": len(small_wiring),
            "benchmark_ready_now": sum(1 for row in table if bool(row.get("benchmark_ready_now"))),
        },
        "implemented_now": implemented,
        "small_wiring_needed": small_wiring,
        "all_entries": table,
    }


def _build_alias_map() -> dict[str, Phase1PropertyEntry]:
    alias_map: dict[str, Phase1PropertyEntry] = {}
    for item in list_phase1_property_entries(include_small_wiring=True):
        aliases = [item.id, *(item.request_aliases or [])]
        for alias in aliases:
            key = _norm(alias)
            if not key:
                continue
            alias_map[key] = item
    return alias_map


def resolve_phase1_property_request(
    requested: str,
    *,
    allow_small_wiring: bool = False,
) -> Phase1PropertyEntry:
    key = _norm(requested)
    alias_map = _build_alias_map()
    item = alias_map.get(key)
    if item is None:
        implemented_ids = [
            row.id
            for row in list_phase1_property_entries(include_small_wiring=False)
        ]
        raise Phase1PropertyResolutionError(
            code="PHASE1_UNKNOWN_PROPERTY_REQUEST",
            requested=requested,
            detail=f"Unknown Phase 1 property/objective request: {requested}",
            suggestions=implemented_ids,
        )
    if item.implementation_status != "implemented_now" and not allow_small_wiring:
        raise Phase1PropertyResolutionError(
            code="PHASE1_SMALL_WIRING_REQUIRED",
            requested=requested,
            detail=(
                f"Phase 1 request '{requested}' maps to '{item.id}', which is available only with small wiring."
            ),
            suggestions=[
                row.id
                for row in list_phase1_property_entries(include_small_wiring=False)
            ],
        )
    return item


def resolve_property_bias_key(
    requested: str | None,
    *,
    allow_small_wiring: bool = False,
) -> str | None:
    if requested is None:
        return None
    item = resolve_phase1_property_request(requested, allow_small_wiring=allow_small_wiring)
    if not isinstance(item.property_key, str) or not item.property_key.strip():
        raise Phase1PropertyResolutionError(
            code="PHASE1_UNSUPPORTED_PROPERTY_BIAS",
            requested=requested,
            detail=(
                f"Phase 1 request '{requested}' resolved to '{item.id}', "
                "but it is not a task_spec.property_bias-compatible key."
            ),
            suggestions=[
                row.id
                for row in list_phase1_property_entries(include_small_wiring=True)
                if isinstance(row.property_key, str) and row.property_key.strip()
            ],
        )
    return item.property_key


def require_phase1_property_for_benchmark(requested: str) -> Phase1PropertyEntry:
    try:
        return resolve_phase1_property_request(requested, allow_small_wiring=False)
    except Phase1PropertyResolutionError as exc:
        raise Phase1BenchmarkModeError(requested=requested, cause=exc) from exc


def qlip_objective_for_phase1_entry(
    entry: Phase1PropertyEntry,
    *,
    formula: str | None = None,
) -> dict[str, Any] | None:
    family = entry.qlip_objective_family
    if family == "spp_energy":
        return {"type": "spp_energy"}
    if family == "density_packing":
        return {"type": "density_packing", "proxy": "pair_distance_packing"}
    if family == "linear_property":
        return {
            "type": "linear_property",
            "linear_property": _default_linear_property(formula),
        }
    if family == "threshold_tradeoff":
        return {
            "type": "threshold_tradeoff",
            "linear_property": _default_linear_property(formula),
            "threshold": {"operator": ">=", "value": 0.0},
            "base": {"type": "spp_energy"},
            "property_weight": 1.0,
        }
    return None


def qlip_objective_for_phase1_request(
    requested: str,
    *,
    formula: str | None = None,
    allow_small_wiring: bool = False,
) -> dict[str, Any] | None:
    entry = resolve_phase1_property_request(requested, allow_small_wiring=allow_small_wiring)
    return qlip_objective_for_phase1_entry(entry, formula=formula)
