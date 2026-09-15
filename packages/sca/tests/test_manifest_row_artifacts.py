from pathlib import Path

import pandas as pd

from sca.benchmark import benchmark_manifest
from sca.spp.schema import SppArtifact


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_valid.cif"


def _write_spp(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        SppArtifact(
            species_pairs={
                "Cl--Na": {"bin_edges": [0.0, 8.0], "penalties": [1.0]},
            },
            cutoff_policy={"cutoff": 8.0},
            provenance={"source": marker},
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )


def _run(manifest: Path, global_spp: Path | None = None):
    return benchmark_manifest(
        manifest,
        evaluator_names=["spp"],
        spp_artifact=global_spp,
    )


def test_two_manifest_rows_can_use_distinct_spp_artifacts(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write_spp(first, "first")
    _write_spp(second, "second")
    pd.DataFrame(
        [
            {"cif_path": str(FIXTURE.resolve()), "spp_artifact": str(first)},
            {"cif_path": str(FIXTURE.resolve()), "spp_artifact": str(second)},
        ]
    ).to_csv(tmp_path / "manifest.csv", index=False)

    records = _run(tmp_path / "manifest.csv")

    assert [r.evaluator_outputs["spp"].details["artifact_path"] for r in records] == [
        str(first),
        str(second),
    ]


def test_global_spp_artifact_remains_backward_compatible(tmp_path: Path) -> None:
    global_spp = tmp_path / "global.json"
    _write_spp(global_spp, "global")
    pd.DataFrame([{"cif_path": str(FIXTURE.resolve())}]).to_csv(
        tmp_path / "manifest.csv", index=False
    )

    record = _run(tmp_path / "manifest.csv", global_spp)[0]

    assert record.evaluator_outputs["spp"].details["artifact_path"] == str(global_spp)


def test_row_spp_artifact_overrides_global_artifact(tmp_path: Path) -> None:
    row_spp = tmp_path / "row.json"
    global_spp = tmp_path / "global.json"
    _write_spp(row_spp, "row")
    _write_spp(global_spp, "global")
    pd.DataFrame(
        [{"cif_path": str(FIXTURE.resolve()), "spp_artifact": str(row_spp)}]
    ).to_csv(tmp_path / "manifest.csv", index=False)

    record = _run(tmp_path / "manifest.csv", global_spp)[0]

    assert record.evaluator_outputs["spp"].details["artifact_path"] == str(row_spp)


def test_missing_spp_artifact_is_structured_skip(tmp_path: Path) -> None:
    pd.DataFrame([{"cif_path": str(FIXTURE.resolve())}]).to_csv(
        tmp_path / "manifest.csv", index=False
    )

    result = _run(tmp_path / "manifest.csv")[0].evaluator_outputs["spp"]

    assert result.ok is False
    assert result.skipped is True
    assert result.error_message == "spp_artifact was not provided"


def test_row_artifact_paths_resolve_relative_to_manifest(tmp_path: Path) -> None:
    row_spp = tmp_path / "artifacts" / "row.json"
    bundle = tmp_path / "bundles" / "row"
    _write_spp(row_spp, "relative")
    bundle.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "cif_path": str(FIXTURE.resolve()),
                "spp_artifact": "artifacts/row.json",
                "hull_reference_path": "references/hull.json",
                "traceable_bundle_dir": "bundles/row",
                "topology_policy": "ROCKSALT",
            }
        ]
    ).to_csv(tmp_path / "manifest.csv", index=False)

    record = _run(tmp_path / "manifest.csv")[0]
    row = record.to_row()

    assert record.evaluator_outputs["spp"].details["artifact_path"] == str(row_spp.resolve())
    assert row["hull_reference_path"] == str((tmp_path / "references" / "hull.json").resolve())
    assert row["traceable_bundle_dir"] == str(bundle.resolve())
    assert row["topology_policy"] == "ROCKSALT"
