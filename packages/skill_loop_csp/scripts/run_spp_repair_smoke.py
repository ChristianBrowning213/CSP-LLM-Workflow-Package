"""Run the bounded 3-layered + 3-spinel dmytro_gr_v1 development smoke."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
CRYSTAL = REPO.parent / "Crystal-DB"
OUT = CRYSTAL / "artifacts" / "spp_repair_smoke_dmytro_gr_v1_retrieval_replay"
FROZEN = CRYSTAL / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed" / "frozen_benchmark.json"
sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages  # noqa: E402
from sok_llm_orchestrator.workflow.spp_only_benchmark import (  # noqa: E402
    SPPOnlyBenchmarkPolicy, run_spp_only_benchmark,
)
from spp_maker.pot_io import read_pot_like_qlip  # noqa: E402


def rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


class PersistedRetrievalStages(ProductionWorkflowStages):
    """Replay immutable v4 retrieval records while exercising new downstream code."""

    def __init__(self, selected_ids: set[str]) -> None:
        self.selected_ids = selected_ids

    def retrieve(self, request, task, config, run_root):  # type: ignore[override]
        experiment_id = next(
            item for item in self.selected_ids if str(config.run_id).startswith(item + "-")
        )
        family = "layered" if experiment_id.startswith("layered-") else "spinel"
        source = CRYSTAL / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed" / "results" / "runs" / family / experiment_id / "retrieval" / "results.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["development_replay_provenance"] = {
            "source": str(source.resolve()), "reason": "LM Studio unavailable; exact persisted retrieval replay",
        }
        return payload


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    chosen = []
    for family in ("layered", "spinel"):
        chosen.extend([row for row in frozen["targets"] if row["family"] == family][:3])
    chosen_ids = {row["benchmark_id"] for row in chosen}
    ordered = dict(frozen)
    ordered["targets"] = chosen + [row for row in frozen["targets"] if row["benchmark_id"] not in chosen_ids]
    ordered_path = OUT / "development_smoke_ordered_frozen_copy.json"
    ordered_path.write_text(json.dumps(ordered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = run_spp_only_benchmark(
        frozen_path=ordered_path, crystal_root=CRYSTAL, output_root=OUT,
        policy=SPPOnlyBenchmarkPolicy(cutoff=10.0), resume=True,
        stages=PersistedRetrievalStages(chosen_ids), max_new_targets=6,
    )
    summary = []
    for row in rows:
        run_dir = Path(row["run_directory"])
        manifests = sorted(run_dir.glob("spp/fit_round_*/spp_build_manifest.json"))
        build = json.loads(manifests[-1].read_text(encoding="utf-8")) if manifests else {}
        blend = build.get("blend_manifest", {})
        ratios = []
        for decision in blend.get("pairs", []):
            pair = decision["pair"]
            local_path = run_dir.parent.parent.parent  # placeholder overwritten by manifest paths below
            output_pot = Path(decision["output_pot"])
            local_candidate = output_pot.parents[2] / "local_common_contract" / pair / f"{pair}.POT"
            global_candidate = output_pot.parents[2] / "global_common_contract" / pair / f"{pair}.POT"
            if local_candidate.is_file() and global_candidate.is_file():
                r_local, u_local = read_pot_like_qlip(local_candidate)
                r_global, u_global = read_pot_like_qlip(global_candidate)
                mask = (r_local >= 1.75) & (r_local <= 6.0)
                if np.allclose(r_local, r_global) and rms(u_local[mask]) > 0:
                    ratios.append(float(decision["global_weight"]) * rms(u_global[mask]) / rms(u_local[mask]))
        sca_path = run_dir / "sca" / "result.json"
        sca = json.loads(sca_path.read_text(encoding="utf-8")) if sca_path.is_file() else {}
        summary.append({
            "experiment_id": row["experiment_id"], "family": row["family"], "formula": row["formula"],
            "artifact_contract": "dmytro_gr_v1", "pair_count": len(blend.get("pairs", [])),
            "local_primary_pair_count": sum(str(item.get("mode", "")).startswith("LOCAL_PRIMARY") for item in blend.get("pairs", [])),
            "global_only_pair_count": sum(str(item.get("mode", "")).startswith("GLOBAL_ONLY") for item in blend.get("pairs", [])),
            "effective_global_to_local_rms_ratio_min": min(ratios) if ratios else "",
            "effective_global_to_local_rms_ratio_max": max(ratios) if ratios else "",
            "qlip_status": row["qlip_status"], "runtime_seconds": row.get("qlip_runtime", ""),
            "generated_cif": str((run_dir / "generated" / "candidate.cif").resolve()) if (run_dir / "generated" / "candidate.cif").is_file() else "",
            "sca_status": row["sca_status"], "minimum_distance_A": row["minimum_distance"],
            "density_g_cm3": row["density"], "topology": sca.get("topology_status", ""),
            "final_classification": row["final_classification"], "failure_message": row["failure_message"],
        })
    write_csv(OUT / "SPP_REPAIR_SMOKE_SUMMARY.csv", summary)
    successes = sum(bool(row["generated_cif"]) for row in summary)
    (OUT / "SPP_REPAIR_SMOKE_SUMMARY.md").write_text(
        "# SPP repair development smoke\n\n"
        "This bounded run contains exactly three layered and three spinel targets and uses "
        "`dmytro_gr_v1` with a 10 A cutoff. It replays each target's exact persisted v4 retrieval "
        "record because the LM Studio endpoint was unavailable, while exercising the repaired SPP, "
        "QLIP, and SCA path. It is isolated from the frozen v4 result root and is not a v5 benchmark "
        "or tuning loop.\n\n"
        f"Generated candidates: {successes}/6. Detailed terminal states and geometry/topology fields are in the CSV.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
