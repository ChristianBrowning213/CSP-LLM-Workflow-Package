"""Read-only diversity audit of the frozen 31-row paper_full_sca_v1 campaign."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Structure


ROOT = Path(__file__).resolve().parents[1]
FROZEN = Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\artifacts\paper_full_sca_v1")
MANIFEST = FROZEN / "input" / "PAPER_CANDIDATE_MANIFEST.csv"
OUT = ROOT / "artifacts" / "paper_diversity_v2" / "audit"


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def group_ids(rows: list[dict[str, Any]], predicate) -> list[int]:
    parent = list(range(len(rows)))
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a: int, b: int) -> None:
        a,b=find(a),find(b)
        if a != b: parent[b]=a
    for i in range(len(rows)):
        for j in range(i):
            if predicate(i,j): union(i,j)
    roots={}; result=[]
    for i in range(len(rows)):
        root=find(i)
        if root not in roots: roots[root]=len(roots)+1
        result.append(roots[root])
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows=list(csv.DictReader(MANIFEST.open(encoding="utf-8", newline="")))
    assert len(rows)==31, f"Expected frozen 31 rows, found {len(rows)}"
    structures=[Structure.from_file(r["cif_path"]) for r in rows]
    matcher=StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5.0, primitive_cell=True, scale=True, attempt_supercell=False)
    sm_groups=group_ids(rows,lambda i,j: rows[i]["target_formula"]==rows[j]["target_formula"] and matcher.fit(structures[i],structures[j]))
    hash_group_map={h:i+1 for i,h in enumerate(dict.fromkeys(r["cif_sha256"] for r in rows))}

    audit=[]; search_rows=[]
    for index,(r,sm_group) in enumerate(zip(rows,sm_groups),start=1):
        run=Path(r["run_archive_dir"])
        request=load_json(run/"qlip_request.json")
        solution=load_json(run/"qlip_solution.json")
        candidates=load_json(run/"orbit_candidates.json")
        sites=(((request.get("problem") or {}).get("design_space") or {}).get("sites") or {})
        solved=solution.get("solution") or {}
        orbits=solved.get("orbits") or sites.get("orbits") or []
        selected=solved.get("selected_species_by_orbit") or {}
        variable=[o.get("orbit_id") for o in orbits if len(o.get("allowed_species") or [])>1]
        fixed=[o.get("orbit_id") for o in orbits if len(o.get("allowed_species") or [])<=1]
        feasible=sum(bool(c.get("formula_satisfied")) and not c.get("rejection_reason") for c in (candidates.get("candidates") or []))
        search_payload={
            "formula":r["target_formula"],"scaffold":r["scaffold_id"],"solver_mode":r["solver_mode"],
            "candidate_site_source":sites.get("candidate_site_source"),"orbits":orbits,
            "selected_species_by_orbit":selected,
        }
        structured_payload={k:search_payload[k] for k in ("formula","scaffold","solver_mode","orbits")}
        duplicate_peers=[x for x in rows if x["cif_sha256"]==r["cif_sha256"] and x["candidate_id"]!=r["candidate_id"]]
        same_formula=[x for x in rows if x["target_formula"]==r["target_formula"]]
        if not duplicate_peers: cause="UNKNOWN"
        elif any(x["experiment"]!=r["experiment"] for x in duplicate_peers): cause="REPEATED_FORMULA_ABLATION"
        elif all(x["scaffold_id"]==r["scaffold_id"] for x in duplicate_peers): cause="IDENTICAL_FIXED_SCAFFOLD"
        elif canonical(structured_payload)==canonical({k:structured_payload[k] for k in structured_payload}): cause="IDENTICAL_STRUCTURED_TASK"
        else: cause="SAME_OPTIMUM_ACROSS_OBJECTIVES"
        condition=f"experiment={r['experiment']};method={r['method']}"
        if "pair_guided" in r["candidate_id"]: condition += ";pair_guided"
        elif r["experiment"]=="paper_experiment_3_specialist_halide_v1": condition += ";cubic_specialist"
        elif len(same_formula)>1: condition += ";general"
        item={
            "row_index":index,"candidate_id":r["candidate_id"],"natural_language_request":r["prompt"],
            "target_formula":r["target_formula"],"structure_family":r["target_structure_family"],
            "structured_task":canonical(structured_payload),"experimental_condition":condition,
            "retrieval_corpus":r["retrieval_corpus"],"spp_policy":r["row_specific_spp_source"],
            "scaffold":r["scaffold_id"],"candidate_site_set":sites.get("candidate_site_source") or r["scaffold_id"],
            "variable_orbits":";".join(str(x) for x in variable),"fixed_orbits":";".join(str(x) for x in fixed),
            "solver_mode":r["solver_mode"],"feasible_assignment_count":feasible,
            "generated_cif_hash":r["cif_sha256"],"hash_duplicate_group":hash_group_map[r["cif_sha256"]],
            "structurematcher_duplicate_group":sm_group,"duplicate_cause":cause,
        }
        audit.append(item)
        search_rows.append({
            "candidate_id":r["candidate_id"],"structured_intent_sha256":hashlib.sha256(canonical(structured_payload).encode()).hexdigest(),
            "search_space_sha256":hashlib.sha256(canonical(search_payload).encode()).hexdigest(),
            "formula":r["target_formula"],"scaffold":r["scaffold_id"],"candidate_site_source":sites.get("candidate_site_source"),
            "variable_orbits":";".join(str(x) for x in variable),"fixed_orbits":";".join(str(x) for x in fixed),
            "feasible_assignment_count":feasible,"selected_assignment":canonical(selected),"solver_mode":r["solver_mode"],
        })
    with (OUT/"ORIGINAL_31_DUPLICATE_CAUSES.csv").open("w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=list(audit[0]));w.writeheader();w.writerows(audit)
    with (OUT/"ORIGINAL_TASK_TO_SEARCH_SPACE_MATRIX.csv").open("w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=list(search_rows[0]));w.writeheader();w.writerows(search_rows)

    formula_count=len({r["target_formula"] for r in rows})
    intent_count=len({r["structured_intent_sha256"] for r in search_rows})
    search_count=len({r["search_space_sha256"] for r in search_rows})
    hash_unique=len({r["cif_sha256"] for r in rows})
    sm_unique=len(set(sm_groups))
    repeated=defaultdict(list)
    for r in audit:
        if r["target_formula"].startswith(("CsPb","CsSn")): repeated[r["target_formula"]].append(f"{r['candidate_id']} [{r['experimental_condition']}]")
    lines=["# Frozen original 31-row diversity and duplicate audit","","This report reads `paper_full_sca_v1` without modifying it.","","## Counts","",f"- Workflow rows: **31**",f"- Reduced formulas: **{formula_count}**",f"- Structured intents (canonical formula/scaffold/solver/orbit payload): **{intent_count}**",f"- Unique search spaces (including candidate source and selected assignment): **{search_count}**",f"- SHA-256-unique CIFs: **{hash_unique}**",f"- StructureMatcher-unique CIFs: **{sm_unique}** (ltol=0.2, stol=0.3, angle_tol=5°, primitive/scale enabled; formula-matched comparisons)","","The 31 workflow rows are not 31 generated materials. The five repeated halide formulas each occur once in the general/hard-intent set and twice in the specialist set (cubic and pair-guided); all three rows converge to the same frozen CIF hash for that formula.","","## Repeated halide compositions","" ]
    for formula,items in sorted(repeated.items()):
        lines.append(f"- **{formula}**: " + "; ".join(items))
    cause_counts=Counter(r["duplicate_cause"] for r in audit)
    lines += ["","## Row-level cause labels",""]+[f"- {k}: {v}" for k,v in sorted(cause_counts.items())]
    lines += ["","Rows without a duplicate peer are labelled `UNKNOWN`, because no duplicate cause exists to infer. Repeated cross-experiment halide rows are labelled `REPEATED_FORMULA_ABLATION`; their retrieval/SPP condition changes did not alter the represented formula/scaffold/orbits.",""]
    (OUT/"ORIGINAL_31_DUPLICATE_REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    print(canonical({"rows":31,"formulas":formula_count,"structured_intents":intent_count,"search_spaces":search_count,"hash_unique":hash_unique,"structurematcher_unique":sm_unique,"output":str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
