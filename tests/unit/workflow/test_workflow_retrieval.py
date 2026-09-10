from llm_csp.retrieval import EvidenceRecord, RetrievalStageResult, retrieve_evidence
from llm_csp.schemas import CSPWorkflowRequest, RetrievalConfig


REQUEST = CSPWorkflowRequest(
    "SrTiO3", "SrTiO3",
    {"template": {"lattice": {}}, "sites": {"mode": "uniform_grid"}},
)


def test_provider_exception_is_backend_unavailable(tmp_path) -> None:
    def provider(**kwargs):
        raise ConnectionError("offline")

    result = retrieve_evidence(REQUEST, RetrievalConfig(), tmp_path / "export", provider=provider)
    assert result.status == "retrieval_backend_unavailable"


def test_empty_provider_result_is_distinct(tmp_path) -> None:
    result = retrieve_evidence(
        REQUEST, RetrievalConfig(), tmp_path / "export",
        provider=lambda **kwargs: RetrievalStageResult("retrieval_success", "fixture"),
    )
    assert result.status == "retrieval_empty"


def test_nonexportable_result_is_distinct(tmp_path) -> None:
    result = retrieve_evidence(
        REQUEST,
        RetrievalConfig(),
        tmp_path / "export",
        provider=lambda **kwargs: RetrievalStageResult(
            "retrieval_success", "fixture", (EvidenceRecord("id", 1.0, None),)
        ),
    )
    assert result.status == "retrieval_no_exportable_cifs"


def test_exportable_result_is_preserved(tmp_path) -> None:
    cif = tmp_path / "safe.cif"
    cif.write_text("fixture", encoding="utf-8")
    record = EvidenceRecord("id", 0.9, str(cif), {"source": "synthetic"})
    result = retrieve_evidence(
        REQUEST,
        RetrievalConfig(),
        tmp_path / "export",
        provider=lambda **kwargs: RetrievalStageResult("retrieval_success", "fixture", (record,)),
    )
    assert result.status == "retrieval_success"
    assert result.records == (record,)


def test_embedding_incompatibility_is_preserved(tmp_path) -> None:
    result = retrieve_evidence(
        REQUEST,
        RetrievalConfig(),
        tmp_path / "export",
        provider=lambda **kwargs: RetrievalStageResult(
            "retrieval_embedding_incompatible", "fixture", diagnostics={"code": "dimension_mismatch"}
        ),
    )
    assert result.status == "retrieval_embedding_incompatible"
