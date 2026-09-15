from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.retrieval.corpus_router import route_corpus
from sok_llm_orchestrator.workflow.evidence import assemble_spp_evidence


def _registry(workdir: Path) -> Path:
    general = workdir / "general.db"
    specialist = workdir / "specialist.db"
    evaluation = workdir / "evaluation.db"
    for path in (general, specialist, evaluation):
        path.write_bytes(b"sqlite-placeholder")
    payload = {
        "schema_version": "specialist_corpus_registry.v1",
        "corpora": {
            "mp_stable_10k_v1": {"database": str(general), "path_base": "repository"},
            "nasicon_specialist_v3": {"database": str(specialist), "path_base": "repository"},
            "nasicon_specialist_all_targets_out_v3": {"database": str(evaluation), "path_base": "repository"},
            "mp_layered_battery_oxides_v1": {"database": str(specialist), "path_base": "repository"},
            "mp_spinel_oxides_v1": {"database": str(specialist), "path_base": "repository"},
        },
    }
    path = workdir / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_general_perovskite_routes_to_general_crystaldb(workdir: Path) -> None:
    route = route_corpus("Generate BaTiO3 perovskite", formula="BaTiO3", registry_path=_registry(workdir))
    assert route.corpus_id == "mp_stable_10k_v1"


def test_halide_routes_to_general_crystaldb(workdir: Path) -> None:
    route = route_corpus("Generate CsPbBr3 halide perovskite", formula="CsPbBr3", registry_path=_registry(workdir))
    assert route.corpus_id == "mp_stable_10k_v1"


def test_spinel_oxide_routes_to_versioned_specialist_corpus(workdir: Path) -> None:
    route = route_corpus("Generate MgAl2O4 as a spinel oxide", formula="MgAl2O4", registry_path=_registry(workdir))
    assert route.corpus_id == "mp_spinel_oxides_v1"


def test_layered_oxide_routes_to_versioned_specialist_corpus(workdir: Path) -> None:
    route = route_corpus("Generate LiCoO2 as a layered battery oxide", formula="LiCoO2", registry_path=_registry(workdir))
    assert route.corpus_id == "mp_layered_battery_oxides_v1"


def test_nasicon_routes_to_specialist_crystaldb(workdir: Path) -> None:
    route = route_corpus("Generate a NASICON candidate", formula="Na3Zr2Si2PO12", registry_path=_registry(workdir))
    assert route.corpus_id == "nasicon_specialist_v3"


def test_nasicon_does_not_silently_use_general_db(workdir: Path) -> None:
    registry = _registry(workdir)
    route = route_corpus("NZP framework", formula="Na3Zr2Si2PO12", evaluation_holdout=True, registry_path=registry)
    general = route_corpus("ordinary oxide", formula="BaTiO3", registry_path=registry)
    assert route.corpus_id == "nasicon_specialist_all_targets_out_v3"
    assert route.database != general.database


def test_changing_physical_location_does_not_change_logical_corpus_identity(workdir: Path) -> None:
    registry = _registry(workdir)
    first = route_corpus("ordinary oxide", formula="BaTiO3", registry_path=registry)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    moved = workdir / "moved-general.db"
    moved.write_bytes(b"sqlite-placeholder-moved")
    payload["corpora"]["mp_stable_10k_v1"]["database"] = str(moved)
    registry.write_text(json.dumps(payload), encoding="utf-8")
    second = route_corpus("ordinary oxide", formula="BaTiO3", registry_path=registry)
    assert first.corpus_id == second.corpus_id == "mp_stable_10k_v1"
    assert first.database != second.database


def _retrieval(workdir: Path) -> tuple[dict, Path]:
    structure = Structure(Lattice.cubic(5.0), ["Na", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    cif = workdir / "evidence.cif"
    structure.to(filename=str(cif))
    return (
        {
            "corpus": {"corpus_id": "test", "hash": "corpus-hash"},
            "selected": [{"rank": 1, "structure_id": "s1", "score": 0.9, "cif_export": {"status": "exported", "path": str(cif)}}],
        },
        cif,
    )


def test_retrieved_ids_feed_spp_evidence_bundle(workdir: Path) -> None:
    retrieval, _ = _retrieval(workdir)
    bundle = assemble_spp_evidence(retrieval=retrieval, required_pairs=["Na-O"])
    assert [item.structure_id for item in bundle.selected] == ["s1"]


def test_request_spp_uses_selected_retrieved_cifs(workdir: Path) -> None:
    retrieval, cif = _retrieval(workdir)
    bundle = assemble_spp_evidence(retrieval=retrieval, required_pairs=["Na-O"])
    assert bundle.selected[0].cif_path == str(cif.resolve())
    assert bundle.selected[0].cif_sha256 == hashlib.sha256(cif.read_bytes()).hexdigest()
