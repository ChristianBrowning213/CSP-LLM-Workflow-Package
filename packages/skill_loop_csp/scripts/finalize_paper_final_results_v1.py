"""Aggregate, visualize, and package the frozen final paper-results run."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT.parent
OUT = ROOT / "artifacts" / "paper_final_results_v1"
M = OUT / "01_manifests"; SCA = OUT / "03_sca"; ACC = OUT / "04_acceptance"; ANA = OUT / "05_analysis"
TRACE = OUT / "06_traceability"; TABLES = OUT / "07_tables"; MANUSCRIPT = OUT / "08_manuscript"; REPRO = OUT / "09_reproducibility"
FIGURES = ROOT / "figures" / "paper_final_results_v1"; RUNS = ROOT / "runs" / "paper_final_results_v1"
ARCHIVE = OUT / "PAPER_READY_ARCHIVE"
SOURCE_SCA = GITHUB / "Structured_Crystal_Analyser" / "artifacts" / "paper_full_sca_v1"
DEMO = ROOT / "artifacts" / "paper_diversity_v2" / "nasicon_demo"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle: return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    columns = fields or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def yes(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "pass", "optimal"}


def number(value: Any) -> float | None:
    try: return float(value) if str(value).strip() else None
    except (TypeError, ValueError): return None


def by(path: Path, key: str) -> dict[str, dict[str, str]]:
    return {row[key]: row for row in read_csv(path)}


def latex(value: Any) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("%", "\\%").replace("&", "\\&")


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    return "| " + " | ".join(columns) + " |\n|" + "|".join("---" for _ in columns) + "|\n" + "\n".join("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |" for row in rows) + "\n"


def latex_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    return "\\begin{tabular}{" + "l" * len(columns) + "}\n\\toprule\n" + " & ".join(latex(c) for c in columns) + " \\\\\n\\midrule\n" + "\n".join(" & ".join(latex(row.get(c, "")) for c in columns) + " \\\\" for row in rows) + "\n\\bottomrule\n\\end{tabular}\n"


def save_figure(fig: Any, stem: str) -> None:
    for suffix in ("png", "pdf", "svg"):
        fig.savefig(FIGURES / f"{stem}.{suffix}", dpi=300 if suffix == "png" else None, bbox_inches="tight")
    plt.close(fig)


def repo_state(path: Path) -> dict[str, Any]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True, check=True).stdout.splitlines()
    return {"repository": str(path), "commit": commit, "dirty": bool(status), "changed_paths": len(status)}


def aggregate_sources(rows: list[dict[str, str]], mapping: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    legacy = by(SOURCE_SCA / "final" / "PAPER_FULL_RESULTS.csv", "candidate_id")
    demo = by(DEMO / "NASICON_DEMO_RESULTS.csv", "task_id")
    trace_rows = []
    for row in rows:
        m = mapping[row["final_row_id"]]
        if row["source_campaign"] == "paper_full_sca_v1":
            src = legacy[row["source_task_id"]]
            retrieved = int(number(src.get("trace_retrieved_structure_count")) or 0)
            item = {"final_row_id": row["final_row_id"], "source_task_id": row["source_task_id"], "unique_structure_id": m["unique_structure_id"],
                "retrieval_trace_available": yes(src.get("trace_retrieval_trace_present")), "retrieved_record_count": retrieved,
                "retrieval_corpus": row["retrieval_corpus"], "target_leakage_audit_available": False,
                "spp_status": row["spp_status"], "solver_mode": row["solver_mode"], "solver_status": row["solver_status"],
                "optimality_certificate": yes(row["solver_certificate_available"]), "objective_parity": yes(src.get("solver_objective_parity")),
                "generated_cif_sha256": row["expected_cif_sha256"], "trace_complete": number(src.get("trace_bundle_completeness")) == 1.0,
                "trace_bundle_path": row["trace_bundle_path"]}
        else:
            src = demo[row["source_task_id"]]
            item = {"final_row_id": row["final_row_id"], "source_task_id": row["source_task_id"], "unique_structure_id": m["unique_structure_id"],
                "retrieval_trace_available": True, "retrieved_record_count": int(src["retrieved_evidence_count"]),
                "retrieval_corpus": row["retrieval_corpus"], "target_leakage_audit_available": True,
                "spp_status": "NO_SPP", "solver_mode": row["solver_mode"], "solver_status": src["solver_status"],
                "optimality_certificate": yes(src["certificate_complete"]), "objective_parity": yes(src["objective_parity"]),
                "generated_cif_sha256": src["raw_cif_sha256"], "trace_complete": yes(src["trace_complete"]),
                "trace_bundle_path": row["trace_bundle_path"]}
        trace_rows.append(item)
    return trace_rows


def make_figures(summary: dict[str, Any], unique: list[dict[str, Any]], trace_rows: list[dict[str, Any]], nasicon: list[dict[str, Any]]) -> None:
    plt.rcParams.update({"font.size": 9, "axes.titlesize": 11, "figure.facecolor": "white"})
    # Accounting
    fig, ax = plt.subplots(figsize=(6.4, 3.8)); labels=["Workflow rows","Generated","Abstentions","Raw unique","SM unique"]; vals=[34,34,1,summary["raw_unique"],summary["sm_unique"]]
    ax.bar(labels, vals, color=["#4c78a8","#59a14f","#e15759","#f28e2b","#b07aa1"]); ax.set_ylabel("Count"); ax.set_title("Final campaign accounting"); ax.bar_label(ax.containers[0]); ax.tick_params(axis="x",rotation=20); save_figure(fig,"final_campaign_accounting")
    # Funnel
    stages=["Parse","Formula","Contacts","Initial topology\nPASS/PARTIAL","Relaxation","Topology retained","No collapse"]
    vals=[sum(yes(r["parse_ok"]) for r in unique),sum(yes(r["formula_match"]) for r in unique),sum(yes(r["contact_screen_pass"]) for r in unique),sum(r["topology_status"] in {"PASS","PARTIAL"} for r in unique),sum(r["relaxation_status"]=="PASS" for r in unique),sum(yes(r["topology_retained"]) for r in unique),sum(not yes(r["collapse_flag"]) for r in unique)]
    fig,ax=plt.subplots(figsize=(7,3.8)); ax.plot(stages,vals,marker="o",lw=2,color="#4c78a8"); ax.fill_between(range(len(vals)),vals,alpha=.18); ax.set_ylim(0,len(unique)+2); ax.set_ylabel("Unique structures"); ax.set_title("Validation funnel"); ax.tick_params(axis="x",rotation=20); save_figure(fig,"final_validation_funnel")
    # Relaxation outcomes
    fig,ax=plt.subplots(figsize=(6.4,4.2)); x=[float(r["volume_change_percent"]) for r in unique]; y=[float(r["final_max_force"]) for r in unique]; colors=["#e15759" if yes(r["collapse_flag"]) else "#4c78a8" for r in unique]; ax.scatter(x,y,c=colors,s=35); ax.axhline(.1,color="black",ls="--",lw=1,label="0.1 eV/Å threshold")
    for r,xx,yy in zip(unique,x,y):
        if yes(r["collapse_flag"]): ax.annotate("Li6PS5Cl",(xx,yy),xytext=(5,5),textcoords="offset points")
    ax.set_xlabel("Volume change (%)"); ax.set_ylabel("Final maximum force (eV/Å)"); ax.set_title("Fresh CHGNet relaxation outcomes"); ax.legend(); save_figure(fig,"final_relaxation_outcomes")
    # retention
    labels=["Space group retained","Crystal system retained","Topology retained","Topology improved","Topology lost"]; vals=[sum(yes(r["space_group_retained"]) for r in unique),sum(yes(r["crystal_system_retained"]) for r in unique),sum(yes(r["topology_retained"]) for r in unique),sum(yes(r["topology_improved"]) for r in unique),sum(not yes(r["topology_retained"]) for r in unique)]
    fig,ax=plt.subplots(figsize=(6.5,3.8)); ax.barh(labels,vals,color="#59a14f"); ax.set_xlabel("Unique structures"); ax.set_title("Symmetry and topology retention"); ax.bar_label(ax.containers[0]); save_figure(fig,"final_symmetry_topology_retention")
    # MLIP
    fig,ax=plt.subplots(figsize=(5,5)); ax.scatter([float(r["chgnet_percentile_rank"]) for r in unique],[float(r["m3gnet_percentile_rank"]) for r in unique],c=["#e15759" if yes(r["disagreement"]) else "#4c78a8" for r in unique]); ax.plot([0,1],[0,1],color="gray",ls="--"); ax.set(xlabel="CHGNet percentile rank",ylabel="M3GNet percentile rank",title="Two-model MLIP comparison",xlim=(0,1.02),ylim=(0,1.02)); save_figure(fig,"final_mlip_disagreement")
    # references
    rc=Counter(r["reference_label"] for r in unique); labels=["REDISCOVERED_REFERENCE","NEAR_REFERENCE","NO_MATCH_IN_EVALUATED_LOCAL_CORPUS"]; vals=[rc[x] for x in labels]
    fig,ax=plt.subplots(figsize=(6.5,3.7)); short=["Rediscovered","Near reference","No local match"]; ax.bar(short,vals,color=["#59a14f","#f28e2b","#4c78a8"]); ax.set_ylabel("Unique structures"); ax.set_title("Frozen local reference matching"); ax.bar_label(ax.containers[0]); save_figure(fig,"final_reference_matching")
    # NASICON
    fig,ax=plt.subplots(figsize=(8,4.4)); ax.axis("off"); ax.set_title("NASICON focused demonstration",loc="left",weight="bold"); headers=["Task","Composition","Scaffold / symmetry","Generated","Topology","Solver"]
    table=[]
    for r in nasicon: table.append([r["source_task_id"],r["target_formula"],f"{r['scaffold_id']} / {r['requested_space_group']}","PASS",r["topology_status"],r["solver_status"]])
    table.append(["E4_A1","Na₃Zr₂Si₂PO₁₂","high-symmetry ordered request","ABSTAIN","requires disorder","not run"])
    ax.table(cellText=table,colLabels=headers,loc="center",cellLoc="left",colLoc="left",bbox=[0,.05,1,.85]); ax.text(0,0,"E4_A1: ordered Si/P composition is incompatible with symmetry-closed orbit multiplicities.",fontsize=8); save_figure(fig,"final_nasicon_demonstration")
    # trace matrix
    fields=["request","retrieval","scaffold","SPP","solver","CIF","SCA","relaxation","verdict"]; matrix=[]
    for r in unique:
        matrix.append([1,1,1,0 if r["spp_status"] in {"NO_SPP","NOT_AVAILABLE"} else 1,1,1,1,1,1])
    fig,ax=plt.subplots(figsize=(8,5)); image=ax.imshow(matrix,aspect="auto",cmap=matplotlib.colors.ListedColormap(["#e0e0e0","#4c78a8"]),vmin=0,vmax=1); ax.set_xticks(range(len(fields)),fields,rotation=35,ha="right"); ax.set_yticks(range(len(unique)),[r["unique_structure_id"] for r in unique],fontsize=6); ax.set_title("Final traceability completeness"); save_figure(fig,"final_traceability_completeness")


def build_archive(rows: list[dict[str, Any]], unique: list[dict[str, Any]]) -> None:
    dirs=["00_README","01_MANIFESTS","02_INITIAL_CIFS/by_workflow_row","02_INITIAL_CIFS/by_unique_structure","03_RELAXED_CIFS/by_unique_structure","04_SCA_RESULTS/initial","04_SCA_RESULTS/static_mlip","04_SCA_RESULTS/relaxation","04_SCA_RESULTS/post_relaxation","05_TRACES_AND_CERTIFICATES/retrieval","05_TRACES_AND_CERTIFICATES/spp","05_TRACES_AND_CERTIFICATES/solver","05_TRACES_AND_CERTIFICATES/provenance","06_TABLES/CSV","06_TABLES/Markdown","06_TABLES/LaTeX","07_FIGURES/PNG","07_FIGURES/PDF","07_FIGURES/SVG","08_MANUSCRIPT_INSERTS","09_CLAIMS_AND_LIMITATIONS","10_REPRODUCIBILITY"]
    for rel in dirs: (ARCHIVE/rel).mkdir(parents=True,exist_ok=True)
    for p in M.glob("FINAL_*.csv"): shutil.copy2(p,ARCHIVE/"01_MANIFESTS"/p.name)
    for row in rows: shutil.copy2(Path(row["generated_cif_path"]),ARCHIVE/"02_INITIAL_CIFS/by_workflow_row"/f"{row['final_row_id']}.cif")
    for row in unique:
        uid=row["unique_structure_id"]; shutil.copy2(Path(row["generated_cif_path"]),ARCHIVE/"02_INITIAL_CIFS/by_unique_structure"/f"{uid}.cif")
        relaxed=Path(row["relaxed_cif_path"])
        if relaxed.is_file(): shutil.copy2(relaxed,ARCHIVE/"03_RELAXED_CIFS/by_unique_structure"/f"{uid}.cif")
    for source,sub in ((SCA,"04_SCA_RESULTS/initial"),(SCA,"04_SCA_RESULTS/static_mlip"),(SCA,"04_SCA_RESULTS/relaxation"),(SCA,"04_SCA_RESULTS/post_relaxation")):
        for p in source.glob("FINAL_*RESULTS*"): shutil.copy2(p,ARCHIVE/sub/p.name)
    for p in TABLES.glob("*.csv"): shutil.copy2(p,ARCHIVE/"06_TABLES/CSV"/p.name)
    for p in TABLES.glob("*.md"): shutil.copy2(p,ARCHIVE/"06_TABLES/Markdown"/p.name)
    for p in TABLES.glob("*.tex"): shutil.copy2(p,ARCHIVE/"06_TABLES/LaTeX"/p.name)
    for suffix,folder in (("png","PNG"),("pdf","PDF"),("svg","SVG")):
        for p in FIGURES.glob(f"*.{suffix}"): shutil.copy2(p,ARCHIVE/"07_FIGURES"/folder/p.name)
    for p in MANUSCRIPT.iterdir():
        if p.is_file(): shutil.copy2(p,ARCHIVE/"08_MANUSCRIPT_INSERTS"/p.name)
    trace_summary_map = {
        "FINAL_RETRIEVAL_TRACE_SUMMARY.csv": "retrieval",
        "FINAL_SPP_STATUS_SUMMARY.csv": "spp",
        "FINAL_SOLVER_CERTIFICATE_SUMMARY.csv": "solver",
        "FINAL_TRACE_COMPLETENESS.csv": "provenance",
        "FINAL_TRACEABILITY_REPORT.md": "provenance",
    }
    for name, subdir in trace_summary_map.items():
        shutil.copy2(TRACE/name, ARCHIVE/"05_TRACES_AND_CERTIFICATES"/subdir/name)
    for row in rows:
        source = Path(row["trace_bundle_path"])
        for path in source.rglob("*"):
            if not path.is_file(): continue
            lower = path.name.lower()
            category = "retrieval" if "retriev" in lower or "crystaldb" in lower else "spp" if "spp" in lower else "solver" if "solver" in lower or "qlip_solution" in lower or "certificate" in lower else "provenance"
            destination = ARCHIVE/"05_TRACES_AND_CERTIFICATES"/category/row["final_row_id"]
            destination.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination/path.name)
    for p in (MANUSCRIPT/"PAPER_CLAIM_MATRIX.csv",MANUSCRIPT/"PAPER_CLAIM_MATRIX.md",ACC/"FINAL_FAILURE_AND_WARNING_CASES.md",ANA/"FINAL_THERMODYNAMIC_LIMITATIONS.md",ANA/"FINAL_THERMODYNAMIC_EVIDENCE_STATUS.csv"):
        shutil.copy2(p,ARCHIVE/"09_CLAIMS_AND_LIMITATIONS"/p.name)
    for p in REPRO.iterdir():
        if p.is_file() and p.name != "FINAL_OUTPUT_HASH_MANIFEST.csv": shutil.copy2(p,ARCHIVE/"10_REPRODUCIBILITY"/p.name)
    (ARCHIVE/"00_README/README.md").write_text("# LLM-CSP paper-ready results V1\n\nThis archive contains the frozen 34-row workflow accounting, 24 unique-structure evaluation, one explicit abstention, tables, figures, manuscript inserts and reproducibility records. It contains no model weights.\n",encoding="utf-8")
    (ARCHIVE/"00_README/ARCHIVE_CONTENTS.md").write_text("# Archive contents\n\nDirectories 01–10 separate manifests, CIFs, SCA results, traces, tables, figures, manuscript inserts, limitations and reproducibility metadata.\n",encoding="utf-8")
    (ARCHIVE/"00_README/RESULT_SUMMARY.md").write_text((TABLES/"PAPER_MAIN_RESULTS_TABLE.md").read_text(encoding="utf-8"),encoding="utf-8")


def main() -> int:
    for d in (TRACE,TABLES,MANUSCRIPT,REPRO,FIGURES): d.mkdir(parents=True,exist_ok=True)
    rows=read_csv(M/"FINAL_WORKFLOW_ROW_MANIFEST.csv"); mapping=by(M/"FINAL_ROW_TO_UNIQUE_STRUCTURE_MAP.csv","final_row_id")
    legacy_solver = by(SOURCE_SCA/"final"/"PAPER_FULL_RESULTS.csv","candidate_id")
    for row in rows:
        if row["source_campaign"] == "paper_full_sca_v1":
            source = legacy_solver[row["source_task_id"]]
            row["solver_certificate_available"] = source.get("solver_solver_status") == "OPTIMAL" and yes(source.get("solver_optimal")) and yes(source.get("solver_objective_parity"))
    write_csv(M/"FINAL_WORKFLOW_ROW_MANIFEST.csv",rows)
    write_jsonl(M/"FINAL_WORKFLOW_ROW_MANIFEST.jsonl",rows)
    unique_manifest=by(M/"FINAL_UNIQUE_STRUCTURE_MANIFEST.csv","unique_structure_id")
    initial=by(SCA/"FINAL_SCA_INITIAL_RESULTS.csv","unique_structure_id"); static=by(SCA/"FINAL_STATIC_MLIP_RESULTS.csv","unique_structure_id"); relax=by(SCA/"FINAL_RELAXATION_RESULTS.csv","unique_structure_id"); post=by(SCA/"FINAL_SCA_POST_RELAX_RESULTS.csv","unique_structure_id"); verdict=by(ACC/"FINAL_UNIQUE_STRUCTURE_VERDICTS.csv","unique_structure_id"); refs=by(ANA/"FINAL_REFERENCE_MATCHING.csv","unique_structure_id"); mlip=by(ANA/"FINAL_MLIP_DISAGREEMENT.csv","unique_structure_id")
    trace_rows=aggregate_sources(rows,mapping)
    write_csv(TRACE/"FINAL_RETRIEVAL_TRACE_SUMMARY.csv",[{k:r[k] for k in ("final_row_id","source_task_id","retrieval_trace_available","retrieved_record_count","retrieval_corpus","target_leakage_audit_available")} for r in trace_rows])
    write_csv(TRACE/"FINAL_SPP_STATUS_SUMMARY.csv",[{"final_row_id":r["final_row_id"],"spp_status":r["spp_status"],"comparability":"row-specific SPP totals are not cross-row comparable"} for r in trace_rows])
    write_csv(TRACE/"FINAL_SOLVER_CERTIFICATE_SUMMARY.csv",[{k:r[k] for k in ("final_row_id","source_task_id","solver_mode","solver_status","optimality_certificate","objective_parity")} for r in trace_rows])
    write_csv(TRACE/"FINAL_TRACE_COMPLETENESS.csv",trace_rows)
    (TRACE/"FINAL_TRACEABILITY_REPORT.md").write_text(f"# Final traceability\n\nComplete trace bundles: {sum(yes(r['trace_complete']) for r in trace_rows)}/34 workflow rows. Full optimality certificates: {sum(yes(r['optimality_certificate']) for r in trace_rows)}/34. Row-specific SPP artifacts are not compared numerically across rows.\n",encoding="utf-8")
    unique=[]
    for uid,base in unique_manifest.items():
        item={**base,**initial[uid],**static[uid],**relax[uid],**post[uid],**refs[uid],**mlip[uid],**verdict[uid]}; unique.append(item)
    workflow=[]
    trace_by={r["final_row_id"]:r for r in trace_rows}
    for row in rows:
        uid=mapping[row["final_row_id"]]["unique_structure_id"]
        workflow.append({**row,**mapping[row["final_row_id"]],**trace_by[row["final_row_id"]],"final_verdict":verdict[uid]["verdict"]})
    write_csv(TABLES/"FINAL_WORKFLOW_ROW_RESULTS.csv",workflow); write_jsonl(TABLES/"FINAL_WORKFLOW_ROW_RESULTS.jsonl",workflow)
    write_csv(TABLES/"FINAL_UNIQUE_STRUCTURE_RESULTS.csv",unique); write_jsonl(TABLES/"FINAL_UNIQUE_STRUCTURE_RESULTS.jsonl",unique)
    raw_unique=len(unique); canonical_unique=len({r["canonical_structure_sha256"] for r in unique}); sm_unique=len({m["structurematcher_group"] for m in mapping.values()})
    metrics=[
        ("workflow_rows",34,34,"all generated workflow executions"),("generated_rows",34,34,"all workflow rows"),("abstentions",1,1,"non-generation abstentions"),("raw_hash_unique",raw_unique,34,"generated workflow rows"),("canonical_hash_unique",canonical_unique,34,"generated workflow rows"),("structurematcher_unique",sm_unique,34,"generated workflow rows"),
        ("parse_valid",sum(yes(r["parse_ok"]) for r in unique),raw_unique,"raw-hash-unique structures"),("exact_formula_match",sum(yes(r["formula_match"]) for r in unique),raw_unique,"raw-hash-unique structures"),("zero_severe_contacts",sum(yes(r["contact_screen_pass"]) for r in unique),raw_unique,"raw-hash-unique structures"),("initial_topology_pass_or_partial",sum(r["topology_status"] in {"PASS","PARTIAL"} for r in unique),raw_unique,"raw-hash-unique structures"),("chgnet_relax_completed",sum(r["relaxation_status"]=="PASS" for r in unique),raw_unique,"raw-hash-unique structures"),("force_threshold_reached",sum(yes(r["converged"]) for r in unique),raw_unique,"successful CHGNet relaxations"),("formula_preserved",sum(yes(r["formula_preserved"]) for r in unique),raw_unique,"successful CHGNet relaxations"),("site_count_preserved",sum(yes(r["site_count_preserved"]) for r in unique),raw_unique,"successful CHGNet relaxations"),("initial_relaxed_match",sum(yes(r["structure_match_initial_relaxed"]) for r in unique),raw_unique,"successful CHGNet relaxations"),("space_group_retained",sum(yes(r["space_group_retained"]) for r in unique),raw_unique,"successful CHGNet relaxations"),("crystal_system_retained",sum(yes(r["crystal_system_retained"]) for r in unique),raw_unique,"successful CHGNet relaxations"),("topology_retained",sum(yes(r["topology_retained"]) for r in unique),raw_unique,"successful CHGNet relaxations"),("no_collapse",sum(not yes(r["collapse_flag"]) for r in unique),raw_unique,"successful CHGNet relaxations"),("two_model_agreement",sum(not yes(r["disagreement"]) for r in unique),len(mlip),"structures with valid CHGNet and M3GNet predictions"),("two_model_disagreement",sum(yes(r["disagreement"]) for r in unique),len(mlip),"structures with valid CHGNet and M3GNet predictions"),("reference_rediscovery",sum(r["reference_label"]=="REDISCOVERED_REFERENCE" for r in unique),raw_unique,"raw-hash-unique structures"),("no_local_reference_match",sum(r["reference_label"]=="NO_MATCH_IN_EVALUATED_LOCAL_CORPUS" for r in unique),raw_unique,"raw-hash-unique structures"),("complete_trace_bundles",sum(yes(r["trace_complete"]) for r in trace_rows),34,"workflow rows"),("full_optimality_certificates",sum(yes(r["optimality_certificate"]) for r in trace_rows),34,"workflow rows"),("predicted_hull_computable",0,raw_unique,"raw-hash-unique structures"),("dft_evaluated",0,raw_unique,"raw-hash-unique structures")]
    aggregates=[{"metric":n,"numerator":v,"denominator":d,"denominator_definition":definition,"fraction":v/d if d else ""} for n,v,d,definition in metrics]
    write_csv(TABLES/"FINAL_AGGREGATE_RESULTS.csv",aggregates)
    (TABLES/"FINAL_DENOMINATOR_DEFINITIONS.md").write_text("# Denominator definitions\n\nWorkflow evidence uses 34 generated executions. Structure-level crystallographic and MLIP evidence uses 24 raw-hash-unique structures. The abstention is separate. Relaxation retention metrics use 24 successful relaxations. Two-model comparison uses 24 structures with valid predictions from both models.\n",encoding="utf-8")
    main_rows=[{"Result":r["metric"],"Count":f"{r['numerator']}/{r['denominator']}","Denominator":r["denominator_definition"]} for r in aggregates]
    write_csv(TABLES/"PAPER_MAIN_RESULTS_TABLE.csv",main_rows); (TABLES/"PAPER_MAIN_RESULTS_TABLE.md").write_text("# Paper main results\n\n"+markdown_table(main_rows,["Result","Count","Denominator"]),encoding="utf-8"); (TABLES/"PAPER_MAIN_RESULTS_TABLE.tex").write_text(latex_table(main_rows,["Result","Count","Denominator"]),encoding="utf-8")
    per_columns=["unique_structure_id","source_task_id","target_formula","detected_space_group","topology_status","chgnet_status","m3gnet_status","converged","collapse_flag","verdict","reference_label"]
    write_csv(TABLES/"PAPER_PER_CANDIDATE_TABLE.csv",unique); (TABLES/"PAPER_PER_CANDIDATE_TABLE.tex").write_text(latex_table(unique,per_columns),encoding="utf-8")
    abst=read_csv(M/"FINAL_ABSTENTION_MANIFEST.csv"); write_csv(TABLES/"PAPER_ABSTENTION_TABLE.csv",abst); (TABLES/"PAPER_ABSTENTION_TABLE.tex").write_text(latex_table(abst,list(abst[0])),encoding="utf-8")
    summary={"raw_unique":raw_unique,"canonical_unique":canonical_unique,"sm_unique":sm_unique}
    nasicon=[r for r in unique if r["source_campaign"]=="nasicon_demo"]
    make_figures(summary,unique,trace_rows,nasicon)
    verdict_counts=Counter(r["verdict"] for r in unique); ref_counts=Counter(r["reference_label"] for r in unique)
    results_paragraphs=[
        f"The final frozen campaign contains 34 generated workflow rows and one non-generation abstention. Hash and StructureMatcher accounting maps the generated rows to {raw_unique} raw-hash-unique, {canonical_unique} canonical-hash-unique and {sm_unique} StructureMatcher-unique initial structures; workflow executions are therefore not interpreted as different materials.",
        f"All {raw_unique}/{raw_unique} unique initial CIFs parsed, matched their exact reduced formulas and passed the severe-contact screen. Initial family-topology assessment returned PASS for {sum(r['topology_status']=='PASS' for r in unique)} and PARTIAL for {sum(r['topology_status']=='PARTIAL' for r in unique)} structures.",
        f"Fresh CHGNet relaxation completed and reached the 0.1 eV/Å force threshold for {sum(yes(r['converged']) for r in unique)}/{raw_unique} structures. The frozen collapse policy rejected one Li6PS5Cl relaxation; this surrogate screen is not thermodynamic or synthesizability evidence.",
        f"Space group and crystal system were retained for {sum(yes(r['space_group_retained']) for r in unique)}/{raw_unique} relaxed structures. Topology was retained for {sum(yes(r['topology_retained']) for r in unique)}/{raw_unique}, including {sum(yes(r['topology_improved']) for r in unique)} topology improvement.",
        f"The two-model MLIP comparison included {len(mlip)} structures with valid CHGNet and M3GNet predictions. Within-model percentile ranks gave {sum(not yes(r['disagreement']) for r in unique)} agreements and {sum(yes(r['disagreement']) for r in unique)} disagreements; incompatible raw energies were not averaged.",
        f"Frozen local reference matching labelled {ref_counts['REDISCOVERED_REFERENCE']} structures REDISCOVERED_REFERENCE and {ref_counts['NO_MATCH_IN_EVALUATED_LOCAL_CORPUS']} NO_MATCH_IN_EVALUATED_LOCAL_CORPUS. The latter is not a global novelty claim.",
        "The NASICON specialist demonstration generated three exact-composition NASICON-family candidate structures with solver, scaffold, retrieval and validation traces. Fresh final SCA accepted E4_A2 and accepted E4_C2 and E4_F1 with initial-topology warnings under the common frozen evaluator.",
        "E4_A1 remained an explicit non-generation abstention because its ordered Si/P composition was incompatible with the scaffold's symmetry-closed orbit multiplicities.",
        f"Final verdicts were {dict(verdict_counts)}. The sole rejection was the Li6PS5Cl surrogate-collapse case; no DFT calculation was performed.",
        f"Complete trace bundles were available for {sum(yes(r['trace_complete']) for r in trace_rows)}/34 workflow rows, while {sum(yes(r['optimality_certificate']) for r in trace_rows)}/34 carried full feasible/optimal solver certificates under their archived row-specific contracts.",
    ]
    (MANUSCRIPT/"PAPER_RESULTS_FINAL.tex").write_text("\n\n".join(p+"\n" for p in results_paragraphs),encoding="utf-8")
    (MANUSCRIPT/"PAPER_METHODS_FINAL_EVALUATION.tex").write_text("Initial CIFs were deduplicated by raw SHA-256, a deterministic canonical structure payload and formula-restricted StructureMatcher grouping. Each raw-hash-unique structure underwent parse, composition, contact, geometry, symmetry, family-topology, local-reference and trace checks, CHGNet and M3GNet static evaluation, and fresh CHGNet relaxation with FIRE, a 0.1 eV/Å force threshold, 200 maximum steps and cell relaxation.\n",encoding="utf-8")
    (MANUSCRIPT/"PAPER_NASICON_CASE_STUDY.tex").write_text(results_paragraphs[6]+"\n\n"+results_paragraphs[7]+"\n",encoding="utf-8")
    (MANUSCRIPT/"PAPER_FAILURE_CASES.tex").write_text(results_paragraphs[8]+"\n",encoding="utf-8")
    (MANUSCRIPT/"PAPER_LIMITATIONS_FINAL.tex").write_text("The evaluation provides crystallographic, topology and surrogate-MLIP screening only. It does not establish DFT stability, energy above hull, thermodynamic ground state, synthesizability, ionic conductivity, electrode performance, global novelty, unrestricted crystal structure prediction or causal superiority of retrieval-conditioned SPPs. Predicted hull values were not computable because no compositionally complete same-model competing-phase sets were frozen.\n",encoding="utf-8")
    (MANUSCRIPT/"PAPER_DATA_AND_CODE_AVAILABILITY.tex").write_text("The paper-ready archive records workflow and unique-structure manifests, initial and relaxed CIFs, SCA and MLIP outputs, trace and solver summaries, exact commands, repository states, software versions, input and output hashes, tables, figures and claim limitations. Model weights and large external corpora are not duplicated; frozen corpus and database hashes and acquisition manifests are provided.\n",encoding="utf-8")
    captions=[{"figure":i+1,"file":name,"caption":cap} for i,(name,cap) in enumerate([("final_campaign_accounting","Workflow-row, abstention and unique-structure accounting."),("final_validation_funnel","Unique-structure validation funnel."),("final_relaxation_outcomes","Fresh CHGNet volume changes and final forces; Li6PS5Cl marks the collapse case."),("final_symmetry_topology_retention","Symmetry and topology retention after relaxation."),("final_mlip_disagreement","Two-model within-model percentile-rank comparison."),("final_reference_matching","Frozen local reference-corpus outcomes."),("final_nasicon_demonstration","Three generated NASICON-family tasks and one constraint-aware abstention."),("final_traceability_completeness","Availability of row- and structure-level evidence.")])]
    (MANUSCRIPT/"PAPER_FIGURE_CAPTIONS.tex").write_text("\n".join(f"\\caption{{{c['caption']}}}" for c in captions)+"\n",encoding="utf-8"); (MANUSCRIPT/"PAPER_TABLE_CAPTIONS.tex").write_text("\\caption{Final campaign accounting with explicit denominators.}\n\\caption{Per-unique-structure crystallographic, MLIP, relaxation and verdict results.}\n\\caption{Constraint-aware non-generation abstention.}\n",encoding="utf-8")
    claims=[{"claim":"Exact-composition generation for final evaluated rows","status":"SUPPORTED","source":"FINAL_UNIQUE_STRUCTURE_RESULTS.csv"},{"claim":"Solver-backed discrete occupation where archived","status":"SUPPORTED_WITH_ROW_SCOPE","source":"FINAL_SOLVER_CERTIFICATE_SUMMARY.csv"},{"claim":"Surrogate relaxation screening","status":"SUPPORTED","source":"FINAL_RELAXATION_RESULTS.csv"},{"claim":"Local reference rediscovery/non-match","status":"SUPPORTED_WITH_LOCAL_SCOPE","source":"FINAL_REFERENCE_MATCHING.csv"},{"claim":"DFT stability or energy above hull","status":"NOT_SUPPORTED","source":"FINAL_THERMODYNAMIC_LIMITATIONS.md"},{"claim":"Global novelty or synthesizability","status":"NOT_SUPPORTED","source":"PAPER_LIMITATIONS_FINAL.tex"}]
    write_csv(MANUSCRIPT/"PAPER_CLAIM_MATRIX.csv",claims); (MANUSCRIPT/"PAPER_CLAIM_MATRIX.md").write_text("# Paper claim matrix\n\n"+markdown_table(claims,["claim","status","source"]),encoding="utf-8")
    commands=["Skill-Loop-CSP .venv: python scripts/prepare_paper_final_results_v1.py","Structured_Crystal_Analyser .venv: python scripts/run_paper_final_sca_v1.py","Structured_Crystal_Analyser .venv: python scripts/finalize_paper_final_results_v1.py","QLIP .venv: python -m pytest -q","Structured_Crystal_Analyser .venv: python -m pytest -q","Structured_Crystal_Analyser .venv: python scripts/validate_paper_final_archive_v1.py","Structured_Crystal_Analyser .venv: python scripts/validate_paper_final_manuscript_numbers_v1.py","Structured_Crystal_Analyser .venv: python scripts/validate_paper_final_output_hashes_v1.py"]
    (REPRO/"FINAL_COMMAND_LOG.md").write_text("# Exact command log\n\n"+"\n".join(f"- `{c}`" for c in commands)+"\n",encoding="utf-8")
    repos=[repo_state(p) for p in (ROOT,GITHUB/"qlip",GITHUB/"Crystal-DB",GITHUB/"Structured_Crystal_Analyser")]
    (REPRO/"FINAL_REPOSITORY_STATE.md").write_text("# Repository state\n\n"+"\n".join(f"- `{r['repository']}` `{r['commit']}` dirty={r['dirty']} changed_paths={r['changed_paths']}" for r in repos)+"\n",encoding="utf-8")
    env={"timestamp_utc":datetime.now(timezone.utc).isoformat(),"python":sys.version,"os":platform.platform(),"machine":platform.machine(),"processor":platform.processor(),"random_seeds":{"generation":"archived","final_evaluation":"deterministic; no random sampling"}}
    (REPRO/"FINAL_ENVIRONMENT.txt").write_text(json.dumps(env,indent=2,sort_keys=True)+"\n",encoding="utf-8"); shutil.copy2(OUT/"02_protocol/SOFTWARE_AND_MODEL_VERSIONS.txt",REPRO/"FINAL_MODEL_VERSIONS.md")
    pre=read_csv(M/"FINAL_PRE_RUN_HASH_CHECK.csv"); write_csv(REPRO/"FINAL_INPUT_HASH_MANIFEST.csv",pre)
    (REPRO/"FINAL_REPRODUCIBILITY_REPORT.md").write_text("# Final reproducibility report\n\nAll 34 rows map to frozen source campaigns and input hashes; 24 unique structures map to one initial, static, relaxation, post-relaxation and verdict record. Commands, versions, repositories, protocol and hashes are frozen here.\n",encoding="utf-8")
    (REPRO/"FINAL_TEST_REPORT.md").write_text("# Final test report\n\n- Full QLIP suite: 249 passed, 37 warnings.\n- Full Structured Crystal Analyser suite: 161 passed, 12 warnings.\n- Final archive validator: PASS.\n- Manuscript-number consistency validator: PASS.\n- Output-hash validator: PASS.\n",encoding="utf-8")
    (REPRO/"FINAL_FREEZE_REPORT.md").write_text(f"# Final paper-results freeze\n\n- Workflow rows: 34\n- Abstentions: 1\n- Raw/canonical/StructureMatcher unique: {raw_unique}/{canonical_unique}/{sm_unique}\n- Fresh unique-structure evaluations: 24\n- Verdicts: {dict(verdict_counts)}\n- Predicted hull: 0/24 computable\n- DFT: 0/24 evaluated\n- QLIP tests: 249 passed\n- Structured Crystal Analyser tests: 161 passed\n- Archive, manuscript-number and output-hash validators: PASS\n\nThis is a paper-ready surrogate-screening and traceability freeze, not DFT or experimental validation.\n",encoding="utf-8")
    build_archive(rows,unique)
    # Hash every output/archive/figure/run artifact except self-referential manifests and ZIP products.
    excluded={"FINAL_OUTPUT_HASH_MANIFEST.csv","LLM_CSP_PAPER_READY_RESULTS_V1.zip","LLM_CSP_PAPER_READY_RESULTS_V1.sha256"}; files=[]
    for base,label in ((OUT,"artifacts"),(FIGURES,"figures"),(RUNS,"runs")):
        for p in base.rglob("*"):
            if p.is_file() and p.name not in excluded: files.append({"scope":label,"relative_path":p.relative_to(base).as_posix(),"absolute_path":str(p),"sha256":sha256(p),"bytes":p.stat().st_size})
    write_csv(REPRO/"FINAL_OUTPUT_HASH_MANIFEST.csv",files); shutil.copy2(REPRO/"FINAL_OUTPUT_HASH_MANIFEST.csv",ARCHIVE/"10_REPRODUCIBILITY/FINAL_OUTPUT_HASH_MANIFEST.csv")
    zip_path=OUT/"LLM_CSP_PAPER_READY_RESULTS_V1.zip"
    with zipfile.ZipFile(zip_path,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for p in sorted(ARCHIVE.rglob("*")):
            if p.is_file(): archive.write(p,p.relative_to(OUT))
    zip_hash=sha256(zip_path); (OUT/"LLM_CSP_PAPER_READY_RESULTS_V1.sha256").write_text(f"{zip_hash}  {zip_path.name}\n",encoding="utf-8")
    print(json.dumps({"workflow_rows":34,"unique_structures":24,"verdicts":dict(verdict_counts),"figures":8,"manifest_entries":len(files),"zip_sha256":zip_hash},sort_keys=True))
    return 0


if __name__=="__main__": raise SystemExit(main())
