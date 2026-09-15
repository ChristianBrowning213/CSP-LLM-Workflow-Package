"""Freeze PAPER-RESULTS-REDESIGN-1 before any new retrieval or generation."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_final_redesign" / "00_design"

ABX3 = [
    ("RDX-BATIO3", "BaTiO3", "oxide perovskite", "mp-d8426545", "local_runs/paper_experiment_1_common_v1/exp1_batio3_perovskite/exported_cifs/mp-d8426545.cif", "Ba", "Ti", "O"),
    ("RDX-CATIO3", "CaTiO3", "oxide perovskite", "mp-45ce5f93", "local_runs/paper_experiment_2_hard_v3/exp2v3_catio3_perovskite/exported_cifs/mp-45ce5f93.cif", "Ca", "Ti", "O"),
    ("RDX-SRTIO3", "SrTiO3", "oxide perovskite", "historical-srtio3-pm3m", "local_runs/paper_experiment_2_hard_v3/exp2v3_srtio3_perovskite/generated.cif", "Sr", "Ti", "O"),
    ("RDX-CSPBBR3", "CsPbBr3", "halide perovskite", "mp-d2f87a03", "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbbr3_halide/exported_cifs/mp-d2f87a03.cif", "Cs", "Pb", "Br"),
    ("RDX-CSPBCL3", "CsPbCl3", "halide perovskite", "mp-21acda64", "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbcl3_halide/exported_cifs/mp-21acda64.cif", "Cs", "Pb", "Cl"),
    ("RDX-CSPBI3", "CsPbI3", "halide perovskite", "mp-3f08b96a", "local_runs/paper_experiment_2_hard_v3/exp2v3_cspbi3_halide/exported_cifs/mp-3f08b96a.cif", "Cs", "Pb", "I"),
    ("RDX-CSSNBR3", "CsSnBr3", "halide perovskite", "mp-78e8fe69", "local_runs/paper_experiment_2_hard_v3/exp2v3_cssnbr3_halide/exported_cifs/mp-78e8fe69.cif", "Cs", "Sn", "Br"),
    ("RDX-CSSNI3", "CsSnI3", "halide perovskite", "mp-7b6d2307", "local_runs/paper_experiment_2_hard_v3/exp2v3_cssni3_halide/exported_cifs/mp-7b6d2307.cif", "Cs", "Sn", "I"),
]

NASICON = [
    ("RDX-E4-A2", "Na3Zr2Si2PO12", "NASICON/NZP", "nasicon-mp1221148", "data/nasicon/reference/reference.cif", "C2", "nasicon_na3zr2si2po12_c2_ordered", "nasicon-mp1221148", "TARGET_DERIVED"),
    ("RDX-E4-C2", "Na3Ti2(PO4)3", "NASICON/NZP", "nasicon-mp761046", "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp761046.cif", "R-3", "nasicon_na3ti2po43_r3", "nasicon-mp761046", "TARGET_DERIVED"),
    ("RDX-E4-F1", "LiZr2(PO4)3", "NASICON/NZP", "nasicon-mp10499", "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp10499.cif", "P2_1/c", "nzp_nazr2po43_r3c", "nasicon-mp6475", "FAMILY_MEMBER_NOT_EQUIVALENT"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(path: Path) -> str:
    structure = Structure.from_file(path)
    payload = {
        "lattice": [round(float(v), 10) for row in structure.lattice.matrix for v in row],
        "sites": sorted((str(site.specie), *[round(float(v) % 1.0, 10) for v in site.frac_coords]) for site in structure),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def pairs(species: list[str]) -> str:
    return ";".join(sorted({"-".join(sorted((a, b), key=str.lower)) for a in species for b in species}, key=str.lower))


def git_commit(repo: Path) -> str:
    result = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "NOT_AVAILABLE"


def main() -> None:
    if (OUT / "BENCHMARK_MANIFEST.csv").exists():
        raise RuntimeError("benchmark manifest already exists; refusing to rewrite the prospective freeze")
    OUT.mkdir(parents=True, exist_ok=True)
    data = []
    for case_id, formula, family, ref_id, ref_rel, a, b, x in ABX3:
        path = ROOT / ref_rel
        sg = SpacegroupAnalyzer(Structure.from_file(path), symprec=1e-2, angle_tolerance=5).get_space_group_symbol()
        source = "Crystal-DB phase6_mp_10k frozen Materials Project-derived CIF" if ref_id.startswith("mp-") else "frozen historical ideal candidate; no exact Crystal-DB target found"
        data.append({
            "case_id": case_id, "target_formula": formula, "target_family": family, "target_reference_id": ref_id,
            "target_reference_cif": str(path.resolve()), "reference_source": source, "target_space_group": sg,
            "benchmark_role": "SCAFFOLD_SPP_FACTORIAL", "candidate_scaffold_id": "cubic_perovskite_variable_cation_v1",
            "scaffold_source_id": "CURATED_PM3M_WYCKOFF_PROTOTYPE_FAMILY_SCALE",
            "scaffold_provenance_class": "CURATED_CONFIGURATION_NOT_TARGET_DERIVED",
            "retrieval_corpus_id": "Crystal-DB phase6_mp_10k production BGE-M3 robocrys space",
            "target_exclusion_protocol": "exclude exact target ID; exact reduced formula; raw hash; canonical hash; StructureMatcher-equivalent target before SPP fitting",
            "SPP_required_pairs": pairs([a, b, x]),
            "planned_conditions": "TIGHT_NO_SPP;TIGHT_CORRECT_SPP;LOOSE_NO_SPP;LOOSE_CORRECT_SPP;LOOSE_PERTURBED_SPP",
            "planned_evaluators": "production POT quality gate;Gurobi objective parity;SCA;StructureMatcher;CHGNet;Robocrys predicate audit",
            "reference_raw_hash": sha256(path), "reference_canonical_hash": canonical_hash(path),
            "predeclared_evidence_gate": "reference exists; complete required POTs; production spp_pot_quality_status=usable; loose feasible count >1",
            "design_notes": "All eight ABX3 targets retained irrespective of earlier exploratory performance. Curated family lattice: oxide a=4.0 A; halide a=6.0 A. SrTiO3 reference provenance is UNCLEAR and cannot enter strict headline.",
        })
    for case_id, formula, family, ref_id, ref_rel, sg, scaffold, scaffold_source, provenance in NASICON:
        path = ROOT / ref_rel
        species = [str(e) for e in Structure.from_file(path).composition.elements]
        data.append({
            "case_id": case_id, "target_formula": formula, "target_family": family, "target_reference_id": ref_id,
            "target_reference_cif": str(path.resolve()), "reference_source": "frozen specialist NASICON corpus",
            "target_space_group": sg, "benchmark_role": "NASICON_EXTENSION", "candidate_scaffold_id": scaffold,
            "scaffold_source_id": scaffold_source, "scaffold_provenance_class": provenance,
            "retrieval_corpus_id": "nasicon_specialist_v3 320-record corpus / production BGE-M3",
            "target_exclusion_protocol": "exclude target ID; exact reduced formula; raw/canonical duplicates; StructureMatcher-equivalent target",
            "SPP_required_pairs": pairs(species),
            "planned_conditions": "NASICON_LOOSE_NO_SPP;NASICON_LOOSE_CORRECT_SPP;NASICON_LOOSE_PERTURBED_SPP_IF_VALID",
            "planned_evaluators": "production POT quality gate;Gurobi objective parity;SCA;StructureMatcher;CHGNet",
            "reference_raw_hash": sha256(path), "reference_canonical_hash": canonical_hash(path),
            "predeclared_evidence_gate": "complete target-excluded POT set; production status usable; >1 crystallographically distinct feasible assignment",
            "design_notes": "Preserve target-derived provenance where unavoidable. Failed quality/search-space gates produce NASICON_D rather than substitution of cases.",
        })
    for case_id, formula, sg, reason in [
        ("RDX-NEG-E4-A1", "Na3Zr2Si2PO12", "R-3c", "ordered Si4/P2 incompatible with one multiplicity-6 tetrahedral orbit"),
        ("RDX-NEG-E4-A3", "Na3Ti2Si2PO12", "R-3", "requested space group incompatible with selected registered scaffold"),
        ("RDX-NEG-E4-A4", "Na3Hf2Si2PO12", "R-3", "requested space group incompatible with selected registered scaffold"),
    ]:
        data.append({
            "case_id": case_id, "target_formula": formula, "target_family": "NASICON/NZP", "target_reference_id": "NA",
            "target_reference_cif": "NA", "reference_source": "NA", "target_space_group": sg,
            "benchmark_role": "NEGATIVE_REPRESENTABILITY", "candidate_scaffold_id": "predeclared registered NASICON scaffold",
            "scaffold_source_id": "NASICON_SCAFFOLD_REGISTRY", "scaffold_provenance_class": "CONTROLLED_NEGATIVE",
            "retrieval_corpus_id": "NOT_RUN_PRE_GENERATION_ABSTENTION", "target_exclusion_protocol": "NOT_APPLICABLE",
            "SPP_required_pairs": "NOT_APPLICABLE", "planned_conditions": "REPRESENTABILITY_PREFLIGHT;NEARBY_POSITIVE_CONTROL_E4_A2",
            "planned_evaluators": "integer orbit-multiplicity/domain preflight", "reference_raw_hash": "NA", "reference_canonical_hash": "NA",
            "predeclared_evidence_gate": "mathematical incompatibility must be demonstrated without malformed input",
            "design_notes": reason,
        })
    fields = list(data[0])
    manifest = OUT / "BENCHMARK_MANIFEST.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(data)
    frozen_at = datetime.now(timezone.utc).isoformat()
    protocol = f"""# Prospective benchmark protocol

