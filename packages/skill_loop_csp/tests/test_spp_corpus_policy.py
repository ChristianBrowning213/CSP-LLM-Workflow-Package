from __future__ import annotations

import pytest

from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle
from sok_llm_orchestrator.spp.corpus_policy import select_corpus_manifest


def test_spp_corpus_manifest_is_reproducible() -> None:
    retrieval = RetrievalBundle(
        retrieval_id="retrieval-1",
        mode="metadata",
        fusion_notes=[],
        items=[
            {
                "structure_id": "mp-1",
                "provenance": "db",
                "scores": {"score": 0.9},
                "property_metadata": {"property_x": 0.8},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "composition",
            },
            {
                "structure_id": "mp-2",
                "provenance": "db",
                "scores": {"score": 0.8},
                "property_metadata": {"property_x": 0.6},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "composition",
            },
        ],
    )
    m1 = select_corpus_manifest(retrieval, "top_k", top_k=2)
    m2 = select_corpus_manifest(retrieval, "top_k", top_k=2)
    assert m1.content_hash == m2.content_hash
    assert m1.selected_ids == ["mp-1", "mp-2"]


def test_property_biased_corpus_requires_explicit_metadata_key() -> None:
    retrieval = RetrievalBundle(
        retrieval_id="retrieval-prop",
        mode="metadata",
        fusion_notes=[],
        items=[
            {
                "structure_id": "mp-1",
                "provenance": "db",
                "scores": {"score": 0.1},
                "property_metadata": {"property_x": 0.3},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "property match",
            },
            {
                "structure_id": "mp-2",
                "provenance": "db",
                "scores": {"score": 0.9},
                "property_metadata": {"property_x": 0.9},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "property match",
            },
        ],
    )
    manifest = select_corpus_manifest(retrieval, "property_biased", top_k=2, property_key="property_x")
    assert manifest.selected_ids == ["mp-2", "mp-1"]


def test_property_biased_corpus_fails_when_metadata_missing() -> None:
    retrieval = RetrievalBundle(
        retrieval_id="retrieval-missing",
        mode="metadata",
        fusion_notes=[],
        items=[
            {
                "structure_id": "mp-1",
                "provenance": "db",
                "scores": {"score": 0.9},
                "property_metadata": {"different_key": 0.1},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "property match",
            }
        ],
    )
    with pytest.raises(ValueError, match="No retrieval rows contain numeric metadata"):
        select_corpus_manifest(retrieval, "property_biased", top_k=1, property_key="property_x")
