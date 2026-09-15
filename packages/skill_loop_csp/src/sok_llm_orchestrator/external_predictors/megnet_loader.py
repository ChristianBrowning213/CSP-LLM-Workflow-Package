from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CANONICAL_MEGNET_MODEL_IDS = (
    "Eform_MP_2018",
    "Bandgap_MP_2018",
    "logK_MP_2018",
    "logG_MP_2018",
)


class MEGNetLoaderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MEGNetModelFiles:
    model_id: str
    model_path: Path
    config_path: Path
    model_exists: bool
    config_exists: bool
    searched_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_path": str(self.model_path),
            "config_path": str(self.config_path),
            "model_exists": bool(self.model_exists),
            "config_exists": bool(self.config_exists),
            "searched_paths": [str(path) for path in self.searched_paths],
        }


_LOADED_MODELS: dict[str, Any] = {}


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def _import_megnet_stack() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from megnet.layers import _CUSTOM_OBJECTS
        from megnet.models import GraphModel
        from megnet.utils import models as megnet_models
        from monty.serialization import loadfn
        from tensorflow.keras.models import load_model as keras_load_model
    except Exception as exc:  # pragma: no cover - depends on optional runtime stack
        raise MEGNetLoaderError(f"MEGNet runtime stack is not available: {exc}") from exc
    return _CUSTOM_OBJECTS, GraphModel, megnet_models, loadfn, keras_load_model


def _model_mapping(megnet_models: Any, model_id: str) -> str:
    mapping = getattr(megnet_models, "MODEL_MAPPING", {})
    if model_id not in mapping:
        supported = sorted(str(item) for item in mapping)
        raise MEGNetLoaderError(
            f"Unknown MEGNet model id: {model_id}. Supported ids include: {', '.join(supported)}"
        )
    return str(mapping[model_id])


def _candidate_model_paths(megnet_models: Any, model_id: str) -> tuple[Path, ...]:
    relative = _model_mapping(megnet_models, model_id)
    roots: list[Path] = []
    for attr in ("MODEL_PATH", "LOCAL_MODEL_PATH"):
        value = getattr(megnet_models, attr, None)
        if value is not None:
            root = Path(str(value)).resolve()
            if root not in roots:
                roots.append(root)
    return tuple(root / relative for root in roots)


def resolve_megnet_model_files(model_id: str) -> MEGNetModelFiles:
    _, _, megnet_models, _, _ = _import_megnet_stack()
    candidates = _candidate_model_paths(megnet_models, model_id)
    if not candidates:
        raise MEGNetLoaderError(f"MEGNet exposes no MODEL_PATH roots for {model_id}")
    selected = next((path for path in candidates if path.is_file()), candidates[-1])
    config_path = Path(str(selected) + ".json")
    return MEGNetModelFiles(
        model_id=model_id,
        model_path=selected,
        config_path=config_path,
        model_exists=selected.is_file(),
        config_exists=config_path.is_file(),
        searched_paths=candidates,
    )


def get_model_path(model_id: str) -> Path:
    return resolve_megnet_model_files(model_id).model_path


def get_config_path(model_id: str) -> Path:
    return resolve_megnet_model_files(model_id).config_path


def load_megnet_graphmodel(model_id: str) -> Any:
    if model_id in _LOADED_MODELS:
        return _LOADED_MODELS[model_id]

    custom_objects, graph_model_cls, _, loadfn, keras_load_model = _import_megnet_stack()
    files = resolve_megnet_model_files(model_id)
    if not files.model_exists or not files.config_exists:
        searched = ", ".join(str(path) for path in files.searched_paths)
        raise MEGNetLoaderError(
            f"Missing MEGNet model files for {model_id}; searched model paths: {searched}; "
            f"selected config path: {files.config_path}"
        )

    keras_model = keras_load_model(
        str(files.model_path),
        custom_objects=custom_objects,
        compile=False,
    )
    configs = loadfn(str(files.config_path))
    if not isinstance(configs, dict):
        raise MEGNetLoaderError(f"MEGNet config for {model_id} is not a JSON object: {files.config_path}")
    graph_model = graph_model_cls(model=keras_model, **configs)
    _LOADED_MODELS[model_id] = graph_model
    return graph_model


def load_megnet_model(model_id: str) -> Any:
    return load_megnet_graphmodel(model_id)


def megnet_loader_report() -> dict[str, Any]:
    runtime_available = True
    runtime_error: str | None = None
    models: list[dict[str, Any]] = []
    try:
        _import_megnet_stack()
        for model_id in CANONICAL_MEGNET_MODEL_IDS:
            models.append(resolve_megnet_model_files(model_id).to_dict())
    except Exception as exc:  # noqa: BLE001
        runtime_available = False
        runtime_error = str(exc)
    return {
        "schema_version": "phase3.megnet_loader_report.v1",
        "runtime_available": runtime_available,
        "runtime_error": runtime_error,
        "backend_versions": {
            "megnet": _package_version("megnet"),
            "tensorflow": _package_version("tensorflow"),
            "monty": _package_version("monty"),
        },
        "canonical_model_ids": list(CANONICAL_MEGNET_MODEL_IDS),
        "models": models,
        "production_loader": {
            "uses_megnet_utils_models_load_model": False,
            "uses_model_mapping": True,
            "uses_model_path": True,
            "uses_local_model_path": True,
            "uses_custom_objects": True,
            "uses_compile_false": True,
            "uses_paired_json_config": True,
            "reconstructs_graph_model": True,
        },
    }


__all__ = [
    "CANONICAL_MEGNET_MODEL_IDS",
    "MEGNetLoaderError",
    "MEGNetModelFiles",
    "get_config_path",
    "get_model_path",
    "load_megnet_graphmodel",
    "load_megnet_model",
    "megnet_loader_report",
    "resolve_megnet_model_files",
]
