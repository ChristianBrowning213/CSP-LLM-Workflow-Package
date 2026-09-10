import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from .db import connect, init_db, resolve_db_path
from .embeddings import (
    DEFAULT_EMBED_ENGINE,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    resolve_embed_engine,
    resolve_model_version,
)
from .readiness import backend_status_to_error, inspect_backend_readiness
from .retrieval import text_search
from .runlog import RunLogger
from .utils import now_iso_utc, parse_formula

TEXT_VIEW_ROBOCRYS = "robocrys"
TEXT_VIEW_CAPTION = "caption"
FINGERPRINT_METHOD = "fp.simple.v1"
FINGERPRINT_VERSION = "v1"

FAMILY_PATTERNS: List[Tuple[str, str]] = [
    ("perovskite", "perovskite"),
    ("spinel", "spinel"),
    ("laves", "laves"),
    ("wurtzite", "wurtzite"),
    ("rocksalt", "rocksalt"),
    ("layered", "layered"),
    ("van der waals", "van_der_waals"),
    ("boride", "boride"),
]

CONNECTIVITY_PATTERNS: List[Tuple[str, str]] = [
    ("corner-sharing octahedra", "corner-sharing octahedra"),
    ("edge-sharing", "edge-sharing"),
    ("tetrahedra", "tetrahedra"),
    ("octahedra", "octahedra"),
    ("layered", "layered"),
    ("van der waals", "van der waals"),
    ("2d", "2d"),
]

CRYSTAL_SYSTEM_TOKENS = [
    "triclinic",
    "monoclinic",
    "orthorhombic",
    "tetragonal",
    "trigonal",
    "hexagonal",
    "cubic",
]


@dataclass(frozen=True)
class SPPCorpusSelectionConfig:
    minimum_spp_cifs: int = 5
    preferred_spp_cifs: int = 10
    max_spp_cifs: int = 50
    minimum_direct_pair_observations_per_required_pair: int = 20
    preferred_direct_pair_observations_per_required_pair: int = 50
    minimum_total_pair_observations_per_required_pair: int = 30
    preferred_total_pair_observations_per_required_pair: int = 100
    minimum_supported_required_pair_fraction: float = 1.0
    allow_partial_pair_coverage: bool = False
    allow_analogue_pair_support: bool = True
    analogue_pair_support_weight: float = 0.5
    direct_pair_support_weight: float = 1.0
    semantic_score_weight: float = 0.4
    pair_coverage_weight: float = 0.4
    chemistry_family_weight: float = 0.2
    semantic_min_threshold: float = 0.25
    chemistry_min_threshold: float = 0.0
    pair_support_min_threshold: float = 0.0
    max_cap_fraction_threshold: float = 0.5
    max_unusable_pair_fraction_for_solver_compatible: float = 0.0
    minimum_nonempty_histogram_bin_fraction: float = 0.1
    preferred_nonempty_histogram_bin_fraction: float = 0.25
    include_semantic_neighbours_in_spp_seed: bool = True
    expand_beyond_semantic_neighbours: bool = True
    require_all_target_elements_for_candidate: bool = False
    pair_level_candidate_selection: bool = True
    block_solver_compatible_spp_if_quality_fails: bool = True
    allow_diagnostic_pot_export_when_quality_fails: bool = True


def _spp_corpus_config(overrides: Optional[Dict[str, Any]] = None) -> SPPCorpusSelectionConfig:
    if not overrides:
        return SPPCorpusSelectionConfig()
    allowed = set(SPPCorpusSelectionConfig.__dataclass_fields__.keys())
    clean = {key: value for key, value in overrides.items() if key in allowed}
    return SPPCorpusSelectionConfig(**clean)

ELEMENT_TOKENS = {
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "U",
}


def _resolve_text_view(text_engine: str, text_view: Optional[str]) -> str:
    value = (text_view or "").strip().lower()
    if value:
        if value not in (TEXT_VIEW_ROBOCRYS, TEXT_VIEW_CAPTION):
            raise ValueError(f"unsupported text_view: {text_view}")
        return value
    return TEXT_VIEW_CAPTION if (text_engine or "").strip().lower() == "caption" else TEXT_VIEW_ROBOCRYS


def _decode_vector(raw_value: Any) -> Optional[List[float]]:
    if raw_value is None:
        return None
    if isinstance(raw_value, memoryview):
        raw_value = raw_value.tobytes()
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8", errors="replace")
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw_value, list):
        decoded = raw_value
    else:
        return None
    if not isinstance(decoded, list):
        return None
    try:
        return [float(item) for item in decoded]
    except (TypeError, ValueError):
        return None


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


