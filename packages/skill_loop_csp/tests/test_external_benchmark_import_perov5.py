from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.bench.external import import_external_dataset


def _prepare_raw_layout(root: Path, dataset: str) -> None:
    raw = root / "benchmarks" / "external" / dataset / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (raw / f"{split}.lmdb").write_bytes(b"")


def test_external_benchmark_import_perov5(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    _prepare_raw_layout(workdir, "perov_5")

    def _fake_iter(path: Path) -> list[tuple[str, dict[str, object]]]:
        return [
            (
                "a",
                {
                    "ids": f"{path.stem}-a",
                    "atomic_numbers": [56, 22, 8, 8, 8],  # BaTiO3
                    "cell": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
                    "pos": [[0.0, 0.0, 0.0], [2.0, 2.0, 2.0], [2.0, 2.0, 0.0], [2.0, 0.0, 2.0], [0.0, 2.0, 2.0]],
                },
            )
        ]

    monkeypatch.setattr("sok_llm_orchestrator.bench.external._iter_lmdb_records", _fake_iter)
    summary = import_external_dataset(dataset="perov_5", repo_root=workdir)

    assert summary["dataset"] == "perov_5"
    assert summary["split_counts"]["test"] == 1
    test_path = Path(summary["normalized_split_paths"]["test"])
    row = json.loads(test_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["benchmark_dataset"] == "perov_5"
    assert row["split"] == "test"
    assert row["composition"] in {"BaO3Ti", "BaTiO3"}
    assert isinstance(row["cif"], str) and row["cif"]
    assert isinstance(row["source_metadata"]["reference_cif_signature"], str)
