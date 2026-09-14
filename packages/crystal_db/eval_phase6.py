import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from crystal_db.crystalcard import build_crystalcard
from crystal_db.db import connect, init_db
from crystal_db.embeddings import DEFAULT_MODEL_NAME, DEFAULT_MODEL_VERSION, embed_text, l2_distance
from crystal_db.fingerprint import FINGERPRINT_METHOD, FINGERPRINT_VERSION, fingerprint_structure
from crystal_db.ingest import ingest_sample
from crystal_db.ingest_folder import ingest_folder
from crystal_db.novelty import run_novelty
from crystal_db.retrieval import similar_hybrid, similar_seq, similar_struct, similar_text
from crystal_db.sequence_index import canonicalize_cif, embed_sequences, encode_sequences
from crystal_db.text_index import embed_texts
from crystal_db.textgen import generate_text


def _structure_id_for_source(db_path: str, source: str, source_id: str) -> str:
    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT structure_id FROM provenance WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    conn.close()
    return row["structure_id"]


def _load_gold(db_path: str) -> List[str]:
    gold_dir = Path(__file__).resolve().parents[0] / "data" / "gold"
    if not gold_dir.exists():
        gold_dir = Path("data") / "gold"
    ingest_folder(
        db_path=db_path,
        folder_path=str(gold_dir),
        source="gold",
        policy_name="synthetic",
        cache_dir=None,
    )
    expectations = json.loads((gold_dir / "gold_expectations.json").read_text(encoding="utf-8"))
    return [_structure_id_for_source(db_path, "gold", entry["file"]) for entry in expectations]


def _load_embeddings(db_path: str, modality: str, model_name: str, model_version: str) -> Dict[str, List[float]]:
    conn = connect(db_path)
    init_db(conn)
    rows = conn.execute(
        "SELECT structure_id, vector_json FROM structure_embeddings "
        "WHERE modality = ? AND model_name = ? AND model_version = ?",
        (modality, model_name, model_version),
    ).fetchall()
    conn.close()
    return {row["structure_id"]: json.loads(row["vector_json"]) for row in rows}


def _load_fingerprints(db_path: str) -> Dict[str, List[float]]:
    conn = connect(db_path)
    init_db(conn)
    rows = conn.execute(
        "SELECT structure_id, vector_json FROM structure_fingerprints "
        "WHERE fingerprint_method = ? AND fingerprint_version = ?",
        (FINGERPRINT_METHOD, FINGERPRINT_VERSION),
    ).fetchall()
    conn.close()
    return {row["structure_id"]: json.loads(row["vector_json"]) for row in rows}


def _rank_target(distances: List[Tuple[str, float]], target_id: str) -> int:
    distances.sort(key=lambda item: (item[1], item[0]))
    for idx, (sid, _) in enumerate(distances, start=1):
        if sid == target_id:
            return idx
    return 0


def _mrr(ranks: List[int]) -> float:
    total = 0.0
    for rank in ranks:
        if rank > 0:
            total += 1.0 / rank
    return total / len(ranks) if ranks else 0.0


def _hit_rate(ranks: List[int], k: int) -> float:
    if not ranks:
        return 0.0
    hits = sum(1 for rank in ranks if 0 < rank <= k)
    return hits / len(ranks)


def _chemsys(card: Dict[str, Any]) -> str:
    return (card.get("summary") or {}).get("chemsys", "unknown")


def _chemsys_hit(distances: List[Tuple[str, float]], target_id: str, db_path: str) -> int:
    distances.sort(key=lambda item: (item[1], item[0]))
    query_card = build_crystalcard(structure_id=target_id, db_path=db_path, engine="baseline")
    query_sys = _chemsys(query_card)
    for sid, _ in distances:
        if sid == target_id:
            continue
        neighbor_card = build_crystalcard(structure_id=sid, db_path=db_path, engine="baseline")
        if _chemsys(neighbor_card) == query_sys:
            return 1
        return 0
    return 0


def _distance_list_from_query(
    *,
    surface: str,
    cif_text: str,
    embeddings: Dict[str, List[float]],
) -> List[Tuple[str, float]]:
    if surface == "text":
        text_info = generate_text(cif_text=cif_text, engine="baseline")
        query_vector = embed_text(text_info["text"], model_name=DEFAULT_MODEL_NAME, model_version=DEFAULT_MODEL_VERSION)
    elif surface == "seq":
        seq_text = canonicalize_cif(cif_text)
        query_vector = embed_text(seq_text, model_name=DEFAULT_MODEL_NAME, model_version=DEFAULT_MODEL_VERSION)
    else:
        fp = fingerprint_structure(cif_text=cif_text, store=False)
        query_vector = fp.get("vector", [])

    return [(sid, l2_distance(query_vector, vector)) for sid, vector in embeddings.items()]


