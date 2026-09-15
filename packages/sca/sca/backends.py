"""Optional benchmark backend availability checks."""

from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path
from typing import Any


BACKEND_CHECKS = {
    "alignn": {
        "modules": ("alignn",),
        "extra": "alignn",
        "install": "pip install -e .[alignn]",
    },
    "chgnet_static": {
        "modules": ("chgnet",),
        "extra": "chgnet",
        "install": "pip install -e .[chgnet]",
    },
    "m3gnet_static": {
        "modules": ("matgl",),
        "extra": "matgl",
        "install": "pip install -e .[matgl]",
    },
    "mace_static": {
        "modules": ("mace",),
        "extra": "advanced-mlip",
        "install": "pip install -e .[advanced-mlip], then set SCA_MACE_MODEL or SCA_MACE_PRETRAINED.",
        "model_env": "SCA_MACE_MODEL",
        "pretrained_env": "SCA_MACE_PRETRAINED",
    },
    "sevennet_static": {
        "modules": ("sevenn",),
        "extra": "advanced-mlip",
        "install": "pip install -e .[advanced-mlip], then set SCA_SEVENNET_MODEL or SCA_SEVENNET_PRETRAINED.",
        "model_env": "SCA_SEVENNET_MODEL",
        "pretrained_env": "SCA_SEVENNET_PRETRAINED",
    },
}


def verify_optional_backends(functional: bool = False) -> list[dict[str, Any]]:
    """Return deterministic optional-backend readiness records without loading models."""

    rows = []
    for name in sorted(BACKEND_CHECKS):
        check = BACKEND_CHECKS[name]
        modules = tuple(check["modules"])
        missing_modules = [module for module in modules if find_spec(module) is None]
        model_env = check.get("model_env")
        pretrained_env = check.get("pretrained_env")
        model_path = os.environ.get(str(model_env)) if model_env else None
        pretrained_name = os.environ.get(str(pretrained_env)) if pretrained_env else None
        model_path_exists = bool(model_path and Path(model_path).is_file())
        model_ready = True if model_env is None else bool(model_path_exists or pretrained_name)
        ready = not missing_modules and model_ready
        notes = []
        if missing_modules:
            notes.append("missing modules: " + ", ".join(missing_modules))
        if model_env and not model_path and not pretrained_name:
            notes.append(f"{model_env} is not set")
        elif model_env and model_path and not model_path_exists:
            notes.append(f"{model_env} does not point to an existing file")
        if pretrained_env and not pretrained_name and not model_path_exists:
            notes.append(f"{pretrained_env} is not set")
        if missing_modules:
            readiness_status = "SKIPPED_DEPENDENCY"
        elif not model_ready:
            readiness_status = "SKIPPED_MODEL"
        else:
            readiness_status = "READY"
        row = {
            "backend": name,
            "status": readiness_status,
            "ready": ready,
            "modules": ",".join(modules),
            "missing_modules": ",".join(missing_modules),
            "extra": check.get("extra"),
            "model_env": model_env,
            "model_path": model_path,
            "model_path_exists": model_path_exists if model_env else None,
            "pretrained_env": pretrained_env,
            "pretrained_name": pretrained_name,
            "install_hint": check["install"],
            "notes": "; ".join(notes),
        }
        if functional and name == "m3gnet_static" and not missing_modules:
            smoke = _functional_check_m3gnet()
            row["functional_ok"] = smoke.get("ok")
            row["functional_error_type"] = smoke.get("error_type")
            row["functional_error_message"] = smoke.get("error_message")
            row["functional_model"] = smoke.get("model")
            row["functional_energy_per_atom"] = smoke.get("energy_per_atom")
            row["ready"] = bool(ready and smoke.get("ok"))
            if not smoke.get("ok"):
                row["status"] = "FAILED_INITIALIZATION"
        elif functional:
            row["functional_ok"] = None
            row["functional_error_type"] = None
            row["functional_error_message"] = None
            row["functional_model"] = None
            row["functional_energy_per_atom"] = None
        rows.append(row)
    return rows


def _functional_check_m3gnet() -> dict[str, Any]:
    from sca.evaluators.mlip import m3gnet_static_smoke

    return m3gnet_static_smoke()
