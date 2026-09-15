"""Export normalized final-pair provenance from a completed SPP package audit."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sok_llm_orchestrator.workflow.spp_package_audit import final_curve_provenance_hash


FIELDS = (
    "experiment_id", "family", "formula", "pair", "local_observation_count",
    "local_structure_count", "local_curve_valid", "global_curve_valid", "local_weight",
    "global_weight", "final_source", "request_curve_hash", "global_curve_hash",
    "final_curve_hash", "final_curve_hash_kind",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", type=Path, required=True)
    args = parser.parse_args()
    audit_root = args.audit_root.resolve()
    rows = []
    for path in sorted(audit_root.glob("targets/*/*/spp_package_audit.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = payload["summary_row"]
        for pair in payload["package_audit"]["pair_diagnostics"]:
            source = str(pair["intended_final_source"])
            request_hash = pair.get("request_pot_sha256")
            global_hash = pair.get("regulator_pot_sha256")
            local_weight = float(pair["weight_local"])
            global_weight = float(pair["weight_global"])
            final_hash, final_hash_kind = final_curve_provenance_hash(
                source=source, request_hash=request_hash, global_hash=global_hash,
                local_weight=local_weight, global_weight=global_weight,
            )
            rows.append({
                "experiment_id": summary["experiment_id"],
                "family": summary["family"],
                "formula": summary["formula"],
                "pair": pair["required_pair"],
                "local_observation_count": pair["local_observations"],
                "local_structure_count": pair["local_structure_count"],
                "local_curve_valid": pair["local_curve_exists"] and pair["local_curve_quality"] == "usable",
                "global_curve_valid": pair["global_curve_valid"],
                "local_weight": local_weight,
                "global_weight": global_weight,
                "final_source": source,
                "request_curve_hash": request_hash,
                "global_curve_hash": global_hash,
                "final_curve_hash": final_hash,
                "final_curve_hash_kind": final_hash_kind,
            })
    output = audit_root / "SPP_FINAL_PAIR_PROVENANCE.csv"
    temporary = output.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output)
    summary = {
        "pair_rows": len(rows),
        "rows_with_final_curve_hash": sum(bool(row["final_curve_hash"]) for row in rows),
        "unsupported_rows": sum(row["final_source"] == "unsupported" for row in rows),
        "output": str(output),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
