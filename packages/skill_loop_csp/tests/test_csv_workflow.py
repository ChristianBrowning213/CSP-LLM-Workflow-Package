from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pymatgen.core import Composition, Lattice, Structure

from sok_llm_orchestrator.workflow.cell_strategy import ResolvedCell
from sok_llm_orchestrator.workflow.component_paths import (
    ComponentConfigurationError,
    ComponentRoots,
)
from sok_llm_orchestrator.workflow.csv_workflow import (
    CsvWorkflowError,
    generate_batch,
    load_workflow_config,
    run_sca,
    validate_csv,
    visualise_row,
)


REPO = Path(__file__).resolve().parents[1]


def _roots(base: Path) -> ComponentRoots:
    values = {}
    for variable, name in (
        ("CRYSTAL_DB_ROOT", "Crystal-DB"),
        ("SPP_MAKER_ROOT", "SPP-Maker-QLIP"),
        ("QLIP_ROOT", "qlip"),
        ("SCA_ROOT", "Structured_Crystal_Analyser"),
    ):
        root = base / name
        root.mkdir(parents=True)
        values[variable] = str(root)
    (base / "Crystal-DB" / "crystal_db").mkdir()
    (base / "Crystal-DB" / "data").mkdir()
    (base / "SPP-Maker-QLIP" / "src").mkdir()
    (base / "qlip" / "src").mkdir()
    (base / "qlip" / "data" / "spp" / "regulators" / "icsd_broad_regulator_v1").mkdir(parents=True)
    (base / "Structured_Crystal_Analyser" / "sca").mkdir()
    return ComponentRoots.load(base, environ=values)


