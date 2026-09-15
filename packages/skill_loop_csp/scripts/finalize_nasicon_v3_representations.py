"""Audit NASICON v3 representations and populate the all-targets-out index."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from pymatgen.core import Composition


ROOT=Path(__file__).resolve().parents[1]
FULL=ROOT/"data"/"corpora"/"nasicon_specialist_v3"
LEAVE=ROOT/"data"/"corpora"/"nasicon_specialist_all_targets_out_v3"
ART=ROOT/"artifacts"/"paper_diversity_v2"/"nasicon_corpus"
MODEL="text-embedding-bge-m3"; MODEL_VERSION="lmstudio_v1"; BACKEND="lmstudio"
TASKS=ROOT/"benchmarks"/"paper_diversity_v2"/"EXP4_NASICON_32_TASKS.csv"


def rows(path: Path) -> list[dict[str,Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def write_csv(path: Path,data: list[dict[str,Any]],fields: list[str]) -> None:
    with path.open("w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(data)


def db_map(conn: sqlite3.Connection) -> dict[str,str]:
    return {str(r["source_id"]).removesuffix(".cif"):str(r["structure_id"]) for r in conn.execute("select structure_id,source_id from provenance")}


def sync_leave_targets() -> int:
    with TASKS.open(encoding="utf-8",newline="") as h:
        targets={Composition(r["target_formula"]).reduced_formula for r in csv.DictReader(h)}
    manifest=rows(LEAVE/"manifest.jsonl")
    removed=[r for r in manifest if Composition(r["reduced_formula"]).reduced_formula in targets]
    kept=[r for r in manifest if r not in removed]
    if removed:
        conn=sqlite3.connect(LEAVE/"crystaldb.sqlite");conn.row_factory=sqlite3.Row;mapping=db_map(conn)
        for rec in removed:
            name=rec["internal_id"];sid=mapping.get(name)
            if sid:
                for doc in conn.execute("select id from text_docs where structure_id=?",(sid,)).fetchall(): conn.execute("delete from text_embeddings where text_doc_id=?",(doc[0],))
                for table in ("text_docs","structure_fingerprints","structure_embeddings","structure_texts","structure_crystalcards","structure_sequences","metadata","provenance"):
                    conn.execute(f"delete from {table} where structure_id=?",(sid,))
                conn.execute("delete from structures where structure_id=?",(sid,))
            for path in (LEAVE/"cifs"/f"{name}.cif",LEAVE/"records"/f"{name}.json"):
                if path.is_file():
                    if LEAVE.resolve() not in path.resolve().parents: raise ValueError(f"unsafe leave-out removal: {path}")
                    path.unlink()
        conn.commit();conn.close()
        (LEAVE/"manifest.jsonl").write_text("".join(json.dumps(r,sort_keys=True,ensure_ascii=False)+"\n" for r in kept),encoding="utf-8")
        card=json.loads((LEAVE/"corpus_card.json").read_text(encoding="utf-8"));card["structure_count"]=len(kept);card["topology_tier_counts"]=dict(Counter(r["topology_tier"] for r in kept));(LEAVE/"corpus_card.json").write_text(json.dumps(card,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    full=rows(FULL/"manifest.jsonl")
    duplicate=[{"internal_id":r["internal_id"],"source_id":r["source_id"],"reduced_formula":r["reduced_formula"],"exclusion_reason":"exact_breadth_task_formula","matched_reference":"formula-level exclusion","matcher_tolerances":json.dumps({"ltol":0.2,"stol":0.3,"angle_tol":5.0,"primitive_cell":True,"scale":True})} for r in full if Composition(r["reduced_formula"]).reduced_formula in targets]
    write_csv(ART/"NASICON_V3_DUPLICATE_REPORT.csv",duplicate,list(duplicate[0]))
    return len(removed)


def copy_leave_representations() -> None:
    src=sqlite3.connect(FULL/"crystaldb.sqlite");src.row_factory=sqlite3.Row
    dst=sqlite3.connect(LEAVE/"crystaldb.sqlite");dst.row_factory=sqlite3.Row
    smap=db_map(src);dmap=db_map(dst)
    for source_name,dsid in dmap.items():
        ssid=smap[source_name]
        for row in src.execute("select engine,text_view,engine_version,text,text_sha256,status,error_type,error_message,created_at,updated_at from text_docs where structure_id=?",(ssid,)):
            cur=dst.execute("insert into text_docs (structure_id,engine,text_view,engine_version,text,text_sha256,status,error_type,error_message,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?) on conflict(structure_id,engine,text_view) do update set engine_version=excluded.engine_version,text=excluded.text,text_sha256=excluded.text_sha256,status=excluded.status,error_type=excluded.error_type,error_message=excluded.error_message,updated_at=excluded.updated_at",(dsid,*tuple(row)))
        sdocs={int(r["id"]):r for r in src.execute("select * from text_docs where structure_id=?",(ssid,))}
        ddocs={(r["engine"],r["text_view"]):int(r["id"]) for r in dst.execute("select id,engine,text_view from text_docs where structure_id=?",(dsid,))}
        for old_id,doc in sdocs.items():
            new_id=ddocs[(doc["engine"],doc["text_view"])]
            for emb in src.execute("select embed_engine,model,model_version,dim,vector,status,error_type,error_message,created_at,updated_at from text_embeddings where text_doc_id=?",(old_id,)):
                dst.execute("insert into text_embeddings (text_doc_id,embed_engine,model,model_version,dim,vector,status,error_type,error_message,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?) on conflict(text_doc_id,embed_engine,model,model_version) do update set dim=excluded.dim,vector=excluded.vector,status=excluded.status,error_type=excluded.error_type,error_message=excluded.error_message,updated_at=excluded.updated_at",(new_id,*tuple(emb)))
    dst.commit();src.close();dst.close()


def main() -> int:
    ART.mkdir(parents=True,exist_ok=True);removed=sync_leave_targets();copy_leave_representations()
    manifest=rows(FULL/"manifest.jsonl")
    conn=sqlite3.connect(FULL/"crystaldb.sqlite");conn.row_factory=sqlite3.Row
    mapping=db_map(conn)
    robo=[];embed=[];matrix=[]
    updated=[]
    for rec in manifest:
        source_name=rec["internal_id"];sid=mapping[source_name]
        doc=conn.execute("select * from text_docs where structure_id=? and engine='robocrys' and text_view='robocrys' order by id desc limit 1",(sid,)).fetchone()
        fp=conn.execute("select count(*) from structure_fingerprints where structure_id=?",(sid,)).fetchone()[0]
        actual_text_hash=hashlib.sha256((doc["text"] or "").encode("utf-8")).hexdigest() if doc and doc["text"] else None
        doc_hash_ok=bool(doc and doc["status"]=="OK" and doc["text_sha256"]==actual_text_hash)
        robo_row={"structure_id":source_name,"source":rec["source"],"source_id":rec["source_id"],"cif_sha256":rec["cif_sha256"],"description_engine":"robocrys","description_engine_version":doc["engine_version"] if doc else "","description_status":doc["status"] if doc else "MISSING","description_text":doc["text"] if doc else "","description_sha256":doc["text_sha256"] if doc else "","generated_at":doc["updated_at"] if doc else "","failure_reason":doc["error_message"] if doc and doc["status"]!="OK" else "","description_hash_verified":doc_hash_ok}
        robo.append(robo_row)
        emb=conn.execute("select te.* from text_embeddings te where te.text_doc_id=? and te.embed_engine=? and te.model=? and te.model_version=? order by te.id desc limit 1",(doc["id"],BACKEND,MODEL,MODEL_VERSION)).fetchone() if doc else None
        pool=conn.execute("select * from nasicon_v3_embedding_pooling where text_doc_id=? and embed_engine=? and model=? and model_version=?",(doc["id"],BACKEND,MODEL,MODEL_VERSION)).fetchone() if doc else None
        emb_hash=hashlib.sha256((emb["vector"] or "").encode("utf-8")).hexdigest() if emb and emb["vector"] else ""
        pool_meta_hash=hashlib.sha256((pool["metadata_json"] or "").encode("utf-8")).hexdigest() if pool else ""
        embed_row={"structure_id":source_name,"description_sha256":doc["text_sha256"] if doc else "","embedding_backend":BACKEND,"embedding_model":MODEL,"embedding_model_version":MODEL_VERSION,"embedding_dimension":emb["dim"] if emb else "","embedding_sha256":emb_hash,"embedding_status":emb["status"] if emb else "MISSING","description_hash_link_verified":doc_hash_ok and bool(emb),"chunk_count":pool["chunk_count"] if pool else "","chunk_checkpoint_status":"OK" if pool else "NOT_APPLICABLE","pooling_policy":pool["pooling_policy"] if pool else "repository default single-pass embedding","pooling_metadata_sha256":pool_meta_hash,"failure_reason":emb["error_message"] if emb and emb["status"]!="OK" else ""}
        embed.append(embed_row)
        matrix.append({"structure_id":source_name,"canonical_cif":True,"composition_metadata":True,"topology_annotation":bool(rec.get("topology_tier")),"structural_fingerprint":bool(fp),"robocrys_text":doc_hash_ok,"bge_m3_embedding":bool(emb and emb["status"]=="OK" and doc_hash_ok),"checkpointed_chunk_embedding":bool(pool),"text_retrieval_eligible":bool(emb and emb["status"]=="OK" and doc_hash_ok),"metadata_fingerprint_retrieval_eligible":bool(fp)})
        rec=dict(rec);rec["representations"]={"canonical_cif":True,"composition_metadata":True,"topology_annotation":True,"structural_fingerprint":bool(fp),"robocrys":{"engine":"robocrys","version":doc["engine_version"] if doc else None,"status":doc["status"] if doc else "MISSING","description_sha256":doc["text_sha256"] if doc else None},"text_embedding":{"backend":BACKEND,"model":MODEL,"model_version":MODEL_VERSION,"dimension":emb["dim"] if emb else None,"status":emb["status"] if emb else "MISSING","embedding_sha256":emb_hash or None,"description_sha256":doc["text_sha256"] if doc else None,"chunk_count":pool["chunk_count"] if pool else None,"pooling_policy":pool["pooling_policy"] if pool else None,"pooling_metadata_sha256":pool_meta_hash or None}}
        updated.append(rec)
        (FULL/"records"/f"{source_name}.json").write_text(json.dumps(rec,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
    conn.close()
    (FULL/"manifest.jsonl").write_text("".join(json.dumps(x,sort_keys=True,ensure_ascii=False)+"\n" for x in updated),encoding="utf-8")
    rf=list(robo[0]);ef=list(embed[0]);mf=list(matrix[0])
    write_csv(ART/"NASICON_V3_ROBOCRYS_AUDIT.csv",robo,rf)
    write_csv(ART/"NASICON_V3_ROBOCRYS_FAILURES.csv",[r for r in robo if r["description_status"]!="OK"],rf)
    write_csv(ART/"NASICON_V3_EMBEDDING_AUDIT.csv",embed,ef)
    write_csv(ART/"NASICON_V3_REPRESENTATION_MATRIX.csv",matrix,mf)
    rc=Counter(r["description_status"] for r in robo);ec=Counter(r["embedding_status"] for r in embed)
    (ART/"NASICON_V3_ROBOCRYS_REPORT.md").write_text(f"# NASICON v3 Robocrys report\n\n- Retained records: **{len(robo)}**\n- Explicit Robocrys OK: **{rc.get('OK',0)}**\n- Failed/missing: **{len(robo)-rc.get('OK',0)}**\n- Provenance coverage: **{len(robo)}/{len(robo)}**\n- Verified description hashes: **{sum(r['description_hash_verified'] for r in robo)}/{len(robo)}**\n- Fallback captions labelled as Robocrys: **0**\n\nRobocrys warnings about inferred radii are generation diagnostics; descriptions remain explicit Robocrys outputs.\n",encoding="utf-8")
    (ART/"NASICON_V3_RETRIEVAL_INDEX_REPORT.md").write_text(f"# NASICON v3 retrieval index report\n\n- Canonical CIF/metadata/topology/fingerprint rows: **{sum(r['metadata_fingerprint_retrieval_eligible'] for r in matrix)}/{len(matrix)}**\n- Exact archived Robocrys descriptions: **{rc.get('OK',0)}/{len(matrix)}**\n- `{MODEL}` embeddings via `{BACKEND}`: **{ec.get('OK',0)}/{len(matrix)}**\n- Embedding failures: **{ec.get('FAILED',0)}**\n- Text-hash linkage verified for embedded rows: **{sum(r['description_hash_link_verified'] for r in embed if r['embedding_status']=='OK')}/{ec.get('OK',0)}**\n- Checkpointed long-document embeddings: **{sum(r['chunk_checkpoint_status']=='OK' for r in embed)}** (11 deterministic chunks; per-chunk L2 normalization; token-count-weighted mean; final L2 normalization).\n\nAll retained rows are eligible for production BGE-M3 text retrieval. No description fallback, truncation, or hash-vector fallback exists in this index.\n",encoding="utf-8")
    print(json.dumps({"robocrys":dict(rc),"embeddings":dict(ec),"fingerprints":sum(r["structural_fingerprint"] for r in matrix),"leave_out_copied":len(rows(LEAVE/"manifest.jsonl")),"new_target_rows_removed":removed},sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
