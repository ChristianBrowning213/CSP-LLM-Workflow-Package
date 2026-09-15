"""Acquire, screen and freeze the NASICON/NZP specialist v3 corpora.

Materials Project is queried through its authenticated summary endpoint.  The
screen is intentionally explicit: Tier 1 means that an ordered structure passes
the inherited coordination/single-component/rank-3 periodic framework proxy;
it is not an experimental phase-identification claim.  Tier 2 retains only
chemically relevant oxide phosphate/silicate framework evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import truststore
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


ROOT = Path(__file__).resolve().parents[1]
CRYSTAL_DB_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
if str(CRYSTAL_DB_ROOT) not in sys.path:
    sys.path.insert(0, str(CRYSTAL_DB_ROOT))

from scripts.build_crystaldb_corpus import load_mp_api_key  # noqa: E402
from scripts.build_nasicon_specialist_corpus import CENTER_CUTOFFS, framework_metrics  # noqa: E402


CORPORA = ROOT / "data" / "corpora"
FULL = CORPORA / "nasicon_specialist_v3"
LEAVE = CORPORA / "nasicon_specialist_all_targets_out_v3"
ART = ROOT / "artifacts" / "paper_diversity_v2" / "nasicon_corpus"
BASE = CORPORA / "nasicon_specialist_v2"
TASKS = ROOT / "benchmarks" / "paper_diversity_v2" / "EXP4_NASICON_32_TASKS.csv"
QUERIES = (
    ("Na", "Zr", "P", "O"),
    ("Na", "Ti", "P", "O"),
    ("Na", "Hf", "P", "O"),
    ("Na", "Sc", "P", "O"),
    ("Na", "Zr", "Si", "O"),
    ("Li", "Zr", "P", "O"),
)
RETAINED_TARGET = 320
TIER1_TARGET = 200
MOBILE = {"Li", "Na", "K", "Rb", "Cs", "Ag", "Mg", "Ca"}
TETRA = {"P", "Si"}
FRAMEWORK = set(CENTER_CUTOFFS) - TETRA
MATCHER_KW = {"ltol": 0.2, "stol": 0.3, "angle_tol": 5.0, "primitive_cell": True, "scale": True, "attempt_supercell": False}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cif_bytes(structure: Structure) -> bytes:
    return (str(CifWriter(structure, symprec=None)) + "\n").encode("utf-8")


def tier(structure: Structure) -> tuple[str | None, dict[str, Any], str | None]:
    elements = {e.symbol for e in structure.composition.elements}
    if "O" not in elements or not (elements & MOBILE) or not (elements & TETRA) or not (elements & FRAMEWORK):
        return None, {}, "missing_mobile_tetrahedral_or_framework_chemistry"
    if not structure.is_ordered:
        return "TIER_2_CHEMICAL_FRAMEWORK", {"topology_claimed": False}, "disordered_structure_not_tier1"
    metrics = framework_metrics(structure)
    passed = bool(metrics["coordination_all_expected"] and metrics["framework_components"] == 1 and metrics["framework_dimensionality"] == 3)
    if passed:
        return "TIER_1_TOPOLOGY_PROXY", metrics, None
    chemically_relevant = metrics["framework_center_count"] >= 2 and (metrics["framework_dimensionality"] >= 1 or metrics["framework_components"] >= 1)
    if chemically_relevant:
        return "TIER_2_CHEMICAL_FRAMEWORK", {**metrics, "topology_claimed": False}, "tier1_geometry_proxy_failed"
    return None, metrics, "not_a_relevant_connected_framework"


def spacegroup(structure: Structure) -> tuple[str, int, str]:
    a = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
    return a.get_space_group_symbol(), a.get_space_group_number(), a.get_crystal_system()


def task_formulas() -> set[str]:
    with TASKS.open(encoding="utf-8", newline="") as handle:
        return {Composition(r["target_formula"]).reduced_formula for r in csv.DictReader(handle)}


def base_records() -> list[dict[str, Any]]:
    return [json.loads(x) for x in (BASE / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def acquire() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    truststore.inject_into_ssl()
    from mp_api.client import MPRester
    import mp_api

    key = load_mp_api_key(CRYSTAL_DB_ROOT)
    if not key:
        raise RuntimeError("Materials Project API key unavailable")
    acquired: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with MPRester(key) as mpr:
        for query in QUERIES:
            query_id = "elements=" + "-".join(query) + ";num_elements=4..6;energy_above_hull=0..0.25"
            try:
                docs = mpr.materials.summary.search(
                    elements=list(query), num_elements=(4, 6), energy_above_hull=(0, 0.25),
                    fields=["material_id", "formula_pretty", "chemsys", "energy_above_hull", "formation_energy_per_atom", "structure"],
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({"query": query_id, "status": "ERROR", "failure_reason": f"{type(exc).__name__}: {exc}"})
                continue
            for doc in docs:
                sid = str(doc.material_id)
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                acquired.append({
                    "source": "Materials Project", "source_id": sid, "source_query": query_id,
                    "source_version": f"mp-api {getattr(mp_api, '__version__', 'unknown')}; endpoint live at acquisition",
                    "formula": str(doc.formula_pretty), "chemical_system": str(doc.chemsys),
                    "energy_above_hull_eV_per_atom": float(doc.energy_above_hull) if doc.energy_above_hull is not None else None,
                    "formation_energy_eV_per_atom": float(doc.formation_energy_per_atom) if doc.formation_energy_per_atom is not None else None,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(), "structure": doc.structure,
                    "status": "ACQUIRED",
                })
    return acquired, errors


def record_from_structure(source: dict[str, Any], structure: Structure, cif_hash: str, tier_name: str, evidence: dict[str, Any]) -> dict[str, Any]:
    sg,sgn,system=spacegroup(structure)
    sid=str(source["source_id"])
    return {
        "internal_id": f"nasicon-{sid.replace('mp-', 'mp')}", "source": source["source"], "source_id": sid,
        "source_version": source["source_version"], "source_query": source["source_query"],
        "retrieval_timestamp": source["retrieved_at"], "formula": source["formula"],
        "reduced_formula": structure.composition.reduced_formula, "chemical_system": source["chemical_system"],
        "elements": sorted(e.symbol for e in structure.composition.elements), "space_group": sg,
        "space_group_number": sgn, "crystal_system": system, "number_of_sites": len(structure),
        "topology_tier": tier_name,
        "family_assignment": "NASICON/NZP topology proxy" if tier_name.startswith("TIER_1") else "NASICON/NZP chemical framework support",
        "family_assignment_method": "ordered_coordination_single_component_rank3_periodic_framework_proxy" if tier_name.startswith("TIER_1") else "chemistry_plus_connected_framework_support",
        "family_assignment_evidence": evidence, "cif_sha256": cif_hash, "is_ordered": structure.is_ordered,
        "occupancies": sorted({float(v) for site in structure for v in site.species.values()}),
        "energy_above_hull_eV_per_atom": source.get("energy_above_hull_eV_per_atom"),
        "formation_energy_eV_per_atom": source.get("formation_energy_eV_per_atom"),
        "license_policy": {"policy_id": "local_cif", "allow_cif_store": True, "allow_cif_return": True, "allow_derivatives": True, "allow_export": False, "notes": "Materials Project API data; external redistribution remains policy-gated."},
    }


def freeze(root: Path, records: list[dict[str, Any]], cif_map: dict[str, bytes], *, force: bool) -> None:
    if root.exists():
        if not force: raise FileExistsError(f"Refusing to overwrite {root}; pass --force")
        if root.resolve().parent != CORPORA.resolve(): raise ValueError(f"Unsafe rebuild target: {root}")
        shutil.rmtree(root)
    (root / "cifs").mkdir(parents=True); (root / "records").mkdir()
    for r in records:
        data=cif_map[r["cif_sha256"]]
        cif_path=root/"cifs"/f"{r['internal_id']}.cif"; cif_path.write_bytes(data)
        r["frozen_cif_path"]=str(cif_path)
        (root/"records"/f"{r['internal_id']}.json").write_text(json.dumps(r,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
    (root/"manifest.jsonl").write_text("".join(dumps(r)+"\n" for r in records),encoding="utf-8")
    (root/"corpus_card.json").write_text(json.dumps({
        "corpus_id":root.name,"created_at":datetime.now(timezone.utc).isoformat(),"structure_count":len(records),
        "topology_tier_counts":dict(Counter(r["topology_tier"] for r in records)),"parent_corpus_id":"nasicon_specialist_v2",
        "tier1_semantics":"ordered coordination/single-component/rank-3 periodic framework proxy; not experimental verification",
        "structurematcher_tolerances":MATCHER_KW,"policy":"local research corpus; external CIF export remains policy-gated",
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=fields or list(rows[0])
    with path.open("w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--force",action="store_true"); args=ap.parse_args()
    ART.mkdir(parents=True,exist_ok=True)
    acquired,query_errors=acquire()
    acquisition_rows=[]; rejected=list(query_errors); new_records=[]; cif_map={}; seen_hashes=set()
    for source in acquired:
        structure=source.pop("structure")
        data=cif_bytes(structure); cif_hash=sha_bytes(data)
        t,evidence,reason=tier(structure)
        acquisition_rows.append({k:v for k,v in source.items() if k!="structure"}|{"cif_sha256":cif_hash,"screened_tier":t or "REJECTED","screen_reason":reason or "passed"})
        if not t:
            rejected.append({"source_id":source["source_id"],"formula":source["formula"],"cif_sha256":cif_hash,"reason":reason,"source_query":source["source_query"]}); continue
        if cif_hash in seen_hashes:
            rejected.append({"source_id":source["source_id"],"formula":source["formula"],"cif_sha256":cif_hash,"reason":"duplicate_cif_sha256","source_query":source["source_query"]}); continue
        seen_hashes.add(cif_hash); cif_map[cif_hash]=data
        new_records.append(record_from_structure(source,structure,cif_hash,t,evidence))

    # Preserve the already frozen v2 records and their exact bytes.
    records=[]; source_ids=set(); all_hashes=set()
    for old in base_records():
        data=Path(old["frozen_cif_path"]).read_bytes(); h=hashlib.sha256(data).hexdigest()
        old=dict(old); old["cif_sha256"]=h
        if h in all_hashes: continue
        if old["topology_tier"]=="TIER_1_TOPOLOGY": old["topology_tier"]="TIER_1_TOPOLOGY_PROXY"
        elif old["topology_tier"].startswith("TIER_2"): old["topology_tier"]="TIER_2_CHEMICAL_FRAMEWORK"
        records.append(old); cif_map[h]=data; all_hashes.add(h); source_ids.add(str(old["source_id"]))
    for r in new_records:
        if r["cif_sha256"] in all_hashes or r["source_id"] in source_ids:
            rejected.append({"source_id":r["source_id"],"formula":r["formula"],"cif_sha256":r["cif_sha256"],"reason":"duplicate_of_v2","source_query":r["source_query"]}); continue
        records.append(r); all_hashes.add(r["cif_sha256"]); source_ids.add(r["source_id"])
    # The acquisition is exhaustive for the declared queries, while the frozen
    # retrieval corpus is a diverse target-sized selection.  Preserve every v2
    # row, then choose low-hull additions round-robin by reduced formula so a
    # few populous GNoME formula families cannot dominate the corpus.
    base_ids={str(r["source_id"]) for r in base_records()}
    base_selected=[r for r in records if str(r["source_id"]) in base_ids]
    additions=[r for r in records if str(r["source_id"]) not in base_ids]
    def diverse_take(pool: list[dict[str, Any]], amount: int) -> list[dict[str, Any]]:
        buckets: dict[str,list[dict[str,Any]]]=defaultdict(list)
        for item in pool: buckets[item["reduced_formula"]].append(item)
        for values in buckets.values(): values.sort(key=lambda x:(x.get("energy_above_hull_eV_per_atom") is None,x.get("energy_above_hull_eV_per_atom") or 0.0,x["source_id"]))
        chosen=[]
        while len(chosen)<amount and buckets:
            for formula in sorted(list(buckets)):
                if len(chosen)>=amount: break
                chosen.append(buckets[formula].pop(0))
                if not buckets[formula]: del buckets[formula]
        return chosen
    need_t1=max(0,TIER1_TARGET-sum(r["topology_tier"].startswith("TIER_1") for r in base_selected))
    selected_t1=diverse_take([r for r in additions if r["topology_tier"].startswith("TIER_1")],need_t1)
    need_total=max(0,RETAINED_TARGET-len(base_selected)-len(selected_t1))
    selected_t2=diverse_take([r for r in additions if r["topology_tier"].startswith("TIER_2")],need_total)
    selected_ids={r["internal_id"] for r in base_selected+selected_t1+selected_t2}
    for r in records:
        if r["internal_id"] not in selected_ids:
            rejected.append({"source_id":r["source_id"],"formula":r["formula"],"cif_sha256":r["cif_sha256"],"reason":"screened_valid_not_selected_after_diverse_target_reached","source_query":r.get("source_query","")})
    records=base_selected+selected_t1+selected_t2
    records.sort(key=lambda r:(r["topology_tier"],r["reduced_formula"],r["source_id"]))

    targets=task_formulas()
    designated={}
    for formula in sorted(targets):
        choices=[r for r in records if Composition(r["reduced_formula"]).reduced_formula==formula and r["topology_tier"].startswith("TIER_1")]
        if choices: designated[formula]=choices[0]["internal_id"]
    leave=[]; duplicate_rows=[]
    for r in records:
        rf=Composition(r["reduced_formula"]).reduced_formula
        reason=None
        if rf in targets: reason="exact_breadth_task_formula"
        if r["internal_id"] in designated.values(): reason="designated_evaluation_reference"
        if reason:
            duplicate_rows.append({"internal_id":r["internal_id"],"source_id":r["source_id"],"reduced_formula":rf,"exclusion_reason":reason,"matched_reference":designated.get(rf,""),"matcher_tolerances":dumps(MATCHER_KW)})
        else: leave.append(dict(r))

    freeze(FULL,records,cif_map,force=args.force); freeze(LEAVE,leave,cif_map,force=args.force)
    (ART/"NASICON_V3_ACQUISITION_MANIFEST.jsonl").write_text("".join(dumps(x)+"\n" for x in acquisition_rows),encoding="utf-8")
    retained_fields=["internal_id","source","source_id","source_query","retrieval_timestamp","formula","reduced_formula","chemical_system","elements","space_group","space_group_number","crystal_system","number_of_sites","topology_tier","family_assignment","family_assignment_method","cif_sha256","is_ordered","energy_above_hull_eV_per_atom","formation_energy_eV_per_atom"]
    write_csv(ART/"NASICON_V3_RETAINED_MANIFEST.csv",records,retained_fields)
    if rejected: write_csv(ART/"NASICON_V3_REJECTED_MANIFEST.csv",rejected,sorted({k for r in rejected for k in r}))
    else: write_csv(ART/"NASICON_V3_REJECTED_MANIFEST.csv",[],["source_id","reason"])
    write_csv(ART/"NASICON_V3_DUPLICATE_REPORT.csv",duplicate_rows or [{}],list(duplicate_rows[0]) if duplicate_rows else ["internal_id"])
    for name,key in (("NASICON_V3_TOPOLOGY_SUMMARY.csv","topology_tier"),("NASICON_V3_FORMULA_SUMMARY.csv","reduced_formula"),("NASICON_V3_SPACEGROUP_SUMMARY.csv","space_group")):
        counts=Counter(str(r[key]) for r in records); write_csv(ART/name,[{key:k,"count":v} for k,v in sorted(counts.items())],[key,"count"])
    pairs=Counter()
    for r in records:
        els=sorted(r["elements"])
        for i,a in enumerate(els):
            for b in els[i:]: pairs["-".join(sorted((a,b),key=str.lower))]+=1
    write_csv(ART/"NASICON_V3_PAIR_SUPPORT.csv",[{"pair":k,"support_count":v,"supported":v>0} for k,v in sorted(pairs.items())],["pair","support_count","supported"])
    tiers=Counter(r["topology_tier"] for r in records)
    report=["# NASICON specialist corpus v3 report","",f"Acquired at: {datetime.now(timezone.utc).isoformat()}","",f"- Lawful MP records returned by {len(QUERIES)} explicit element queries: **{len(acquired)}**",f"- Hash-unique retained structures (including frozen v2): **{len(records)}**",f"- Tier 1 topology-proxy structures: **{tiers.get('TIER_1_TOPOLOGY_PROXY',0)}**",f"- Tier 2 chemical-framework structures: **{tiers.get('TIER_2_CHEMICAL_FRAMEWORK',0)}**",f"- All-targets-out retained structures: **{len(leave)}**",f"- Distinct retained formulas: **{len(set(r['reduced_formula'] for r in records))}**",f"- Distinct space groups: **{len(set(r['space_group'] for r in records))}**","","Tier 1 is a reproducible structural proxy (ordered; expected coordination; one framework component; rank-3 periodic connectivity), not an assertion of experimental NASICON identity. The all-targets-out set excludes every exact reduced formula in the 32-task manifest and all designated evaluation references. StructureMatcher tolerances are recorded for reference-near-duplicate auditing; exact-formula exclusion is stricter for this frozen set.","",f"Acquisition query errors: {len(query_errors)}. Rejected/duplicate rows: {len(rejected)}."]
    (ART/"NASICON_V3_CORPUS_REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    print(dumps({"acquired":len(acquired),"retained":len(records),"leave_out":len(leave),"tiers":dict(tiers),"formulas":len(set(r['reduced_formula'] for r in records)),"space_groups":len(set(r['space_group'] for r in records))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