def _write_cif(path: Path, formula: str = "MgO") -> None:
    if formula == "BaTiO3":
        structure = Structure(
            Lattice.cubic(4.1),
            ["Ba", "Ti", "O", "O", "O"],
            [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
        )
    else:
        structure = Structure(Lattice.cubic(4.2), ["Mg", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    path.parent.mkdir(parents=True, exist_ok=True)
    structure.to(filename=path)


class FakeStages:
    def normalise(self, request: str) -> dict[str, object]:
        formula = "BaTiO3" if "BaTiO3" in request else "MgO"
        return {"formula": formula, "family": "perovskite" if formula == "BaTiO3" else "rocksalt", "prototype": None, "space_group": None}

    def retrieve(self, request, task, config, run_root):
        selected = []
        for index in range(6):
            path = Path(run_root) / "retrieved_cifs" / f"fake-{index}.cif"
            _write_cif(path, str(task["formula"]))
            selected.append(
                {
                    "rank": index + 1,
                    "structure_id": f"fake-{index}",
                    "score": 1.0 - index * 0.01,
                    "retrieval_score": 1.0 - index * 0.01,
                    "cif_export": {"path": str(path), "status": "exported"},
                }
            )
        return {
            "corpus": {"corpus_id": "fake", "database": "fake.db", "hash": "abc"},
            "backend": "fake",
            "config": {"k": config.retrieval_depth},
            "selected": selected,
        }

    def required_pairs(self, task, config):
        species = sorted(Composition(str(task["formula"])).get_el_amt_dict())
        return [f"{left}-{right}" for index, left in enumerate(species) for right in species[index:]]

    def fit_request_spp(self, evidence, task, config, run_root):
        pot_root = Path(run_root) / "pots"
        pair_results = []
        for pair in evidence.required_pairs:
            pair_dir = pot_root / pair
            pair_dir.mkdir(parents=True, exist_ok=True)
            pot = pair_dir / f"{pair}.POT"
            pot.write_text("# fixture\n0.0 12.0\n2.0 -1.0\n10.0 0.0\n", encoding="utf-8")
            pair_results.append(
                {
                    "species_pair": pair,
                    "request_pair_status": "REQUEST_USABLE",
                    "structures_contributing": 1,
                    "observations": 10,
                    "selected_pot_source": "LOCAL_PRIMARY_GLOBAL_WEAK_PRIOR",
                    "selected_pot_path": str(pot),
                    "guidance_mode": "PREBLENDED_COMPLETE",
                    "blend_decision": {"global_weight": 0.1},
                }
            )
        return {
            "pot_root": pot_root,
            "artifact": pot_root.parent,
            "regulator_root": config.regulator_root,
            "regulator_hash": "fixture",
            "blend_mode": "preblended_pair_level",
            "artifact_contract": "dmytro_gr_v1",
            "quality": {
                "request_pair_results": pair_results,
                "request_supported_pair_count": len(pair_results),
                "regulator_fallback_pair_count": 0,
            },
        }

    def solve(self, task, request_spp, config, run_root):
        output = Path(run_root) / "generated.cif"
        _write_cif(output, str(task["formula"]))
        return {
            "cif_path": output,
            "status": "OPTIMAL",
            "solver_objective": -1.25,
            "solver_summary": {"status": "OPTIMAL"},
            "solver_diagnostics": {"model_stats": {"binary_variables": 128}},
            "search_space": request_spp["dynamic_cell"],
            "qlip_adapter": {"required_pairs": []},
            "components": SimpleNamespace(solver_objective=-1.25),
            "difference": 0.0,
        }


def _dynamic(formula, evidence, *, grid_density, proximity_scale):
    del evidence
    atom_count = int(round(Composition(formula).num_atoms))
    cell = ResolvedCell(
        cell_mode="retrieval_feasible_cell_v1",
        a=5.0,
        b=5.0,
        c=5.0,
        alpha=90.0,
        beta=90.0,
        gamma=90.0,
        grid_density=grid_density,
        grid_spacing_A=5.0 / grid_density,
        n_target_atoms=atom_count,
        vpa_source="fixture",
        vpa_value=125.0 / atom_count,
        cell_volume_A3=125.0,
        provenance={},
    )
    prior = {"valid_observation_count": 6, "median_volume_per_atom_A3": 20.0}
    provenance = {
        "retrieval_volume_prior": prior,
        "feasibility_checks": [{"status": "FEASIBLE", "proximity_scale": proximity_scale}],
        "final_status": "GEOMETRY_FEASIBLE_AT_PRIOR",
    }
    return cell, provenance


def test_request_only_and_advanced_csv_defaults_and_overrides() -> None:
    config = load_workflow_config()
    minimal = validate_csv(REPO / "tests" / "data" / "workflow_batch_minimal.csv", config, stages=FakeStages())
    assert [row.row_id for row in minimal] == ["row_0001", "row_0002"]
    assert minimal[0].effective_config["solver_time_limit_s"] == 300
    assert minimal[0].effective_config["spp_contract"] == "dmytro_gr_v1"
    advanced = validate_csv(REPO / "tests" / "data" / "workflow_batch_advanced.csv", config, stages=FakeStages())
    assert advanced[0].effective_config["retrieval_top_k"] == 12
    assert advanced[0].effective_config["solver_threads"] == 2
    assert advanced[1].effective_config["solver_time_limit_s"] == 300


def test_csv_validation_rejects_duplicate_and_malformed_before_execution() -> None:
    config = load_workflow_config()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        duplicate = root / "duplicate.csv"
        duplicate.write_text('row_id,request_text\nsame,"Generate MgO"\nsame,"Generate MgO"\n', encoding="utf-8")
        with pytest.raises(CsvWorkflowError, match="duplicate row_id"):
            validate_csv(duplicate, config, stages=FakeStages())
        malformed = root / "malformed.csv"
        malformed.write_text('request_text,solver_threads\n"Generate MgO",many\n', encoding="utf-8")
        with pytest.raises(CsvWorkflowError, match="invalid solver_threads"):
            validate_csv(malformed, config, stages=FakeStages())


def test_environment_roots_override_dotenv_and_missing_root_fails() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        roots = _roots(root)
        assert roots.crystal_db == (root / "Crystal-DB").resolve()
        values = roots.as_dict()
        values.pop("QLIP_ROOT")
        with pytest.raises(ComponentConfigurationError, match="QLIP_ROOT is not configured"):
            ComponentRoots.load(root, environ=values)
        (root / ".env").write_text(
            "\n".join(f"{name}={value}" for name, value in roots.as_dict().items()),
            encoding="utf-8",
        )
        with pytest.raises(ComponentConfigurationError, match="QLIP_ROOT is not configured"):
            ComponentRoots.load(root, environ={"QLIP_ROOT": ""})


def test_logical_database_selector_resolves_through_configured_crystal_root() -> None:
    from sok_llm_orchestrator.retrieval.corpus_router import route_corpus

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        crystal = root / "relocated-crystal-db"
        database = crystal / "data" / "general.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"sqlite fixture")
        registry = root / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": "specialist_corpus_registry.v1",
                    "corpora": {
                        "mp_stable_10k_v1": {
                            "database": "Crystal-DB/data/general.db",
                            "path_base": "github_parent",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        route = route_corpus(
            "Generate MgO",
            formula="MgO",
            registry_path=registry,
            logical_selector="general",
            crystal_db_root=crystal,
        )
        assert route.corpus_id == "mp_stable_10k_v1"
        assert route.database == database.resolve()


def test_generation_bundle_resume_sca_and_visualisation_are_separate_and_portable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        roots = _roots(root / "components")
        input_path = root / "input.csv"
        input_path.write_text('request_text\n"Generate a plausible rocksalt MgO crystal"\n', encoding="utf-8")
        run_root = root / "run"
        result = generate_batch(
            input_path=input_path,
            output_root=run_root,
            roots=roots,
            stages=FakeStages(),
            dynamic_resolver=_dynamic,
        )
        assert result["status"] == "PASS"
        row = run_root / "row_0001"
        candidate = row / "generated" / "candidate.cif"
        candidate_hash = candidate.read_bytes()
        assert not (row / "sca" / "result.json").exists()
        assert (row / "retrieval" / "neighbours" / "0001_fake-0.cif").is_file()
        assert list((row / "spp" / "potentials").rglob("*.POT"))
        second = generate_batch(
            input_path=input_path,
            output_root=run_root,
            roots=roots,
            resume=True,
            stages=FakeStages(),
            dynamic_resolver=_dynamic,
        )
        assert second["status"] == "PASS"
        assert candidate.read_bytes() == candidate_hash

        fake_sca = {
            "parse_ok": True,
            "target_formula_match": True,
            "geometry_ok": True,
            "num_bad_contacts": 0,
            "min_distance": 2.1,
            "detected_space_group": "Pm-3m",
            "space_group_consistent": None,
            "topology_status": "PASS",
            "novel_by_structure_matcher": None,
        }
        with patch(
            "sok_llm_orchestrator.workflow.runner.ProductionWorkflowStages.evaluate",
            return_value=fake_sca,
        ):
            sca = run_sca(roots=roots, row=row)
        assert sca["sca_status"] == "PASS"
        assert candidate.read_bytes() == candidate_hash
        existing = (row / "sca" / "result.json").read_bytes()
        run_sca(roots=roots, row=row)
        assert (row / "sca" / "result.json").read_bytes() == existing

        # Portability acceptance: rendering succeeds with every component root moved away.
        moved = root / "components_moved"
        (root / "components").rename(moved)
        metadata = visualise_row(row)
        assert metadata["input_scope"] == "row_folder_only"
        assert metadata["crystal_db_queried"] is False
        assert metadata["request_text"] == "Generate a plausible rocksalt MgO crystal"
        assert (row / "visualisation" / "workflow.png").is_file()
        assert (row / "visualisation" / "workflow.pdf").is_file()
        assert candidate.read_bytes() == candidate_hash


def test_run_level_sca_skips_missing_candidate_and_updates_manifest() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        roots = _roots(root / "components")
        input_path = root / "input.csv"
        input_path.write_text(
            'request_text\n"Generate a plausible rocksalt MgO crystal"\n"Generate BaTiO3"\n',
            encoding="utf-8",
        )
        run_root = root / "run"
        generate_batch(
            input_path=input_path,
            output_root=run_root,
            roots=roots,
            rows=["row_0001"],
            stages=FakeStages(),
            dynamic_resolver=_dynamic,
        )
        fake_sca = {
            "parse_ok": True,
            "target_formula_match": True,
            "geometry_ok": True,
            "num_bad_contacts": 0,
            "topology_status": "NOT_EVALUATED",
        }
        with patch(
            "sok_llm_orchestrator.workflow.runner.ProductionWorkflowStages.evaluate",
            return_value=fake_sca,
        ):
            result = run_sca(roots=roots, run=run_root)
        statuses = {row["row_id"]: row["sca_status"] for row in result["rows"]}
        assert statuses == {"row_0001": "PASS", "row_0002": "SKIPPED_NO_CANDIDATE"}
        assert (run_root / "SCA_RUN_SUMMARY.csv").is_file()
        manifest = list(csv.DictReader((run_root / "run_manifest.csv").open(newline="", encoding="utf-8")))
        assert manifest[0]["sca_status"] == "PASS"
        assert manifest[1]["sca_status"] == "NOT_RUN"