def _rrf_fuse(rank_maps: Dict[str, Dict[str, int]], weights: Dict[str, float]) -> List[Tuple[str, float]]:
    fused: Dict[str, float] = {}
    for source, ranks in rank_maps.items():
        weight = weights.get(source, 1.0)
        for sid, rank in ranks.items():
            fused[sid] = fused.get(sid, 0.0) + weight / (60 + rank)
    fused_list = list(fused.items())
    fused_list.sort(key=lambda item: (-item[1], item[0]))
    return [(sid, -score) for sid, score in fused_list]


def _eval_surface_vectors(db_path: str, gold_ids: List[str], surface: str, k: int) -> Dict[str, Any]:
    ranks = []
    chemsys_hits = 0
    novelty_false = 0

    if surface == "text":
        embeddings = _load_embeddings(db_path, "text", DEFAULT_MODEL_NAME, DEFAULT_MODEL_VERSION)
    elif surface == "seq":
        embeddings = _load_embeddings(db_path, "seq", DEFAULT_MODEL_NAME, DEFAULT_MODEL_VERSION)
    else:
        embeddings = _load_fingerprints(db_path)

    for sid in gold_ids:
        conn = connect(db_path)
        init_db(conn)
        cif_row = conn.execute("SELECT cif_text FROM structures WHERE structure_id = ?", (sid,)).fetchone()
        conn.close()
        if not cif_row or not cif_row["cif_text"]:
            continue

        distances = _distance_list_from_query(surface=surface, cif_text=cif_row["cif_text"], embeddings=embeddings)
        ranks.append(_rank_target(distances[:], sid))
        chemsys_hits += _chemsys_hit(distances[:], sid, db_path)

        novelty = run_novelty(cif_text=cif_row["cif_text"], db_path=db_path, threshold=25.0, k=5)
        if novelty.get("is_novel"):
            novelty_false += 1

    return {
        "surface": surface,
        "topk_hit_rate": _hit_rate(ranks, k),
        "mrr": _mrr(ranks),
        "chemsys_hit_rate": chemsys_hits / len(gold_ids) if gold_ids else 0.0,
        "false_novelty_rate": novelty_false / len(gold_ids) if gold_ids else 0.0,
    }


def _eval_hybrid(db_path: str, gold_ids: List[str], k: int) -> Dict[str, Any]:
    text_embeddings = _load_embeddings(db_path, "text", DEFAULT_MODEL_NAME, DEFAULT_MODEL_VERSION)
    seq_embeddings = _load_embeddings(db_path, "seq", DEFAULT_MODEL_NAME, DEFAULT_MODEL_VERSION)
    struct_embeddings = _load_fingerprints(db_path)

    ranks = []
    chemsys_hits = 0
    novelty_false = 0

    for sid in gold_ids:
        conn = connect(db_path)
        init_db(conn)
        cif_row = conn.execute("SELECT cif_text FROM structures WHERE structure_id = ?", (sid,)).fetchone()
        conn.close()
        if not cif_row or not cif_row["cif_text"]:
            continue

        distances_text = _distance_list_from_query(surface="text", cif_text=cif_row["cif_text"], embeddings=text_embeddings)
        distances_seq = _distance_list_from_query(surface="seq", cif_text=cif_row["cif_text"], embeddings=seq_embeddings)
        distances_struct = _distance_list_from_query(surface="struct", cif_text=cif_row["cif_text"], embeddings=struct_embeddings)

        rank_maps = {
            "text": {sid: idx for idx, (sid, _) in enumerate(sorted(distances_text, key=lambda x: (x[1], x[0])), start=1)},
            "seq": {sid: idx for idx, (sid, _) in enumerate(sorted(distances_seq, key=lambda x: (x[1], x[0])), start=1)},
            "struct": {sid: idx for idx, (sid, _) in enumerate(sorted(distances_struct, key=lambda x: (x[1], x[0])), start=1)},
        }
        fused = _rrf_fuse(rank_maps, {"text": 0.5, "struct": 0.5, "seq": 1.0})

        ranks.append(_rank_target(fused[:], sid))
        chemsys_hits += _chemsys_hit(fused[:], sid, db_path)

        novelty = run_novelty(cif_text=cif_row["cif_text"], db_path=db_path, threshold=25.0, k=5)
        if novelty.get("is_novel"):
            novelty_false += 1

    return {
        "surface": "hybrid",
        "topk_hit_rate": _hit_rate(ranks, k),
        "mrr": _mrr(ranks),
        "chemsys_hit_rate": chemsys_hits / len(gold_ids) if gold_ids else 0.0,
        "false_novelty_rate": novelty_false / len(gold_ids) if gold_ids else 0.0,
    }


