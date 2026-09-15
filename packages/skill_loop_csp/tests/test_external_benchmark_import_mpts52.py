from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.bench.external import import_external_dataset


def _prepare_raw_layout(root: Path, dataset: str) -> None:
    raw = root / "benchmarks" / "external" / dataset / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (raw / f"{split}.lmdb").write_bytes(b"")


def test_external_benchmark_import_mpts52(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    _prepare_raw_layout(workdir, "mpts_52")

    def _fake_iter(path: Path) -> list[tuple[str, dict[str, object]]]:
        return [
            (
                "m0",
                {
                    "metadata": {"identifier": f"{path.stem}-m0", "formula": "Na3Zr2Si2PO12"},
                    # intentionally no CIF to force placeholder fallback
                },
            )
        ]

    monkeypatch.setattr("sok_llm_orchestrator.bench.external._iter_lmdb_records", _fake_iter)
    summary = import_external_dataset(dataset="mpts_52", repo_root=workdir)

    assert summary["dataset"] == "mpts_52"
    val_path = Path(summary["normalized_split_paths"]["val"])
    row = json.loads(val_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["benchmark_dataset"] == "mpts_52"
    assert row["composition"] == "Na3Zr2Si2PO12"
    assert "source_cif_unavailable_in_lmdb_record" in row["cif"]
    assert row["case_id"].startswith("mpts_52_val_")
