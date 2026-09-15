"""Validate final paper archive relationships and required contents."""

from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_final_results_v1"
FIGURES = ROOT / "figures" / "paper_final_results_v1"
RUNS = ROOT / "runs" / "paper_final_results_v1"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle: return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest(); return digest


def main() -> int:
    manifest = rows(OUT / "01_manifests" / "FINAL_WORKFLOW_ROW_MANIFEST.csv")
    abstentions = rows(OUT / "01_manifests" / "FINAL_ABSTENTION_MANIFEST.csv")
    mapping = rows(OUT / "01_manifests" / "FINAL_ROW_TO_UNIQUE_STRUCTURE_MAP.csv")
    unique = rows(OUT / "01_manifests" / "FINAL_UNIQUE_STRUCTURE_MANIFEST.csv")
    initial = rows(OUT / "03_sca" / "FINAL_SCA_INITIAL_RESULTS.csv")
    static = rows(OUT / "03_sca" / "FINAL_STATIC_MLIP_RESULTS.csv")
    relax = rows(OUT / "03_sca" / "FINAL_RELAXATION_RESULTS.csv")
    post = rows(OUT / "03_sca" / "FINAL_SCA_POST_RELAX_RESULTS.csv")
    verdicts = rows(OUT / "04_acceptance" / "FINAL_UNIQUE_STRUCTURE_VERDICTS.csv")
    assert len(manifest) == 34 and len({r["final_row_id"] for r in manifest}) == 34
    assert len(abstentions) == 1 and abstentions[0]["abstention_id"] == "E4_A1" and abstentions[0]["generated"] == "False"
    assert len(mapping) == 34 and {r["final_row_id"] for r in mapping} == {r["final_row_id"] for r in manifest}
    assert len(unique) == 24 and len({r["unique_structure_id"] for r in unique}) == 24
    assert {r["unique_structure_id"] for r in mapping} == {r["unique_structure_id"] for r in unique}
    for table in (initial, static, relax, post, verdicts):
        assert len(table) == 24 and {r["unique_structure_id"] for r in table} == {r["unique_structure_id"] for r in unique}
    for row in manifest:
        path = Path(row["generated_cif_path"]); assert path.is_file() and sha256(path) == row["expected_cif_sha256"]
    for row in relax:
        if row["relaxation_status"] == "PASS":
            path = Path(row["relaxed_cif_path"]); assert path.is_file() and sha256(path) == row["relaxed_cif_sha256"]
    aggregate = {r["metric"]: r for r in rows(OUT / "07_tables" / "FINAL_AGGREGATE_RESULTS.csv")}
    assert aggregate["workflow_rows"]["numerator"] == "34"
    assert aggregate["raw_hash_unique"]["numerator"] == "24"
    assert aggregate["structurematcher_unique"]["numerator"] == "24"
    stems = ["final_campaign_accounting","final_validation_funnel","final_relaxation_outcomes","final_symmetry_topology_retention","final_mlip_disagreement","final_reference_matching","final_nasicon_demonstration","final_traceability_completeness"]
    for stem in stems:
        for suffix in ("png","pdf","svg"):
            path = FIGURES / f"{stem}.{suffix}"; assert path.is_file() and path.stat().st_size > 100
    required_dirs = ["00_README","01_MANIFESTS","02_INITIAL_CIFS","03_RELAXED_CIFS","04_SCA_RESULTS","05_TRACES_AND_CERTIFICATES","06_TABLES","07_FIGURES","08_MANUSCRIPT_INSERTS","09_CLAIMS_AND_LIMITATIONS","10_REPRODUCIBILITY"]
    archive_root = OUT / "PAPER_READY_ARCHIVE"
    for name in required_dirs: assert (archive_root / name).is_dir()
    for name in ("retrieval","spp","solver","provenance"):
        directory = archive_root / "05_TRACES_AND_CERTIFICATES" / name
        assert directory.is_dir() and any(path.is_file() for path in directory.rglob("*")), f"empty trace archive: {name}"
    forbidden_extensions = {".pt", ".pth", ".ckpt", ".onnx", ".h5"}
    assert not [p for p in archive_root.rglob("*") if p.suffix.lower() in forbidden_extensions]
    zip_path = OUT / "LLM_CSP_PAPER_READY_RESULTS_V1.zip"; hash_path = OUT / "LLM_CSP_PAPER_READY_RESULTS_V1.sha256"
    assert zip_path.is_file() and hash_path.is_file()
    assert hash_path.read_text(encoding="utf-8").split()[0] == sha256(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist(); assert names and all(name.startswith("PAPER_READY_ARCHIVE/") for name in names)
        assert "PAPER_READY_ARCHIVE/10_REPRODUCIBILITY/FINAL_OUTPUT_HASH_MANIFEST.csv" in names
    protected = rows(OUT / "01_manifests" / "FINAL_PRE_RUN_HASH_CHECK.csv")
    assert len(protected) == 1985 and all(r["status"] == "PASS" for r in protected)
    print(json.dumps({"workflow_rows":34,"unique_structures":24,"archive_files":sum(p.is_file() for p in archive_root.rglob('*')),"figures":24,"protected_checks":1985,"status":"PASS"},sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
