"""Freeze the balanced Paper 1 SPP ablation subset before ablation execution."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


ABlation_VERSION = "paper1_spp_ablation_v1"
PER_FAMILY = 5


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def select_balanced(targets: Sequence[Mapping[str, Any]], per_family: int = PER_FAMILY) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for target in targets:
        grouped[str(target["family"])].append(target)
    selected: list[dict[str, Any]] = []
    for family in sorted(grouped):
        candidates = sorted(grouped[family], key=lambda row: str(row["row_id"]))
        selected.extend(dict(row) for row in candidates[:per_family])
    return selected


def freeze(*, benchmark_freeze: Path, runner_path: Path, config_path: Path, output_root: Path) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"ablation freeze already exists: {output_root}")
    benchmark = json.loads(benchmark_freeze.read_text(encoding="utf-8"))
    selected = select_balanced(benchmark["targets"])
    family_counts = dict(Counter(str(item["family"]) for item in selected))
    if len(selected) != PER_FAMILY * len(family_counts):
        raise ValueError("every frozen family must supply the balanced per-family count")
    payload = {
        "schema_version": "paper1_spp_ablation_freeze.v1",
        "ablation_version": ABlation_VERSION,
        "source_benchmark_version": benchmark["benchmark_version"],
        "source_benchmark_freeze": str(benchmark_freeze.resolve()),
        "source_benchmark_freeze_sha256": sha256_file(benchmark_freeze),
        "selection_rule": "stable lexical row_id order; first five targets per frozen family",
        "selected_before_ablation_execution": True,
        "selected_count": len(selected), "family_counts": family_counts,
        "conditions": {
            "A_PROXIMITY_ONLY": {
                "status": "NOT_SUPPORTED_BY_FROZEN_SOLVER",
                "reason": (
                    "csv_workflow_v1 and the native QLIP request require spp_energy guidance; "
                    "no mathematically honest no-SPP objective is exposed, so no fake baseline is run."
                ),
            },
            "B_GLOBAL_REGULATOR_ONLY": {
                "status": "SUPPORTED",
                "request_spp_mode": "disabled",
                "qlip_representation": "REGULATOR_AS_PRIMARY_WEIGHTED",
            },
            "C_RETRIEVAL_CONDITIONED_PLUS_REGULATOR": {
                "status": "SUPPORTED_PRIMARY_METHOD",
                "request_spp_mode": "enabled",
                "source": "frozen primary benchmark outputs",
            },
        },
        "controlled_variables": {
            "target": "identical frozen row",
            "cell": "reuse persisted primary dynamic_cell payload",
            "grid": [4, 4, 4], "solver_time_limit_s": 300, "solver_threads": 1,
            "solver_mip_gap": 0.0, "random_seed": 0, "proximity_scale": 1.0,
            "target_exclusion": "identical primary SPP evidence bundle",
        },
        "scientific_source_hashes": {
            "workflow_runner": sha256_file(runner_path),
            "workflow_config": sha256_file(config_path),
            "freeze_builder": sha256_file(Path(__file__)),
        },
        "targets": selected,
    }
    payload["freeze_payload_sha256"] = canonical_hash(payload)
    output_root.mkdir(parents=True)
    (output_root / "FROZEN_SPP_ABLATION_MANIFEST.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Paper 1 SPP ablation freeze", "",
        f"Subset: {len(selected)} targets ({PER_FAMILY} per family), selected by frozen row ID before ablation execution.", "",
        "Condition B uses the existing canonical `request_spp_mode=disabled` path, making the frozen "
        "global regulator the complete weighted SPP objective. Condition C reuses the primary method. "
        "Condition A is not executed because the frozen solver exposes no honest no-SPP objective.", "",
        "All target, cell, grid, proximity, exclusion, timeout, thread, gap, and seed settings are fixed.",
    ]
    (output_root / "SPP_ABLATION_FREEZE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--benchmark-freeze", type=Path,
        default=root / "artifacts" / "paper1_spp_positive_domain" / "freeze_v1" / "FROZEN_BENCHMARK_MANIFEST.json",
    )
    parser.add_argument("--runner", type=Path, default=root / "src" / "sok_llm_orchestrator" / "workflow" / "runner.py")
    parser.add_argument("--config", type=Path, default=root / "config" / "final_workflow_v1.json")
    parser.add_argument(
        "--output-root", type=Path,
        default=root / "artifacts" / "paper1_spp_positive_domain" / "ablation_freeze_v1",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = freeze(
        benchmark_freeze=args.benchmark_freeze.resolve(), runner_path=args.runner.resolve(),
        config_path=args.config.resolve(), output_root=args.output_root.resolve(),
    )
    print(json.dumps({"status": "FROZEN", "selected_count": payload["selected_count"], "family_counts": payload["family_counts"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
