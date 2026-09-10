"""Retrieval integration package boundary."""
"""Workflow-facing retrieval normalization over packaged Crystal-DB."""

from .adapter import EvidenceRecord, RetrievalStageResult, retrieve_evidence

__all__ = ["EvidenceRecord", "RetrievalStageResult", "retrieve_evidence"]
