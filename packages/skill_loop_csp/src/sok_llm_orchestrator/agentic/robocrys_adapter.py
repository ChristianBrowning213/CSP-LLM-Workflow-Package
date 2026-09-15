from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _base_result(cif_path: Path) -> dict[str, Any]:
    return {
        "robocrys_available": False,
        "description": None,
        "condensed_structure": None,
        "engine": "robocrys",
        "text_view": "robocrys",
        "robocrys_version": None,
        "cif_path": str(cif_path),
        "warnings": [],
        "error": None,
    }


def describe_cif_with_robocrys(
    cif_path: Path,
    strict: bool = False,
    robocrys_python: str | None = None,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Describe a generated CIF with robocrys when the local dependency stack exists.

    The adapter is deliberately non-blocking by default: paper evidence generation
    can record missing robocrys support without converting that into a QLIP or
    visualisation failure.
    """

    path = Path(cif_path)
    result = _base_result(path)
    if not str(path):
        result["error"] = "cif_path_missing"
        if strict:
            raise FileNotFoundError("cif_path_missing")
        return result
    if not path.is_file():
        result["error"] = "no_solution_cif"
        if strict:
            raise FileNotFoundError(str(path))
        return result

    cif_text = path.read_text(encoding="utf-8", errors="ignore")
    textgen_error: str | None = None
    try:
        textgen = importlib.import_module("crystal_db.textgen")
        payload = textgen.generate_text(cif_text=cif_text, engine="robocrys")
        if isinstance(payload, dict) and payload.get("text"):
            result["description"] = str(payload["text"])
            result["robocrys_available"] = True
        elif isinstance(payload, dict) and payload.get("error"):
            textgen_error = str(payload.get("error"))
            result["warnings"].append(f"crystal_db_textgen_error={textgen_error}")
    except Exception as exc:  # noqa: BLE001 - optional adapter, reported in metadata.
        textgen_error = f"{type(exc).__name__}: {exc}"
        result["warnings"].append(f"crystal_db_textgen_unavailable={textgen_error}")

    try:
        robocrys = importlib.import_module("robocrys")
        structure_mod = importlib.import_module("pymatgen.core")
        version = getattr(robocrys, "__version__", None)
        result["robocrys_version"] = str(version) if version is not None else None
        structure = structure_mod.Structure.from_file(str(path))
        condenser = robocrys.StructureCondenser()
        describer = robocrys.StructureDescriber()
        condensed = condenser.condense_structure(structure)
        description = describer.describe(condensed)
        result["condensed_structure"] = condensed
        result["description"] = str(description)
        result["robocrys_available"] = True
        result["error"] = None
    except Exception as exc:  # noqa: BLE001
        direct_error = f"{type(exc).__name__}: {exc}"
        result["warnings"].append(f"direct_robocrys_error={direct_error}")
        if not result["description"]:
            result["error"] = textgen_error or direct_error or "robocrys_unavailable"
            if strict:
                raise RuntimeError(result["error"]) from exc
        elif result["error"] is None:
            result["error"] = None

    if result["description"] and result["error"] in {"engine_unavailable", "robocrys_unavailable"}:
        result["error"] = None
    if not result["description"] and robocrys_python:
        external = _describe_with_external_python(path, robocrys_python, timeout_s=timeout_s)
        if external.get("description"):
            return external
        result["warnings"].append(f"external_robocrys_error={external.get('error') or 'unknown'}")
        if external.get("stdout"):
            result["warnings"].append("external_robocrys_stdout_captured")
        if external.get("stderr"):
            result["warnings"].append("external_robocrys_stderr_captured")
        result["error"] = external.get("error") or result.get("error") or "external_robocrys_failed"
        if strict:
            raise RuntimeError(str(result["error"]))
    if not result["description"] and result["error"] is None:
        result["error"] = textgen_error or "robocrys_unavailable"
        if strict:
            raise RuntimeError(result["error"])
    return result


def _describe_with_external_python(cif_path: Path, robocrys_python: str, *, timeout_s: float) -> dict[str, Any]:
    helper = Path(__file__).with_name("robocrys_external_describe.py")
    result = _base_result(cif_path)
    result["external_python"] = robocrys_python
    result["external_helper"] = str(helper)
    if not Path(robocrys_python).is_file():
        result["error"] = "robocrys_python_missing"
        return result
    try:
        completed = subprocess.run(
            [robocrys_python, str(helper), "--cif", str(cif_path)],
            text=True,
            capture_output=True,
            timeout=float(timeout_s),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        result["error"] = f"external_robocrys_timeout:{exc}"
        return result
    except OSError as exc:
        result["error"] = f"external_robocrys_launch_failed:{type(exc).__name__}: {exc}"
        return result
    result["stdout"] = completed.stdout[-5000:]
    result["stderr"] = completed.stderr[-5000:]
    if completed.returncode != 0:
        result["error"] = f"external_robocrys_returncode:{completed.returncode}"
        return result
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        result["error"] = f"external_robocrys_json_parse_failed:{exc}"
        return result
    if not isinstance(payload, dict):
        result["error"] = "external_robocrys_non_object_json"
        return result
    merged = {**result, **payload}
    merged["external_python"] = robocrys_python
    merged["external_helper"] = str(helper)
    merged["stdout"] = completed.stdout[-5000:]
    merged["stderr"] = completed.stderr[-5000:]
    return merged


__all__ = ["describe_cif_with_robocrys"]