def _eval_latency(db_path: str, gold_ids: List[str], surface: str, k: int) -> float:
    latencies = []
    for sid in gold_ids:
        start = time.perf_counter()
        if surface == "text":
            similar_text(structure_id=sid, db_path=db_path, k=k)
        elif surface == "seq":
            similar_seq(structure_id=sid, db_path=db_path, k=k)
        elif surface == "struct":
            similar_struct(structure_id=sid, db_path=db_path, k=k)
        else:
            similar_hybrid(structure_id=sid, db_path=db_path, k=k, sources=["text", "struct", "seq"])
        latencies.append((time.perf_counter() - start) * 1000.0)
    return sum(latencies) / len(latencies) if latencies else 0.0


def _explainability(db_path: str, gold_ids: List[str], surface: str) -> float:
    hits = 0
    for sid in gold_ids:
        if surface == "text":
            result = similar_text(structure_id=sid, db_path=db_path, k=3)
            neighbors = result.get("neighbors", [])
            ok = bool(neighbors and neighbors[0].get("why"))
        elif surface == "seq":
            result = similar_seq(structure_id=sid, db_path=db_path, k=3)
            neighbors = result.get("neighbors", [])
            ok = bool(neighbors and neighbors[0].get("why"))
        elif surface == "struct":
            result = similar_struct(structure_id=sid, db_path=db_path, k=3)
            neighbors = result.get("neighbors", [])
            ok = bool(neighbors and neighbors[0].get("why"))
        else:
            result = similar_hybrid(structure_id=sid, db_path=db_path, k=3, sources=["text", "struct", "seq"])
            neighbors = result.get("neighbors", [])
            ok = bool(neighbors and neighbors[0].get("sources"))
        if ok:
            hits += 1
    return hits / len(gold_ids) if gold_ids else 0.0


def run_eval_phase6(base_dir: Path, fast: bool = True) -> Dict[str, Any]:
    base_dir.mkdir(parents=True, exist_ok=True)
    db_path = base_dir / "phase6.db"

    ingest_sample(db_path=str(db_path), count=12 if fast else 50)
    gold_ids = _load_gold(str(db_path))

    embed_texts(db_path=str(db_path), engine="baseline", model_name=DEFAULT_MODEL_NAME, model_version=DEFAULT_MODEL_VERSION)
    encode_sequences(db_path=str(db_path), format="cif_canon")
    embed_sequences(db_path=str(db_path), format="cif_canon", model_name=DEFAULT_MODEL_NAME, model_version=DEFAULT_MODEL_VERSION)

    results = []
    for surface in ["text", "struct", "seq"]:
        metrics = _eval_surface_vectors(str(db_path), gold_ids, surface, k=5)
        metrics["latency_ms_avg"] = _eval_latency(str(db_path), gold_ids, surface, k=5)
        metrics["explainability"] = _explainability(str(db_path), gold_ids, surface)
        results.append(metrics)

    hybrid_metrics = _eval_hybrid(str(db_path), gold_ids, k=5)
    hybrid_metrics["latency_ms_avg"] = _eval_latency(str(db_path), gold_ids, "hybrid", k=5)
    hybrid_metrics["explainability"] = _explainability(str(db_path), gold_ids, "hybrid")
    results.append(hybrid_metrics)

    db_size = os.path.getsize(db_path)

    summary = {
        "status": "ok",
        "db_path": str(db_path),
        "db_size_bytes": db_size,
        "results": results,
    }

    out_dir = base_dir / "reports_phase6_eval"
    out_dir.mkdir(exist_ok=True)
    json_path = out_dir / "eval_phase6.json"
    md_path = out_dir / "eval_phase6.md"

    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Phase 6 Evaluation",
        "",
        "| surface | topk_hit_rate | mrr | chemsys_hit_rate | explainability | latency_ms_avg |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in results:
        lines.append(
            f"| {row['surface']} | {row['topk_hit_rate']:.2f} | {row['mrr']:.2f} | {row['chemsys_hit_rate']:.2f} | {row['explainability']:.2f} | {row['latency_ms_avg']:.2f} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    summary["out_dir"] = str(out_dir)
    summary["json_path"] = str(json_path)
    summary["md_path"] = str(md_path)
    return summary


def main() -> int:
    base_dir = Path("data") / "phase6_eval"
    result = run_eval_phase6(base_dir, fast=True)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
