"""Validate the frozen paper_diversity_v2 preflight package."""

from __future__ import annotations

import csv, hashlib, json, sqlite3
from collections import Counter
from itertools import combinations
from pathlib import Path

from PIL import Image
from pymatgen.core import Composition
from paper_diversity_semantics import substitution_operation

ROOT=Path(__file__).resolve().parents[1];BENCH=ROOT/"benchmarks"/"paper_diversity_v2";ART=ROOT/"artifacts"/"paper_diversity_v2";FINAL=ART/"final";CORP=ROOT/"data"/"corpora";FIG=ROOT/"figures"/"paper_diversity_v2"

def table(path):
    return list(csv.DictReader(path.open(encoding="utf-8",newline="")))
def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()
def sig(r):
    return tuple(r[k] for k in ("target_formula","target_family","target_topology","allowed_space_groups","scaffold_hypotheses","lattice_candidate_policy","fixed_species_orbits","variable_species_orbits","site_ordering_requirement","vacancy_ordering_requirement","mixed_anion_ordering_requirement","supercell_requirement","requested_distinct_solutions"))

def main()->int:
    names=["EXP1_BASIC_TASKS.csv","EXP2_COMMON_DESIRES_TASKS.csv","EXP3_HALIDE_TASKS.csv","EXP4_NASICON_32_TASKS.csv"]
    groups=[table(BENCH/n) for n in names];assert [len(g) for g in groups]==[10,20,20,32]
    for g in groups:
        assert len({sig(r) for r in g})==len(g)
        assert all(sig(a)!=sig(b) for a,b in combinations(g,2))
    e1,e2,e3,e4=groups
    assert len({r["target_formula"] for r in e1})==10 and len({r["target_family"] for r in e1})>=5
    assert len({r["target_formula"] for r in e2})>=16 and len({r["target_family"] for r in e2})>=8
    assert sum(int(r["requested_distinct_solutions"])>1 for r in e2)>=4
    substitutions=[substitution_operation(r) for r in e2]
    substitutions=[operation for operation in substitutions if operation is not None]
    assert len(substitutions)>=4
    assert all(operation["from_species"] and operation["to_species"] and operation["target_orbit"] for operation in substitutions)
    assert len({r["target_formula"] for r in e3})>=12
    assert sum(r["mixed_anion_ordering_requirement"]!="none" for r in e3)>=4
    assert sum("tilt" in r["site_ordering_requirement"].lower() for r in e3)>=4
    assert sum(int(r["requested_distinct_solutions"])>1 for r in e3)>=4
    fc=Counter(r["target_formula"] for r in e4);assert len(fc)>=16 and max(fc.values())<=2
    assert Counter(r["task_id"].split("_")[1][0] for r in e4)==Counter({x:4 for x in "ABCDEFGH"})
    assert sum(int(r["requested_distinct_solutions"])>1 for r in e4)>=8
    assert sum(";" in r["variable_species_orbits"] or "/" in r["variable_species_orbits"] for r in e4)>=8
    assert any("phosphate/sulfate" in r["site_ordering_requirement"] for r in e4)

    full=[json.loads(x) for x in (CORP/"nasicon_specialist_v3"/"manifest.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    leave=[json.loads(x) for x in (CORP/"nasicon_specialist_all_targets_out_v3"/"manifest.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(full)==320 and len({r["cif_sha256"] for r in full})==320
    tiers=Counter(r["topology_tier"] for r in full);assert tiers=={"TIER_1_TOPOLOGY_PROXY":200,"TIER_2_CHEMICAL_FRAMEWORK":120}
    targets={Composition(r["target_formula"]).reduced_formula for r in e4}
    assert not any(Composition(r["reduced_formula"]).reduced_formula in targets for r in leave)
    assert len(leave)==281
    db=sqlite3.connect(CORP/"nasicon_specialist_v3"/"crystaldb.sqlite")
    assert db.execute("select count(*) from structures").fetchone()[0]==320
    assert db.execute("select count(*) from structure_fingerprints").fetchone()[0]==320
    assert db.execute("select count(*) from text_docs where engine='robocrys' and text_view='robocrys' and status='OK'").fetchone()[0]==320
    assert db.execute("select count(*) from text_docs where engine!='robocrys' or text_view!='robocrys'").fetchone()[0]==0
    assert db.execute("select count(*) from text_embeddings where embed_engine='lmstudio' and model='text-embedding-bge-m3' and model_version='lmstudio_v1' and status='OK'").fetchone()[0]==320
    assert db.execute("select count(*) from text_embeddings where status='FAILED'").fetchone()[0]==0
    assert db.execute("select count(*) from nasicon_v3_embedding_chunks where status='OK'").fetchone()[0]==11
    pool=db.execute("select chunk_count,pooling_policy,final_l2_norm from nasicon_v3_embedding_pooling").fetchone();assert pool and pool[0]==11 and "weighted mean" in pool[1] and abs(pool[2]-1.0)<1e-9;db.close()
    robo=table(ART/"nasicon_corpus"/"NASICON_V3_ROBOCRYS_AUDIT.csv");emb=table(ART/"nasicon_corpus"/"NASICON_V3_EMBEDDING_AUDIT.csv")
    assert len(robo)==320 and all(r["description_engine"]=="robocrys" and r["description_status"]=="OK" and r["description_hash_verified"]=="True" for r in robo)
    assert len(emb)==320 and sum(r["embedding_status"]=="OK" for r in emb)==320 and all(r["description_hash_link_verified"]=="True" for r in emb)
    checkpointed=[r for r in emb if r["chunk_checkpoint_status"]=="OK"];assert len(checkpointed)==1 and checkpointed[0]["chunk_count"]=="11" and checkpointed[0]["pooling_metadata_sha256"]

    protected=table(Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\artifacts\paper_full_sca_v1\input\INPUT_HASH_MANIFEST.csv"))
    assert all(Path(r["path"]).is_file() and digest(Path(r["path"]))==r["sha256"] for r in protected)
    required=["FOUR_EXPERIMENT_TASK_MANIFEST.csv","FOUR_EXPERIMENT_RESULTS.csv","FOUR_EXPERIMENT_AGGREGATES.csv","EXP1_BASIC_RESULTS.csv","EXP2_COMMON_DESIRES_RESULTS.csv","EXP3_HALIDE_RESULTS.csv","EXP4_NASICON_32_RESULTS.csv","RETRIEVAL_SPP_ABLATION_RESULTS.csv","WITHIN_TASK_DIVERSITY_RESULTS.csv","DUPLICATE_CAUSE_AUDIT.csv","TASK_TO_SEARCH_SPACE_MATRIX.csv","NASICON_V3_REPRESENTATION_REPORT.md","FOUR_EXPERIMENT_DIVERSITY_REPORT.md","FAILURE_CASES.md","CLAIM_MATRIX.csv","PAPER_RESULTS_INSERT_DIVERSITY.tex","PAPER_METHODS_INSERT_DIVERSITY.tex","PAPER_LIMITATIONS_INSERT_DIVERSITY.tex","OUTPUT_HASH_MANIFEST.csv","FINAL_FREEZE_REPORT.md"]
    assert all((FINAL/n).is_file() for n in required)
    results=table(FINAL/"FOUR_EXPERIMENT_RESULTS.csv");assert len(results)==82 and all(r["status"]=="NOT_RUN_REPRESENTABILITY_GATE" for r in results)
    for i in range(1,10):
        stems=list(FIG.glob(f"{i:02d}_*"));assert len(stems)==3
        png=next(p for p in stems if p.suffix==".png");Image.open(png).verify()
        pdf=next(p for p in stems if p.suffix==".pdf");assert pdf.read_bytes().startswith(b"%PDF")
        svg=next(p for p in stems if p.suffix==".svg");assert "<svg" in svg.read_text(encoding="utf-8")[:1000]
    for r in table(FINAL/"OUTPUT_HASH_MANIFEST.csv"):
        p=Path(r["path"]);assert p.is_file() and digest(p)==r["sha256"] and p.stat().st_size==int(r["bytes"])
    print(json.dumps({"status":"PASS","tasks":82,"nasicon_tasks":32,"corpus":320,"tier1":200,"tier2":120,"robocrys_ok":320,"bge_m3_ok":320,"leave_out":281,"figures":27,"protected_hashes":len(protected)},sort_keys=True));return 0

if __name__=="__main__":raise SystemExit(main())
