import json

from crystal_db.__main__ import main
from crystal_db.bench_retrieval import load_benchmark_cases, validate_case_schema
from crystal_db.cases_tools import build_semantic_query, normalize_cases, sample_cases
from crystal_db.db import connect, init_db
from crystal_db.schema_validate import validate


def _seed_sample_db(db_path):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    rows = [
        (
            "s-001",
            (
                "Li2O crystallizes in the orthorhombic Pnma space group. "
                "The framework has corner-sharing octahedra and layered connectivity. "
                "Li(1) is sixfold coordinated."
            ),
            "Li2O",
        ),
        (
            "s-002",
            (
                "MgAl2O4 crystallizes in the cubic Fd-3m space group. "
                "It forms a spinel-type network with edge-sharing octahedra."
            ),
            "MgAl2O4",
        ),
        (
            "s-003",
            (
                "AB2 crystallizes in a hexagonal setting. "
                "The structure is related to a laves motif with tetrahedra."
            ),
            "AB2",
        ),
    ]
    for sid, text, formula in rows:
        conn.execute(
            "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, f"data_{sid}\n_cell_length_a 1\n", formula, 1, 1.0, 0),
        )
        conn.execute(
            "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, formula, ",Li,O,", "P1", 0.1),
        )
        conn.execute(
            "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "test", f"{sid}.cif", ts, 1, 1),
        )
        conn.execute(
            "INSERT INTO text_docs "
            "(structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "caption", "caption", "v1", text, f"h-{sid}", "OK", None, None, ts, ts),
        )
    conn.commit()
    conn.close()


def _seed_single_case_db(db_path, *, structure_id: str, text: str, formula: str = "ABO3"):
    conn = connect(str(db_path))
    init_db(conn)
    ts = "2026-02-18T00:00:00Z"
    conn.execute(
        "INSERT INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (structure_id, f"data_{structure_id}\n_cell_length_a 1\n", formula, 1, 1.0, 0),
    )
    conn.execute(
        "INSERT INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
        "VALUES (?, ?, ?, ?, ?)",
        (structure_id, formula, ",A,B,O,", "P1", 0.1),
    )
    conn.execute(
        "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export, allow_derivatives) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (structure_id, "test", f"{structure_id}.cif", ts, 1, 1),
    )
    conn.execute(
        "INSERT INTO text_docs "
        "(structure_id, engine, text_view, engine_version, text, text_sha256, status, error_type, error_message, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (structure_id, "robocrys", "robocrys", "v1", text, f"h-{structure_id}", "OK", None, None, ts, ts),
    )
    conn.commit()
    conn.close()


def test_cases_sample_semantic_query_is_meaningful(tmp_path):
    db_path = tmp_path / "semantic.db"
    out_path = tmp_path / "semantic.jsonl"
    _seed_single_case_db(
        db_path,
        structure_id="s-semantic",
        text=(
            "BaTiO3 crystallizes in the cubic Pm-3m space group. "
            "The structure features corner-sharing TiO6 octahedra in a 3D framework. "
            "Ba(1) is 12-fold coordinated."
        ),
    )

    result = sample_cases(
        db_path=str(db_path),
        out_path=str(out_path),
        n=1,
        text_view="robocrys",
        text_engine="robocrys",
        selection_mode="hash",
        query_mode="semantic",
        query_min_sentences=2,
        query_max_sentences=2,
        query_max_chars=700,
    )
    assert result["errors"] is None
    payload = json.loads(out_path.read_text(encoding="utf-8").splitlines()[0])
    assert "crystallizes in the cubic Pm-3m space group." in payload["query"]
    assert "corner-sharing TiO6 octahedra" in payload["query"]
    assert not payload["query"].endswith("Ba(1) is")
    assert payload["query_mode"] == "semantic"
    assert payload["query_sentences_used"] == 2
    assert payload["query_keywords_hit_count"] >= 1


def test_cases_sample_fallback_first_sentences():
    text = (
        "X crystallizes in the monoclinic P2_1/c space group. "
        "The atoms occupy two independent sites. "
        "A(1) is sixfold coordinated."
    )
    query = build_semantic_query(
        text,
        max_chars=500,
        min_sentences=2,
        max_sentences=3,
        keyword_list=["corner-sharing", "octahedra", "van der waals"],
    )
    assert query == (
        "X crystallizes in the monoclinic P2_1/c space group. "
        "The atoms occupy two independent sites."
    )
    assert not query.endswith("A(1) is")


