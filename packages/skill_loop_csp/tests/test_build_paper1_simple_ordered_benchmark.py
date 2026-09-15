from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

from pymatgen.core import Lattice, Structure
from sok_llm_orchestrator.workflow.csv_workflow import _infer_structured_task


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_paper1_simple_ordered_benchmark.py"
SPEC = importlib.util.spec_from_file_location("paper1_simple_ordered_builder", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def _candidate(family: str, formula: str, index: int) -> object:
    return builder.Candidate(
        record_id=f"ref-{family}-{index}", source_reference_id=f"mp-{index}.cif",
        materials_project_id=f"mp-{index}", formula=formula, reduced_formula=formula,
        family=family, space_group_symbol="X", space_group_number=1,
        source_atom_count=2, primitive_atom_count=2, species_count=2, ordered=True,
        cif_sha256=f"{index:064x}", source_corpus="mp_stable_10k_v1",
        source_database="source.db", source_provenance="mp",
        family_assignment_method=builder.CLASSIFIER_VERSION,
        family_assignment_reason="fixture", aflow_strukturbericht="fixture",
    )


def test_family_assignment_for_ideal_prototypes() -> None:
    structures = {
        "rocksalt_b1": Structure.from_spacegroup("Fm-3m", Lattice.cubic(5.6), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]),
        "cscl_b2": Structure.from_spacegroup("Pm-3m", Lattice.cubic(4.1), ["Cs", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]),
        "zinc_blende_b3": Structure.from_spacegroup("F-43m", Lattice.cubic(5.4), ["Zn", "S"], [[0, 0, 0], [0.25, 0.25, 0.25]]),
        "fluorite_antifluorite": Structure.from_spacegroup("Fm-3m", Lattice.cubic(5.5), ["Ca", "F"], [[0, 0, 0], [0.25, 0.25, 0.25]]),
        "oxide_perovskite": Structure.from_spacegroup("Pm-3m", Lattice.cubic(3.9), ["Sr", "Ti", "O"], [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0]]),
        "halide_perovskite": Structure.from_spacegroup("Pm-3m", Lattice.cubic(5.9), ["Cs", "Sn", "I"], [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0]]),
    }
    for expected, structure in structures.items():
        decision, status, _detail = builder.classify_structure(structure)
        assert status == "ELIGIBLE"
        assert decision["family"] == expected


def test_disorder_and_unsupported_topology_are_excluded() -> None:
    disordered = Structure(Lattice.cubic(4), [{"Na": 0.5, "K": 0.5}, "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    assert builder.classify_structure(disordered)[1] == "DISORDERED_OR_PARTIAL_OCCUPANCY"
    diamond = Structure.from_spacegroup("Fd-3m", Lattice.cubic(3.5), ["C"], [[0, 0, 0]])
    assert builder.classify_structure(diamond)[0] is None


def test_selection_is_deterministic_unique_and_quota_limited() -> None:
    rows = [
        _candidate("rocksalt_b1", "MgO", 1), _candidate("rocksalt_b1", "NaCl", 2),
        _candidate("rocksalt_b1", "CaO", 3), _candidate("rocksalt_b1", "MgO", 4),
    ]
    quota = dict(builder.QUOTAS) | {"rocksalt_b1": 2}
    first = builder.select_targets(rows, quota)
    second = builder.select_targets(list(reversed(rows)), quota)
    assert [item.record_id for item in first] == [item.record_id for item in second]
    assert len(first) == 2
    assert len({item.reduced_formula for item in first}) == 2


def test_csv_construction_and_reference_exclusion() -> None:
    targets = [_candidate("rocksalt_b1", "MgO", 1)]
    rows = builder.benchmark_rows(targets)
    assertions = builder.assert_freeze(targets, rows)
    assert assertions["all_exclude_target_reference_true"] is True
    assert rows[0]["target_reference_id"] == targets[0].record_id
    assert rows[0]["database"] == "general"
    assert assertions["target_count_nonzero"] is True
    assert "rocksalt" in rows[0]["request_text"]


def test_hashes_are_canonical_and_source_files_are_not_mutated() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.db"
        source.write_bytes(b"source")
        before = builder.sha256_file(source)
        assert builder.canonical_json_hash({"b": 2, "a": 1}) == builder.canonical_json_hash({"a": 1, "b": 2})
        builder.write_json(root / "out" / "manifest.json", {"source": str(source)})
        assert builder.sha256_file(source) == before


def test_benchmark_csv_has_established_contract_columns() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "benchmark.csv"
        rows = builder.benchmark_rows([_candidate("rocksalt_b1", "MgO", 1)])
        builder.write_csv(path, rows, builder.CSV_FIELDS)
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert tuple(reader.fieldnames or ()) == builder.CSV_FIELDS
            assert list(reader)[0]["exclude_target_reference"] == "true"


def test_fallback_parser_preserves_all_paper1_family_intents() -> None:
    class Stages:
        @staticmethod
        def normalise(_request: str) -> dict:
            raise ValueError("use fallback")

    requests = {
        "CsCl-type": "cscl",
        "zinc-blende": "zinc blende",
        "fluorite or anti-fluorite": "fluorite or anti-fluorite",
    }
    for phrase, expected in requests.items():
        task = _infer_structured_task(
            f"Generate an ordered {phrase} structure with composition CdAg.", Stages()
        )
        assert task["formula"] == "CdAg"
        assert task["family"] == expected


def test_selection_manifest_shape_is_json_serializable() -> None:
    target = _candidate("rocksalt_b1", "MgO", 1)
    payload = {"targets": [builder.asdict(target)], "hash": builder.canonical_json_hash(builder.asdict(target))}
    assert json.loads(json.dumps(payload))["targets"][0]["record_id"] == target.record_id