Frozen at: `{frozen_at}`  
Manifest SHA-256: `{sha256(manifest)}`  
Skill-Loop-CSP commit: `{git_commit(ROOT)}`

## Fixed target set

The target list is frozen before redesigned retrieval, SPP fitting or generation: eight ABX3 cases, three named NASICON/NZP cases and three mathematical negative controls. No case may be replaced after observing performance. Earlier exploratory GRID8 and target-derived-cell results are known boundary evidence, not results of this redesigned benchmark.

## Reference exclusion

For each positive target, the reference ID and raw/canonical hashes are frozen first. Evidence selection excludes the exact ID and every exact reduced-formula record. Exact-formula exclusion necessarily subsumes same-composition raw/canonical/StructureMatcher equivalents; explicit audit fields still record each tested category. References never supply coordinates, lattice constants or objective coefficients.

## Independent ABX3 scaffold

ABX3 candidates use the validated `cubic_perovskite_variable_cation_v1` Wyckoff geometry with a predeclared curated family cell (`a=4.0 Å` oxide; `a=6.0 Å` halide). The scaffold source is the generic Pm-3m 1a/1b/3c prototype, not a target CIF. Tight conditions fix the two cation roles; loose conditions permit both role permutations. The candidate set is frozen before SPP results.

## Evidence and SPP quality gates

