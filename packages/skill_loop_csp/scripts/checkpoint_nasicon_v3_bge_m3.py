"""Checkpoint and pool failed long-document NASICON v3 BGE-M3 embeddings."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT=Path(__file__).resolve().parents[1]
CRYSTAL_DB=Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
if str(CRYSTAL_DB) not in sys.path: sys.path.insert(0,str(CRYSTAL_DB))

from crystal_db.embeddings import (  # noqa: E402
    DEFAULT_CHUNK_OVERLAP_TOKENS,
    DEFAULT_MAX_CTX_TOKENS,
    LMSTUDIO_MODEL_NAME,
    LMSTUDIO_MODEL_VERSION,
    TOKEN_CHAR_RATIO,
    chunk_text_for_embedding,
    embed_texts,
    estimate_tokens,
)

DB=ROOT/"data"/"corpora"/"nasicon_specialist_v3"/"crystaldb.sqlite"
OUT=ROOT/"artifacts"/"paper_diversity_v2"/"nasicon_corpus"/"embedding_checkpoints"
BACKEND="lmstudio";MODEL=LMSTUDIO_MODEL_NAME;VERSION=LMSTUDIO_MODEL_VERSION


def canonical_vector(vector: list[float]) -> str:
    return json.dumps([float(x) for x in vector],separators=(",",":"),allow_nan=False)


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize(vector: list[float]) -> tuple[list[float],float]:
    norm=math.sqrt(sum(float(x)*float(x) for x in vector))
    if not math.isfinite(norm) or norm<=0: raise ValueError("embedding vector has invalid L2 norm")
    return [float(x)/norm for x in vector],norm


def checkpoint_path(structure_id: str) -> Path:
    return OUT/f"{structure_id}__{MODEL}__chunks.json"


def write_checkpoint(path: Path,payload: dict[str,Any]) -> None:
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    tmp.replace(path)


def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--db",type=Path,default=DB);ap.add_argument("--max-attempts",type=int,default=5);ap.add_argument("--base-backoff",type=float,default=1.0);args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(args.db);conn.row_factory=sqlite3.Row
    failed=conn.execute("select te.id embedding_id,td.id text_doc_id,td.structure_id,td.text,td.text_sha256,te.created_at from text_embeddings te join text_docs td on td.id=te.text_doc_id where te.embed_engine=? and te.model=? and te.model_version=? and te.status='FAILED' order by td.structure_id",(BACKEND,MODEL,VERSION)).fetchall()
    if len(failed)!=1: raise AssertionError(f"Expected exactly one failed BGE-M3 record, found {len(failed)}")
    row=failed[0];text=str(row["text"]);description_hash=sha_text(text)
    if description_hash!=row["text_sha256"]: raise AssertionError("Archived Robocrys description hash mismatch")
    chunks=chunk_text_for_embedding(text,max_ctx_tokens=DEFAULT_MAX_CTX_TOKENS,overlap_tokens=DEFAULT_CHUNK_OVERLAP_TOKENS)
    if len(chunks)!=11: raise AssertionError(f"Recorded long-document policy should yield 11 chunks, got {len(chunks)}")
    conn.executescript("""
    create table if not exists nasicon_v3_embedding_chunks (
      text_doc_id integer not null, embed_engine text not null, model text not null, model_version text not null,
      chunk_index integer not null, chunk_count integer not null, chunk_text_sha256 text not null,
      weight_tokens integer not null, character_count integer not null, vector_json text,
      vector_sha256 text, raw_l2_norm real, normalized_l2_norm real, status text not null,
      attempts integer not null, last_error text, updated_at text not null,
      primary key(text_doc_id,embed_engine,model,model_version,chunk_index));
    create table if not exists nasicon_v3_embedding_pooling (
      text_doc_id integer not null, embed_engine text not null, model text not null, model_version text not null,
      description_sha256 text not null, chunk_count integer not null, chunk_hashes_json text not null,
      chunk_vector_hashes_json text not null, chunk_weights_json text not null, pooling_policy text not null,
      pooled_vector_sha256 text not null, pooled_dimension integer not null, pre_normalization_l2_norm real not null,
      final_l2_norm real not null, metadata_json text not null, created_at text not null,
      primary key(text_doc_id,embed_engine,model,model_version));
    """);conn.commit()
    payload={"structure_id":row["structure_id"],"text_doc_id":row["text_doc_id"],"description_sha256":description_hash,"description_character_count":len(text),"description_estimated_tokens":estimate_tokens(text),"backend":BACKEND,"model":MODEL,"model_version":VERSION,"chunking_policy":{"implementation":"crystal_db.embeddings.chunk_text_for_embedding","max_context_tokens":DEFAULT_MAX_CTX_TOKENS,"overlap_tokens":DEFAULT_CHUNK_OVERLAP_TOKENS,"token_character_ratio":TOKEN_CHAR_RATIO},"pooling_policy":"L2-normalize each chunk; weight by estimated token count; arithmetic weighted mean; L2-normalize pooled vector","chunks":[]}
    vectors=[];weights=[];chunk_hashes=[];vector_hashes=[]
    for index,item in enumerate(chunks):
        chunk=str(item["text"]);weight=max(1,int(item["weight_tokens"]));chunk_hash=sha_text(chunk)
        prior=conn.execute("select * from nasicon_v3_embedding_chunks where text_doc_id=? and embed_engine=? and model=? and model_version=? and chunk_index=? and status='OK' and chunk_text_sha256=?",(row["text_doc_id"],BACKEND,MODEL,VERSION,index,chunk_hash)).fetchone()
        attempts=int(prior["attempts"]) if prior else 0
        if prior:
            vector=[float(x) for x in json.loads(prior["vector_json"])]
            vector_hash=str(prior["vector_sha256"]);raw_norm=float(prior["raw_l2_norm"])
        else:
            last_error=""
            for attempt in range(1,args.max_attempts+1):
                attempts=attempt
                try:
                    result=embed_texts([chunk],model_name=MODEL,model_version=VERSION,embed_engine=BACKEND)
                    if len(result)!=1: raise RuntimeError(f"expected one vector, received {len(result)}")
                    vector,raw_norm=normalize([float(x) for x in result[0]])
                    vector_json=canonical_vector(vector);vector_hash=sha_text(vector_json)
                    now=datetime.now(timezone.utc).isoformat()
                    conn.execute("insert into nasicon_v3_embedding_chunks (text_doc_id,embed_engine,model,model_version,chunk_index,chunk_count,chunk_text_sha256,weight_tokens,character_count,vector_json,vector_sha256,raw_l2_norm,normalized_l2_norm,status,attempts,last_error,updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(text_doc_id,embed_engine,model,model_version,chunk_index) do update set chunk_count=excluded.chunk_count,chunk_text_sha256=excluded.chunk_text_sha256,weight_tokens=excluded.weight_tokens,character_count=excluded.character_count,vector_json=excluded.vector_json,vector_sha256=excluded.vector_sha256,raw_l2_norm=excluded.raw_l2_norm,normalized_l2_norm=excluded.normalized_l2_norm,status=excluded.status,attempts=excluded.attempts,last_error=excluded.last_error,updated_at=excluded.updated_at",(row["text_doc_id"],BACKEND,MODEL,VERSION,index,len(chunks),chunk_hash,weight,len(chunk),vector_json,vector_hash,raw_norm,1.0,"OK",attempts,None,now));conn.commit()
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error=f"{type(exc).__name__}: {exc}";now=datetime.now(timezone.utc).isoformat()
                    conn.execute("insert into nasicon_v3_embedding_chunks (text_doc_id,embed_engine,model,model_version,chunk_index,chunk_count,chunk_text_sha256,weight_tokens,character_count,status,attempts,last_error,updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(text_doc_id,embed_engine,model,model_version,chunk_index) do update set status=excluded.status,attempts=excluded.attempts,last_error=excluded.last_error,updated_at=excluded.updated_at",(row["text_doc_id"],BACKEND,MODEL,VERSION,index,len(chunks),chunk_hash,weight,len(chunk),"FAILED",attempts,last_error,now));conn.commit()
                    if attempt<args.max_attempts: time.sleep(args.base_backoff*(2**(attempt-1)))
            else: raise RuntimeError(f"Chunk {index} failed after {args.max_attempts} attempts: {last_error}")
        vectors.append(vector);weights.append(weight);chunk_hashes.append(chunk_hash);vector_hashes.append(vector_hash)
        payload["chunks"].append({"chunk_index":index,"chunk_sha256":chunk_hash,"character_count":len(chunk),"weight_tokens":weight,"vector_sha256":vector_hash,"raw_l2_norm":raw_norm,"normalized_l2_norm":math.sqrt(sum(x*x for x in vector)),"attempts":attempts,"status":"OK"})
        write_checkpoint(checkpoint_path(str(row["structure_id"])),payload)
        print(f"[checkpoint-bge-m3] chunk {index+1}/{len(chunks)} OK attempts={attempts}",flush=True)
    total=float(sum(weights));mean=[sum(vector[i]*weight for vector,weight in zip(vectors,weights))/total for i in range(len(vectors[0]))]
    pooled,pre_norm=normalize(mean);pooled_json=canonical_vector(pooled);pooled_hash=sha_text(pooled_json);final_norm=math.sqrt(sum(x*x for x in pooled))
    now=datetime.now(timezone.utc).isoformat();metadata={"schema":"nasicon_v3_checkpointed_embedding.v1","description_sha256":description_hash,"backend":BACKEND,"model":MODEL,"model_version":VERSION,"chunk_count":len(chunks),"chunking_policy":payload["chunking_policy"],"pooling_policy":payload["pooling_policy"],"all_chunks_checkpointed":True}
    conn.execute("update text_embeddings set dim=?,vector=?,status='OK',error_type=null,error_message=null,updated_at=? where id=?",(len(pooled),pooled_json,now,row["embedding_id"]))
    conn.execute("insert into nasicon_v3_embedding_pooling (text_doc_id,embed_engine,model,model_version,description_sha256,chunk_count,chunk_hashes_json,chunk_vector_hashes_json,chunk_weights_json,pooling_policy,pooled_vector_sha256,pooled_dimension,pre_normalization_l2_norm,final_l2_norm,metadata_json,created_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(text_doc_id,embed_engine,model,model_version) do update set description_sha256=excluded.description_sha256,chunk_count=excluded.chunk_count,chunk_hashes_json=excluded.chunk_hashes_json,chunk_vector_hashes_json=excluded.chunk_vector_hashes_json,chunk_weights_json=excluded.chunk_weights_json,pooling_policy=excluded.pooling_policy,pooled_vector_sha256=excluded.pooled_vector_sha256,pooled_dimension=excluded.pooled_dimension,pre_normalization_l2_norm=excluded.pre_normalization_l2_norm,final_l2_norm=excluded.final_l2_norm,metadata_json=excluded.metadata_json,created_at=excluded.created_at",(row["text_doc_id"],BACKEND,MODEL,VERSION,description_hash,len(chunks),json.dumps(chunk_hashes),json.dumps(vector_hashes),json.dumps(weights),payload["pooling_policy"],pooled_hash,len(pooled),pre_norm,final_norm,json.dumps(metadata,sort_keys=True),now));conn.commit();conn.close()
    payload["pooling"]={"pooled_vector_sha256":pooled_hash,"dimension":len(pooled),"pre_normalization_l2_norm":pre_norm,"final_l2_norm":final_norm,"completed_at":now};write_checkpoint(checkpoint_path(str(row["structure_id"])),payload)
    if sha_text(text)!=description_hash: raise AssertionError("Robocrys description changed during embedding")
    print(json.dumps({"status":"OK","structure_id":row["structure_id"],"description_sha256":description_hash,"chunk_count":len(chunks),"pooled_vector_sha256":pooled_hash,"dimension":len(pooled),"backend":BACKEND,"model":MODEL,"model_version":VERSION},sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
