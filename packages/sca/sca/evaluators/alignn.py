"""ALIGNN evaluator wrapper."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pymatgen.core import Structure

from sca.evaluators.base import CrystalEvaluator, StructurePredictor
from sca.schemas import AlignnResult, EvaluatorResult


DEFAULT_ALIGNN_MODEL = "jv_formation_energy_peratom_alignn"
DEFAULT_CRYSTALLM_ALIGNN_MODEL = "mp_e_form_alignn"


class AlignnEvaluator(CrystalEvaluator):
    """Predict formation energy per atom with an ALIGNN model.

    A predictor callable can be injected for tests or internal deployments. Without one, the
    evaluator first tries a small set of known Python API entry points, then an optional
    subprocess fallback configured with ``SCA_ALIGNN_COMMAND``.
    """

    name = "alignn"

    def __init__(
        self,
        model_name: str = DEFAULT_ALIGNN_MODEL,
        predictor: StructurePredictor | None = None,
        command_template: str | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self.model_name = model_name
        self._predictor = predictor
        self._command_template = command_template or os.environ.get("SCA_ALIGNN_COMMAND")
        self._timeout_seconds = timeout_seconds

    def evaluate(self, structure: Structure, input_path: str) -> EvaluatorResult:
        try:
            value = self._predict(structure, input_path)
        except Exception as exc:
            return EvaluatorResult(
                ok=False,
                model=self.model_name,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        return EvaluatorResult(
            ok=True,
            model=self.model_name,
            values={"formation_energy_per_atom": float(value)},
        )

    def _predict(self, structure: Structure, input_path: str) -> float:
        if self._predictor is not None:
            return float(self._predictor(structure, input_path))

        try:
            return self._predict_with_python_api(structure, input_path)
        except Exception as api_exc:
            if self._command_template:
                try:
                    return self._predict_with_subprocess(structure)
                except Exception as subprocess_exc:
                    raise RuntimeError(
                        f"ALIGNN Python API failed ({api_exc}); subprocess fallback failed ({subprocess_exc})"
                    ) from subprocess_exc
            raise RuntimeError(
                "ALIGNN prediction is unavailable. Install alignn and its pretrained prediction "
                "dependencies, inject a predictor, or set SCA_ALIGNN_COMMAND."
            ) from api_exc

    def _predict_with_python_api(self, structure: Structure, input_path: str) -> float:
        candidates = [
            ("alignn.pretrained", "get_prediction"),
            ("alignn.pretrained", "predict_structure"),
            ("alignn.scripts.pretrained", "get_prediction"),
        ]
        errors: list[str] = []
        for module_name, function_name in candidates:
            try:
                module = __import__(module_name, fromlist=[function_name])
                function = getattr(module, function_name)
            except Exception as exc:
                errors.append(f"{module_name}.{function_name}: {exc}")
                continue

            try:
                prediction = self._call_alignn_function(function, structure, input_path)
                return _extract_scalar(prediction)
            except Exception as exc:
                errors.append(f"{module_name}.{function_name}: {exc}")

        raise RuntimeError("No compatible ALIGNN Python API entry point succeeded: " + "; ".join(errors))

    def _call_alignn_function(self, function: Any, structure: Structure, input_path: str) -> Any:
        try:
            from jarvis.core.atoms import Atoms
        except Exception:
            atoms = None
        else:
            atoms = Atoms.from_pymatgen(structure)

        call_attempts = []
        if atoms is not None:
            call_attempts.extend(
                [
                    lambda: function(atoms=atoms, model_name=self.model_name),
                    lambda: function(atoms, model_name=self.model_name),
                    lambda: function(atoms, self.model_name),
                ]
            )
        call_attempts.extend(
            [
                lambda: function(filename=input_path, model_name=self.model_name),
                lambda: function(input_path, model_name=self.model_name),
                lambda: function(input_path, self.model_name),
            ]
        )

        errors: list[str] = []
        for call in call_attempts:
            try:
                return call()
            except TypeError as exc:
                errors.append(str(exc))
                continue

        raise TypeError("; ".join(errors))

    def _predict_with_subprocess(self, structure: Structure) -> float:
        if not self._command_template:
            raise RuntimeError("No ALIGNN subprocess command configured")

        with tempfile.TemporaryDirectory(prefix="sca-alignn-") as tmp_dir:
            poscar_path = Path(tmp_dir) / "POSCAR"
            structure.to(fmt="poscar", filename=str(poscar_path))
            command = self._command_template.format(input=str(poscar_path), model=self.model_name)
            completed = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                stderr = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(f"ALIGNN subprocess exited {completed.returncode}: {stderr}")
            return _extract_scalar(completed.stdout)


def predict_alignn_formation_energy(
    cif_path: str | Path,
    model_name: str = DEFAULT_CRYSTALLM_ALIGNN_MODEL,
) -> AlignnResult:
    """Predict formation energy per atom for a CIF path, returning structured errors."""

    try:
        structure = Structure.from_file(str(cif_path))
    except Exception as exc:
        return AlignnResult(
            alignn_ok=False,
            alignn_model=model_name,
            alignn_error=f"CIF parse failed before ALIGNN prediction: {type(exc).__name__}: {exc}",
        )

    evaluator = AlignnEvaluator(model_name=model_name)
    result = evaluator.evaluate(structure, str(cif_path))
    if not result.ok:
        return AlignnResult(
            alignn_ok=False,
            alignn_model=model_name,
            alignn_error=result.error_message or result.error_type or "ALIGNN prediction failed",
        )
    return AlignnResult(
        alignn_ok=True,
        alignn_model=model_name,
        formation_energy_per_atom=result.values.get("formation_energy_per_atom"),
    )


def _extract_scalar(prediction: Any) -> float:
    """Extract a scalar prediction from common API or CLI response shapes."""

    if isinstance(prediction, int | float):
        return float(prediction)

    if isinstance(prediction, str):
        text = prediction.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            for token in reversed(text.replace(",", " ").split()):
                try:
                    return float(token)
                except ValueError:
                    continue
            raise ValueError(f"Could not find numeric prediction in ALIGNN output: {text[:200]}")
        return _extract_scalar(parsed)

    if isinstance(prediction, dict):
        for key in (
            "formation_energy_per_atom",
            "prediction",
            "predictions",
            "target",
            "output",
            DEFAULT_ALIGNN_MODEL,
        ):
            if key in prediction:
                return _extract_scalar(prediction[key])

    if isinstance(prediction, list | tuple) and prediction:
        return _extract_scalar(prediction[0])

    raise ValueError(f"Could not extract scalar prediction from {type(prediction).__name__}")
