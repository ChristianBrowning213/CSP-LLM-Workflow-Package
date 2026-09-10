from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ChemistrySpec:
    formula: str
    charge_model: str = "none"
    oxidation_states: Optional[Dict[str, int]] = None
    charge_policy: str = "NOT_ENFORCED"
    compensation_operation: Optional[str] = None
    assumptions_source: Optional[str] = None


@dataclass
class LatticeSpec:
    a: float
    b: float
    c: float
    alpha: float
    beta: float
    gamma: float
    units: str = "angstrom"


@dataclass
class TemplateSpec:
    lattice: LatticeSpec
    name: Optional[str] = None


@dataclass
class UniformGridSpec:
    density: int
    jitter: float = 0.0
    seed: Optional[int] = None


@dataclass
class SitesSpec:
    mode: str
    uniform_grid: Optional[UniformGridSpec] = None
    explicit_fractional_sites: Optional[List[List[float]]] = None
    ordered_orbits: Optional[List[Dict[str, Any]]] = None
    vacancy_count: Optional[int] = None


@dataclass
class DesignSpaceSpec:
    template: TemplateSpec
    sites: SitesSpec


@dataclass
class BaseObjectiveSpec:
    type: str = "spp_energy"
    direction: Optional[str] = None
    proxy: Optional[str] = None
    property: Optional[Dict[str, Any]] = None
    base_objective: Optional[str] = None
    threshold: Optional[Dict[str, Any]] = None
    tradeoff_direction: Optional[str] = None
    tradeoff_weight: float = 0.0


@dataclass
class ProblemSpec:
    chemistry: ChemistrySpec
    design_space: DesignSpaceSpec
    objective: Optional[BaseObjectiveSpec] = None


@dataclass
class ConstraintInvocation:
    id: str
    params: Dict[str, Any] = field(default_factory=dict)
    name: Optional[str] = None
    enabled: bool = True
    priority: int = 100


@dataclass
class GuidanceInvocation:
    id: str
    params: Dict[str, Any] = field(default_factory=dict)
    name: Optional[str] = None
    enabled: bool = True
    weight: float = 1.0
    level: int = 0
    epsilon: float = 0.0


@dataclass
class SolverConfig:
    name: str
    time_limit_s: int = 60
    mip_gap: float = 0.0
    threads: Optional[int] = None
    seed: Optional[int] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactSpec:
    return_cif: bool = True
    return_decoder_debug: bool = False
    render_vesta: bool = False
    vesta_path: Optional[str] = None
    supercell: Optional[List[int]] = None


@dataclass
class RuntimeLimits:
    max_sites: Optional[int] = None
    max_binary_vars: Optional[int] = None
    max_constraints: Optional[int] = None
    export_gurobi_visuals: bool = False
    gurobi_visuals_dir: Optional[str] = None


@dataclass
class ContextSpec:
    run_id: Optional[str] = None
    pot_root: Optional[str] = None
    motif_root: Optional[str] = None
    gurobi_visuals_dir: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class SearchSpec:
    requested_k: int = 1
    distinctness_policy: str = "STRUCTURE_DISTINCT"
    scaffold_ids: List[str] = field(default_factory=list)


@dataclass
class SolveRequest:
    version: str
    problem: ProblemSpec
    constraints: List[ConstraintInvocation] = field(default_factory=list)
    guidance: List[GuidanceInvocation] = field(default_factory=list)
    guidance_mode: str = "weighted_sum"
    solver: SolverConfig = field(default_factory=SolverConfig)
    artifacts: ArtifactSpec = field(default_factory=ArtifactSpec)
    runtime: RuntimeLimits = field(default_factory=RuntimeLimits)
    context: ContextSpec = field(default_factory=ContextSpec)
    search: SearchSpec = field(default_factory=SearchSpec)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PluginCatalogEntry:
    id: str
    kind: str
    title: str
    description: str
    params_schema: Dict[str, Any]
    tags: List[str] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactItem:
    kind: str
    data: str
    mime: str = "application/octet-stream"


@dataclass
class SolveOutputs:
    cif: Optional[str] = None
    decoder_debug: Optional[str] = None
    artifacts: List[ArtifactItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SolveSummary:
    solver: str
    timing_ms: int
    objective_value: Optional[float] = None
    best_bound: Optional[float] = None
    mip_gap: Optional[float] = None
    termination: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SolveError:
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details or {}}


@dataclass
class SolveResult:
    status: str
    summary: SolveSummary
    outputs: SolveOutputs
    certificates: Dict[str, Any] = field(default_factory=dict)
    errors: List[SolveError] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "status": self.status,
            "summary": self.summary.to_dict(),
            "outputs": self.outputs.to_dict(),
        }
        if self.certificates is not None:
            out["certificates"] = self.certificates
        if self.errors:
            out["errors"] = [e.to_dict() for e in self.errors]
        else:
            out["errors"] = []
        if self.logs:
            out["logs"] = list(self.logs)
        else:
            out["logs"] = []
        return out


@dataclass
class ValidationIssue:
    code: str
    message: str
    path: str
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "details": self.details or {},
        }


@dataclass
class ValidationReport:
    valid: bool
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    normalized_request: Optional[Dict[str, Any]] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    missing_fields: List[str] = field(default_factory=list)
    invalid_guidance_params: List[Dict[str, Any]] = field(default_factory=list)
    path_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    data_diagnostics: Dict[str, Any] = field(default_factory=dict)
    missing_data: List[Dict[str, Any]] = field(default_factory=list)
    available_data: List[Dict[str, Any]] = field(default_factory=list)
    required_data: List[Dict[str, Any]] = field(default_factory=list)
    suggested_next_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        validation_errors = [e.to_dict() for e in self.errors]
        validation_warnings = [w.to_dict() for w in self.warnings]
        out = {
            "valid": self.valid,
            "errors": validation_errors,
            "warnings": validation_warnings,
            "capabilities": self.capabilities,
            "validation_error_codes": [e.code for e in self.errors],
            "validation_errors": validation_errors,
            "validation_warnings": validation_warnings,
            "missing_fields": list(self.missing_fields),
            "invalid_guidance_params": list(self.invalid_guidance_params),
            "path_diagnostics": list(self.path_diagnostics),
            "data_diagnostics": dict(self.data_diagnostics),
            "missing_data": list(self.missing_data),
            "available_data": list(self.available_data),
            "required_data": list(self.required_data),
            "suggested_next_actions": list(self.suggested_next_actions),
        }
        if self.normalized_request is not None:
            out["normalized_request"] = self.normalized_request
        return out
