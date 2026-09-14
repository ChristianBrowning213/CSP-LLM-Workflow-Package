import json
import os
from typing import Any, Dict, Optional

from .audit_log import fetch_audit_bundle


def _apply_export_policy(bundle: Dict[str, Any]) -> Dict[str, Any]:
    evidence = bundle.get("evidence", {})
    if not evidence or "evidence" not in evidence:
        return bundle

    structures = evidence["evidence"].get("structures", [])
    redacted_structures = []
    for item in structures:
        provenance = item.get("provenance", {})
        allow_export = provenance.get("allow_export")
        if allow_export in (0, False):
            redacted_structures.append(
                {
                    "structure_id": item.get("structure_id"),
                    "provenance": provenance,
                    "redacted": True,
                }
            )
        else:
            redacted_structures.append(item)

    evidence["evidence"]["structures"] = redacted_structures
    bundle["evidence"] = evidence
    return bundle


def export_run(*, db_path: Optional[str], run_id: str, out_path: str) -> str:
    bundle = fetch_audit_bundle(run_id, db_path)
    bundle = _apply_export_policy(bundle)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)
    return out_path