def test_normalize_cases_dedupes_and_sorts(tmp_path):
    in_path = tmp_path / "cases_in.jsonl"
    out_path = tmp_path / "cases_out.jsonl"
    lines = [
        {
            "case_id": "b_case",
            "query": "q2",
            "expected": {"must_contain_any": ["x"]},
            "notes": "second",
        },
        {
            "case_id": "a_case",
            "query": "q1",
            "expected": {"must_contain_any": ["y"]},
            "notes": "first",
        },
        {
            "case_id": "b_case",
            "query": "q2",
            "expected": {"must_contain_any": ["x"]},
            "notes": "duplicate",
        },
    ]
    with open(in_path, "w", encoding="utf-8") as handle:
        for item in lines:
            handle.write(json.dumps(item) + "\n")

    result = normalize_cases(in_path=str(in_path), out_path=str(out_path))
    assert result["errors"] is None
    assert result["selected"] == 3
    assert result["written"] == 2

    written = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [item["case_id"] for item in written] == ["a_case", "b_case"]
    validate(result, "cases_normalize.v1")


def test_cases_sample_determinism(tmp_path):
    db_path = tmp_path / "sample.db"
    out_one = tmp_path / "sample_one.jsonl"
    out_two = tmp_path / "sample_two.jsonl"
    _seed_sample_db(db_path)

    first = sample_cases(
        db_path=str(db_path),
        out_path=str(out_one),
        n=2,
        text_view="caption",
        text_engine="caption",
        selection_mode="hash",
    )
    second = sample_cases(
        db_path=str(db_path),
        out_path=str(out_two),
        n=2,
        text_view="caption",
        text_engine="caption",
        selection_mode="hash",
    )
    assert first["errors"] is None
    assert second["errors"] is None
    assert out_one.read_text(encoding="utf-8") == out_two.read_text(encoding="utf-8")
    lines = [json.loads(line) for line in out_one.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    for idx, item in enumerate(lines, start=1):
        assert "expected" not in item
        assert item["query_mode"] == "semantic"
        assert validate_case_schema(item, idx) is None
    validate(first, "cases_sample.v1")


def test_cases_sample_self_label_mode_sets_expected_structure_ids(tmp_path):
    db_path = tmp_path / "sample_self.db"
    out_path = tmp_path / "sample_self.jsonl"
    _seed_sample_db(db_path)

    result = sample_cases(
        db_path=str(db_path),
        out_path=str(out_path),
        n=1,
        text_view="caption",
        text_engine="caption",
        selection_mode="hash",
        label_mode="self",
    )
    assert result["errors"] is None
    assert result["label_mode"] == "self"
    lines = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    case = lines[0]
    sid = case["provenance"]["structure_id"]
    assert case["expected_structure_ids"] == [sid]
    assert case.get("expected_formula") == case["provenance"]["formula"]
    assert validate_case_schema(case, 1) is None


def test_loader_accepts_existing_labeled_cases(tmp_path):
    path = tmp_path / "labeled_cases.jsonl"
    payload = {
        "case_id": "labeled_001",
        "query": "perovskite oxide",
        "expected": {"must_contain_any": ["perovskite"], "family": "perovskite"},
        "notes": "regression",
    }
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")
    cases, error = load_benchmark_cases(str(path))
    assert error is None
    assert cases is not None
    assert len(cases) == 1
    assert cases[0]["expected"]["family"] == "perovskite"


def test_cases_sample_cli_self_label_mode(tmp_path, capsys):
    db_path = tmp_path / "sample_cli.db"
    out_path = tmp_path / "sample_cli.jsonl"
    _seed_sample_db(db_path)

    code = main(
        [
            "cases-sample",
            "--db",
            str(db_path),
            "--out",
            str(out_path),
            "--n",
            "1",
            "--text-engine",
            "caption",
            "--text-view",
            "caption",
            "--label-mode",
            "self",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["errors"] is None
    case = json.loads(out_path.read_text(encoding="utf-8").splitlines()[0])
    assert case["expected_structure_ids"] == [case["provenance"]["structure_id"]]
