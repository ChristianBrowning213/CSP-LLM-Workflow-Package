"""PAPER-RESULTS-1D: SPP-dominant generic-grid experiment.

The script writes only artifacts/paper_results_extension_v2/00d_spp_dominant_search.
It uses fresh target-formula-excluded Crystal-DB retrieval and the production
SPP-Maker 11 A periodic fitting path.  References are evaluated only after a
candidate search space and its objective have been constructed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import shutil
import sqlite3
import statistics
import sys
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
CRYSTAL_DB_REPO = ROOT.parent / "Crystal-DB"
SPP_REPO = ROOT.parent / "SPP-Maker-QLIP"
SCA_REPO = ROOT.parent / "Structured_Crystal_Analyser"
sys.path[:0] = [str(ROOT / "src"), str(CRYSTAL_DB_REPO), str(SPP_REPO / "src"), str(SCA_REPO)]

OUT = ROOT / "artifacts" / "paper_results_extension_v2" / "00d_spp_dominant_search"
DB = CRYSTAL_DB_REPO / "data" / "phase6_mp_10k.db"
CUTOFF = 11.0
HARDCORE = 0.75
NA = "NA"

CASES = {
    "cspbbr3": ("CsPbBr3", "Cs", "Pb", "Br", "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbbr3_halide"),
    "cspbcl3": ("CsPbCl3", "Cs", "Pb", "Cl", "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbcl3_halide"),
    "cspbi3": ("CsPbI3", "Cs", "Pb", "I", "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbi3_halide"),
    "cssnbr3": ("CsSnBr3", "Cs", "Sn", "Br", "local_runs/paper_experiment_2_hard_v3/exp2v3_cssnbr3_halide"),
    "cssni3": ("CsSnI3", "Cs", "Sn", "I", "local_runs/paper_experiment_2_hard_v3/exp2v3_cssni3_halide"),
    "batio3": ("BaTiO3", "Ba", "Ti", "O", "local_runs/paper_experiment_1_common_v1/exp1_batio3_perovskite"),
    "catio3": ("CaTiO3", "Ca", "Ti", "O", "local_runs/paper_experiment_2_hard_v3/exp2v3_catio3_perovskite"),
    "srtio3": ("SrTiO3", "Sr", "Ti", "O", "local_runs/paper_experiment_2_hard_v3/exp2v3_srtio3_perovskite"),
}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path, pattern: str = "*.POT") -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob(pattern)):
        digest.update(str(item.relative_to(path)).replace("\\", "/").encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def canonical_pair(a: str, b: str) -> str:
    return "-".join(sorted((str(a), str(b)), key=str.lower))


def case_reference(case_id: str) -> Path:
    return ROOT / CASES[case_id][4] / "generated.cif"


@lru_cache(maxsize=None)
def case_lattice_a(case_id: str) -> float:
    from pymatgen.core import Structure
    return float(Structure.from_file(case_reference(case_id)).lattice.a)


def query_text(case_id: str) -> str:
    formula, a, b, x, _ = CASES[case_id]
    kind = "oxide" if x == "O" else "halide"
    return f"cubic {kind} perovskite {formula} {a} {b} {x} ABX3 corner sharing octahedra"


def build_fresh_spp() -> None:
    from crystal_db.retrieval import text_search
    from pymatgen.core import Composition
    from spp_maker_qlip.required_pair_extraction import derive_required_pairs, export_required_pair_spp_root

    rows = []
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    for case_id, (formula, a, b, x, _) in CASES.items():
        case_root = OUT / "spp" / case_id
        evidence = case_root / "retrieved_target_excluded_cifs"
        if evidence.exists():
            shutil.rmtree(evidence)
        evidence.mkdir(parents=True, exist_ok=True)
        result = text_search(
            query_text=query_text(case_id), db_path=str(DB), k=200,
            embed_engine="lmstudio", model_name="text-embedding-bge-m3", model_version="lmstudio_v1",
            text_engine="robocrys", text_view="robocrys", hybrid=False,
            show_text_top=0, export_dir=None, export_top=0, redacted=False,
        )
        if result["status"] != "ok":
            raise RuntimeError(f"Crystal-DB retrieval failed for {case_id}: {result.get('errors')}")
        selected = []
        selected_ids: set[str] = set()
        target_reduced = Composition(formula).reduced_composition
        query_records = [{"purpose": "request_semantic_retrieval", "query": result["query"]}]

        def consider_neighbor(neighbor: dict[str, Any], purpose: str) -> bool:
            if neighbor["structure_id"] in selected_ids:
                return False
            record = connection.execute(
                "SELECT s.structure_id,s.cif_text,s.reduced_formula,p.source,p.source_id,p.allow_derivatives "
                "FROM structures s JOIN provenance p USING(structure_id) WHERE s.structure_id=?",
                (neighbor["structure_id"],),
            ).fetchone()
            if record is None or not record["cif_text"] or not record["allow_derivatives"]:
                return False
            try:
                reduced = Composition(record["reduced_formula"]).reduced_composition
            except Exception:
                return False
            if reduced == target_reduced:
                return False  # exact-composition exclusion is stronger than exact-structure exclusion
            present = {str(el) for el in reduced.elements}
            relevant = present & {a, b, x}
            if len(relevant) < 2:
                return False
            cif_path = evidence / f"{record['structure_id']}.cif"
            cif_path.write_text(record["cif_text"], encoding="utf-8")
            selected.append({
                "rank": neighbor["rank"], "score": neighbor["score"],
                "structure_id": record["structure_id"], "reduced_formula": record["reduced_formula"],
                "source": record["source"], "source_id": record["source_id"],
                "exact_target_excluded": True, "cif_sha256": sha256(cif_path),
                "retrieval_purpose": purpose,
            })
            selected_ids.add(record["structure_id"])
            return True

        for neighbor in result["neighbors"]:
            consider_neighbor(neighbor, "request_semantic_retrieval")
            if len(selected) >= 60:
                break

        required = derive_required_pairs([a, b, x])
        def chemical_pairs_present() -> set[str]:
            present_pairs: set[str] = set()
            for item in selected:
                elements = [str(el) for el in Composition(item["reduced_formula"]).elements]
                present_pairs.update(canonical_pair(left, right) for left in elements for right in elements)
            return present_pairs

        # Supplement only genuinely absent chemical pairs with a second
        # production semantic query.  Exact target exclusion remains unchanged.
        for missing_pair in sorted(set(required) - chemical_pairs_present()):
            left, right = missing_pair.split("-", 1)
            supplemental = text_search(
                query_text=f"inorganic crystal containing {left} and {right} {left}-{right} coordination bond distances",
                db_path=str(DB), k=200, embed_engine="lmstudio",
                model_name="text-embedding-bge-m3", model_version="lmstudio_v1",
                text_engine="robocrys", text_view="robocrys", hybrid=False,
                show_text_top=0, export_dir=None, export_top=0, redacted=False,
            )
            if supplemental["status"] != "ok":
                raise RuntimeError(f"Supplemental retrieval failed for {case_id}/{missing_pair}: {supplemental.get('errors')}")
            query_records.append({"purpose": f"missing_pair_{missing_pair}", "query": supplemental["query"]})
            added = 0
            for neighbor in supplemental["neighbors"]:
                # Require the targeted chemical pair, not merely two arbitrary
                # target elements, before accepting supplemental evidence.
                db_row = connection.execute("SELECT reduced_formula FROM structures WHERE structure_id=?", (neighbor["structure_id"],)).fetchone()
                if db_row is None:
                    continue
                try: elems = {str(el) for el in Composition(db_row["reduced_formula"]).elements}
                except Exception: continue
                if not {left, right}.issubset(elems):
                    continue
                if consider_neighbor(neighbor, f"missing_pair_{missing_pair}"):
                    added += 1
                if added >= 20:
                    break
        # If the semantic neighborhood still lacks a required pair, use the
        # production Crystal-DB metadata index as a deterministic pair-coverage
        # supplement.  This remains target-composition-excluded and is recorded
        # separately; it is not represented as semantic retrieval.
        for missing_pair in sorted(set(required) - chemical_pairs_present()):
            left, right = missing_pair.split("-", 1)
            metadata_rows = connection.execute("SELECT structure_id,reduced_formula FROM structures ORDER BY structure_id").fetchall()
            added = 0
            for db_row in metadata_rows:
                try:
                    comp = Composition(db_row["reduced_formula"])
                    elems = {str(el) for el in comp.elements}
                except Exception:
                    continue
                if not {left, right}.issubset(elems) or comp.reduced_composition == target_reduced:
                    continue
                if consider_neighbor(
                    {"structure_id": db_row["structure_id"], "rank": NA, "score": NA},
                    f"metadata_pair_coverage_{missing_pair}",
                ):
                    added += 1
                if added >= 20:
                    break
            query_records.append({
                "purpose": f"metadata_pair_coverage_{missing_pair}",
                "query": {"text": NA, "method": "Crystal-DB exact element-cooccurrence metadata filter"},
                "records_added": added,
            })
        write_json(case_root / "retrieval.json", {
            "queries": query_records, "backend_status": result["backend_status"],
            "target_exclusion_protocol": "exclude every exact reduced-composition match before SPP fitting",
            "reference_coordinates_used_for_retrieval_or_fit": False, "selected": selected,
        })
        if not selected:
            raise RuntimeError(f"No eligible target-excluded evidence for {case_id}")
        spp_root = case_root / "spp_root"
        if spp_root.exists():
            shutil.rmtree(spp_root)
        generation = export_required_pair_spp_root(
            cif_dir=evidence, formula=formula, out_root=spp_root,
            name=f"paper_results_1d_{case_id}_target_excluded", cutoff=CUTOFF,
            supercell=None, alpha=1e-3, d_min=0.5, bin_width=0.05,
        )
        write_json(case_root / "spp_generation.json", generation)
        covered = sorted({canonical_pair(*pot.stem.split("-", 1)) for pot in spp_root.rglob("*.POT")})
        coverage = 100.0 * len(set(required) & set(covered)) / len(required)
        rows.append({
            "case_id": case_id, "composition": formula,
            "spp_artifact": str(spp_root.relative_to(ROOT)).replace("\\", "/"),
            "retrieval_corpus": "Crystal-DB phase6_mp_10k / production BGE-M3 robocrys space",
            "target_exclusion_protocol": "all exact reduced-composition matches excluded; no reference coordinates used",
            "retrieved_structure_count": len(selected), "required_pairs": ";".join(required),
            "covered_pairs": ";".join(covered), "coverage_percent": coverage,
            "spp_artifact_hash": tree_hash(spp_root),
            "notes": f"11 A periodic SPP-Maker path; generation_ok={generation.get('ok')}; quality={generation.get('spp_pot_quality',{}).get('spp_pot_quality_status','unknown')}",
        })
    connection.close()
    write_csv(OUT / "SPP_SOURCE_MANIFEST.csv", rows, [
        "case_id", "composition", "spp_artifact", "retrieval_corpus", "target_exclusion_protocol",
        "retrieved_structure_count", "required_pairs", "covered_pairs", "coverage_percent",
        "spp_artifact_hash", "notes",
    ])
    incomplete = [row for row in rows if float(row["coverage_percent"]) < 100.0]
    print("PASS SPP:", ", ".join(f"{r['case_id']}={r['retrieved_structure_count']} CIFs/{r['coverage_percent']}%" for r in rows))
    if incomplete:
        print("EXCLUDED_INCOMPLETE_SPP:", ",".join(r["case_id"] for r in incomplete))


def included_case_ids() -> list[str]:
    manifest = read_csv(OUT / "SPP_SOURCE_MANIFEST.csv")
    return [row["case_id"] for row in manifest if float(row["coverage_percent"]) == 100.0]


@lru_cache(maxsize=None)
def load_curves(case_id: str) -> dict[str, list[tuple[float, float]]]:
    curves = {}
    for pot in (OUT / "spp" / case_id / "spp_root").rglob("*.POT"):
        points = []
        for line in pot.read_text(encoding="utf-8").splitlines():
            parts = line.strip().replace(",", " ").split()
            if not parts or line.lstrip().startswith("#") or len(parts) < 2:
                continue
            try: points.append((float(parts[0]), float(parts[1])))
            except ValueError: continue
        if points:
            curves[canonical_pair(*pot.stem.split("-", 1))] = sorted(points)
    return curves


def interpolate(curve: list[tuple[float, float]], distance: float) -> float:
    if distance <= curve[0][0]: return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if distance <= x1:
            return y1 if abs(x1-x0) < 1e-12 else y0 + (distance-x0)/(x1-x0)*(y1-y0)
    return curve[-1][1]


def periodic_pair_value(
    frac_i: tuple[float, float, float], frac_j: tuple[float, float, float],
    lattice_a: float, curve: list[tuple[float, float]], *, self_pair: bool,
) -> float:
    span = int(math.ceil(CUTOFF / lattice_a)) + 1
    total = 0.0
    for tx, ty, tz in itertools.product(range(-span, span + 1), repeat=3):
        if self_pair and tx == ty == tz == 0:
            continue
        delta = (frac_j[0]+tx-frac_i[0], frac_j[1]+ty-frac_i[1], frac_j[2]+tz-frac_i[2])
        distance = lattice_a * math.sqrt(sum(value*value for value in delta))
        if 1e-12 < distance <= CUTOFF + 1e-12:
            total += interpolate(curve, distance)
    return 0.5 * total if self_pair else total


@lru_cache(maxsize=None)
def periodic_coefficient(
    case_id: str, frac_i: tuple[float, float, float], frac_j: tuple[float, float, float],
    pair: str, self_pair: bool,
) -> float:
    return periodic_pair_value(frac_i, frac_j, case_lattice_a(case_id), load_curves(case_id)[pair], self_pair=self_pair)


def score_occupation(
    case_id: str, coords: list[tuple[float, float, float]], species: list[str], *, swapped: bool = False,
) -> float:
    _, c1, c2, x, _ = CASES[case_id]
    total = 0.0
    for i, (coord_i, sp_i) in enumerate(zip(coords, species)):
        pair = canonical_pair(sp_i, sp_i)
        total += periodic_coefficient(case_id, coord_i, coord_i, pair, True)
        for j in range(i+1, len(coords)):
            sp_j = species[j]
            coefficient_i, coefficient_j = sp_i, sp_j
            if swapped and x in {sp_i, sp_j} and ({sp_i, sp_j} & {c1, c2}):
                if coefficient_i == c1: coefficient_i = c2
                elif coefficient_i == c2: coefficient_i = c1
                if coefficient_j == c1: coefficient_j = c2
                elif coefficient_j == c2: coefficient_j = c1
            pair = canonical_pair(coefficient_i, coefficient_j)
            total += periodic_coefficient(case_id, coord_i, coords[j], pair, False)
    return total


GRID8 = list(itertools.product((0.0, 0.5), repeat=3))
GRID64 = list(itertools.product((0.0, 0.25, 0.5, 0.75), repeat=3))


def assignment_structure(case_id: str, grid, a_site: int, b_site: int, x_sites: Iterable[int]):
    from pymatgen.core import Lattice, Structure
    _, a, b, x, _ = CASES[case_id]
    indices = [a_site, b_site, *sorted(x_sites)]
    return Structure(Lattice.cubic(case_lattice_a(case_id)), [a, b, x, x, x], [grid[i] for i in indices])


def occupation_score(case_id: str, grid, a_site: int, b_site: int, x_sites: Iterable[int], *, swapped=False) -> float:
    _, a, b, x, _ = CASES[case_id]
    indices = [a_site, b_site, *sorted(x_sites)]
    return score_occupation(case_id, [grid[i] for i in indices], [a, b, x, x, x], swapped=swapped)


def coordinate_label(coord) -> str:
    return "(" + ",".join(f"{value:g}" for value in coord) + ")"


def assignment_id(case_id: str, grid_name: str, a_site: int, b_site: int, x_sites: Iterable[int]) -> str:
    return f"{case_id}-{grid_name}-A{a_site:02d}-B{b_site:02d}-X" + "-".join(f"{i:02d}" for i in sorted(x_sites))


def build_grid8() -> None:
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from sca.evaluators.topology import family_topology_metrics
    from sok_llm_orchestrator.structures.variable_perovskite import canonical_structure_hash

    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=False, scale=False, attempt_supercell=False)
    all_rows, control_rows, recovery_rows = [], [], []
    for case_id in included_case_ids():
        formula, a, b, x, _ = CASES[case_id]
        reference = __import__("pymatgen.core", fromlist=["Structure"]).Structure.from_file(case_reference(case_id))
        policy = "PEROVSKITE_3D" if x == "O" else "HALIDE_PEROVSKITE_3D"
        case_rows = []
        for a_site in range(8):
            for b_site in range(8):
                if b_site == a_site: continue
                remaining = [i for i in range(8) if i not in {a_site, b_site}]
                for x_sites in itertools.combinations(remaining, 3):
                    structure = assignment_structure(case_id, GRID8, a_site, b_site, x_sites)
                    distances = structure.distance_matrix.copy(); distances[distances < 1e-12] = float("inf")
                    topology, _ = family_topology_metrics(structure, policy)
                    exact_reference = a_site == 0 and b_site == 7 and set(x_sites) == {3, 5, 6}
                    case_rows.append({
                        "case_id": case_id,
                        "assignment_id": assignment_id(case_id, "GRID8", a_site, b_site, x_sites),
                        "A_species_site": coordinate_label(GRID8[a_site]),
                        "B_species_site": coordinate_label(GRID8[b_site]),
                        "X_species_sites": ";".join(coordinate_label(GRID8[i]) for i in x_sites),
                        "spp_score": occupation_score(case_id, GRID8, a_site, b_site, x_sites),
                        "spp_rank": NA, "minimum_distance_A": float(distances.min()),
                        "detected_space_group": SpacegroupAnalyzer(structure, symprec=1e-3).get_space_group_symbol(),
                        "topology_status": topology["topology_status"],
                        "canonical_structure_hash": canonical_structure_hash(structure),
                        "structurematcher_reference": matcher.fit(structure, reference),
                        "reference_assignment": exact_reference,
                        "notes": "Generic half-grid indices only; no roles, symmetry, topology, orbit closure or distance constraint used in construction.",
                        "_a": a_site, "_b": b_site, "_x": tuple(x_sites),
                    })
        assert len(case_rows) == 8 * 7 * math.comb(6, 3) == 1120
        case_rows.sort(key=lambda row: (float(row["spp_score"]), row["assignment_id"]))
        previous = None; current_rank = 0
        for index, row in enumerate(case_rows, start=1):
            if previous is None or abs(float(row["spp_score"]) - previous) > 1e-9:
                current_rank = index; previous = float(row["spp_score"])
            row["spp_rank"] = current_rank
        all_rows.extend(case_rows)

        reference_matches = [row for row in case_rows if row["structurematcher_reference"]]
        exact_reference = next(row for row in case_rows if row["reference_assignment"])
        recovered = min(reference_matches, key=lambda row: (row["spp_rank"], row["assignment_id"]))
        best = case_rows[0]
        recovery_rows.append({
            "case_id": case_id, "composition": formula,
            "reference_id": str(case_reference(case_id).relative_to(ROOT)).replace("\\", "/"),
            "reference_independence_class": "frozen historical CIF; excluded by exact composition from SPP fitting",
            "total_assignments": len(case_rows), "reference_representable": True,
            "reference_assignment_id": exact_reference["assignment_id"],
            "reference_spp_rank": recovered["spp_rank"],
            "reference_rank_percentile": 100.0 * float(recovered["spp_rank"]) / len(case_rows),
            "reference_top1": int(recovered["spp_rank"]) == 1,
            "reference_top5": int(recovered["spp_rank"]) <= 5,
            "reference_top10": int(recovered["spp_rank"]) <= 10,
            "reference_score": recovered["spp_score"], "best_score": best["spp_score"],
            "score_gap_to_best": float(recovered["spp_score"]) - float(best["spp_score"]),
            "best_assignment_topology": best["topology_status"],
            "best_assignment_reference_match": best["structurematcher_reference"],
            "best_assignment_space_group": best["detected_space_group"],
            "notes": f"Reference rank is best rank among {len(reference_matches)} StructureMatcher-equivalent grid translations/orientations; exact conventional assignment rank={exact_reference['spp_rank']}.",
        })

        for condition, swapped in (("CORRECT_SPP", False), ("LABEL_SWAPPED_SPP_CONTROL", True)):
            ranked = []
            for row in case_rows:
                score = occupation_score(case_id, GRID8, row["_a"], row["_b"], row["_x"], swapped=swapped)
                ranked.append((score, row))
            ranked.sort(key=lambda item: (item[0], item[1]["assignment_id"]))
            ref_scores = [(score, row) for score, row in ranked if row["structurematcher_reference"]]
            ref_score, ref_row = min(ref_scores, key=lambda item: (item[0], item[1]["assignment_id"]))
            unique_scores = sorted({round(score, 9) for score, _ in ranked})
            ref_rank = 1 + sum(score < ref_score - 1e-9 for score in [item[0] for item in ranked])
            top_score, top_row = ranked[0]
            control_rows.append({
                "case_id": case_id, "condition": condition, "reference_rank": ref_rank,
                "reference_percentile": 100.0 * ref_rank / len(ranked),
                "top_assignment_id": top_row["assignment_id"],
                "top_assignment_reference_match": top_row["structurematcher_reference"],
                "top_assignment_topology": top_row["topology_status"],
                "score_margin": unique_scores[1]-unique_scores[0] if len(unique_scores)>1 else 0.0,
                "notes": "Identical 1120-state search; label-swapped condition changes only cation-X curve identity." if swapped else "Production target-excluded SPP.",
            })
        control_rows.append({
            "case_id": case_id, "condition": "NO_SPP", "reference_rank": "NO_UNIQUE_RANKING",
            "reference_percentile": NA, "top_assignment_id": "NO_UNIQUE_RANKING",
            "top_assignment_reference_match": NA, "top_assignment_topology": NA,
            "score_margin": 0.0, "notes": "All 1120 feasible assignments tied; enumeration order is not a prediction.",
        })

    clean_rows = [{k:v for k,v in row.items() if not k.startswith("_")} for row in all_rows]
    write_csv(OUT / "GRID8_ALL_ASSIGNMENTS.csv", clean_rows, [
        "case_id", "assignment_id", "A_species_site", "B_species_site", "X_species_sites",
        "spp_score", "spp_rank", "minimum_distance_A", "detected_space_group", "topology_status",
        "canonical_structure_hash", "structurematcher_reference", "reference_assignment", "notes",
    ])
    write_csv(OUT / "GRID8_REFERENCE_RECOVERY.csv", recovery_rows, [
        "case_id", "composition", "reference_id", "reference_independence_class", "total_assignments",
        "reference_representable", "reference_assignment_id", "reference_spp_rank", "reference_rank_percentile",
        "reference_top1", "reference_top5", "reference_top10", "reference_score", "best_score",
        "score_gap_to_best", "best_assignment_topology", "best_assignment_reference_match",
        "best_assignment_space_group", "notes",
    ])
    write_csv(OUT / "GRID8_OBJECTIVE_CONTROL.csv", control_rows, [
        "case_id", "condition", "reference_rank", "reference_percentile", "top_assignment_id",
        "top_assignment_reference_match", "top_assignment_topology", "score_margin", "notes",
    ])
    print(f"PASS GRID8: {len(clean_rows)} assignments")


def coefficient_for_species(
    case_id: str, coord_i, coord_j, species_i: str, species_j: str, *, swapped: bool, self_pair: bool,
) -> float:
    _, c1, c2, x, _ = CASES[case_id]
    left, right = species_i, species_j
    if swapped and not self_pair and x in {left, right} and ({left, right} & {c1, c2}):
        if left == c1: left = c2
        elif left == c2: left = c1
        if right == c1: right = c2
        elif right == c2: right = c1
    return periodic_coefficient(case_id, tuple(coord_i), tuple(coord_j), canonical_pair(left, right), self_pair)


def build_ip_model(case_id: str, grid, *, swapped: bool, hardcore: bool):
    import gurobipy as gp
    from gurobipy import GRB

    _, a, b, x_species, _ = CASES[case_id]
    species = (a, b, x_species); counts = (1, 1, 3)
    model = gp.Model(f"{case_id}_{len(grid)}")
    model.Params.OutputFlag = 0; model.Params.Seed = 0; model.Params.Threads = 8
    model.Params.MIPGap = 0.0; model.Params.NonConvex = 2
    variables = {(p, i): model.addVar(vtype=GRB.BINARY, name=f"x_{p}_{i}") for p in species for i in range(len(grid))}
    for p, count in zip(species, counts):
        model.addConstr(gp.quicksum(variables[p, i] for i in range(len(grid))) == count, name=f"count_{p}")
    for i in range(len(grid)):
        model.addConstr(gp.quicksum(variables[p, i] for p in species) <= 1, name=f"exclusive_{i}")
    hardcore_pairs = []
    if hardcore:
        from pymatgen.core import Lattice
        lattice = Lattice.cubic(case_lattice_a(case_id))
        for i in range(len(grid)):
            for j in range(i+1, len(grid)):
                distance, _ = lattice.get_distance_and_image(grid[i], grid[j])
                if float(distance) < HARDCORE - 1e-12:
                    model.addConstr(
                        gp.quicksum(variables[p, i] + variables[p, j] for p in species) <= 1,
                        name=f"hardcore_{i}_{j}",
                    )
                    hardcore_pairs.append((i, j))
    objective = gp.QuadExpr()
    for p in species:
        for i in range(len(grid)):
            objective += coefficient_for_species(case_id, grid[i], grid[i], p, p, swapped=swapped, self_pair=True) * variables[p, i]
    for i in range(len(grid)):
        for j in range(i+1, len(grid)):
            for p in species:
                for q in species:
                    coefficient = coefficient_for_species(case_id, grid[i], grid[j], p, q, swapped=swapped, self_pair=False)
                    objective += coefficient * variables[p, i] * variables[q, j]
    model.setObjective(objective, GRB.MINIMIZE)
    return model, variables, species, hardcore_pairs


def extract_ip_assignment(variables, species, site_count: int):
    selected = {p: [i for i in range(site_count) if variables[p, i].X > 0.5] for p in species}
    return selected[species[0]][0], selected[species[1]][0], tuple(sorted(selected[species[2]]))


def build_grid8_solver_confirmation() -> None:
    import gurobipy as gp
    rows = []
    all_assignments = read_csv(OUT / "GRID8_ALL_ASSIGNMENTS.csv")
    for case_id in included_case_ids():
        started = time.perf_counter()
        model, variables, species, hardcore_pairs = build_ip_model(case_id, GRID8, swapped=False, hardcore=False)
        model.optimize()
        status = "OPTIMAL" if model.Status == gp.GRB.OPTIMAL else str(model.Status)
        if model.Status != gp.GRB.OPTIMAL:
            raise RuntimeError(f"GRID8 solver failed for {case_id}: {model.Status}")
        a_site, b_site, x_sites = extract_ip_assignment(variables, species, len(GRID8))
        aid = assignment_id(case_id, "GRID8", a_site, b_site, x_sites)
        independent = occupation_score(case_id, GRID8, a_site, b_site, x_sites)
        case_rows = [r for r in all_assignments if r["case_id"] == case_id]
        exhaustive = next(r for r in case_rows if r["assignment_id"] == aid)
        min_score = min(float(r["spp_score"]) for r in case_rows)
        parity = abs(float(model.ObjVal) - independent) <= 1e-6 and abs(independent-min_score) <= 1e-6
        if not parity:
            raise RuntimeError(f"GRID8 solver/enumeration parity failure for {case_id}")
        rows.append({
            "case_id": case_id, "solver_backend": "Gurobi exact binary nonconvex MIQP",
            "solver_status": status, "selected_assignment": aid, "solver_objective": model.ObjVal,
            "independently_enumerated_objective": independent,
            "objective_difference": float(model.ObjVal)-independent, "objective_parity": parity,
            "solver_selection_is_exhaustive_rank1": int(exhaustive["spp_rank"]) == 1,
            "solve_time_s": time.perf_counter()-started,
            "binary_variables": len(variables), "hardcore_constraints": len(hardcore_pairs),
            "notes": "Same exact composition/site-exclusivity model as exhaustive GRID8; no family roles or reference constraints.",
        })
    write_csv(OUT / "GRID8_SOLVER_CONFIRMATION.csv", rows, [
        "case_id", "solver_backend", "solver_status", "selected_assignment", "solver_objective",
        "independently_enumerated_objective", "objective_difference", "objective_parity",
        "solver_selection_is_exhaustive_rank1", "solve_time_s", "binary_variables",
        "hardcore_constraints", "notes",
    ])
    print("PASS GRID8 SOLVER:", len(rows))


def translated_assignments(grid, a_site: int, b_site: int, x_sites: tuple[int, ...]):
    levels = sorted({float(value) for coord in grid for value in coord})
    step_count = len(levels)
    index = {tuple(round(v, 8) for v in coord): i for i, coord in enumerate(grid)}
    seen = set()
    for shift in itertools.product(levels, repeat=3):
        def shifted(site: int) -> int:
            coord = tuple(round((grid[site][axis] + shift[axis]) % 1.0, 8) for axis in range(3))
            return index[coord]
        candidate = (shifted(a_site), shifted(b_site), tuple(sorted(shifted(i) for i in x_sites)))
        if candidate not in seen:
            seen.add(candidate); yield candidate


def build_grid64_topk() -> None:
    import gurobipy as gp
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from sca.evaluators.topology import family_topology_metrics
    from sok_llm_orchestrator.structures.variable_perovskite import canonical_structure_hash

    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=False, scale=False, attempt_supercell=False)
    rows, recovery = [], []
    for case_id in included_case_ids():
        formula, _, _, x_species, _ = CASES[case_id]
        reference = __import__("pymatgen.core", fromlist=["Structure"]).Structure.from_file(case_reference(case_id))
        policy = "PEROVSKITE_3D" if x_species == "O" else "HALIDE_PEROVSKITE_3D"
        for condition, hardcore in (("GRID64_SPP_ONLY", False), ("GRID64_SPP_HARDCORE", True)):
            model, variables, species, hardcore_pairs = build_ip_model(case_id, GRID64, swapped=False, hardcore=hardcore)
            accepted_structures = []; condition_rows = []; solve_started = time.perf_counter(); attempts = 0
            while len(condition_rows) < 20 and attempts < 500:
                attempt_started = time.perf_counter(); model.optimize(); attempts += 1
                if model.Status != gp.GRB.OPTIMAL:
                    break
                a_site, b_site, x_sites = extract_ip_assignment(variables, species, len(GRID64))
                direct = occupation_score(case_id, GRID64, a_site, b_site, x_sites)
                if abs(float(model.ObjVal)-direct) > 1e-5:
                    raise RuntimeError(f"GRID64 objective parity failure {case_id}/{condition}")
                structure = assignment_structure(case_id, GRID64, a_site, b_site, x_sites)
                # Exclude every periodic grid translation with exact no-good cuts.
                for ta, tb, txs in translated_assignments(GRID64, a_site, b_site, x_sites):
                    selected = [variables[species[0], ta], variables[species[1], tb], *[variables[species[2], i] for i in txs]]
                    model.addConstr(gp.quicksum(selected) <= 4)
                if any(matcher.fit(structure, previous) for previous in accepted_structures):
                    continue
                accepted_structures.append(structure)
                distances = structure.distance_matrix.copy(); distances[distances < 1e-12] = float("inf")
                topology, _ = family_topology_metrics(structure, policy)
                rank = len(condition_rows)+1
                aid = assignment_id(case_id, "GRID64", a_site, b_site, x_sites)
                condition_rows.append({
                    "case_id": case_id, "condition": condition, "rank": rank,
                    "assignment_id": aid, "spp_score": direct,
                    "canonical_structure_hash": canonical_structure_hash(structure),
                    "minimum_distance_A": float(distances.min()),
                    "detected_space_group": SpacegroupAnalyzer(structure, symprec=1e-3).get_space_group_symbol(),
                    "topology_status": topology["topology_status"], "reference_match": matcher.fit(structure, reference),
                    "solve_time_s": time.perf_counter()-attempt_started,
                    "notes": f"Exact MIQP with translation no-good cuts; raw attempts={attempts}; hardcore_pair_constraints={len(hardcore_pairs)}.",
                })
                cif = OUT / "cifs" / "grid64" / f"{formula}_{condition}_rank{rank:03d}.cif"
                cif.parent.mkdir(parents=True, exist_ok=True)
                from pymatgen.io.cif import CifWriter
                CifWriter(structure).write_file(cif)
            rows.extend(condition_rows)
            matching_ranks = [int(r["rank"]) for r in condition_rows if r["reference_match"]]
            recovery.append({
                "case_id": case_id, "composition": formula, "condition": condition,
                "solutions_requested": 20, "solutions_returned": len(condition_rows),
                "reference_top1": bool(matching_ranks and min(matching_ranks)<=1),
                "reference_top5": bool(matching_ranks and min(matching_ranks)<=5),
                "reference_top10": bool(matching_ranks and min(matching_ranks)<=10),
                "reference_top20": bool(matching_ranks and min(matching_ranks)<=20),
                "best_reference_rank": min(matching_ranks) if matching_ranks else NA,
                "hardcore_constraints_added": len(hardcore_pairs),
                "total_solve_time_s": time.perf_counter()-solve_started,
                "notes": "Reference absence is a scientific non-recovery result, not a software failure.",
            })
    write_csv(OUT / "GRID64_TOPK.csv", rows, [
        "case_id", "condition", "rank", "assignment_id", "spp_score", "canonical_structure_hash",
        "minimum_distance_A", "detected_space_group", "topology_status", "reference_match", "solve_time_s", "notes",
    ])
    write_csv(OUT / "GRID64_REFERENCE_RECOVERY.csv", recovery, [
        "case_id", "composition", "condition", "solutions_requested", "solutions_returned",
        "reference_top1", "reference_top5", "reference_top10", "reference_top20", "best_reference_rank",
        "hardcore_constraints_added", "total_solve_time_s", "notes",
    ])
    print("PASS GRID64:", len(rows), "top-k rows")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("spp", "grid8", "grid8-solver", "grid64"))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == "spp": build_fresh_spp()
    elif args.stage == "grid8": build_grid8()
    elif args.stage == "grid8-solver": build_grid8_solver_confirmation()
    elif args.stage == "grid64": build_grid64_topk()


if __name__ == "__main__":
    main()
