"""Configuration and result models for the packaged deterministic workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class CSPWorkflowRequest:
    query: str
    formula: str
    design_space: dict[str, Any]
    constraints: tuple[dict[str, Any], ...] = ()
    target_space_group: str | None = None
    topology_family: str | None = None
    scaffold_id: str | None = None

    def __post_init__(self) -> None:
        if not self.query.strip() or not self.formula.strip():
            raise ValueError("query and formula must be non-empty")
        if not isinstance(self.design_space, dict) or not self.design_space:
            raise ValueError("design_space must be an explicit packaged QLIP design space")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CSPWorkflowRequest":
        payload = dict(value)
        payload["constraints"] = tuple(payload.get("constraints") or ())
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    db_path: Path | None = None
    k: int = 40
    embed_engine: str = "lmstudio"
    model_name: str = "text-embedding-bge-m3"
    model_version: str = "lmstudio_v1"
    text_engine: str = "robocrys"
    text_view: str = "robocrys"
    demo_export: bool = False

    def __post_init__(self) -> None:
        if self.k <= 0:
            raise ValueError("retrieval k must be positive")


@dataclass(frozen=True, slots=True)
class SPPConfig:
    request_mode: str = "fit"
    regulator_root: Path | None = None
    cutoff: float = 11.0
    request_coefficient: float = 1.0
    regulator_coefficient: float = 2.0
    outer_objective_scale: float = 10.0

    def __post_init__(self) -> None:
        if self.request_mode not in {"fit", "disabled"}:
            raise ValueError("SPP request_mode must be 'fit' or 'disabled'")
        if self.cutoff <= 0 or self.request_coefficient < 0 or self.regulator_coefficient < 0:
            raise ValueError("SPP cutoff must be positive and coefficients non-negative")


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    solver_name: str = "gurobi"
    time_limit_s: int = 300
    mip_gap: float = 0.0
    threads: int = 1
    seed: int = 0

    def __post_init__(self) -> None:
        if self.time_limit_s <= 0 or self.threads <= 0 or self.mip_gap < 0:
            raise ValueError("invalid solver limits")


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    enabled: bool = True
    topology: bool = True


@dataclass(frozen=True, slots=True)
class WorkflowConfig:
    output_root: Path
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    spp: SPPConfig = field(default_factory=SPPConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    run_id: str | None = None
    retrieval_provider: Callable[..., Any] | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("retrieval_provider", None)
        return _jsonable(payload)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowConfig":
        payload = dict(value)
        payload["output_root"] = Path(payload["output_root"])
        payload["retrieval"] = RetrievalConfig(**payload.get("retrieval", {}))
        if payload["retrieval"].db_path is not None:
            payload["retrieval"] = RetrievalConfig(
                **(asdict(payload["retrieval"]) | {"db_path": Path(payload["retrieval"].db_path)})
            )
        spp = dict(payload.get("spp", {}))
        if spp.get("regulator_root") is not None:
            spp["regulator_root"] = Path(spp["regulator_root"])
        payload["spp"] = SPPConfig(**spp)
        payload["generation"] = GenerationConfig(**payload.get("generation", {}))
        payload["validation"] = ValidationConfig(**payload.get("validation", {}))
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    run_id: str
    status: str
    request: dict[str, Any]
    stages: dict[str, Any]
    artifacts: dict[str, str]
    provenance: dict[str, Any]
    warnings: tuple[str, ...] = ()
    errors: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))
