import csv
import json
from pathlib import Path

from crystal_db.crystaldb_retrieval_pdf import (
    classify_cif_neighbourhood,
    render_crystaldb_neighbourhood_pdf,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "crystaldb_retrieval" / "neighbourhood_fixture.json"


def _load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_classifies_blocked_neighbourhood():
    assert classify_cif_neighbourhood(0) == "blocked"


def test_classifies_sparse_neighbourhood():
    assert classify_cif_neighbourhood(2, min_fit_ready=3) == "sparse"


def test_classifies_fit_ready_neighbourhood():
    assert classify_cif_neighbourhood(3, min_fit_ready=3) == "fit_ready"


def test_renders_pdf_json_and_csv(tmp_path):
    fixture = _load_fixture()
    result = render_crystaldb_neighbourhood_pdf(
        fixture,
        output_pdf=tmp_path / "neighbourhood.pdf",
        output_json=tmp_path / "neighbourhood.json",
        output_csv=tmp_path / "neighbourhood.csv",
        title="Crystal-DB semantic retrieval neighbourhood for perovskite-like BaTiO3 / CaTiO3 query",
    )

    pdf_path = Path(result["pdf_path"])
    json_path = Path(result["json_path"])
    csv_path = Path(result["csv_path"])

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000
    assert json_path.exists()
    assert csv_path.exists()
    assert result["exportable_cif_count"] == 2
    assert result["neighbour_count"] == 4
    assert result["spp_corpus_status"] == "sparse"

    sidecar = json.loads(json_path.read_text(encoding="utf-8"))
    assert sidecar["query"] == "perovskite-like BaTiO3 or CaTiO3 candidates"
    assert sidecar["computed"]["exportable_cif_count"] == 2
    assert sidecar["computed"]["spp_corpus_status"] == "sparse"
    assert sidecar["neighbours"][2]["blocked_reason"] == "export policy blocked"

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert rows[0]["structure_id"] == "mp-batio3-demo-001"
    assert rows[0]["cif_exportable"] == "True"
    assert rows[2]["blocked_reason"] == "export policy blocked"
