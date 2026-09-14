import json
import sys
import tempfile
import types
from pathlib import Path

from scripts import build_crystaldb_corpus as builder


def _make_cif(path: Path, formula: str = "Li2O", tag: str = "demo") -> None:
    path.write_text(
        (
            f"data_{tag}\n"
            "_symmetry_space_group_name_H-M 'P1'\n"
            "_cell_length_a 5.0\n"
            "_cell_length_b 5.0\n"
            "_cell_length_c 5.0\n"
            "_cell_angle_alpha 90\n"
            "_cell_angle_beta 90\n"
            "_cell_angle_gamma 90\n"
            f"_chemical_formula_sum '{formula}'\n"
        ),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_env_key_loader_supports_mp_api_key_and_hyphenated_alias(monkeypatch):
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        monkeypatch.delenv("MP_API_KEY", raising=False)
        monkeypatch.delenv("MP-API-KEY", raising=False)
        monkeypatch.delenv("MATERIALS_PROJECT_API_KEY", raising=False)
        (tmp_path / ".env").write_text("MP-API-KEY=secret-hyphen\n", encoding="utf-8")
        assert builder.load_mp_api_key(tmp_path) == "secret-hyphen"

        monkeypatch.setenv("MP_API_KEY", "secret-normal")
        assert builder.load_mp_api_key(tmp_path) == "secret-normal"


def test_dry_run_does_not_touch_db():
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        cif_dir = tmp_path / "cifs"
        cif_dir.mkdir()
        _make_cif(cif_dir / "one.cif")
        out_db = tmp_path / "dry_run.db"

        code = builder.main(
            [
                "--dataset-id",
                "local_dry_run",
                "--source",
                "local_cif",
                "--cif-dir",
                str(cif_dir),
                "--out-root",
                str(tmp_path / "out"),
                "--out-db",
                str(out_db),
                "--dry-run",
            ]
        )

        assert code == 0
        assert not out_db.exists()


def test_local_cif_folder_mode_writes_manifest_and_card():
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        cif_dir = tmp_path / "cifs"
        cif_dir.mkdir()
        _make_cif(cif_dir / "one.cif", "NaCl", "nacl")

        builder.main(
            [
                "--dataset-id",
                "local_fixture",
                "--source",
                "local_cif",
                "--cif-dir",
                str(cif_dir),
                "--out-root",
                str(tmp_path / "out"),
                "--out-db",
                str(tmp_path / "local_fixture.db"),
                "--force",
            ]
        )

        dataset_dir = tmp_path / "out" / "local_fixture"
        rows = _read_jsonl(dataset_dir / "manifest.jsonl")
        card = json.loads((dataset_dir / "dataset_card.json").read_text(encoding="utf-8"))
        assert rows and rows[0]["status"] == "OK"
        assert rows[0]["source_query"]
        assert card["dataset_id"] == "local_fixture"
        assert card["cif_count"] == 1


def test_combined_view_preserves_source_corpus_id():
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        source_manifest = tmp_path / "source_manifest.jsonl"
        source_manifest.write_text(
            json.dumps(
                {
                    "dataset_id": "source_a",
                    "formula": "Li2O",
                    "source": "local_cif",
                    "status": "OK",
                    "source_query": {"mode": "fixture"},
                    "retrieved_at": "2026-01-01T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        builder.main(
            [
                "--dataset-id",
                "combined",
                "--source",
                "combined_view",
                "--source-manifests",
                str(source_manifest),
                "--out-root",
                str(tmp_path / "out"),
                "--out-db",
                str(tmp_path / "combined.db"),
                "--dry-run",
            ]
        )

        rows = _read_jsonl(tmp_path / "out" / "combined" / "manifest.jsonl")
        assert rows[0]["dataset_id"] == "combined"
        assert rows[0]["source_corpus_id"] == "source_a"


def test_formula_anchors_not_full_corpus_without_target_only():
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        builder.main(
            [
                "--dataset-id",
                "anchors",
                "--source",
                "materials_project",
                "--formulas",
                "CoAs2",
                "Li6PS5Cl",
                "--out-root",
                str(tmp_path / "out"),
                "--out-db",
                str(tmp_path / "anchors.db"),
                "--dry-run",
            ]
        )

        rows = _read_jsonl(tmp_path / "out" / "anchors" / "manifest.jsonl")
        card = json.loads((tmp_path / "out" / "anchors" / "dataset_card.json").read_text(encoding="utf-8"))
        assert rows[0]["status"] == "BLOCKED"
        assert "--target-only" in rows[0]["error_text"]
        assert card["corpus_role"] == "retrieval-scale"


def test_target_only_is_explicit_role():
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        builder.main(
            [
                "--dataset-id",
                "targets",
                "--source",
                "materials_project",
                "--formulas",
                "CoAs2",
                "--target-only",
                "--out-root",
                str(tmp_path / "out"),
                "--out-db",
                str(tmp_path / "targets.db"),
                "--dry-run",
            ]
        )

        card = json.loads((tmp_path / "out" / "targets" / "dataset_card.json").read_text(encoding="utf-8"))
        queries = json.loads((tmp_path / "out" / "targets" / "source_queries.json").read_text(encoding="utf-8"))
        assert card["corpus_role"] == "target-only"
        assert queries["source_queries"][0]["query_type"] == "exact_formula_target_only"


def test_missing_mp_formula_writes_missing_not_crash(monkeypatch):
    class FakeSummary:
        def search(self, **_kwargs):
            return []

    class FakeMaterials:
        summary = FakeSummary()

    class FakeMPRester:
        materials = FakeMaterials()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    mp_api_module = types.ModuleType("mp_api")
    client_module = types.ModuleType("mp_api.client")
    client_module.MPRester = lambda _key: FakeMPRester()
    monkeypatch.setenv("MP_API_KEY", "secret")
    monkeypatch.setitem(sys.modules, "mp_api", mp_api_module)
    monkeypatch.setitem(sys.modules, "mp_api.client", client_module)

    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        builder.main(
            [
                "--dataset-id",
                "missing_formula",
                "--source",
                "materials_project",
                "--formulas",
                "UnobtainiumO2",
                "--target-only",
                "--out-root",
                str(tmp_path / "out"),
                "--out-db",
                str(tmp_path / "missing.db"),
            ]
        )

        rows = _read_jsonl(tmp_path / "out" / "missing_formula" / "manifest.jsonl")
        assert rows[0]["status"] == "MISSING"


def test_dataset_card_required_fields_and_artifacts_do_not_contain_api_key(monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "super-secret-value")
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        cif_dir = tmp_path / "cifs"
        cif_dir.mkdir()
        _make_cif(cif_dir / "one.cif")

        builder.main(
            [
                "--dataset-id",
                "secret_check",
                "--source",
                "local_cif",
                "--cif-dir",
                str(cif_dir),
                "--out-root",
                str(tmp_path / "out"),
                "--out-db",
                str(tmp_path / "secret_check.db"),
                "--dry-run",
            ]
        )

        dataset_dir = tmp_path / "out" / "secret_check"
        card = json.loads((dataset_dir / "dataset_card.json").read_text(encoding="utf-8"))
        for field in builder.DATASET_CARD_REQUIRED_FIELDS:
            assert field in card
        for path in dataset_dir.glob("*"):
            if path.is_file():
                assert "super-secret-value" not in path.read_text(encoding="utf-8")


def test_source_query_metadata_is_present():
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        cif_dir = tmp_path / "cifs"
        cif_dir.mkdir()
        _make_cif(cif_dir / "one.cif")

        builder.main(
            [
                "--dataset-id",
                "source_query",
                "--source",
                "local_cif",
                "--cif-dir",
                str(cif_dir),
                "--source-query-name",
                "local_fixture_query",
                "--out-root",
                str(tmp_path / "out"),
                "--out-db",
                str(tmp_path / "source_query.db"),
                "--dry-run",
            ]
        )

        rows = _read_jsonl(tmp_path / "out" / "source_query" / "manifest.jsonl")
        assert rows[0]["source_query"]
        assert rows[0]["source_query_name"] == "local_fixture_query"