def _safe_cif_filename(structure_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (structure_id or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or "structure"


def _normalize_text_doc_status(status: Optional[str]) -> str:
    return "ok" if str(status or "").upper() == "OK" else "failed"


def _load_display_text_doc(conn, structure_id: str, text_engine: str, text_view: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT id, engine, text_view, status, error_type, error_message, text, updated_at "
        "FROM text_docs WHERE structure_id = ? ORDER BY updated_at DESC, id DESC",
        (structure_id,),
    ).fetchall()
    if not rows:
        return {
            "text_doc_id": None,
            "text_engine": text_engine,
            "text_view": text_view,
            "status": "failed",
            "error": "text_doc_not_found",
        }

    selected = None
    if text_engine == "auto":
        for engine_name in ("caption", "robocrys", "baseline"):
            for row in rows:
                if (
                    row["engine"] == engine_name
                    and row["text_view"] == text_view
                    and _normalize_text_doc_status(row["status"]) == "ok"
                ):
                    selected = row
                    break
            if selected is not None:
                break
    else:
        for row in rows:
            if row["engine"] == text_engine and row["text_view"] == text_view:
                selected = row
                break

    if selected is None:
        return {
            "text_doc_id": None,
            "text_engine": text_engine,
            "text_view": text_view,
            "status": "failed",
            "error": f"text_doc_not_found_for_engine_or_view:{text_engine}/{text_view}",
        }

    status = _normalize_text_doc_status(selected["status"])
    error = selected["error_message"] or selected["error_type"]
    payload: Dict[str, Any] = {
        "text_doc_id": selected["id"],
        "text_engine": selected["engine"],
        "text_view": selected["text_view"],
        "status": status,
        "error": error,
    }
    if status == "ok" and selected["text"] is not None:
        payload["text"] = selected["text"]
    return payload


def _id_retrieval(
    *,
    structure_id: str,
    db_path: Optional[str],
    k: int,
    embed_engine: str,
    model_name: str,
    model_version: str,
    text_engine: str,
    text_view: str,
    redacted: bool,
    hybrid: bool,
    w_text: float,
    w_fp: float,
    backend_status: Dict[str, Any],
) -> Dict[str, Any]:
    conn = connect(db_path)
    init_db(conn)
    where = [
        "te.status = 'OK'",
        "te.embed_engine = ?",
        "te.model = ?",
        "te.model_version = ?",
        "td.text_view = ?",
    ]
    params: List[Any] = [embed_engine, model_name, model_version, text_view]
    if text_engine != "auto":
        where.append("td.engine = ?")
        params.append(text_engine)
    where_sql = " AND ".join(where)

    query_row = conn.execute(
        "SELECT te.vector "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        f"WHERE td.structure_id = ? AND {where_sql} "
        "ORDER BY te.id DESC LIMIT 1",
        tuple([structure_id] + params),
    ).fetchone()
    if query_row is None:
        conn.close()
        return {
            "status": "error",
            "query": {
                "mode": "id",
                "structure_id": structure_id,
                "embed_engine": embed_engine,
                "model_name": model_name,
                "model_version": model_version,
                "text_engine": text_engine,
                "text_view": text_view,
                "hybrid": hybrid,
                "w_text": w_text,
                "w_fp": w_fp,
                "k": k,
            },
            "neighbors": [],
            "errors": {
                "code": "candidate_set_empty",
                "message": "No query embedding found for structure id in the requested embedding space.",
                "diagnostics": {
                    "query_embedding_found": False,
                    "candidate_count": 0,
                    "searched_tables": ["text_docs", "text_embeddings"],
                    "filter_key": {
                        "embed_engine": embed_engine,
                        "model_name": model_name,
                        "model_version": model_version,
                        "text_engine": text_engine,
                        "text_view": text_view,
                    },
                },
            },
            "backend_status": backend_status,
        }

    query_vec = _decode_vector(query_row["vector"])
    if query_vec is None:
        conn.close()
        return {
            "status": "error",
            "query": {
                "mode": "id",
                "structure_id": structure_id,
                "embed_engine": embed_engine,
                "model_name": model_name,
                "model_version": model_version,
                "text_engine": text_engine,
                "text_view": text_view,
                "hybrid": hybrid,
                "w_text": w_text,
                "w_fp": w_fp,
                "k": k,
            },
            "neighbors": [],
            "errors": {
                "code": "candidate_set_empty",
                "message": "Query embedding could not be decoded.",
                "diagnostics": {"query_embedding_found": True, "candidate_count": 0},
            },
            "backend_status": backend_status,
        }

    rows = conn.execute(
        "SELECT td.structure_id, te.vector, p.source, p.source_id, p.retrieved_at, p.allow_export "
        "FROM text_embeddings te "
        "JOIN text_docs td ON td.id = te.text_doc_id "
        "LEFT JOIN provenance p ON p.structure_id = td.structure_id "
        f"WHERE {where_sql} AND td.structure_id != ? "
        "ORDER BY td.structure_id ASC, te.id DESC",
        tuple(params + [structure_id]),
    ).fetchall()
    if not rows:
        conn.close()
        return {
            "status": "empty",
            "query": {
                "mode": "id",
                "structure_id": structure_id,
                "embed_engine": embed_engine,
                "model_name": model_name,
                "model_version": model_version,
                "text_engine": text_engine,
                "text_view": text_view,
                "hybrid": hybrid,
                "w_text": w_text,
                "w_fp": w_fp,
                "k": k,
            },
            "neighbors": [],
            "errors": {
                "code": "empty_result",
                "message": "Backend is ready, but no other candidates are available for this structure id in the requested embedding space.",
                "diagnostics": {
                    "backend_ready": True,
                    "result_reason": "no_other_candidates_after_excluding_query",
                    "candidate_count": 0,
                    "query_embedding_found": True,
                    "searched_tables": ["text_docs", "text_embeddings"],
                },
            },
            "backend_status": backend_status,
        }

    best_by_structure: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        vec = _decode_vector(row["vector"])
        if vec is None or len(vec) != len(query_vec):
            continue
        sid = row["structure_id"]
        text_score = _cosine_similarity(query_vec, vec)
        existing = best_by_structure.get(sid)
        if existing is not None and existing["text_score"] >= text_score:
            continue
        best_by_structure[sid] = {
            "structure_id": sid,
            "text_score": text_score,
            "score": text_score,
            "provenance": {
                "source": row["source"],
                "source_id": row["source_id"],
                "retrieved_at": row["retrieved_at"],
                "allow_export": row["allow_export"],
            },
        }

    ranked = sorted(best_by_structure.values(), key=lambda item: (-item["score"], item["structure_id"]))
    if not ranked:
        conn.close()
        return {
            "status": "error",
            "query": {
                "mode": "id",
                "structure_id": structure_id,
                "embed_engine": embed_engine,
                "model_name": model_name,
                "model_version": model_version,
                "text_engine": text_engine,
                "text_view": text_view,
                "hybrid": hybrid,
                "w_text": w_text,
                "w_fp": w_fp,
                "k": k,
            },
            "neighbors": [],
            "errors": {
                "code": "candidate_set_empty",
                "message": "Candidates were present but unusable.",
                "diagnostics": {"query_embedding_found": True, "candidate_count": len(rows)},
            },
            "backend_status": backend_status,
        }

    if hybrid:
        fp_rows = conn.execute(
            "SELECT structure_id, vector_json FROM structure_fingerprints "
            "WHERE fingerprint_method = ? AND fingerprint_version = ?",
            (FINGERPRINT_METHOD, FINGERPRINT_VERSION),
        ).fetchall()
        fp_map: Dict[str, List[float]] = {}
        for row in fp_rows:
            vec = _decode_vector(row["vector_json"])
            if vec is not None:
                fp_map[row["structure_id"]] = vec
        query_fp = fp_map.get(structure_id)
        for item in ranked:
            fp_score = 0.0
            candidate_fp = fp_map.get(item["structure_id"])
            if (
                query_fp is not None
                and candidate_fp is not None
                and len(query_fp) == len(candidate_fp)
                and len(query_fp) > 0
            ):
                fp_score = _cosine_similarity(query_fp, candidate_fp)
            item["fp_score"] = fp_score
            item["final_score"] = w_text * item["text_score"] + w_fp * fp_score
            item["score"] = item["final_score"]
        ranked = sorted(ranked, key=lambda item: (-item["score"], -item["text_score"], item["structure_id"]))

    neighbors: List[Dict[str, Any]] = []
    for rank, item in enumerate(ranked[: max(1, k)], start=1):
        provenance = item["provenance"]
        content_redacted = redacted and provenance.get("allow_export") in (0, False)
        neighbor: Dict[str, Any] = {
            "rank": rank,
            "structure_id": item["structure_id"],
            "score": item["score"],
            "provenance": provenance,
            "redacted": bool(content_redacted),
        }
        if hybrid:
            neighbor["text_score"] = item.get("text_score", item["score"])
            neighbor["fp_score"] = item.get("fp_score", 0.0)
            neighbor["final_score"] = item.get("final_score", item["score"])
        text_doc = _load_display_text_doc(conn, item["structure_id"], text_engine, text_view)
        if content_redacted and "text" in text_doc:
            text_doc.pop("text", None)
            text_doc["error"] = text_doc.get("error") or "redacted_by_policy"
        neighbor["text_doc"] = text_doc
        neighbors.append(neighbor)

    conn.close()
    return {
        "status": "ok",
        "query": {
            "mode": "id",
            "structure_id": structure_id,
            "embed_engine": embed_engine,
            "model_name": model_name,
            "model_version": model_version,
            "text_engine": text_engine,
            "text_view": text_view,
            "hybrid": hybrid,
            "w_text": w_text,
            "w_fp": w_fp,
            "k": k,
        },
        "neighbors": neighbors,
        "errors": None,
        "backend_status": backend_status,
    }


def _collect_metadata(conn, structure_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not structure_ids:
        return {}
    placeholders = ", ".join(["?"] * len(structure_ids))
    rows = conn.execute(
        "SELECT structure_id, formula, space_group FROM metadata "
        f"WHERE structure_id IN ({placeholders})",
        tuple(structure_ids),
    ).fetchall()
    return {
        row["structure_id"]: {
            "formula": row["formula"],
            "space_group": row["space_group"],
        }
        for row in rows
    }


def _pair_label(left: str, right: str) -> str:
    parts = sorted([left.strip(), right.strip()], key=str.lower)
    return f"{parts[0]}-{parts[1]}"


def _elements_from_formula(formula: Optional[str]) -> List[str]:
    return sorted(parse_formula(formula).keys(), key=str.lower)


def _required_pairs_from_elements(elements: List[str]) -> List[str]:
    cleaned = []
    for element in elements:
        if element and element not in cleaned:
            cleaned.append(element)
    return sorted(
        {
            _pair_label(cleaned[i], cleaned[j])
            for i in range(len(cleaned))
            for j in range(i, len(cleaned))
        },
        key=str.lower,
    )


def _semantic_score(neighbor: Dict[str, Any]) -> float:
    value = neighbor.get("text_score", neighbor.get("score", 0.0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _candidate_tier(
    *,
    exact_formula: bool,
    candidate_elements: set[str],
    target_elements: set[str],
    covered_pairs: List[str],
) -> str:
    if exact_formula:
        return "tier_0_exact_formula"
    if target_elements and target_elements.issubset(candidate_elements):
        return "tier_1_same_element_set"
    if covered_pairs:
        return "tier_2_required_pair_support"
    return "tier_4_semantic_only"


def _chemistry_row(
    neighbor: Dict[str, Any],
    *,
    metadata: Dict[str, Any],
    target_formula: str,
    target_elements: List[str],
    required_pairs: List[str],
    semantic_min_threshold: float,
    config: Optional[SPPCorpusSelectionConfig] = None,
) -> Dict[str, Any]:
    cfg = config or SPPCorpusSelectionConfig()
    formula = str(metadata.get("formula") or "")
    elements = _elements_from_formula(formula)
    element_set = set(elements)
    target_set = set(target_elements)
    candidate_pairs = set(_required_pairs_from_elements(elements))
    covered_pairs = sorted(set(required_pairs).intersection(candidate_pairs), key=str.lower)
    semantic = _semantic_score(neighbor)
    chemistry_overlap = (len(target_set.intersection(element_set)) / float(len(target_set))) if target_set else 0.0
    pair_coverage = (len(covered_pairs) / float(len(required_pairs))) if required_pairs else 0.0
    exact_formula = bool(target_formula and formula.lower() == target_formula.lower())
    tier = _candidate_tier(
        exact_formula=exact_formula,
        candidate_elements=element_set,
        target_elements=target_set,
        covered_pairs=covered_pairs,
    )
    chemistry_family_score = chemistry_overlap
    pair_support_score = pair_coverage * cfg.direct_pair_support_weight
    final_spp_corpus_score = (
        cfg.semantic_score_weight * semantic
        + cfg.pair_coverage_weight * pair_support_score
        + cfg.chemistry_family_weight * chemistry_family_score
        + (0.10 if exact_formula else 0.0)
    )
    joint_score = semantic + 0.25 * chemistry_overlap + 0.35 * pair_coverage + (0.15 if exact_formula else 0.0)
    unsupported_pairs = [pair for pair in required_pairs if pair not in set(covered_pairs)]
    return {
        "structure_id": neighbor.get("structure_id"),
        "candidate_id": neighbor.get("structure_id"),
        "source_id": (neighbor.get("provenance") or {}).get("source_id"),
        "material_id": neighbor.get("structure_id"),
        "rank": neighbor.get("rank"),
        "semantic_score": round(semantic, 8),
        "semantic_pass": semantic >= semantic_min_threshold,
        "formula": formula or None,
        "elements": elements,
        "chemistry_overlap": round(chemistry_overlap, 8),
        "chemistry_family_score": round(chemistry_family_score, 8),
        "pair_coverage_utility": round(pair_coverage, 8),
        "direct_required_pairs_supported": covered_pairs,
        "analogue_required_pairs_supported": [],
        "unsupported_required_pairs": unsupported_pairs,
        "all_candidate_pairs_present": sorted(candidate_pairs, key=str.lower),
        "tier": tier,
        "score_components": {
            "semantic": round(cfg.semantic_score_weight * semantic, 8),
            "direct_pair_support": round(cfg.pair_coverage_weight * pair_support_score, 8),
            "chemistry_family": round(cfg.chemistry_family_weight * chemistry_family_score, 8),
            "exact_formula_bonus": 0.10 if exact_formula else 0.0,
        },
        "final_spp_corpus_score": round(final_spp_corpus_score, 8),
        "include_reason": None,
        "excluded_reason": None,
        "covered_pairs": covered_pairs,
        "missing_pairs": unsupported_pairs,
        "exact_formula_match": exact_formula,
        "joint_score": round(joint_score, 8),
    }


def _select_semantic_chemistry_corpus(
    *,
    neighbors: List[Dict[str, Any]],
    metadata_map: Dict[str, Dict[str, Any]],
    target_formula: str,
    semantic_min_threshold: float,
    export_top: int,
    spp_config: Optional[SPPCorpusSelectionConfig] = None,
) -> Tuple[List[str], Dict[str, Any], Optional[Dict[str, Any]]]:
    cfg = spp_config or SPPCorpusSelectionConfig()
    target_elements = _elements_from_formula(target_formula)
    required_pairs = _required_pairs_from_elements(target_elements)
    rows = [
        _chemistry_row(
            neighbor,
            metadata=metadata_map.get(str(neighbor.get("structure_id")), {}),
            target_formula=target_formula,
            target_elements=target_elements,
            required_pairs=required_pairs,
            semantic_min_threshold=semantic_min_threshold,
            config=cfg,
        )
        for neighbor in neighbors
        if neighbor.get("structure_id")
    ]
    above_floor = [row for row in rows if row["semantic_pass"]]
    below_floor = [row for row in rows if not row["semantic_pass"]]
    selected: List[Dict[str, Any]] = []
    covered: set[str] = set()
    max_selected = max(1, min(int(cfg.max_spp_cifs), max(int(export_top or 1), int(cfg.preferred_spp_cifs))))
    useful_rows = [
        row for row in above_floor
        if row["covered_pairs"]
        and (
            not cfg.require_all_target_elements_for_candidate
            or set(target_elements).issubset(set(row.get("elements") or []))
        )
    ]

    ranked = sorted(
        useful_rows,
        key=lambda row: (
            -float(row["final_spp_corpus_score"]),
            -float(row["joint_score"]),
            -float(row["semantic_score"]),
            str(row["structure_id"]),
        ),
    )

    def _select_row(row: Dict[str, Any], reason: str) -> None:
        row = dict(row)
        row["include_reason"] = reason
        selected.append(row)
        covered.update(str(pair) for pair in row["covered_pairs"])

    while len(selected) < max_selected and set(required_pairs) - covered:
        best: Optional[Dict[str, Any]] = None
        best_new_pairs = 0
        for row in ranked:
            if any(item["structure_id"] == row["structure_id"] for item in selected):
                continue
            new_pairs = len(set(row["covered_pairs"]) - covered)
            if best is None or new_pairs > best_new_pairs or (
                new_pairs == best_new_pairs
                and (
                    float(row["final_spp_corpus_score"]),
                    float(row["joint_score"]),
                    float(row["semantic_score"]),
                    str(row["structure_id"]),
                )
                > (
                    float(best["final_spp_corpus_score"]),
                    float(best["joint_score"]),
                    float(best["semantic_score"]),
                    str(best["structure_id"]),
                )
            ):
                best = row
                best_new_pairs = new_pairs
        if best is None:
            break
        if best_new_pairs <= 0 and covered:
            break
        _select_row(best, "adds_new_required_pair_evidence")

    for row in ranked:
        if len(selected) >= max_selected:
            break
        if len(selected) >= max(int(export_top or 0), int(cfg.preferred_spp_cifs)):
            break
        if any(item["structure_id"] == row["structure_id"] for item in selected):
            continue
        _select_row(row, "fills_preferred_spp_corpus_with_pair_evidence")

    missing_pairs = [pair for pair in required_pairs if pair not in covered]
    selected_ids = [str(row["structure_id"]) for row in selected if row.get("structure_id")]
    chemistry_rejected = [
        row for row in below_floor
        if float(row["chemistry_overlap"]) > 0.0 or float(row["pair_coverage_utility"]) > 0.0
    ]
    semantic_incomplete = [
        row for row in above_floor
        if float(row["pair_coverage_utility"]) < 1.0
    ]
    excluded_rows: List[Dict[str, Any]] = []
    selected_set = set(selected_ids)
    for row in rows:
        if row.get("structure_id") in selected_set:
            continue
        excluded = dict(row)
        if not excluded["semantic_pass"]:
            excluded["excluded_reason"] = "below_semantic_floor"
        elif not excluded["covered_pairs"]:
            excluded["excluded_reason"] = "semantic_only_no_required_pair_support"
        elif cfg.require_all_target_elements_for_candidate and not set(target_elements).issubset(set(excluded.get("elements") or [])):
            excluded["excluded_reason"] = "missing_required_target_elements"
        else:
            excluded["excluded_reason"] = "not_needed_after_pair_coverage_and_corpus_fill"
        excluded_rows.append(excluded)

    pair_support_summary = []
    for pair in required_pairs:
        direct_ids = [str(row["structure_id"]) for row in selected if pair in set(row.get("covered_pairs") or [])]
        semantic_only_ids = [
            str(row["structure_id"]) for row in above_floor
            if pair not in set(row.get("covered_pairs") or []) and not row.get("covered_pairs")
        ]
        direct_count = len(direct_ids)
        pair_support_summary.append(
            {
                "required_pair": pair,
                "direct_support_candidate_ids": direct_ids,
                "analogue_support_candidate_ids": [],
                "semantic_only_candidate_ids": semantic_only_ids,
                "direct_observation_count": direct_count,
                "analogue_observation_count": 0,
                "total_weighted_observation_count": round(direct_count * cfg.direct_pair_support_weight, 8),
                "nonempty_histogram_bin_fraction": None,
                "pair_quality": "usable" if direct_count > 0 else "missing",
                "pair_quality_reason": "direct_candidate_support" if direct_count > 0 else "no_direct_or_analogue_candidate_support",
            }
        )
    tiers_used = sorted({str(row.get("tier")) for row in selected if row.get("tier")})
    useful_partial_pair_evidence = bool(selected_ids and covered and missing_pairs)
    if not neighbors:
        corpus_selection_status = "no_semantic_support"
    elif not selected_ids and not above_floor:
        corpus_selection_status = "no_semantic_support"
    elif selected_ids and not missing_pairs:
        corpus_selection_status = "complete_pair_coverage"
    elif useful_partial_pair_evidence:
        corpus_selection_status = "partial_pair_coverage"
    elif above_floor:
        corpus_selection_status = "semantic_only_no_pair_coverage"
    else:
        corpus_selection_status = "no_exportable_cifs"
    selection_status = "usable" if not missing_pairs else "partial_pair_evidence" if useful_partial_pair_evidence else "missing_required_pair_evidence"
    if not missing_pairs and len(selected) < int(cfg.minimum_spp_cifs):
        selection_status = "sparse_pair_evidence"
    diagnostics: Dict[str, Any] = {
        "policy": "semantic_floor_pair_level_spp_corpus",
        "spp_corpus_selection_mode": "pair_level_evidence_expansion",
        "spp_corpus_config": asdict(cfg),
        "target_formula": target_formula,
        "target_elements": target_elements,
        "required_pairs": required_pairs,
        "semantic_min_threshold": semantic_min_threshold,
        "semantic_neighbour_count": len(neighbors),
        "semantic_neighbour_ids": [str(item.get("structure_id")) for item in neighbors if item.get("structure_id")],
        "spp_candidate_count_before_expansion": len(above_floor),
        "spp_candidate_count_after_expansion": len(useful_rows),
        "spp_exported_cif_count": len(selected_ids),
        "corpus_selection_status": corpus_selection_status,
        "covered_required_pairs": sorted(covered, key=str.lower),
        "missing_required_pairs": missing_pairs,
        "useful_partial_pair_evidence": useful_partial_pair_evidence,
        "exported_partial_cif_count": len(selected_ids) if useful_partial_pair_evidence else 0,
        "export_block_reason": None,
        "can_attempt_partial_spp": bool(selected_ids and covered),
        "can_attempt_qlip_without_fresh_spp": bool(selected_ids),
        "spp_corpus_ids": selected_ids,
        "spp_corpus_tiers_used": tiers_used,
        "spp_corpus_pair_support_summary": pair_support_summary,
        "spp_corpus_quality_status": selection_status,
        "semantic_candidates_considered": above_floor,
        "candidates_below_semantic_floor": below_floor,
        "chemistry_compatible_but_semantically_rejected": chemistry_rejected,
        "semantically_relevant_but_chemistry_incomplete": semantic_incomplete,
        "spp_corpus_candidates_selected": selected,
        "spp_corpus_candidates_excluded": excluded_rows,
        "selected_structure_ids": selected_ids,
        "selected_corpus_pair_coverage": {
            "covered_pairs": sorted(covered, key=str.lower),
            "missing_pairs": missing_pairs,
            "coverage_fraction": round(len(covered) / float(len(required_pairs)), 8) if required_pairs else 0.0,
        },
        "final_selection_reason": "selected_semantic_chemistry_corpus" if not missing_pairs else "selected_partial_semantic_chemistry_corpus" if useful_partial_pair_evidence else "no_valid_semantic_chemistry_corpus",
    }
    if not required_pairs or missing_pairs:
        has_chemistry_below_floor = bool(chemistry_rejected)
        has_semantic_support = bool(above_floor)
        if useful_partial_pair_evidence:
            reason = "semantic_support_exists_with_partial_pair_coverage"
        elif has_chemistry_below_floor and not any(float(row["pair_coverage_utility"]) > 0 for row in above_floor):
            reason = "chemistry_exists_but_below_semantic_floor"
        elif has_semantic_support:
            reason = "semantic_support_exists_but_pair_coverage_incomplete"
        else:
            reason = "no_chemistry_support_above_semantic_floor"
        diagnostics["final_selection_reason"] = reason
        error_code = "partial_pair_coverage" if useful_partial_pair_evidence else "no_valid_semantic_chemistry_corpus"
        error_message = (
            "Retrieved corpus has useful partial pair evidence but does not cover all required pairs."
            if useful_partial_pair_evidence
            else "No retrieved corpus satisfies both semantic relevance and chemistry/pair coverage requirements."
        )
        return selected_ids if useful_partial_pair_evidence else [], diagnostics, {
            "code": error_code,
            "message": error_message,
            "diagnostics": diagnostics,
        }
    return selected_ids, diagnostics, None


def _ranked_counts(counter: Dict[str, int]) -> List[Dict[str, Any]]:
    return [
        {"name": key, "count": counter[key]}
        for key in sorted(counter.keys(), key=lambda k: (-counter[k], k))
        if counter[key] > 0
    ]


def _extract_text_values(neighbors: List[Dict[str, Any]]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for item in neighbors:
        sid = item.get("structure_id")
        text_doc = item.get("text_doc") or {}
        text_value = text_doc.get("text")
        if not sid or not text_value:
            continue
        if text_doc.get("error") == "redacted_by_policy":
            continue
        values[sid] = str(text_value)
    return values


def _extract_hints(
    *,
    neighbors: List[Dict[str, Any]],
    metadata_map: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    family_counts: Dict[str, int] = {}
    connectivity_counts: Dict[str, int] = {}
    chemistry_counts: Dict[str, int] = {}
    symmetry_counts: Dict[str, int] = {}
    bond_lengths: List[float] = []
    tilt_angles: List[float] = []

    text_by_structure = _extract_text_values(neighbors)
    usable_items = 0
    for item in neighbors:
        sid = item.get("structure_id")
        if not sid:
            continue
        meta = metadata_map.get(sid, {})
        formula = meta.get("formula")
        if formula:
            for token, count in parse_formula(str(formula)).items():
                chemistry_counts[token] = chemistry_counts.get(token, 0) + int(count)

        space_group = meta.get("space_group")
        if space_group:
            symmetry_counts[str(space_group)] = symmetry_counts.get(str(space_group), 0) + 1

        text = text_by_structure.get(sid, "")
        if not text:
            continue
        usable_items += 1
        lowered = text.lower()
        for raw, normalized in FAMILY_PATTERNS:
            if raw in lowered:
                family_counts[normalized] = family_counts.get(normalized, 0) + 1
        for raw, normalized in CONNECTIVITY_PATTERNS:
            if raw in lowered:
                connectivity_counts[normalized] = connectivity_counts.get(normalized, 0) + 1
        for token in CRYSTAL_SYSTEM_TOKENS:
            if token in lowered:
                symmetry_counts[token] = symmetry_counts.get(token, 0) + 1

        for value in re.findall(r"(\d+(?:\.\d+)?)\s*(?:a|å|angstrom)\b", lowered):
            bond_lengths.append(float(value))
        for value in re.findall(r"(?:tilt|angle)[^0-9]{0,12}(\d+(?:\.\d+)?)", lowered):
            tilt_angles.append(float(value))
        for token in re.findall(r"\b([A-Z][a-z]?)\b", text):
            if token in ELEMENT_TOKENS:
                chemistry_counts[token] = chemistry_counts.get(token, 0) + 1

    family_candidates = _ranked_counts(family_counts)
    connectivity_keywords = _ranked_counts(connectivity_counts)
    chemistry_tokens = [item["name"] for item in _ranked_counts(chemistry_counts)]
    symmetry_tokens = [item["name"] for item in _ranked_counts(symmetry_counts)]

    has_any = bool(family_candidates or connectivity_keywords or chemistry_tokens or symmetry_tokens)
    if not has_any and usable_items == 0:
        return None, {
            "code": "hint_extraction_unavailable",
            "message": "No usable text or metadata was available for hint extraction.",
            "diagnostics": {
                "neighbor_count": len(neighbors),
                "usable_text_count": usable_items,
            },
        }

    family_agreement = family_candidates[0]["count"] if family_candidates else 0
    connectivity_agreement = connectivity_keywords[0]["count"] if connectivity_keywords else 0
    denom = max(1, usable_items)
    confidence = min(1.0, (family_agreement + connectivity_agreement) / float(2 * denom))

    quantitative = {}
    if bond_lengths:
        quantitative["bond_length_angstrom"] = {"min": round(min(bond_lengths), 4), "max": round(max(bond_lengths), 4)}
    if tilt_angles:
        quantitative["tilt_angle_deg"] = {"min": round(min(tilt_angles), 4), "max": round(max(tilt_angles), 4)}

    hints = {
        "family_candidates": family_candidates,
        "connectivity_keywords": connectivity_keywords,
        "chemistry_tokens": chemistry_tokens,
        "symmetry_tokens": symmetry_tokens,
        "quantitative_clues": quantitative,
        "confidence": round(confidence, 4),
        "usable_text_count": usable_items,
    }
    return hints, None


def derive_hints_for_neighbors(
    *,
    db_path: Optional[str],
    neighbors: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    conn = connect(db_path)
    init_db(conn)
    metadata_map = _collect_metadata(conn, [str(item.get("structure_id")) for item in neighbors if item.get("structure_id")])
    conn.close()
    return _extract_hints(neighbors=neighbors, metadata_map=metadata_map)


def _export_bundle(
    *,
    conn,
    neighbors: List[Dict[str, Any]],
    out_dir: Optional[str],
    export_top: int,
    demo_export: bool,
    selected_structure_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not out_dir:
        return {
            "out_dir": None,
            "manifest_path": None,
            "results_path": None,
            "cif_dir": None,
            "items": [],
        }

    abs_out_dir = os.path.abspath(out_dir)
    cif_dir = os.path.join(abs_out_dir, "cifs")
    os.makedirs(cif_dir, exist_ok=True)
    items: List[Dict[str, Any]] = []
    selected_ids = set(selected_structure_ids or [])
    for item in neighbors:
        rank = int(item.get("rank", 0))
        structure_id = item.get("structure_id")
        provenance = item.get("provenance") or {}
        allow_export = provenance.get("allow_export")
        export_item = {
            "structure_id": structure_id,
            "rank": rank,
            "score": item.get("score"),
            "source_id": provenance.get("source_id"),
            "export_status": "skipped",
            "cif_path": None,
            "error": None,
        }
        if selected_structure_ids is not None and structure_id not in selected_ids:
            export_item["error"] = "not_selected_for_spp_corpus"
            items.append(export_item)
            continue
        if selected_structure_ids is None and rank > export_top:
            items.append(export_item)
            continue
        if allow_export in (0, False) and not demo_export:
            export_item["export_status"] = "blocked"
            export_item["error"] = "policy_blocked: allow_export=0 and demo_export=false"
            items.append(export_item)
            continue
        row = conn.execute(
            "SELECT cif_text FROM structures WHERE structure_id = ?",
            (structure_id,),
        ).fetchone()
        if row is None or row["cif_text"] is None:
            export_item["export_status"] = "error"
            export_item["error"] = "export_failed: cif_missing"
            items.append(export_item)
            continue
        try:
            out_path = os.path.join(cif_dir, _safe_cif_filename(str(structure_id)) + ".cif")
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write(row["cif_text"])
            export_item["export_status"] = "exported"
            export_item["cif_path"] = out_path
        except Exception as exc:  # pylint: disable=broad-except
            export_item["export_status"] = "error"
            export_item["error"] = f"export_failed: {exc}"
        items.append(export_item)
    return {
        "out_dir": abs_out_dir,
        "manifest_path": os.path.join(abs_out_dir, "manifest.json"),
        "results_path": os.path.join(abs_out_dir, "results.json"),
        "cif_dir": cif_dir,
        "items": items,
    }


def run_csp_pack(
    *,
    db_path: Optional[str],
    query_text: Optional[str],
    structure_id: Optional[str],
    k: int = 10,
    embed_engine: str = DEFAULT_EMBED_ENGINE,
    model_name: Optional[str] = DEFAULT_MODEL_NAME,
    model_version: Optional[str] = DEFAULT_MODEL_VERSION,
    text_engine: str = "caption",
    text_view: Optional[str] = "caption",
    hybrid: bool = True,
    w_text: float = 0.7,
    w_fp: float = 0.3,
    out_dir: Optional[str] = None,
    export_top: Optional[int] = None,
    redacted: bool = True,
    demo_export: bool = False,
    run_name: Optional[str] = None,
    material_system: Optional[str] = None,
    formula: Optional[str] = None,
    semantic_min_threshold: Optional[float] = None,
    spp_corpus_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    query_value = (query_text or "").strip()
    sid_value = (structure_id or "").strip()
    if not query_value and not sid_value:
        return {
            "run_id": None,
            "status": "error",
            "query": None,
            "neighbors": [],
            "hints": None,
            "export": None,
            "errors": {"code": "invalid_input", "message": "Provide --query or --id."},
            "backend_status": None,
        }
    if query_value and sid_value:
        return {
            "run_id": None,
            "status": "error",
            "query": None,
            "neighbors": [],
            "hints": None,
            "export": None,
            "errors": {"code": "invalid_input", "message": "Use exactly one of --query or --id."},
            "backend_status": None,
        }

    if k <= 0:
        k = 1
    if export_top is None:
        export_top = k
    if export_top < 0:
        export_top = 0
    model = model_name or DEFAULT_MODEL_NAME
    resolved_engine = resolve_embed_engine(embed_engine, model)
    resolved_model_version = resolve_model_version(model, model_version, embed_engine=resolved_engine)
    resolved_text_view = _resolve_text_view(text_engine, text_view)

    args = {
        "query": query_value if query_value else None,
        "structure_id": sid_value if sid_value else None,
        "k": k,
        "engine": resolved_engine,
        "model": model,
        "model_version": resolved_model_version,
        "text_engine": text_engine,
        "text_view": resolved_text_view,
        "hybrid": hybrid,
        "w_text": w_text,
        "w_fp": w_fp,
        "out": out_dir,
        "export_top": export_top,
        "redacted": redacted,
        "demo_export": demo_export,
        "run_name": run_name,
        "material_system": material_system,
        "formula": formula,
        "semantic_min_threshold": semantic_min_threshold,
        "spp_corpus_config": spp_corpus_config,
    }

    backend_status = inspect_backend_readiness(
        db_path=db_path or "",
        surface="csp_pack",
        query_mode="id" if sid_value else "query",
        text_engine=text_engine,
        text_view=resolved_text_view,
        embed_engine=resolved_engine,
        model_name=model,
        model_version=resolved_model_version,
        require_fingerprint_index=bool(hybrid),
        query_structure_id=sid_value or None,
    )
    if not backend_status["ready"]:
        retrieval_error = backend_status_to_error(backend_status)
        return {
            "run_id": None,
            "status": "error",
            "query": {
                "mode": "id" if sid_value else "query",
                "structure_id": sid_value or None,
                "text": query_value if query_value else None,
                "embed_engine": resolved_engine,
                "model_name": model,
                "model_version": resolved_model_version,
                "text_engine": text_engine,
                "text_view": resolved_text_view,
                "hybrid": hybrid,
                "w_text": w_text,
                "w_fp": w_fp,
                "k": k,
            },
            "neighbors": [],
            "hints": None,
            "export": None,
            "errors": retrieval_error,
            "backend_status": backend_status,
        }

    logger = RunLogger(db_path)
    run_id = logger.start_run("csp-pack", args)

    retrieval_input = dict(args)
    if query_value:
        retrieval_result = text_search(
            query_text=query_value,
            db_path=db_path,
            k=k,
            embed_engine=resolved_engine,
            model_name=model,
            model_version=resolved_model_version,
            text_engine=text_engine,
            text_view=resolved_text_view,
            hybrid=hybrid,
            w_text=w_text,
            w_fp=w_fp,
            show_text_top=k,
            export_dir=None,
            export_top=0,
            redacted=redacted,
            demo_export=demo_export,
        )
    else:
        retrieval_result = _id_retrieval(
            structure_id=sid_value,
            db_path=db_path,
            k=k,
            embed_engine=resolved_engine,
            model_name=model,
            model_version=resolved_model_version,
            text_engine=text_engine,
            text_view=resolved_text_view,
            redacted=redacted,
            hybrid=hybrid,
            w_text=w_text,
            w_fp=w_fp,
            backend_status=backend_status,
        )
    retrieval_errors = retrieval_result.get("errors")
    retrieval_status = str(retrieval_result.get("status") or ("error" if retrieval_errors else "ok"))
    logger.log_step(
        "csp_pack_retrieval",
        retrieval_input,
        retrieval_result,
        "error" if retrieval_status == "error" else retrieval_status,
        error_text=(retrieval_errors or {}).get("message") if isinstance(retrieval_errors, dict) else None,
    )
    logger.add_evidence("retrieval", retrieval_result)
    if retrieval_status == "error":
        logger.finalize_run(status="error", error_text=(retrieval_errors or {}).get("message"))
        return {
            "run_id": run_id,
            "status": "error",
            "query": retrieval_result.get("query"),
            "neighbors": [],
            "hints": None,
            "export": None,
            "errors": retrieval_errors,
            "backend_status": retrieval_result.get("backend_status", backend_status),
        }
    if retrieval_status == "empty":
        logger.finalize_run(status="empty", error_text=(retrieval_errors or {}).get("message"))
        return {
            "run_id": run_id,
            "status": "empty",
            "query": retrieval_result.get("query"),
            "neighbors": [],
            "hints": None,
            "export": None,
            "errors": retrieval_errors,
            "backend_status": retrieval_result.get("backend_status", backend_status),
        }

    neighbors = retrieval_result.get("neighbors", [])
    for item in neighbors:
        sid = item.get("structure_id")
        if sid:
            logger.add_explored(str(sid), "retrieved_neighbor")

    conn = connect(db_path)
    init_db(conn)
    metadata_map = _collect_metadata(conn, [str(item.get("structure_id")) for item in neighbors if item.get("structure_id")])
    hints, hint_error = _extract_hints(neighbors=neighbors, metadata_map=metadata_map)
    hint_step_output = {"hints": hints, "errors": hint_error}
    logger.log_step(
        "csp_pack_hints",
        {"neighbor_count": len(neighbors)},
        hint_step_output,
        "error" if hint_error else "ok",
        error_text=(hint_error or {}).get("message") if isinstance(hint_error, dict) else None,
    )
    logger.add_evidence("hints", hint_step_output)
    if hint_error:
        conn.close()
        logger.finalize_run(status="error", error_text=hint_error["message"])
        return {
            "run_id": run_id,
            "status": "error",
            "query": retrieval_result.get("query"),
            "neighbors": neighbors,
            "hints": None,
            "export": None,
            "errors": hint_error,
            "backend_status": retrieval_result.get("backend_status", backend_status),
        }

    target_formula = (formula or material_system or "").strip()
    selected_structure_ids: Optional[List[str]] = None
    corpus_selection: Optional[Dict[str, Any]] = None
    corpus_selection_error: Optional[Dict[str, Any]] = None
    if target_formula and semantic_min_threshold is not None:
        resolved_spp_config = _spp_corpus_config(spp_corpus_config)
        selected_structure_ids, corpus_selection, corpus_selection_error = _select_semantic_chemistry_corpus(
            neighbors=neighbors,
            metadata_map=metadata_map,
            target_formula=target_formula,
            semantic_min_threshold=float(semantic_min_threshold),
            export_top=export_top,
            spp_config=resolved_spp_config,
        )
        logger.log_step(
            "csp_pack_corpus_selection",
            {
                "material_system": material_system,
                "formula": formula,
                "semantic_min_threshold": semantic_min_threshold,
                "export_top": export_top,
            },
            {"selection": corpus_selection, "errors": corpus_selection_error},
            "partial" if corpus_selection_error else "ok",
            error_text=(corpus_selection_error or {}).get("message") if isinstance(corpus_selection_error, dict) else None,
        )
        logger.add_evidence("corpus_selection", {"selection": corpus_selection, "errors": corpus_selection_error})

    export_payload = _export_bundle(
        conn=conn,
        neighbors=neighbors,
        out_dir=out_dir,
        export_top=export_top,
        demo_export=demo_export,
        selected_structure_ids=selected_structure_ids,
    )
    conn.close()
    logger.log_step("csp_pack_export", {"out_dir": out_dir, "export_top": export_top}, export_payload, "ok")

    manifest_payload = None
    if export_payload["out_dir"]:
        os.makedirs(export_payload["out_dir"], exist_ok=True)
        manifest_payload = {
            "created_at": now_iso_utc(),
            "run_id": run_id,
            "db_path_basename": os.path.basename(resolve_db_path(db_path)),
            "retrieval_config": retrieval_result.get("query"),
            "structures": [
                {
                    "structure_id": item["structure_id"],
                    "rank": item["rank"],
                    "score": item.get("score"),
                    "provenance_source_id": (item.get("provenance") or {}).get("source_id"),
                    "export_status": exp.get("export_status"),
                    "cif_path": exp.get("cif_path"),
                }
                for item, exp in zip(neighbors, export_payload["items"])
            ],
            "hints": hints,
            "corpus_selection": corpus_selection,
        }
        with open(export_payload["manifest_path"], "w", encoding="utf-8") as handle:
            json.dump(manifest_payload, handle, indent=2)
    logger.add_evidence(
        "export",
        {
            "manifest": manifest_payload,
            "export": export_payload,
        },
    )

    result = {
        "run_id": run_id,
        "status": "partial" if corpus_selection_error else "ok",
        "query": retrieval_result.get("query"),
        "neighbors": neighbors,
        "hints": hints,
        "export": export_payload,
        "errors": corpus_selection_error,
        "backend_status": retrieval_result.get("backend_status", backend_status),
        "corpus_selection": corpus_selection,
    }
    if export_payload["results_path"]:
        with open(export_payload["results_path"], "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)

    logger.finalize_run(status="partial" if corpus_selection_error else "ok", error_text=(corpus_selection_error or {}).get("message") if isinstance(corpus_selection_error, dict) else None)
    return result
