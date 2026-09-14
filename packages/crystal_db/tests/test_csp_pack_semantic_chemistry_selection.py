import json
import os

from crystal_db.csp_pack import run_csp_pack
from crystal_db.db import connect, init_db


def _seed_semantic_chemistry_db(db_path, rows):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-05-20T00:00:00Z"
    for sid, formula, text, emb in rows:
        elements = "," + ",".join(sorted(set(_elements(formula)))) + ","
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_chemical_formula_sum '{formula}'\n", formula, 1, 1.0, 0),
        )
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, formula, elements, "P1", 0.1),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "test", f"{sid}.cif", ts, 1, 1),
        )
        text_doc_id = conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "caption", "caption", "v1", text, f"h-{sid}", "OK", None, None, ts, ts),
        ).lastrowid
        conn.execute(
            "INSERT INTO text_embeddings "
            "(text_doc_id, embed_engine, model, model_version, dim, vector, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (text_doc_id, "hash", "hash-embed", "v1", 2, json.dumps(emb), "OK", None, None, ts, ts),
        )
    conn.commit()
    conn.close()


def _elements(formula):
    out = []
    i = 0
    while i < len(formula):
        if formula[i].isupper():
            token = formula[i]
            i += 1
            if i < len(formula) and formula[i].islower():
                token += formula[i]
                i += 1
            out.append(token)
        else:
            i += 1
    return out


def _run(db_path, tmp_path, *, material_system="ZnS", threshold=0.75):
    return run_csp_pack(
        db_path=str(db_path),
        query_text="zinc sulfide candidate with tetrahedral analogue evidence",
        structure_id=None,
        k=10,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=False,
        out_dir=str(tmp_path / "out"),
        export_top=2,
        redacted=True,
        demo_export=False,
        material_system=material_system,
        semantic_min_threshold=threshold,
    )


def test_high_chemistry_low_semantic_candidate_is_rejected(tmp_path, monkeypatch):
    db_path = tmp_path / "semantic_chem.db"
    _seed_semantic_chemistry_db(
        db_path,
        [
            ("semantic-wrong", "NaCl", "high semantic wrong chemistry", [0.99, 0.01]),
            ("chem-low-semantic", "ZnS", "chemically exact but irrelevant text", [0.40, 0.9165]),
            ("medium-good", "ZnS", "medium semantic useful chemistry", [0.80, 0.60]),
        ],
    )
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = _run(db_path, tmp_path, threshold=0.75)

    assert result["status"] == "ok"
    selection = result["corpus_selection"]
    assert selection["selected_structure_ids"] == ["medium-good"]
    rejected = selection["chemistry_compatible_but_semantically_rejected"]
    assert [item["structure_id"] for item in rejected] == ["chem-low-semantic"]
    exported = [item for item in result["export"]["items"] if item["export_status"] == "exported"]
    assert [item["structure_id"] for item in exported] == ["medium-good"]


def test_high_semantic_wrong_chemistry_is_analogue_not_spp_corpus(tmp_path, monkeypatch):
    db_path = tmp_path / "semantic_wrong.db"
    _seed_semantic_chemistry_db(
        db_path,
        [("semantic-wrong", "NaCl", "high semantic wrong chemistry", [0.99, 0.01])],
    )
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = _run(db_path, tmp_path, threshold=0.75)

    assert result["status"] == "partial"
    assert result["errors"]["code"] == "no_valid_semantic_chemistry_corpus"
    assert result["neighbors"][0]["structure_id"] == "semantic-wrong"
    assert result["export"]["items"][0]["export_status"] == "skipped"
    assert result["export"]["items"][0]["error"] == "not_selected_for_spp_corpus"


def test_medium_semantic_good_pair_coverage_candidate_can_be_selected(tmp_path, monkeypatch):
    db_path = tmp_path / "medium_good.db"
    _seed_semantic_chemistry_db(
        db_path,
        [("medium-good", "ZnS", "medium semantic useful chemistry", [0.80, 0.60])],
    )
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = _run(db_path, tmp_path, threshold=0.75)

    assert result["status"] == "ok"
    assert result["corpus_selection"]["selected_corpus_pair_coverage"]["missing_pairs"] == []
    assert os.path.exists(result["export"]["items"][0]["cif_path"])


def test_no_valid_joint_corpus_returns_structured_partial(tmp_path, monkeypatch):
    db_path = tmp_path / "no_valid.db"
    _seed_semantic_chemistry_db(
        db_path,
        [
            ("semantic-wrong", "NaCl", "semantic but wrong chemistry", [0.99, 0.01]),
            ("chem-low-semantic", "ZnS", "chemistry below semantic floor", [0.40, 0.9165]),
        ],
    )
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = _run(db_path, tmp_path, threshold=0.75)

    assert result["status"] == "partial"
    assert result["errors"]["code"] == "no_valid_semantic_chemistry_corpus"
    assert result["corpus_selection"]["final_selection_reason"] in {
        "chemistry_exists_but_below_semantic_floor",
        "semantic_support_exists_but_pair_coverage_incomplete",
    }