Production Crystal-DB BGE-M3/Robocrys retrieval is run with deterministic target exclusion. SPP construction uses the production 11 Å periodic path. A case enters primary scoring only if every required pair is present and the production `spp_pot_quality_status` is `usable`. `unusable`, `missing`, `diagnostic_only` and supplemented objectives are excluded from the strict headline; missing interactions are never zeroed or invented.

## Evaluators

Candidate selection uses only declared hard constraints and SPP coefficients. SCA, StructureMatcher, CHGNet and Robocrystallographer predicate checks are post-generation evaluators and never feed back into retrieval, fitting or selection. CHGNet convergence is structural QC, not stability.

## Predeclared classifications

Factorial evidence is classified RESULT_A–D without dropping failures. NASICON is classified independently as NASICON_A–D. If no quality-valid complete NASICON SPP exists, the required result is NASICON_D. GRID8 is copied unchanged as a supplementary boundary experiment; GRID64 and DFT are prohibited.
"""
    (OUT / "BENCHMARK_PROTOCOL.md").write_text(protocol, encoding="utf-8")
    (OUT / "FREEZE_METADATA.json").write_text(json.dumps({"frozen_at": frozen_at, "manifest_sha256": sha256(manifest), "row_count": len(data), "abx3_count": len(ABX3), "nasicon_count": len(NASICON), "negative_count": 3}, indent=2) + "\n", encoding="utf-8")
    print(f"FROZEN {len(data)} rows {sha256(manifest)}")


if __name__ == "__main__":
    main()
