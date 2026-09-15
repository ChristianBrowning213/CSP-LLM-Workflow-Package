from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path

import pytest

from qlip.core.paths import resolve_and_check_path
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    _qlip_data_root,
    _qlip_pot_authorization,
    _qlip_repo_root,
    _qlip_runtime_root,
    _request_spp_runtime_root,
)


def _config(temporary_root: Path) -> WorkflowConfig:
    return WorkflowConfig(
        output_root=temporary_root / "output",
        qlip_runtime_root=temporary_root / "qlip-runtime",
        qlip_data_root=temporary_root / "qlip-data",
    )


def _scoped_hash(root: Path, *, pot_only: bool) -> tuple[str, int, int, dict[str, str]]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and (not pot_only or path.suffix.lower() == ".pot")
    ]
    files.sort(key=lambda path: path.relative_to(root).as_posix().lower())
    aggregate = hashlib.sha256()
    individual_hashes: dict[str, str] = {}
    total_bytes = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        contents = path.read_bytes()
        file_hash = hashlib.sha256(contents).hexdigest()
        individual_hashes[relative] = file_hash
        total_bytes += len(contents)
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(bytes.fromhex(file_hash))
        aggregate.update(b"\n")
    return aggregate.hexdigest(), len(files), total_bytes, individual_hashes


def test_canonical_request_pots_are_under_qlip_allowed_root() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        config = _config(temporary_root)
        pot_root = _request_spp_runtime_root(config, "bundle-a", temporary_root / "run-a") / "request_spp" / "supported_pairs"
        pot_root.mkdir(parents=True)

        with _qlip_pot_authorization(config) as allowed_roots:
            assert resolve_and_check_path(pot_root, allowed_roots) == pot_root.resolve()
        assert pot_root.is_relative_to(_qlip_runtime_root(config))


def test_registered_regulator_is_under_qlip_allowed_root() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        config = _config(temporary_root)
        regulator = _qlip_data_root(config) / "regulators" / config.regulator_id
        regulator.mkdir(parents=True)

        with _qlip_pot_authorization(config) as allowed_roots:
            assert ProductionWorkflowStages._regulator_root(config) == regulator.resolve()
            assert resolve_and_check_path(regulator, allowed_roots) == regulator.resolve()


def test_arbitrary_external_pot_path_is_still_rejected() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        config = _config(temporary_root)
        external = temporary_root / "unregistered" / "EXTERNAL.POT"
        external.parent.mkdir()
        external.write_text("not an authorized POT", encoding="utf-8")

        with _qlip_pot_authorization(config) as allowed_roots:
            with pytest.raises(ValueError, match="not in allowed roots"):
                resolve_and_check_path(external, allowed_roots)


def test_regulator_relocation_preserves_hash() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (repo_root / "artifacts" / "workflow_cleanup" / "12_qlip_paths" / "REGULATOR_RELOCATION_MANIFEST.json").read_text(encoding="utf-8")
    )
    original = Path.home() / "Downloads" / "SPP" / "SPP" / "SPP" / "SPP"
    canonical = _qlip_repo_root() / "data" / "spp" / "regulators" / manifest["regulator_id"]
    original_tree = _scoped_hash(original, pot_only=False)
    canonical_tree = _scoped_hash(canonical, pot_only=False)
    original_pots = _scoped_hash(original, pot_only=True)
    canonical_pots = _scoped_hash(canonical, pot_only=True)

    assert original_tree[0] == manifest["tree_hash_original"]
    assert canonical_tree[0] == manifest["tree_hash_canonical"]
    assert original_tree[:3] == canonical_tree[:3]
    assert original_tree[3] == canonical_tree[3]
    assert original_pots[0] == manifest["pot_set_hash_original"]
    assert canonical_pots[0] == manifest["pot_set_hash_canonical"]
    assert original_pots[:3] == canonical_pots[:3]
    assert original_pots[3] == canonical_pots[3]
    assert original_pots[1] == manifest["pot_file_count_original"] == manifest["pot_file_count_canonical"]
    assert original_pots[2] == manifest["pot_total_bytes_original"] == manifest["pot_total_bytes_canonical"]
    assert manifest["tree_hash_match"] is True
    assert manifest["pot_set_hash_match"] is True
    assert manifest["scientific_content_changed"] is False


def test_request_spp_run_directory_is_unique_per_run() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        config = _config(temporary_root)
        first = _request_spp_runtime_root(config, "same-bundle", temporary_root / "run-a")
        second = _request_spp_runtime_root(config, "same-bundle", temporary_root / "run-b")

        assert first != second
        assert first.parent == second.parent == _qlip_runtime_root(config) / "runs"


def test_no_user_specific_absolute_path_required() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        config = WorkflowConfig(output_root=Path(temporary_directory) / "output")
        qlip_repo = _qlip_repo_root()
        default_config = (Path(__file__).resolve().parents[1] / "config" / "workflow" / "default.json").read_text(encoding="utf-8")

        assert _qlip_runtime_root(config) == (qlip_repo / "gen_artifacts" / "skill_loop_csp").resolve()
        assert _qlip_data_root(config) == (qlip_repo / "data" / "spp").resolve()
        assert "C:\\Users\\" not in default_config
        assert "Downloads/SPP" not in default_config
