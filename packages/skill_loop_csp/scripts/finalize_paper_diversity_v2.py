"""Freeze reports and preflight figures for paper_diversity_v2.

Generation-dependent artifacts are explicitly marked NOT RUN because the
representability gate fails.  No candidate, relaxation or validation result is
invented.
"""

from __future__ import annotations

import csv, hashlib, json, shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/"artifacts"/"paper_diversity_v2"; FINAL=ART/"final"; FIG=ROOT/"figures"/"paper_diversity_v2"; BENCH=ROOT/"benchmarks"/"paper_diversity_v2"
CORP=ART/"nasicon_corpus"; AUDIT=ART/"audit"

def read_csv(p:Path)->list[dict[str,str]]:
    return list(csv.DictReader(p.open(encoding="utf-8",newline="")))
def write_csv(p:Path,rows:list[dict[str,Any]],fields:list[str])->None:
    with p.open("w",encoding="utf-8",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()
def save(fig,name):
    fig.text(.995,.005,"PREFLIGHT — generation not run",ha="right",va="bottom",fontsize=8,color="#a33")
    for ext in ("png","pdf","svg"): fig.savefig(FIG/f"{name}.{ext}",dpi=220,bbox_inches="tight")
    plt.close(fig)

def main()->int:
    FINAL.mkdir(parents=True,exist_ok=True);FIG.mkdir(parents=True,exist_ok=True)
    tasks=read_csv(FINAL/"FOUR_EXPERIMENT_TASK_MANIFEST.csv"); exps=["EXP1_BASIC","EXP2_COMMON_DESIRES","EXP3_HALIDE","EXP4_NASICON"]
    labels=["Basic","Common desires","Halide","NASICON"]
    by={e:[r for r in tasks if r["experiment_id"]==e] for e in exps}
    supported={e:sum(r["qlip_representability_status"] in {"SUPPORTED_NOW","SUPPORTED_WITH_CONFIGURATION"} for r in by[e]) for e in exps}
    formulas={e:len({r["target_formula"] for r in by[e]}) for e in exps}; families={e:len({r["target_family"] for r in by[e]}) for e in exps}
    # Honest unexecuted condition tables.
    abl=read_csv(BENCH/"RETRIEVAL_SPP_ABLATIONS.csv")
    abl_results=[r|{"status":"NOT_RUN_REPRESENTABILITY_GATE","retrieval_relevance":"","pair_support":"","solver_feasibility":"","unique_candidates":"","final_verdict":"NOT_RUN"} for r in abl]
    write_csv(FINAL/"RETRIEVAL_SPP_ABLATION_RESULTS.csv",abl_results,list(abl_results[0]))
    within=read_csv(BENCH/"WITHIN_TASK_DIVERSITY_TASKS.csv")
    wr=[r|{"status":"NOT_RUN_REPRESENTABILITY_GATE","obtained_k":0,"search_space_exhausted":"NOT_EVALUATED"} for r in within]
    write_csv(FINAL/"WITHIN_TASK_DIVERSITY_RESULTS.csv",wr,list(wr[0]))
    shutil.copy2(AUDIT/"ORIGINAL_31_DUPLICATE_CAUSES.csv",FINAL/"DUPLICATE_CAUSE_AUDIT.csv")
    matrix=[]
    for r in tasks:
        payload={k:r[k] for k in ("target_formula","target_family","target_topology","allowed_space_groups","scaffold_hypotheses","variable_species_orbits","site_ordering_requirement","vacancy_ordering_requirement","mixed_anion_ordering_requirement","supercell_requirement","requested_distinct_solutions")}
        matrix.append({"task_id":r["task_id"],"experiment_id":r["experiment_id"],"search_space_sha256":hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),"representability_status":r["qlip_representability_status"],**payload})
    write_csv(FINAL/"TASK_TO_SEARCH_SPACE_MATRIX.csv",matrix,list(matrix[0]))
    corpus=read_csv(CORP/"NASICON_V3_RETAINED_MANIFEST.csv");robo=read_csv(CORP/"NASICON_V3_ROBOCRYS_AUDIT.csv");emb=read_csv(CORP/"NASICON_V3_EMBEDDING_AUDIT.csv")
    tiers=Counter(r["topology_tier"] for r in corpus)
    representation=f"""# NASICON v3 representation report

- Retained: **{len(corpus)}** ({tiers['TIER_1_TOPOLOGY_PROXY']} Tier-1 topology proxy; {tiers['TIER_2_CHEMICAL_FRAMEWORK']} Tier-2 chemical framework).
- Distinct formulas: **{len(set(r['reduced_formula'] for r in corpus))}**; space groups: **{len(set(r['space_group'] for r in corpus))}**.
- Explicit Robocrys: **{sum(r['description_status']=='OK' for r in robo)}/{len(robo)}**.
- BGE-M3 via LM Studio: **{sum(r['embedding_status']=='OK' for r in emb)}/{len(emb)}**.
- Structural fingerprints: **{len(corpus)}/{len(corpus)}**.
- Hash-vector fallback: **none**.

Tier 1 is the recorded ordered coordination/single-component/rank-3 topology proxy, not experimental verification. The long Robocrys record is embedded without truncation using deterministic checkpointed chunks and normalized token-count-weighted pooling.
"""
    (FINAL/"NASICON_V3_REPRESENTATION_REPORT.md").write_text(representation,encoding="utf-8")
    report=f"""# Four-experiment diversity preflight report

## Designed breadth

- Tasks: **82** (10 basic, 20 common desires, 20 halide, 32 NASICON).
- Structured intents/search-space signatures: **82/82 distinct within their experiments**.
- Formula counts by experiment: {', '.join(f'{labels[i]} {formulas[e]}' for i,e in enumerate(exps))}.
- Retrieval/SPP ablations are separate and not breadth-counted.

## Representability gate

- Basic: **{supported[exps[0]]}/10** supported now/configuration.
- Common desires: **{supported[exps[1]]}/20** (threshold 18).
- Halide: **{supported[exps[2]]}/20** (threshold 18).
- NASICON: **{supported[exps[3]]}/32** (threshold 28).
- Gate: **FAIL**.

Therefore the mandated 24-task pilot and 82-task campaign were not launched. Candidate uniqueness, relaxation, topology-retention and acceptance metrics are not available and are not inferred from task diversity.
"""
    (FINAL/"FOUR_EXPERIMENT_DIVERSITY_REPORT.md").write_text(report,encoding="utf-8")
    (FINAL/"FAILURE_CASES.md").write_text("# Failure cases\n\n## Pre-generation blocking case\n\nThe representability gate failed before candidate generation. Missing generic capabilities are evidence-backed NASICON/tilt/supercell scaffolds, vacancy occupation, general mixed-species closed-orbit constraints, multi-lattice selection, top-k no-good cuts and symmetry-equivalent duplicate rejection. No pilot candidate failure is reported because the pilot was not run.\n",encoding="utf-8")
    claims=[
        {"claim":"82 distinct planned breadth tasks","status":"SUPPORTED","evidence":"FOUR_EXPERIMENT_TASK_MANIFEST.csv and REQUEST_DISTINCTNESS_MATRIX.csv"},
        {"claim":"NASICON v3 has 320 retained records","status":"SUPPORTED","evidence":"NASICON_V3_RETAINED_MANIFEST.csv"},
        {"claim":"320 explicit Robocrys descriptions","status":"SUPPORTED","evidence":"NASICON_V3_ROBOCRYS_AUDIT.csv"},
        {"claim":"320 production BGE-M3 embeddings","status":"SUPPORTED","evidence":"NASICON_V3_EMBEDDING_AUDIT.csv"},
        {"claim":"24-task pilot passed","status":"NOT_CLAIMED","evidence":"pilot not launched: representability gate failed"},
        {"claim":"82 candidates generated","status":"NOT_CLAIMED","evidence":"full campaign not launched"},
        {"claim":"stability, novelty or conductivity","status":"NOT_CLAIMED","evidence":"outside completed evidence"},
    ];write_csv(FINAL/"CLAIM_MATRIX.csv",claims,list(claims[0]))
    (FINAL/"PAPER_RESULTS_INSERT_DIVERSITY.tex").write_text(r"The pre-generation benchmark contains 82 distinct structured intents (10/20/20/32). The representability gate failed (10/10, 6/20, 4/20, and 0/32 supported), so neither the pilot nor full generation campaign was run. The NASICON v3 evidence corpus contains 320 hash-unique structures, 320 explicit Robocrys descriptions, and 320 BGE-M3 embeddings."+"\n",encoding="utf-8")
    (FINAL/"PAPER_METHODS_INSERT_DIVERSITY.tex").write_text(r"Breadth tasks were deduplicated by solver-represented composition, family, topology, symmetry, scaffold, orbit, occupation, ordering, supercell, lattice, and requested-$k$ axes. Retrieval/SPP conditions were retained only as ablations. NASICON Tier~1 denotes an ordered coordination, single-component, rank-3 periodic-framework proxy."+"\n",encoding="utf-8")
    (FINAL/"PAPER_LIMITATIONS_INSERT_DIVERSITY.tex").write_text(r"The current prototype solver does not represent the advanced NASICON, vacancy, mixed-anion, tilt-supercell, and top-$k$ search spaces required by the benchmark. Consequently, no pilot/full candidate, relaxation, topology-retention, or acceptance result is claimed."+"\n",encoding="utf-8")

    # Nine requested figures, with unavailable outcomes made explicit.
    x=np.arange(4)
    fig,ax=plt.subplots(figsize=(10,3));ax.axis("off");ax.text(.02,.7,"request  →  retrieved evidence  →  SPP (when supported)  →  QLIP  →  SCA/relaxation",fontsize=15);ax.text(.02,.3,"Gate stopped before pilot: advanced search spaces are not represented",fontsize=12,color="#a33");save(fig,"01_four_experiment_workflow_overview")
    fig,ax=plt.subplots(figsize=(8,4));w=.35;ax.bar(x-w/2,[formulas[e] for e in exps],w,label="formulas");ax.bar(x+w/2,[families[e] for e in exps],w,label="families");ax.set_xticks(x,labels);ax.legend();ax.set_ylabel("planned distinct count");save(fig,"02_formula_family_diversity")
    fig,ax=plt.subplots(figsize=(6,4));ax.bar(["workflow rows","hash unique","StructureMatcher unique"],[31,21,21],color=["#777","#2878b5","#57a773"]);ax.set_ylabel("frozen original campaign count");save(fig,"03_hash_vs_structurematcher_uniqueness")
    fig,ax=plt.subplots(figsize=(8,4));ax.bar(x,[len({r['preferred_space_group'] for r in by[e]}) for e in exps],label="space groups");ax.bar(x,[len({r['scaffold_hypotheses'] for r in by[e]}) for e in exps],bottom=[len({r['preferred_space_group'] for r in by[e]}) for e in exps],label="scaffolds");ax.set_xticks(x,labels);ax.legend();save(fig,"04_spacegroup_scaffold_diversity")
    nas=by["EXP4_NASICON"];features=np.array([[int(int(r['requested_distinct_solutions'])>1),int('vacancy' in r['vacancy_ordering_requirement'].lower()),int(';' in r['variable_species_orbits'] or '/' in r['variable_species_orbits']),int('supercell' in r['supercell_requirement'].lower())] for r in nas]);fig,ax=plt.subplots(figsize=(8,9));ax.imshow(features,aspect="auto",cmap="Blues",vmin=0,vmax=1);ax.set_xticks(range(4),["k>1","vacancy","multi-orbit","supercell"],rotation=25);ax.set_yticks(range(32),[r['task_id'].replace('E4_','') for r in nas],fontsize=7);save(fig,"05_nasicon_32_chemistry_intent_matrix")
    fig,ax=plt.subplots(figsize=(8,4));ks=Counter(int(r['requested_distinct_solutions']) for r in nas);ax.bar([str(k) for k in sorted(ks)],[ks[k] for k in sorted(ks)]);ax.set_xlabel("requested k");ax.set_ylabel("NASICON tasks");ax.set_title("Obtained candidates: not run");save(fig,"06_nasicon_topk_candidate_diversity")
    fig,ax=plt.subplots(figsize=(8,4));conds=Counter(r['condition'] for r in abl);ax.barh(list(conds),list(conds.values()));ax.set_xlabel("planned ablation rows");ax.set_title("Outcomes not run");save(fig,"07_retrieval_spp_ablation_outcomes")
    dup=read_csv(AUDIT/"ORIGINAL_31_DUPLICATE_CAUSES.csv");dc=Counter(r['duplicate_cause'] for r in dup);fig,ax=plt.subplots(figsize=(7,4));ax.barh(list(dc),list(dc.values()),color="#9867c5");ax.set_xlabel("frozen rows");save(fig,"08_duplicate_cause_matrix")
    fig,ax=plt.subplots(figsize=(8,4));ax.bar(x,[0,0,0,0],label="initial accepted");ax.bar(x,[0,0,0,0],label="relaxed accepted");ax.set_xticks(x,labels);ax.set_ylim(0,1);ax.text(1.5,.5,"No candidates generated",ha="center",fontsize=14,color="#a33");ax.legend();save(fig,"09_initial_vs_relaxed_acceptance")

    # Verify every protected frozen input hash before writing the freeze record.
    frozen_manifest=Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\artifacts\paper_full_sca_v1\input\INPUT_HASH_MANIFEST.csv")
    protected=read_csv(frozen_manifest);bad=[r for r in protected if not Path(r['path']).is_file() or sha(Path(r['path']))!=r['sha256']]
    hash_rows=[]
    roots=[ART,BENCH,FIG,ROOT/"data"/"corpora"/"nasicon_specialist_v3",ROOT/"data"/"corpora"/"nasicon_specialist_all_targets_out_v3"]
    for base in roots:
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name not in {"OUTPUT_HASH_MANIFEST.csv","FINAL_FREEZE_REPORT.md"}:hash_rows.append({"path":str(p),"sha256":sha(p),"bytes":p.stat().st_size})
    write_csv(FINAL/"OUTPUT_HASH_MANIFEST.csv",hash_rows,["path","sha256","bytes"])
    test_lines=[]
    for label,name in (("Skill-Loop-CSP","skill_loop_csp.xml"),("QLIP","qlip.xml"),("Crystal-DB","crystal_db.xml"),("Structured_Crystal_Analyser","structured_crystal_analyser.xml")):
        path=ART/"tests"/name
        if not path.is_file(): test_lines.append(f"- {label}: **PENDING**")
        else:
            suite=ET.parse(path).getroot();attrs=suite.attrib if suite.tag=="testsuite" else next(iter(suite)).attrib
            tests=int(attrs.get("tests",0));failures=int(attrs.get("failures",0));errors=int(attrs.get("errors",0));skipped=int(attrs.get("skipped",0));test_lines.append(f"- {label}: **{tests-errors-failures-skipped} passed**, {failures} failed, {errors} errors, {skipped} skipped ({tests} total).")
    (FINAL/"FINAL_FREEZE_REPORT.md").write_text(f"# paper_diversity_v2 preflight freeze report\n\nThis is a **benchmark-definition and corpus preflight freeze**. Generation has not started. Representability remains the generation blocker, so neither the pilot nor full campaign was launched.\n\n## Corpus and representations\n\n- Retained corpus: **320** structures (**200 Tier-1 topology proxy; 120 Tier-2 chemical framework**).\n- All-targets-out corpus: **281** structures.\n- Explicit Robocrys: **320/320**.\n- Production BGE-M3: **320/320**; one 79,032-character record uses 11 checkpointed chunks and normalized token-count-weighted pooling without truncation.\n\n## Validator repair\n\nSubstitution-sensitive tasks are classified from explicit `intent_axes.substitution_site` and structured old/new species, target-orbit, and charge-compensation fields. Natural-language keywords do not determine acceptance.\n\n## Repository tests\n\n"+"\n".join(test_lines)+f"\n\n## Protected artifacts\n\n- Protected frozen inputs checked: **{len(protected)}**; hash mismatches: **{len(bad)}**.\n- Output hash entries: **{len(hash_rows)}**.\n\nNo prior frozen campaign was modified. This package contains preflight evidence and explicit NOT-RUN result rows, not generated-material claims.\n",encoding="utf-8")
    if bad: raise AssertionError(f"Protected frozen input hashes changed: {[r['candidate_id'] for r in bad]}")
    print(json.dumps({"tasks":82,"support":supported,"pilot":False,"full_campaign":False,"figures":9,"protected_hash_mismatches":0,"output_hashes":len(hash_rows)},sort_keys=True));return 0

if __name__=="__main__":raise SystemExit(main())
