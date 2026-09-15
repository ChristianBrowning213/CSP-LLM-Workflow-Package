"""Generate explicit Robocrys text for NASICON v3 with parallel workers.

Workers receive the exact CIF text archived in Crystal-DB and call the same
Robocrys condenser/describer used by ``crystal_db.textgen.generate_text``.
Only the parent process writes SQLite, committing each result.  Exceptions are
stored as FAILED rows; no caption/baseline fallback is attempted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import multiprocessing as mp
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/"data"/"corpora"/"nasicon_specialist_v3"/"crystaldb.sqlite"


def worker(item: tuple[str,str]) -> dict[str,Any]:
    sid,cif_text=item
    try:
        from pymatgen.core import Structure
        from robocrys import StructureCondenser, StructureDescriber
        structure=Structure.from_str(cif_text,fmt="cif")
        text=StructureDescriber().describe(StructureCondenser().condense_structure(structure))
        return {"structure_id":sid,"status":"OK","text":text,"text_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),"error_type":None,"error_message":None}
    except Exception as exc:  # noqa: BLE001
        return {"structure_id":sid,"status":"FAILED","text":None,"text_sha256":None,"error_type":type(exc).__name__,"error_message":str(exc)}


def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument("--db",type=Path,default=DB);ap.add_argument("--workers",type=int,default=8);ap.add_argument("--force",action="store_true");args=ap.parse_args()
    conn=sqlite3.connect(args.db);conn.row_factory=sqlite3.Row
    existing={r[0] for r in conn.execute("select structure_id from text_docs where engine='robocrys' and text_view='robocrys'"+("" if args.force else " and status='OK'"))}
    rows=conn.execute("select structure_id,cif_text from structures order by nsites,structure_id").fetchall()
    pending=[(str(r["structure_id"]),str(r["cif_text"])) for r in rows if args.force or str(r["structure_id"]) not in existing]
    version=f"robocrys {importlib.metadata.version('robocrys')}"
    now=lambda:datetime.now(timezone.utc).isoformat()
    ok=failed=0
    ctx=mp.get_context("spawn")
    with ctx.Pool(processes=max(1,args.workers),maxtasksperchild=8) as pool:
        for index,result in enumerate(pool.imap_unordered(worker,pending,chunksize=1),start=1):
            ts=now()
            conn.execute(
                "insert into text_docs (structure_id,engine,text_view,engine_version,text,text_sha256,status,error_type,error_message,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?) "
                "on conflict(structure_id,engine,text_view) do update set engine_version=excluded.engine_version,text=excluded.text,text_sha256=excluded.text_sha256,status=excluded.status,error_type=excluded.error_type,error_message=excluded.error_message,updated_at=excluded.updated_at",
                (result["structure_id"],"robocrys","robocrys",version,result["text"],result["text_sha256"],result["status"],result["error_type"],result["error_message"],ts,ts),
            )
            conn.commit()
            if result["status"]=="OK":ok+=1
            else:failed+=1
            if index%10==0 or index==len(pending): print(f"[robocrys-v3] {index}/{len(pending)} ok={ok} failed={failed}",flush=True)
    conn.close()
    print({"selected":len(pending),"ok":ok,"failed":failed,"engine_version":version})
    return 0 if ok+failed==len(pending) else 1


if __name__=="__main__":
    raise SystemExit(main())
