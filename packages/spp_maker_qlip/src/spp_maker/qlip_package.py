"""Helpers for QLIP handoff package payloads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from spp_maker.publish import load_json, write_json

PACKAGE_SCHEMA_VERSION = "SPPMakerQLIPPackage.v1"


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def compute_content_hash(*, params_payload: dict[str, Any], cif_names: Sequence[str]) -> str:
    """Return deterministic hash over params payload + selected CIF list."""
    basis = {
        "params": params_payload,
        "cif_list": [str(name) for name in cif_names],
    }
    return hashlib.sha256(_json_bytes(basis)).hexdigest()


def build_package_payload(
    *,
    run_id: str,
    name: str,
    created_at_utc: str,
    content_hash: str,
    lambda_used: float,
    convention: str,
    fit_method: str,
    calibration_method: str,
    corpus: dict[str, Any],
    run_paths: dict[str, str],
    final_paths: dict[str, str],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Build normalized package.json payload."""
    package_id = f"{run_id}_{content_hash[:8]}"
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": package_id,
        "run_id": run_id,
        "name": name,
        "created_at_utc": created_at_utc,
        "content_hash": content_hash,
        "lambda_used": float(lambda_used),
        "convention": str(convention),
        "fit_method": str(fit_method),
        "calibration_method": str(calibration_method),
        "corpus": corpus,
        "paths": {
            "run": run_paths,
            "final_bundle": final_paths,
        },
        "provenance": provenance,
    }


def write_package_json(path: Path, payload: dict[str, Any]) -> None:
    """Write package payload deterministically."""
    write_json(path, payload)


def read_package_json(path: Path) -> dict[str, Any]:
    """Load package payload."""
    return load_json(path)


def render_python_snippet(*, spp_root: str = "./spp_root") -> str:
    """Return a copy/paste QLIP Python snippet."""
    lines = [
        "from qlip.spp import SPPCollection",
        "",
        f'spp_dir = "{spp_root}"',
        "collection = SPPCollection(spp_dir)",
        "collection.load(task.pairs)",
        "allocation.spp_collection = collection",
    ]
    return "\n".join(lines) + "\n"