def test_diagnostics_distinguish_chemistry_and_semantic_failures(tmp_path, monkeypatch):
    db_path = tmp_path / "diagnostics.db"
    _seed_semantic_chemistry_db(
        db_path,
        [
            ("semantic-wrong", "NaCl", "semantic but wrong chemistry", [0.99, 0.01]),
            ("chem-low-semantic", "ZnS", "chemistry below semantic floor", [0.40, 0.9165]),
        ],
    )
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = _run(db_path, tmp_path, threshold=0.75)
    diagnostics = result["errors"]["diagnostics"]

    assert diagnostics["semantic_candidates_considered"]
    assert diagnostics["candidates_below_semantic_floor"]
    assert diagnostics["chemistry_compatible_but_semantically_rejected"]
    assert diagnostics["semantically_relevant_but_chemistry_incomplete"]
    assert diagnostics["selected_corpus_pair_coverage"]["missing_pairs"]
    assert diagnostics["final_selection_reason"]


def test_pair_level_spp_corpus_keeps_selecting_pair_useful_candidates(tmp_path, monkeypatch):
    db_path = tmp_path / "pair_level.db"
    _seed_semantic_chemistry_db(
        db_path,
        [
            ("target", "BaTiO3", "perovskite barium titanate target", [0.99, 0.01]),
            ("ti-o", "TiO2", "titanium oxide octahedral analogue", [0.96, 0.04]),
            ("ba-o", "BaO", "barium oxide rocksalt pair evidence", [0.95, 0.05]),
            ("semantic-only", "NaCl", "semantic oxide wording but no useful pairs", [0.94, 0.06]),
        ],
    )
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = run_csp_pack(
        db_path=str(db_path),
        query_text="barium titanate perovskite oxide pair evidence",
        structure_id=None,
        k=10,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=False,
        out_dir=str(tmp_path / "out"),
        export_top=2,
        redacted=True,
        demo_export=False,
        material_system="BaTiO3",
        semantic_min_threshold=0.75,
    )

    selection = result["corpus_selection"]
    assert result["status"] == "ok"
    assert selection["spp_corpus_selection_mode"] == "pair_level_evidence_expansion"
    assert selection["spp_exported_cif_count"] == 3
    assert selection["selected_structure_ids"] == ["target", "ti-o", "ba-o"]
    assert "tier_2_required_pair_support" in selection["spp_corpus_tiers_used"]
    pair_summary = {
        item["required_pair"]: set(item["direct_support_candidate_ids"])
        for item in selection["spp_corpus_pair_support_summary"]
    }
    assert {"target", "ti-o"}.issubset(pair_summary["O-Ti"])
    assert {"target", "ti-o"}.issubset(pair_summary["Ti-Ti"])
    assert {"target", "ba-o"}.issubset(pair_summary["Ba-O"])
    assert {"target", "ba-o"}.issubset(pair_summary["Ba-Ba"])
    assert selection["spp_corpus_config"]["require_all_target_elements_for_candidate"] is False
    exported = [item["structure_id"] for item in result["export"]["items"] if item["export_status"] == "exported"]
    assert exported == ["target", "ti-o", "ba-o"]


def test_partial_pair_coverage_exports_useful_partial_corpus(tmp_path, monkeypatch):
    db_path = tmp_path / "partial_spinel.db"
    _seed_semantic_chemistry_db(
        db_path,
        [
            ("al2o3", "Al2O3", "spinel-like aluminium oxide neighbour", [0.99, 0.01]),
            ("mgo", "MgO", "magnesium oxide neighbour", [0.98, 0.02]),
            ("semantic-only", "NaCl", "spinel words without useful chemistry", [0.97, 0.03]),
        ],
    )
    monkeypatch.setattr("crystal_db.retrieval.embed_text", lambda *args, **kwargs: [1.0, 0.0])

    result = run_csp_pack(
        db_path=str(db_path),
        query_text="magnesium aluminate spinel with partial pair evidence",
        structure_id=None,
        k=10,
        embed_engine="hash",
        model_name="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=False,
        out_dir=str(tmp_path / "out"),
        export_top=2,
        redacted=True,
        demo_export=False,
        material_system="MgAl2O4",
        semantic_min_threshold=0.75,
    )

    selection = result["corpus_selection"]
    assert result["status"] == "partial"
    assert result["errors"]["code"] == "partial_pair_coverage"
    assert selection["corpus_selection_status"] == "partial_pair_coverage"
    assert selection["useful_partial_pair_evidence"] is True
    assert selection["can_attempt_partial_spp"] is True
    assert selection["can_attempt_qlip_without_fresh_spp"] is True
    assert selection["covered_required_pairs"] == ["Al-Al", "Al-O", "Mg-Mg", "Mg-O", "O-O"]
    assert selection["missing_required_pairs"] == ["Al-Mg"]
    assert "Mg-O" in selection["covered_required_pairs"]
    assert selection["missing_required_pairs"]
    assert selection["exported_partial_cif_count"] == 2
    assert result["errors"]["code"] != "no_valid_semantic_chemistry_corpus"
    exported = [item for item in result["export"]["items"] if item["export_status"] == "exported"]
    assert [item["structure_id"] for item in exported] == ["al2o3", "mgo"]
    assert all(os.path.exists(item["cif_path"]) for item in exported)
