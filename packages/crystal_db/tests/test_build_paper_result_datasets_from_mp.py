import json
from pathlib import Path

import pytest

from scripts import build_paper_result_datasets_from_mp as builder


def test_load_mp_api_key_supports_hyphenated_env_alias(tmp_path, monkeypatch):
    monkeypatch.delenv("MP_API_KEY", raising=False)
    monkeypatch.delenv("MP-API-KEY", raising=False)
    monkeypatch.delenv("MATERIALS_PROJECT_API_KEY", raising=False)
    (tmp_path / ".env").write_text("MP-API-KEY=secret-hyphen\n", encoding="utf-8")

    assert builder.load_mp_api_key(tmp_path) == "secret-hyphen"


def test_load_mp_api_key_prefers_normalized_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "secret-normal")
    (tmp_path / ".env").write_text("MP-API-KEY=secret-hyphen\n", encoding="utf-8")

    assert builder.load_mp_api_key(tmp_path) == "secret-normal"


def test_no_download_writes_blocked_manifest_without_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "super-secret-value")
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    out_root = tmp_path / "datasets"
    db_out = tmp_path / "db"
    db_out.mkdir()

    code = builder.main(
        [
            "--dataset",
            "common_families",
            "--out-root",
            str(out_root),
            "--db-out",
            str(db_out),
            "--no-download",
            "--skip-ingest",
            "--skip-embeddings",
            "--skip-seq",
            "--skip-retrieval-smoke",
        ]
    )

    assert code == 0
    manifest_text = (out_root / "common_families" / "manifest.jsonl").read_text(encoding="utf-8")
    assert "super-secret-value" not in manifest_text
    rows = [json.loads(line) for line in manifest_text.splitlines() if line.strip()]
    assert rows
    assert {row["status"] for row in rows} == {"BLOCKED"}


def test_dataset_card_contains_required_fields_in_no_download(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "secret")
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    out_root = tmp_path / "datasets"
    db_out = tmp_path / "db"
    db_out.mkdir()

    builder.main(
        [
            "--dataset",
            "halide_perovskite",
            "--out-root",
            str(out_root),
            "--db-out",
            str(db_out),
            "--no-download",
            "--skip-ingest",
            "--skip-embeddings",
            "--skip-seq",
            "--skip-retrieval-smoke",
        ]
    )

    card = json.loads((out_root / "halide_perovskite" / "dataset_card.json").read_text(encoding="utf-8"))
    for key in ("dataset_id", "title", "status", "db_path", "manifest_path", "counts", "target_coverage"):
        assert key in card
    assert card["dataset_id"] == "halide_perovskite"
    assert card["target_coverage"]


def test_unknown_dataset_id_fails_clearly():
    with pytest.raises(SystemExit):
        builder.parse_args(["--dataset", "unknown"])


def test_no_download_does_not_mutate_phase6_db(tmp_path, monkeypatch):
    phase6 = Path("data/phase6_mp_10k.db")
    if not phase6.exists():
        pytest.skip("phase6 fixture DB is not present")
    before = (phase6.stat().st_size, phase6.stat().st_mtime_ns)
    monkeypatch.setenv("MP_API_KEY", "secret")
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    out_root = tmp_path / "datasets"
    db_out = tmp_path / "db"
    db_out.mkdir()

    code = builder.main(
        [
            "--dataset",
            "hard_intent",
            "--out-root",
            str(out_root),
            "--db-out",
            str(db_out),
            "--no-download",
            "--skip-ingest",
            "--skip-embeddings",
            "--skip-seq",
            "--skip-retrieval-smoke",
        ]
    )

    after = (phase6.stat().st_size, phase6.stat().st_mtime_ns)
    assert code == 0
    assert after == before
