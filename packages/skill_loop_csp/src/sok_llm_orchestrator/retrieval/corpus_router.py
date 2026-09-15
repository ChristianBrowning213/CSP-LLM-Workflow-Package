"""Deterministic corpus routing for the canonical CSP workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sok_llm_orchestrator.retrieval.specialist_corpora import resolve_corpus


_CANONICAL_NASICON_FORMULAS = frozenset(
    {
        "na3zr2si2po12",
        "na3ti2(po4)3",
        "lizr2(po4)3",
        "na3ti2si2po12",
        "na3hf2si2po12",
    }
)


@dataclass(frozen=True, slots=True)
class CorpusRoute:
    corpus_id: str
    database: Path
    route_reason: str
    evaluation_holdout: bool


def is_nasicon_request(text: str, formula: str | None = None) -> bool:
    value = f"{text} {formula or ''}".lower()
    formula_key = str(formula or "").replace(" ", "").lower()
    return (
        formula_key in _CANONICAL_NASICON_FORMULAS
        or any(token in value for token in ("nasicon", "nzp", "na3zr2si2po12"))
    )


def is_spinel_oxide_request(text: str) -> bool:
    value = str(text).lower()
    return "spinel" in value and "oxide" in value


def is_layered_battery_oxide_request(text: str) -> bool:
    value = str(text).lower()
    return "layered" in value and "oxide" in value


def route_corpus(
    text: str,
    *,
    formula: str | None = None,
    evaluation_holdout: bool = False,
    registry_path: Path | None = None,
    logical_selector: str = "auto",
    crystal_db_root: Path | None = None,
) -> CorpusRoute:
    # Paper_scaffolds_september specialist family selectors map to frozen
    # accepted-only Crystal-DB rebuilds registered under paper_scaffolds_* keys.
    _SPECIALIST_SELECTORS = {
        "rocksalt": "paper_scaffolds_rocksalt_v1",
        "olivine": "paper_scaffolds_olivine_v2",
        "ruddlesden_popper": "paper_scaffolds_ruddlesden_popper_v1",
        "garnet": "paper_scaffolds_garnet_v1",
        "nasicon": "paper_scaffolds_nasicon_v1",
        "argyrodite": "paper_scaffolds_argyrodite_v2",
    }
    allowed = {"auto", "general", "spinel", "layered"} | set(_SPECIALIST_SELECTORS)
    if logical_selector not in allowed:
        raise ValueError(f"unsupported logical database selector: {logical_selector}")
    if logical_selector == "general":
        corpus_id = "mp_stable_10k_v1"
        reason = "explicit logical general corpus selection"
    elif logical_selector == "spinel":
        corpus_id = "mp_spinel_oxides_v1"
        reason = "explicit logical spinel corpus selection"
    elif logical_selector == "layered":
        corpus_id = "mp_layered_battery_oxides_v1"
        reason = "explicit logical layered corpus selection"
    elif logical_selector in _SPECIALIST_SELECTORS:
        corpus_id = _SPECIALIST_SELECTORS[logical_selector]
        reason = f"explicit logical {logical_selector} specialist corpus selection"
    elif is_nasicon_request(text, formula):
        corpus_id = "nasicon_specialist_all_targets_out_v3" if evaluation_holdout else "nasicon_specialist_v3"
        reason = "NASICON/NZP request routed to the specialist Crystal-DB corpus"
    elif is_spinel_oxide_request(text):
        corpus_id = "mp_spinel_oxides_v1"
        reason = "spinel oxide request routed to the versioned specialist Crystal-DB corpus"
    elif is_layered_battery_oxide_request(text):
        corpus_id = "mp_layered_battery_oxides_v1"
        reason = "layered oxide request routed to the versioned specialist Crystal-DB corpus"
    else:
        corpus_id = "mp_stable_10k_v1"
        reason = "ordinary material request routed to the canonical general Crystal-DB corpus"
    resolved = resolve_corpus(
        corpus_id,
        registry_path,
        crystal_db_root=crystal_db_root,
    )
    return CorpusRoute(
        corpus_id=corpus_id,
        database=Path(resolved["database"]),
        route_reason=reason,
        evaluation_holdout=bool(evaluation_holdout),
    )


__all__ = [
    "CorpusRoute",
    "is_layered_battery_oxide_request",
    "is_nasicon_request",
    "is_spinel_oxide_request",
    "route_corpus",
]
