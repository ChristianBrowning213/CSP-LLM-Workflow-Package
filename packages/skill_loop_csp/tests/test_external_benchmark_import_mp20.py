from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.bench.external import import_external_dataset


def _prepare_raw_layout(root: Path, dataset: str) -> None:
    raw = root / "benchmarks" / "external" / dataset / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (raw / f"{split}.lmdb").write_bytes(b"")


def test_external_benchmark_import_mp20(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    _prepare_raw_layout(workdir, "mp_20")

    def _fake_iter(path: Path) -> list[tuple[str, dict[str, object]]]:
        return [
            (
                "0",
                {
                    "identifier": f"{path.stem}-0",
                    "formula": "TiO2",
                    "cif": "data_tio2\n_chemical_formula_sum 'TiO2'\n",
                },
            ),
            (
                "1",
                {
                    "identifier": f"{path.stem}-1",
                    "formula": "BaTiO3",
                    "cif": "data_batio3\n_chemical_formula_sum 'BaTiO3'\n",
                },
            ),
        ]

    monkeypatch.setattr("sok_llm_orchestrator.bench.external._iter_lmdb_records", _fake_iter)
    summary = import_external_dataset(dataset="mp_20", repo_root=workdir)

    assert summary["dataset"] == "mp_20"
    assert summary["split_counts"] == {"train": 2, "val": 2, "test": 2}

    train_path = Path(summary["normalized_split_paths"]["train"])
    lines = [json.loads(line) for line in train_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["benchmark_dataset"] == "mp_20"
    assert lines[0]["split"] == "train"
    assert lines[0]["composition"] == "TiO2"
    assert "cif" in lines[0] and isinstance(lines[0]["cif"], str) and lines[0]["cif"]
    assert "source_metadata" in lines[0]
