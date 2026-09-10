"""Versioned crystallographic scaffold registry and occupation helpers."""

from .registry import (
    ScaffoldCorpusConfigurationError,
    ScaffoldCorpusResolution,
    get_scaffold,
    list_scaffolds,
    resolve_scaffold_corpus_root,
    validate_scaffold,
)
from .schema import ScaffoldRecord, ScaffoldValidation

__all__ = [
    "ScaffoldRecord",
    "ScaffoldValidation",
    "ScaffoldCorpusConfigurationError",
    "ScaffoldCorpusResolution",
    "get_scaffold",
    "list_scaffolds",
    "resolve_scaffold_corpus_root",
    "validate_scaffold",
]
