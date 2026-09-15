"""Optional MLIP-depth benchmark evaluator skeletons."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import Any

from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.chgnet import _extract_forces_max
from sca.schemas import BenchmarkEvaluatorResult


_M3GNET_POTENTIAL_CACHE: dict[tuple[str | None, str | None], tuple[Any, str, list[str] | None] | BaseException] = {}


class M3GNetStaticBenchmarkEvaluator:
    name = "m3gnet_static"
    prefix = "m3gnet"
    description = "Optional MatGL/M3GNet static surrogate-energy evaluator."

    def evaluate_path(self, cif_path: str | Path) -> BenchmarkEvaluatorResult:
        return _ase_calculator_result(
            self.name,
            self.prefix,
            cif_path,
            _load_m3gnet_calculator,
            model_path=os.environ.get("SCA_M3GNET_MODEL"),
            pretrained=os.environ.get("SCA_M3GNET_PRETRAINED"),
        )


class MaceStaticBenchmarkEvaluator:
    name = "mace_static"
    prefix = "mace"
    description = "Optional MACE ASE static surrogate-energy evaluator."

    def evaluate_path(self, cif_path: str | Path) -> BenchmarkEvaluatorResult:
        model_path = os.environ.get("SCA_MACE_MODEL")
        pretrained = os.environ.get("SCA_MACE_PRETRAINED")
        if not model_path and not pretrained:
            return _mlip_result(
                self.name,
                self.prefix,
                False,
                "unavailable",
                "Set SCA_MACE_MODEL to a local model file or SCA_MACE_PRETRAINED to an explicit pretrained keyword",
                "RuntimeError",
                skipped=True,
            )
        return _ase_calculator_result(
            self.name,
            self.prefix,
            cif_path,
            _load_mace_calculator,
            model_path=model_path,
            pretrained=pretrained,
        )


class SevenNetStaticBenchmarkEvaluator:
    name = "sevennet_static"
    prefix = "sevennet"
    description = "Optional SevenNet ASE static surrogate-energy evaluator."

    def evaluate_path(self, cif_path: str | Path) -> BenchmarkEvaluatorResult:
        model_path = os.environ.get("SCA_SEVENNET_MODEL")
        pretrained = os.environ.get("SCA_SEVENNET_PRETRAINED")
        if not model_path and not pretrained:
            return _mlip_result(
                self.name,
                self.prefix,
                False,
                "unavailable",
                "Set SCA_SEVENNET_MODEL to a local model file or SCA_SEVENNET_PRETRAINED to an explicit pretrained keyword",
                "RuntimeError",
                skipped=True,
            )
        return _ase_calculator_result(
            self.name,
            self.prefix,
            cif_path,
            _load_sevennet_calculator,
            model_path=model_path,
            pretrained=pretrained,
        )


class MlipEnsembleBenchmarkEvaluator:
    name = "mlip_ensemble"
    description = "Declares per-row MLIP availability; cross-candidate rank consensus is campaign-level."

    def evaluate_row(self, row: dict) -> BenchmarkEvaluatorResult:
        models_available = []
        for key in (
            "formation_energy_per_atom",
            "alignn_formation_energy_per_atom",
            "chgnet_energy_per_atom",
            "m3gnet_energy_per_atom",
            "mace_energy_per_atom",
            "sevennet_energy_per_atom",
        ):
            value = _float_or_none(row.get(key))
            if value is not None:
                models_available.append(key.removesuffix("_energy_per_atom"))
        enough = len(models_available) >= 2
        label = "RANK_ANALYSIS_REQUIRED" if enough else "INSUFFICIENT_MODELS"
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=enough,
            skipped=not enough,
            summary=label,
            metrics={
                # Backward-compatible identity for a single model, not a cross-model average.
                "mlip_energy_mean": (
                    _float_or_none(row.get(f"{models_available[0]}_energy_per_atom"))
                    if len(models_available) == 1
                    else None
                ),
                "mlip_energy_std": None,
                "models_available": models_available,
                "model_success_count": len(models_available),
                "energy_rank_consensus": None,
                "energy_rank_variance": None,
                "force_rank_consensus": None,
                "mlip_disagreement_flag": None,
                "mlip_consensus_label": label,
                "mlip_ensemble_explanation": (
                    "Requires within-model ranks across a candidate campaign; raw model energies "
                    "are not averaged because their energy conventions are not calibrated."
                ),
            },
            flags={"mlip_disagreement_flag": None},
        )


def _ase_calculator_result(
    name: str,
    prefix: str,
    cif_path: str | Path,
    calculator_loader,
    model_path: str | None,
    pretrained: str | None,
) -> BenchmarkEvaluatorResult:
    structure, parsed = parse_cif(cif_path)
    if structure is None:
        return _mlip_result(name, prefix, False, "parse failed", parsed.error_message, parsed.error_type)
    model_label = None
    details: dict[str, Any] = {}
    try:
        from pymatgen.io.ase import AseAtomsAdaptor
        calculator, model_label, details = _normalize_calculator_loader_result(
            calculator_loader(model_path=model_path, pretrained=pretrained)
        )
        atoms = AseAtomsAdaptor.get_atoms(structure)
        atoms.calc = calculator
        energy_per_atom = float(atoms.get_potential_energy()) / len(atoms)
        forces = atoms.get_forces()
        forces_max = _extract_forces_max({"forces": forces})
        force_norms = [float(sum(component * component for component in row) ** 0.5) for row in forces]
        forces_mean = sum(force_norms) / len(force_norms) if force_norms else None
        try:
            stress = atoms.get_stress(voigt=False)
            stress_norm = float(sum(float(value) ** 2 for row in stress for value in row) ** 0.5)
        except Exception:
            stress_norm = None
    except ModuleNotFoundError as exc:
        return _mlip_result(name, prefix, False, "unavailable", str(exc), type(exc).__name__, skipped=True, details=details)
    except KeyError as exc:
        if prefix == "m3gnet":
            message = _m3gnet_key_error_message(exc, model_label, details.get("supported_elements"))
            return _mlip_result(name, prefix, False, "failed", message, type(exc).__name__, model=model_label, details=details)
        return _mlip_result(name, prefix, False, "failed", str(exc), type(exc).__name__, model=model_label, details=details)
    except Exception as exc:
        return _mlip_result(name, prefix, False, "failed", str(exc), type(exc).__name__, model=model_label, details=details)
    return _mlip_result(
        name,
        prefix,
        True,
        "ok",
        None,
        None,
        model=model_label,
        energy_per_atom=energy_per_atom,
        forces_max=forces_max,
        forces_mean=forces_mean,
        stress_norm=stress_norm,
        details=details,
    )


def _normalize_calculator_loader_result(result: Any) -> tuple[Any, str | None, dict[str, Any]]:
    calculator, model_label, *rest = result
    details = rest[0] if rest else {}
    return calculator, model_label, details or {}


def _load_m3gnet_calculator(
    model_path: str | None,
    pretrained: str | None,
):
    try:
        import matgl
    except Exception as exc:
        raise ModuleNotFoundError("MatGL is unavailable") from exc

    potential, model_label, supported_elements = _cached_m3gnet_potential(
        matgl,
        model_name=model_path,
        pretrained=pretrained,
    )
    details = {
        "matgl_version": getattr(matgl, "__version__", None),
        "supported_elements": supported_elements,
    }
    return _m3gnet_calculator_from_potential(potential), model_label, details


def _cached_m3gnet_potential(
    matgl_module: Any,
    model_name: str | None,
    pretrained: str | None,
) -> tuple[Any, str, list[str] | None]:
    key = (model_name, pretrained)
    cached = _M3GNET_POTENTIAL_CACHE.get(key)
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached
    try:
        potential, model_label = _load_m3gnet_potential(matgl_module, model_name=model_name, pretrained=pretrained)
        loaded = (potential, model_label, _matgl_supported_elements(potential))
    except Exception as exc:
        _M3GNET_POTENTIAL_CACHE[key] = exc
        raise
    _M3GNET_POTENTIAL_CACHE[key] = loaded
    return loaded


def _load_m3gnet_potential(
    matgl_module: Any,
    model_name: str | None,
    pretrained: str | None,
) -> tuple[Any, str]:
    errors = []
    for candidate in _m3gnet_model_candidates(matgl_module, model_name=model_name, pretrained=pretrained):
        try:
            return matgl_module.load_model(candidate), candidate
        except Exception as exc:
            errors.append(f"{candidate}: {_exception_chain_summary(exc)}")
    message = "Could not load an M3GNet MatGL model"
    if errors:
        message += "; attempted " + " | ".join(errors)
    message += "; set SCA_M3GNET_MODEL or SCA_M3GNET_PRETRAINED to an explicit MatGL model name or serialized model path"
    raise RuntimeError(message)


def _m3gnet_model_candidates(
    matgl_module: Any,
    model_name: str | None,
    pretrained: str | None,
) -> list[str]:
    if model_name:
        return [model_name]
    if pretrained:
        return [pretrained]

    candidates = [
        "M3GNet-PES-MatPES-PBE-2025.2",
        "materialyze/M3GNet-PES-MatPES-PBE-2025.2",
        "M3GNet-PES-MatPES-r2SCAN-2025.2",
        "materialyze/M3GNet-PES-MatPES-r2SCAN-2025.2",
        "M3GNet-MP-2021.2.8-DIRECT-PES",
        "M3GNet-MP-2021.2.8-PES",
    ]
    available_loader = getattr(matgl_module, "get_available_pretrained_models", None)
    if os.environ.get("SCA_M3GNET_DISCOVER_MODELS") and callable(available_loader):
        try:
            available = [str(name) for name in available_loader()]
        except Exception:
            available = []
        candidates.extend(sorted(name for name in available if _is_default_m3gnet_pes_candidate(name)))
    return list(dict.fromkeys(candidates))


def _is_default_m3gnet_pes_candidate(name: str) -> bool:
    return "M3GNet" in name and "PES" in name and ("MatPES" in name or "MP-2021.2.8" in name)


def _m3gnet_calculator_from_potential(potential: Any) -> Any:
    errors = []
    for module_name, class_name in (
        ("matgl.ext.ase", "PESCalculator"),
        ("matgl.ext._ase_dgl", "PESCalculator"),
        ("matgl.ext.ase", "M3GNetCalculator"),
    ):
        try:
            calculator_class = getattr(import_module(module_name), class_name)
        except Exception as exc:
            errors.append(f"{module_name}.{class_name}: {type(exc).__name__}: {exc}")
            continue
        for kwargs in ({"potential": potential}, {}):
            try:
                return calculator_class(**kwargs) if kwargs else calculator_class(potential)
            except TypeError as exc:
                errors.append(f"{module_name}.{class_name}: {type(exc).__name__}: {exc}")
                continue
    raise ModuleNotFoundError("MatGL ASE calculator API is unavailable: " + " | ".join(errors))


def _exception_chain_summary(exc: BaseException) -> str:
    parts = [f"{type(exc).__name__}: {exc}"]
    seen = {id(exc)}
    cause = exc.__cause__ or exc.__context__
    while cause is not None and id(cause) not in seen and len(parts) < 4:
        seen.add(id(cause))
        parts.append(f"caused by {type(cause).__name__}: {cause}")
        cause = cause.__cause__ or cause.__context__
    return "; ".join(parts)


def _matgl_supported_elements(potential: Any) -> list[str] | None:
    seen: list[str] = []
    for obj in _walk_attr_chain(potential):
        for attr in ("element_types", "atom_types", "species"):
            values = getattr(obj, attr, None)
            if values is None:
                continue
            try:
                elements = [str(value) for value in values]
            except TypeError:
                continue
            for element in elements:
                if element not in seen:
                    seen.append(element)
    return seen or None


def _walk_attr_chain(root: Any) -> list[Any]:
    objects = [root]
    for attr in ("model", "graph_converter", "potential"):
        obj = getattr(root, attr, None)
        if obj is not None:
            objects.append(obj)
    model = getattr(root, "model", None)
    if model is not None:
        for attr in ("graph_converter", "potential"):
            obj = getattr(model, attr, None)
            if obj is not None:
                objects.append(obj)
    return objects


def _m3gnet_key_error_message(
    exc: KeyError,
    model_label: str | None,
    supported_elements: Any,
) -> str:
    element = _key_error_value(exc)
    model = model_label or "unknown"
    supported = _format_supported_elements(supported_elements)
    if supported:
        return f"MatGL model {model} does not support element {element}. Supported elements: {supported}"
    return (
        f"MatGL model {model} failed while mapping element {element}. "
        "Supported elements could not be determined from the loaded model."
    )


def _key_error_value(exc: KeyError) -> str:
    if exc.args:
        return str(exc.args[0])
    return str(exc)


def _format_supported_elements(elements: Any) -> str | None:
    if not elements:
        return None
    try:
        return ", ".join(str(element) for element in elements)
    except TypeError:
        return str(elements)


def m3gnet_static_smoke(cif_path: str | Path | None = None) -> dict[str, Any]:
    """Run a tiny MatGL/M3GNet static prediction for diagnostics."""

    try:
        from pymatgen.core import Lattice, Structure
        from pymatgen.io.ase import AseAtomsAdaptor
        import matgl
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}

    try:
        if cif_path:
            structure = Structure.from_file(str(cif_path))
        else:
            structure = Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
        potential, model_label = _load_m3gnet_potential(
            matgl,
            model_name=os.environ.get("SCA_M3GNET_MODEL"),
            pretrained=os.environ.get("SCA_M3GNET_PRETRAINED"),
        )
        supported_elements = _matgl_supported_elements(potential)
        calculator = _m3gnet_calculator_from_potential(potential)
        atoms = AseAtomsAdaptor.get_atoms(structure)
        atoms.calc = calculator
        energy = float(atoms.get_potential_energy())
        forces_max = _extract_forces_max({"forces": atoms.get_forces()})
        return {
            "ok": True,
            "matgl_version": getattr(matgl, "__version__", None),
            "model": model_label,
            "num_atoms": len(atoms),
            "energy": energy,
            "energy_per_atom": energy / len(atoms),
            "forces_max": forces_max,
            "supported_elements": supported_elements,
        }
    except KeyError as exc:
        return {
            "ok": False,
            "matgl_version": getattr(matgl, "__version__", None),
            "error_type": type(exc).__name__,
            "error_message": _m3gnet_key_error_message(
                exc,
                locals().get("model_label"),
                locals().get("supported_elements"),
            ),
        }
    except Exception as exc:
        return {
            "ok": False,
            "matgl_version": getattr(matgl, "__version__", None),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }


def _load_mace_calculator(
    model_path: str | None,
    pretrained: str | None,
):
    try:
        from mace.calculators import MACECalculator, mace_mp
    except Exception:
        try:
            from mace.calculators import MACECalculator
        except Exception as exc:
            raise ModuleNotFoundError("MACE calculator APIs are unavailable") from exc
        mace_mp = None

    device = os.environ.get("SCA_MLIP_DEVICE", "cpu")
    if model_path:
        path = Path(model_path)
        if not path.is_file():
            raise RuntimeError(f"SCA_MACE_MODEL does not point to an existing file: {model_path}")
        return MACECalculator(model_paths=str(path), device=device), str(path)
    if mace_mp is None:
        raise RuntimeError("MACE pretrained loader mace_mp is unavailable; set SCA_MACE_MODEL instead")
    keyword = pretrained or "medium"
    return mace_mp(model=keyword, device=device), f"pretrained:{keyword}"


def _load_sevennet_calculator(
    model_path: str | None,
    pretrained: str | None,
):
    try:
        from sevenn.sevennet_calculator import SevenNetCalculator
    except Exception as exc:
        raise ModuleNotFoundError("SevenNet calculator API is unavailable") from exc

    device = os.environ.get("SCA_MLIP_DEVICE", "cpu")
    if model_path:
        path = Path(model_path)
        if not path.is_file():
            raise RuntimeError(f"SCA_SEVENNET_MODEL does not point to an existing file: {model_path}")
        return SevenNetCalculator(str(path), device=device), str(path)
    keyword = pretrained or "7net-0"
    return SevenNetCalculator(keyword, device=device), f"pretrained:{keyword}"


def _mlip_result(
    name: str,
    prefix: str,
    ok: bool,
    summary: str,
    error_message: str | None,
    error_type: str | None,
    skipped: bool = False,
    model: str | None = None,
    energy_per_atom: float | None = None,
    forces_max: float | None = None,
    forces_mean: float | None = None,
    stress_norm: float | None = None,
    details: dict[str, Any] | None = None,
) -> BenchmarkEvaluatorResult:
    return BenchmarkEvaluatorResult(
        name=name,
        ok=ok,
        skipped=skipped,
        model=model,
        summary=summary,
        metrics={
            f"{prefix}_ok": ok,
            f"{prefix}_model": model,
            f"{prefix}_energy_per_atom": energy_per_atom,
            f"{prefix}_forces_max": forces_max,
            f"{prefix}_forces_mean": forces_mean,
            f"{prefix}_stress_norm": stress_norm,
            f"{prefix}_error": error_message,
        },
        flags={f"{prefix}_ok": ok},
        details=details or {},
        error_type=error_type,
        error_message=error_message,
    )


def _float_or_none(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
