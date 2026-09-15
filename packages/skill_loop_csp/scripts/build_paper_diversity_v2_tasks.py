"""Build the frozen paper-diversity-v2 breadth-task and preflight artifacts.

This script defines benchmark intent only.  It never retrieves evidence, fits
SPPs, invokes QLIP, or generates a candidate.  Representability statements are
deliberately conservative and tied to the current prototype-scaffold registry.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "paper_diversity_v2"
ART = ROOT / "artifacts" / "paper_diversity_v2" / "tasks"
FINAL = ROOT / "artifacts" / "paper_diversity_v2" / "final"
RUNS = ROOT / "runs" / "paper_diversity_v2"
FIGURES = ROOT / "figures" / "paper_diversity_v2"

FIELDS = [
    "task_id", "experiment_id", "natural_language_request", "short_request_label",
    "target_formula", "target_family", "target_topology", "target_dimensionality",
    "allowed_space_groups", "preferred_space_group", "forbidden_space_groups",
    "scaffold_hypotheses", "lattice_candidate_policy", "fixed_species_orbits",
    "variable_species_orbits", "site_ordering_requirement", "vacancy_ordering_requirement",
    "mixed_anion_ordering_requirement", "supercell_requirement",
    "requested_distinct_solutions", "retrieval_corpus", "retrieval_filters", "spp_policy",
    "validation_policy", "success_criteria", "unsupported_claims", "difference_vector",
    "qlip_representability_status", "intent_axes", "substitution",
]


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def task(
    task_id: str,
    experiment_id: str,
    formula: str,
    family: str,
    topology: str,
    space_group: str,
    scaffold: str,
    request: str,
    *,
    fixed: str,
    variable: str = "none",
    ordering: str = "fixed prototype assignment",
    vacancy: str = "none",
    mixed_anion: str = "none",
    supercell: str = "primitive/conventional prototype cell",
    k: int = 1,
    status: str = "SUPPORTED_WITH_CONFIGURATION",
    lattice: str = "single registered prototype lattice",
    forbidden: str = "none",
    corpus: str = "materials_project_phase6_mp_10k",
    filters: str = "formula/family/topology relevance",
    spp: str = "row-specific where complete; otherwise no-SPP baseline",
    success: str = "parseable CIF; exact reduced formula; requested symmetry/family; no severe contacts",
    unsupported: str = "no stability, novelty, conductivity, or calibrated-energy claim",
    substitution: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "experiment_id": experiment_id,
        "natural_language_request": request,
        "short_request_label": task_id.replace("_", " "),
        "target_formula": formula,
        "target_family": family,
        "target_topology": topology,
        "target_dimensionality": "3D",
        "allowed_space_groups": space_group,
        "preferred_space_group": space_group.split(";")[0],
        "forbidden_space_groups": forbidden,
        "scaffold_hypotheses": scaffold,
        "lattice_candidate_policy": lattice,
        "fixed_species_orbits": fixed,
        "variable_species_orbits": variable,
        "site_ordering_requirement": ordering,
        "vacancy_ordering_requirement": vacancy,
        "mixed_anion_ordering_requirement": mixed_anion,
        "supercell_requirement": supercell,
        "requested_distinct_solutions": k,
        "retrieval_corpus": corpus,
        "retrieval_filters": filters,
        "spp_policy": spp,
        "validation_policy": "SCA parse/formula/symmetry/contact screen; family topology validator where implemented",
        "success_criteria": success,
        "unsupported_claims": unsupported,
        "difference_vector": "",
        "qlip_representability_status": status,
        "intent_axes": dumps({"substitution_site": substitution is not None}),
        "substitution": dumps(substitution or {}),
    }


def exp1() -> list[dict[str, Any]]:
    specs = [
        ("E1_01", "NiO", "rocksalt", "rocksalt AX", "Fm-3m", "rocksalt", "Ni:4a;O:4b", "Generate rocksalt NiO in Fm-3m with octahedral Ni–O coordination and no severe short contacts."),
        ("E1_02", "CeO2", "fluorite", "fluorite AX2", "Fm-3m", "fluorite", "Ce:4a;O:8c", "Generate fluorite CeO2 in Fm-3m with eight-coordinate Ce and four-coordinate oxygen."),
        ("E1_03", "MgAl2O4", "spinel", "normal spinel AB2O4", "Fd-3m", "spinel_mgal2o4", "Mg:8a;Al:16d;O:32e", "Generate normal-spinel MgAl2O4 in Fd-3m with Mg tetrahedral and Al octahedral sites."),
        ("E1_04", "BaTiO3", "perovskite", "corner-sharing BO6 perovskite", "Pm-3m", "perovskite", "Ba:1a;Ti:1b;O:3c", "Generate cubic BaTiO3 in Pm-3m with an untilted corner-sharing TiO6 framework."),
        ("E1_05", "FeS2", "pyrite", "pyrite AX2", "Pa-3", "pyrite", "Fe:4a;S:8c", "Generate pyrite FeS2 in Pa-3 with S2 dumbbells and octahedral Fe coordination."),
        ("E1_06", "LiCoO2", "layered oxide", "O3 layered oxide", "R-3m", "layered_oxide", "Li:3a;Co:3b;O:6c", "Generate layered LiCoO2 in R-3m with Li confined to the interlayer orbit."),
        ("E1_07", "LiFePO4", "olivine phosphate", "olivine phosphate", "Pnma", "olivine_phosphate", "Li:4a;Fe:4c;P:4c;O:4c/8d", "Generate olivine LiFePO4 in Pnma with isolated PO4 tetrahedra and the registered Li channel sites."),
        ("E1_08", "TiN", "rocksalt-like nitride", "rocksalt AX nitride", "Fm-3m", "nitride", "Ti:4a;N:4b", "Generate rocksalt-like TiN in Fm-3m with octahedral Ti–N coordination."),
        ("E1_09", "Li6PS5Cl", "argyrodite", "argyrodite", "F-43m", "argyrodite", "P:4b;S:4a/16e;Cl:4d;Li:24g", "Generate cubic Li6PS5Cl argyrodite in F-43m using the registered fully ordered prototype."),
        ("E1_10", "CsPbBr3", "halide perovskite", "corner-sharing BX6 perovskite", "Pm-3m", "halide_perovskite", "Cs:1a;Pb:1b;Br:3c", "Generate cubic CsPbBr3 in Pm-3m with an untilted corner-sharing PbBr6 network."),
    ]
    return [
        task(s[0], "EXP1_BASIC", *s[1:6], request=s[7], fixed=s[6], status="SUPPORTED_NOW")
        for s in specs
    ]


def exp2() -> list[dict[str, Any]]:
    rows = [
        task("E2_01", "EXP2_COMMON_DESIRES", "BaTiO3", "perovskite", "untilted perovskite", "Pm-3m", "perovskite", "Generate cubic BaTiO3 in Pm-3m with an untilted corner-sharing TiO6 framework.", fixed="Ba:1a;Ti:1b;O:3c", status="SUPPORTED_NOW"),
        task("E2_02", "EXP2_COMMON_DESIRES", "BaTiO3", "polar perovskite", "tetragonal polar perovskite", "P4mm", "batio3_tetragonal_polar", "Generate tetragonal BaTiO3 in P4mm with a symmetry-represented polar Ti displacement along c.", fixed="O framework", variable="Ti polar displacement orbit", status="REQUIRES_SMALL_EXTENSION", lattice="new tetragonal candidate lattice"),
        task("E2_03", "EXP2_COMMON_DESIRES", "CaTiO3", "tilted perovskite", "orthorhombic a-b+a- tilt", "Pnma", "catio3_pnma_tilt", "Generate orthorhombic CaTiO3 in Pnma with a discrete a-b+a- octahedral-tilt scaffold.", fixed="Ca/Ti/O scaffold orbits", status="REQUIRES_SMALL_EXTENSION", lattice="new orthorhombic tilt lattice"),
        task("E2_04", "EXP2_COMMON_DESIRES", "SrTiO3", "perovskite", "untilted perovskite", "Pm-3m", "perovskite", "Generate cubic SrTiO3 in Pm-3m and return two symmetry-distinct valid candidates if the represented search space permits.", fixed="Ti:1b;O:3c", variable="A:1a", k=2, status="REQUIRES_SMALL_EXTENSION"),
        task("E2_05", "EXP2_COMMON_DESIRES", "MgAl2O4", "spinel", "normal spinel", "Fd-3m", "spinel_mgal2o4", "Generate normal-spinel MgAl2O4 with Mg on tetrahedral and Al on octahedral orbits.", fixed="Mg:8a;Al:16d;O:32e", ordering="normal spinel cation ordering", status="SUPPORTED_WITH_CONFIGURATION"),
        task("E2_06", "EXP2_COMMON_DESIRES", "CoFe2O4", "spinel", "inverse spinel", "Fd-3m", "cofe2o4_inverse_supercell", "Generate inverse-spinel CoFe2O4 with symmetry-closed Co/Fe allocation over tetrahedral and octahedral cation orbits.", fixed="O:32e", variable="Co/Fe:8a/16d", ordering="inverse spinel cation ordering", supercell="ordered spinel cell", status="REQUIRES_SMALL_EXTENSION"),
        task("E2_07", "EXP2_COMMON_DESIRES", "TiO2", "rutile", "rutile chains", "P4_2/mnm", "tio2_rutile", "Generate rutile TiO2 in P4_2/mnm and preserve edge-sharing TiO6 chains.", fixed="Ti/O rutile orbits", status="REQUIRES_SMALL_EXTENSION"),
        task("E2_08", "EXP2_COMMON_DESIRES", "TiO2", "anatase", "anatase network", "I4_1/amd", "tio2_anatase", "Generate anatase TiO2 in I4_1/amd as a search space distinct from rutile.", fixed="Ti/O anatase orbits", status="REQUIRES_SMALL_EXTENSION"),
        task("E2_09", "EXP2_COMMON_DESIRES", "LiCoO2", "layered oxide", "O3 layered oxide", "R-3m", "layered_oxide", "Generate layered LiCoO2 with Li confined to interlayer sites and return three distinct lattice-preserving candidates.", fixed="Co:3b;O:6c", variable="Li:3a occupation", k=3, status="REQUIRES_SMALL_EXTENSION"),
        task("E2_10", "EXP2_COMMON_DESIRES", "NaCoO2", "layered oxide", "O3 layered oxide", "R-3m", "layered_oxide_nacoo2", "Generate layered NaCoO2 in R-3m with Na confined to the registered interlayer orbit.", fixed="Na:3a;Co:3b;O:6c", status="SUPPORTED_WITH_CONFIGURATION"),
        task("E2_11", "EXP2_COMMON_DESIRES", "LiNiO2", "layered oxide", "O3 layered oxide", "R-3m", "layered_oxide_linio2", "Generate layered LiNiO2 in R-3m and reject Li/Ni antisite mixing.", fixed="Li:3a;Ni:3b;O:6c", ordering="explicit no-antisite ordering", status="SUPPORTED_WITH_CONFIGURATION"),
        task("E2_12", "EXP2_COMMON_DESIRES", "LiMnPO4", "olivine phosphate", "olivine phosphate", "Pnma", "olivine_phosphate_limn", "Generate olivine LiMnPO4 in Pnma and keep Li on the channel orbit.", fixed="Li/Mn/P/O olivine orbits", status="SUPPORTED_WITH_CONFIGURATION"),
        task("E2_13", "EXP2_COMMON_DESIRES", "NaFePO4", "olivine phosphate", "olivine phosphate", "Pnma", "olivine_phosphate_nafe", "Generate olivine NaFePO4 in Pnma and return two distinct candidates from separate retrieved lattices.", fixed="Na/Fe/P/O olivine orbits", k=2, lattice="multiple retrieved Pnma lattice candidates", status="REQUIRES_SMALL_EXTENSION"),
        task("E2_14", "EXP2_COMMON_DESIRES", "ZrO2", "fluorite", "fluorite AX2", "Fm-3m", "fluorite_zro2", "Generate cubic fluorite ZrO2 in Fm-3m with the registered Zr and O orbits.", fixed="Zr:4a;O:8c", status="SUPPORTED_NOW"),
        task("E2_15", "EXP2_COMMON_DESIRES", "ZrO2", "monoclinic zirconia", "monoclinic zirconia", "P2_1/c", "zro2_monoclinic", "Generate monoclinic ZrO2 in P2_1/c as a polymorph-distinct task from fluorite ZrO2.", fixed="Zr/O monoclinic orbits", status="REQUIRES_SMALL_EXTENSION"),
        task("E2_16", "EXP2_COMMON_DESIRES", "ZnO", "wurtzite", "wurtzite tetrahedral network", "P6_3mc", "zno_wurtzite", "Generate wurtzite ZnO in P6_3mc with tetrahedral Zn–O coordination.", fixed="Zn/O wurtzite orbits", status="REQUIRES_SMALL_EXTENSION"),
        task("E2_17", "EXP2_COMMON_DESIRES", "Mg0.875Li0.125O", "doped rocksalt", "rocksalt substitution supercell", "Fm-3m subgroups", "mgo_2x2x2_substitution", "Generate a 2×2×2 rocksalt MgO supercell with one symmetry-closed Mg-site orbit replaced by Li and enumerate two inequivalent dopant placements.", fixed="O sublattice", variable="Mg/Li cation orbits", ordering="Li substitution-site ordering", supercell="2x2x2", k=2, status="REQUIRES_MAJOR_EXTENSION", substitution={"from_species":"Mg","to_species":"Li","target_orbit":"Mg cation orbit","charge_compensation_policy":"composition fixed; charge-compensation validation required"}),
        task("E2_18", "EXP2_COMMON_DESIRES", "Ce0.875Gd0.125O1.9375", "doped fluorite", "oxygen-vacancy fluorite", "Fm-3m subgroups", "ceria_doped_vacancy_supercell", "Generate Gd-doped ceria in a 2×2×2 fluorite supercell with a charge-compensating ordered oxygen vacancy and return two arrangements.", fixed="fluorite lattice", variable="Ce/Gd and O/vacancy orbits", ordering="dopant-vacancy association", vacancy="explicit O/vacancy occupation", supercell="2x2x2", k=2, status="REQUIRES_MAJOR_EXTENSION", substitution={"from_species":"Ce","to_species":"Gd","target_orbit":"Ce fluorite cation orbit","charge_compensation_policy":"explicit ordered oxygen-vacancy occupation"}),
        task("E2_19", "EXP2_COMMON_DESIRES", "SrTi0.875Nb0.125O3", "doped perovskite", "B-site substituted perovskite", "Pm-3m subgroups", "srti_nb_supercell", "Generate Nb-substituted SrTiO3 with Nb on a symmetry-closed B-site orbit in a 2×2×2 supercell.", fixed="Sr/O framework", variable="Ti/Nb B-site orbits", ordering="B-site substitution ordering", supercell="2x2x2", status="REQUIRES_MAJOR_EXTENSION", substitution={"from_species":"Ti","to_species":"Nb","target_orbit":"Ti perovskite B-site orbit","charge_compensation_policy":"composition fixed; electronic compensation outside current solver"}),
        task("E2_20", "EXP2_COMMON_DESIRES", "LiFe0.75Mn0.25PO4", "substituted olivine", "olivine phosphate", "Pnma subgroups", "lifepo4_mn_supercell", "Generate Mn-substituted LiFePO4 with Mn assigned to a distinct transition-metal orbit and return three inequivalent orderings.", fixed="Li/P/O olivine framework", variable="Fe/Mn octahedral orbits", ordering="transition-metal ordering", supercell="ordered olivine supercell", k=3, status="REQUIRES_MAJOR_EXTENSION", substitution={"from_species":"Fe","to_species":"Mn","target_orbit":"Fe olivine octahedral orbit","charge_compensation_policy":"isovalent Fe2+/Mn2+ substitution"}),
    ]
    return rows


def exp3() -> list[dict[str, Any]]:
    entries = [
        ("E3_01","CsPbCl3","Pm-3m","halide_perovskite_cspbcl3","cubic untilted","Cs:1a;Pb:1b;Cl:3c","none",1,"SUPPORTED_NOW"),
        ("E3_02","CsPbBr3","Pm-3m","halide_perovskite","cubic untilted","Cs:1a;Pb:1b;Br:3c","none",1,"SUPPORTED_NOW"),
        ("E3_03","CsPbI3","Pm-3m","halide_perovskite_cspbi3","cubic untilted","Cs:1a;Pb:1b;I:3c","none",1,"SUPPORTED_NOW"),
        ("E3_04","CsSnBr3","Pm-3m","halide_perovskite_cssnbr3","cubic untilted","Cs:1a;Sn:1b;Br:3c","none",1,"SUPPORTED_NOW"),
        ("E3_05","CsSnI3","Pm-3m","halide_perovskite_cssni3","cubic untilted","Cs:1a;Sn:1b;I:3c","none",2,"REQUIRES_SMALL_EXTENSION"),
        ("E3_06","RbPbCl3","Pm-3m","rbpbcl3_cubic","cubic untilted","Pb/Cl","none",1,"REQUIRES_SMALL_EXTENSION"),
        ("E3_07","RbSnBr3","Pm-3m","rbsnbr3_cubic","cubic untilted","Sn/Br","none",2,"REQUIRES_SMALL_EXTENSION"),
        ("E3_08","KPbI3","Pm-3m","kpbi3_cubic","cubic untilted","Pb/I","none",1,"REQUIRES_SMALL_EXTENSION"),
        ("E3_09","CsGeCl3","Pm-3m","csgecl3_cubic","cubic untilted","Ge/Cl","none",3,"REQUIRES_SMALL_EXTENSION"),
        ("E3_10","CsGeBr3","Pm-3m","csgebr3_cubic","cubic untilted","Ge/Br","none",1,"REQUIRES_SMALL_EXTENSION"),
        ("E3_11","CsPbBr3","P4/mbm","cspbbr3_tetragonal_tilt","tetragonal tilt","Cs/Pb/Br tilt orbits","none",2,"REQUIRES_SMALL_EXTENSION"),
        ("E3_12","CsSnI3","Pnma","cssni3_pnma_tilt","orthorhombic tilt","Cs/Sn/I tilt orbits","none",3,"REQUIRES_SMALL_EXTENSION"),
        ("E3_13","RbPbBr3","Pnma","rbpbbr3_pnma_tilt","orthorhombic tilt","Rb/Pb/Br tilt orbits","none",1,"REQUIRES_SMALL_EXTENSION"),
        ("E3_14","KPbCl3","P4/mbm","kpbcl3_tetragonal_tilt","tetragonal tilt","K/Pb/Cl tilt orbits","none",3,"REQUIRES_SMALL_EXTENSION"),
        ("E3_15","CsPbBr2Cl","P4mm subgroups","cspbbr2cl_ordered","ordered Br/Cl supercell","Cs/Pb","Br/Cl",2,"REQUIRES_MAJOR_EXTENSION"),
        ("E3_16","CsPbBrI2","P4mm subgroups","cspbbri2_ordered","ordered Br/I supercell","Cs/Pb","Br/I",3,"REQUIRES_MAJOR_EXTENSION"),
        ("E3_17","RbSnBr2Cl","P4mm subgroups","rbsnbr2cl_ordered","ordered Br/Cl supercell","Rb/Sn","Br/Cl",1,"REQUIRES_MAJOR_EXTENSION"),
        ("E3_18","KSnCl2Br","P4mm subgroups","ksncl2br_ordered","ordered Cl/Br supercell","K/Sn","Cl/Br",2,"REQUIRES_MAJOR_EXTENSION"),
        ("E3_19","Cs2AgBiBr6","Fm-3m","double_perovskite_cs2agbibr6","ordered double perovskite","Cs/Br","Ag/Bi",5,"REQUIRES_MAJOR_EXTENSION"),
        ("E3_20","Cs2AgBiCl6","Fm-3m","double_perovskite_cs2agbicl6","ordered double perovskite","Cs/Cl","Ag/Bi",5,"REQUIRES_MAJOR_EXTENSION"),
    ]
    rows=[]
    for tid,formula,sg,scaffold,mode,fixed,var,k,status in entries:
        mixed = f"ordered {var} anion allocation" if "/" in var and any(x in var for x in ("Cl","Br","I")) else "none"
        ordering = f"{mode}; variable allocation {var}" if var != "none" else mode
        supercell = "symmetry-closed ordered supercell" if ("ordered" in mode or "tilt" in mode) else "primitive cubic cell"
        req=f"Generate {k if k > 1 else 'a'} {'distinct ' if k > 1 else ''}{formula} halide-perovskite candidate{'s' if k > 1 else ''} using the {mode} scaffold in {sg}; preserve corner-sharing BX6 connectivity and reject severe contacts."
        rows.append(task(tid,"EXP3_HALIDE",formula,"halide perovskite",mode,sg,scaffold,req,fixed=fixed,variable=var,ordering=ordering,mixed_anion=mixed,supercell=supercell,k=k,status=status,corpus="paper_experiment_3_halide_perovskite_v1",filters="halide-perovskite chemistry, requested A/B/X species and symmetry"))
    return rows


NASICON_SPECS = [
    ("A1","Na3Zr2Si2PO12","R-3c","nasicon_rhombohedral","high-symmetry framework","fixed verified reference orbits",1),
    ("A2","Na3Zr2Si2PO12","C2","nasicon_monoclinic_c2","explicit Si/P orbit closure","Si/P tetrahedral orbits",1),
    ("A3","Na3Ti2Si2PO12","P2_1/c","nasicon_ti_ordered_supercell","alternative Si/P ordering","Si/P tetrahedral orbits",2),
    ("A4","Na3Hf2Si2PO12","C2/c","nasicon_hf_ordered_supercell","top-k Si/P orderings","Si/P tetrahedral orbits",3),
    ("B1","NaZr2(PO4)3","R-3c","nasicon_na_poor","sodium-poor loading","Na/vacancy mobile-ion orbits",1),
    ("B2","Na2ZrSc(PO4)3","C2/c","nasicon_intermediate_na","intermediate sodium loading","Na/vacancy and Zr/Sc orbits",2),
    ("B3","Na4Zr2(SiO4)3","R-3c","nasicon_na_rich_silicate","sodium-rich loading","multiple Na orbits",1),
    ("B4","Na3Fe2(PO4)3","P2_1/c","nasicon_na_vacancy_supercell","ordered Na-vacancy supercell","Na/vacancy mobile-ion orbits",2),
    ("C1","NaZr2(PO4)3","R-3c","nasicon_zr_phosphate","Zr framework chemistry","Na mobile-ion orbits",1),
    ("C2","Na3Ti2(PO4)3","R-3","nasicon_ti_phosphate","Ti framework chemistry","Na orbits",1),
    ("C3","Na3Hf2Si2PO12","R-3c","nasicon_hf_rhombohedral","Hf framework chemistry","Si/P tetrahedral orbits",2),
    ("C4","Na3Sc2(PO4)3","R-3c","nasicon_sc_phosphate","Sc framework chemistry","Na orbits",1),
    ("D1","Na3ZrTiSi2PO12","C2","nasicon_zr_ti_ordered","Zr/Ti framework ordering","Zr/Ti octahedral orbits;Si/P tetrahedral orbits",2),
    ("D2","Na3ZrHfSi2PO12","C2","nasicon_zr_hf_ordered","Zr/Hf framework ordering","Zr/Hf octahedral orbits;Si/P tetrahedral orbits",2),
    ("D3","Na2TiSc(PO4)3","C2/c","nasicon_ti_sc_ordered","Ti/Sc framework ordering","Ti/Sc octahedral orbits",2),
    ("D4","Na2HfSc(PO4)3","P2_1/c","nasicon_hf_sc_ordered","Hf/Sc framework ordering","Hf/Sc octahedral orbits",2),
    ("E1","Na3V2(PO4)3","C2/c","nasicon_v_phosphate","phosphate-rich","Na orbits",1),
    ("E2","Na3Ti2Si2PO12","C2","nasicon_ti_silicophosphate","mixed silico-phosphate","Si/P tetrahedral orbits",2),
    ("E3","Na4Ti2(SiO4)3","R-3c","nasicon_ti_silicate","silicate-rich","Na orbits",1),
    ("E4","Na3Hf2Sc2P5SO24","P1","nasicon_hf_sc_phosphate_sulfate","mixed phosphate/sulfate tetrahedral chemistry","P/S tetrahedral orbits;Hf/Sc octahedral orbits",2),
    ("F1","LiZr2(PO4)3","R-3c","nasicon_li_rhombohedral","rhombohedral scaffold","Li orbits",1),
    ("F2","LiZr2(PO4)3","P2_1/c","nasicon_li_monoclinic","monoclinic scaffold","Li orbits",2),
    ("F3","Na4Hf2(SiO4)3","P2_1/c","nasicon_hf_low_symmetry","lower-symmetry ordered supercell","Na orbits",2),
    ("F4","Na3V2(PO4)3","P2_1/c","nasicon_v_monoclinic","second verified lattice family","Na orbits",2),
    ("G1","Na3ZrHfSi2PO12","P2_1/c","nasicon_zr_hf_coupled","Na-vacancy plus Si/P ordering","Na/vacancy;Si/P;Zr/Hf orbits",2),
    ("G2","Na2ZrSc(PO4)3","P2_1/c","nasicon_zr_sc_coupled","framework-cation plus Na ordering","Na/vacancy;Zr/Sc orbits",2),
    ("G3","Na3TiHfSi2PO12","C2","nasicon_ti_hf_coupled","tetrahedral plus framework ordering","Si/P;Ti/Hf orbits",3),
    ("G4","Na2HfSc(PO4)3","P1","nasicon_hf_sc_vacancy_expanded","expanded vacancy-ordering supercell","Na/vacancy;Hf/Sc orbits",3),
    ("H1","Na3ZrTiSi2PO12","C2","nasicon_zr_ti_ordered","top-3 distinct assignments","Zr/Ti;Si/P orbits",3),
    ("H2","Na3Fe2(PO4)3","C2/c","nasicon_fe_phosphate","top-5 distinct Na arrangements","Na/vacancy orbits",5),
    ("H3","Na3TiHfSi2PO12","P2_1/c","nasicon_ti_hf_exclude_reference","exclude known orbit assignment","Ti/Hf;Si/P orbits",2),
    ("H4","Na4Ti2(SiO4)3","R-3c;P2_1/c","nasicon_multi_lattice","multiple retrieved scaffolds","Na orbits",3),
]


def exp4() -> list[dict[str, Any]]:
    rows=[]
    for code,formula,sg,scaffold,policy,variable,k in NASICON_SPECS:
        vacancy = "explicit Na/vacancy occupation" if "vacancy" in policy.lower() or "Na/vacancy" in variable else "none"
        supercell = "ordered expanded supercell" if any(x in policy.lower() for x in ("supercell","ordering","top-k","top-")) or k > 1 else "verified reference cell"
        req=(f"Generate {k if k > 1 else 'a'} {'distinct ' if k > 1 else ''}{formula} NASICON candidate{'s' if k > 1 else ''}. "
             f"Use the {policy} search space ({sg}), preserve a three-dimensional linked MO6/XO4 framework, represent {variable}, and reject broken topology or severe contacts.")
        rows.append(task(f"E4_{code}","EXP4_NASICON",formula,"NASICON/NZP",policy,sg,scaffold,req,fixed="oxygen framework and non-variable symmetry-closed orbits",variable=variable,ordering=policy,vacancy=vacancy,supercell=supercell,k=k,status="REQUIRES_MAJOR_EXTENSION",corpus="nasicon_specialist_all_targets_out_v3",filters="NASICON/NZP topology; target chemistry; evaluation-target exclusion",spp="all-targets-out row-specific SPP only when every required pair passes support",success="exact formula; requested orbit allocation; 3D NASICON topology PASS; symmetry-compatible; no severe contacts"))
    return rows


def signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[key] for key in (
        "target_formula", "target_family", "target_topology", "allowed_space_groups",
        "scaffold_hypotheses", "lattice_candidate_policy", "fixed_species_orbits",
        "variable_species_orbits", "site_ordering_requirement", "vacancy_ordering_requirement",
        "mixed_anion_ordering_requirement", "supercell_requirement", "requested_distinct_solutions",
    ))


def add_difference_vectors(rows: list[dict[str, Any]]) -> None:
    axes = {
        "composition_changed": "target_formula", "family_changed": "target_family",
        "topology_changed": "target_topology", "symmetry_changed": "allowed_space_groups",
        "scaffold_changed": "scaffold_hypotheses", "lattice_changed": "lattice_candidate_policy",
        "orbit_set_changed": "variable_species_orbits", "occupation_changed": "vacancy_ordering_requirement",
        "ordering_changed": "site_ordering_requirement", "supercell_changed": "supercell_requirement",
        "requested_k_changed": "requested_distinct_solutions",
    }
    previous: dict[str, Any] | None = None
    for row in rows:
        row["difference_vector"] = dumps({name: previous is None or row[key] != previous[key] for name,key in axes.items()})
        previous = row


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer=csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    for path in (BENCH, ART, FINAL, RUNS, FIGURES): path.mkdir(parents=True, exist_ok=True)
    groups=[exp1(),exp2(),exp3(),exp4()]
    expected=[10,20,20,32]
    assert [len(x) for x in groups] == expected
    all_rows=[r for group in groups for r in group]
    for group in groups:
        assert len({signature(r) for r in group}) == len(group), f"non-distinct search space in {group[0]['experiment_id']}"
        add_difference_vectors(group)
    paths=["EXP1_BASIC_TASKS.csv","EXP2_COMMON_DESIRES_TASKS.csv","EXP3_HALIDE_TASKS.csv","EXP4_NASICON_32_TASKS.csv"]
    for name,rows in zip(paths,groups): write_csv(BENCH/name,rows,FIELDS)

    ablations=[]
    for tid in ("E1_04","E2_05","E3_02","E4_A2"):
        base=next(r for r in all_rows if r["task_id"]==tid)
        for condition in ("no_spp","universal_spp","broad_retrieval_spp","specialist_retrieval_spp","all_targets_out_specialist_spp","irrelevant_evidence_negative_control"):
            ablations.append({"ablation_id":f"{tid}__{condition}","task_id":tid,"structured_task_sha256":hashlib.sha256(dumps(signature(base)).encode()).hexdigest(),"condition":condition,"fixed_seed":1729,"breadth_counted":False})
    write_csv(BENCH/"RETRIEVAL_SPP_ABLATIONS.csv",ablations,list(ablations[0]))
    within=[{"within_task_id":"E3_19_TOP5","task_id":"E3_19","requested_k":5,"deduplication":"CIF SHA-256; StructureMatcher; symmetry-equivalent assignment","breadth_counted":False},{"within_task_id":"E4_H2_TOP5","task_id":"E4_H2","requested_k":5,"deduplication":"CIF SHA-256; StructureMatcher; symmetry-equivalent assignment","breadth_counted":False}]
    write_csv(BENCH/"WITHIN_TASK_DIVERSITY_TASKS.csv",within,list(within[0]))

    audit=[]; trace=[]; matrix=[]
    axis_keys=["target_formula","target_family","target_topology","allowed_space_groups","scaffold_hypotheses","lattice_candidate_policy","variable_species_orbits","site_ordering_requirement","vacancy_ordering_requirement","mixed_anion_ordering_requirement","supercell_requirement","requested_distinct_solutions"]
    for r in all_rows:
        represented=[]; missing=[]
        if r["qlip_representability_status"] in {"SUPPORTED_NOW","SUPPORTED_WITH_CONFIGURATION"}: represented=["registered fixed scaffold","formula/symmetry validation","single candidate generation"]
        else:
            missing=[x for x in ("scaffold/lattice registry","general mixed-orbit occupation","vacancy state","top-k no-good cuts","symmetry-equivalent rejection") if (r["experiment_id"]=="EXP4_NASICON" or "ordered" in r["site_ordering_requirement"] or int(r["requested_distinct_solutions"])>1)]
        audit.append({"task_id":r["task_id"],"request_sha256":hashlib.sha256(r["natural_language_request"].encode()).hexdigest(),"structured_task_sha256":hashlib.sha256(dumps(signature(r)).encode()).hexdigest(),"actionable_terms_encoded":True,"discarded_actionable_terms":"","representability_status":r["qlip_representability_status"]})
        trace.append({"task_id":r["task_id"],"natural_language_request":r["natural_language_request"],"structured_task":{k:r[k] for k in FIELDS if k not in {"natural_language_request","difference_vector"}},"represented_capabilities":represented,"missing_capabilities":missing,"execution_authorized":r["qlip_representability_status"] in {"SUPPORTED_NOW","SUPPORTED_WITH_CONFIGURATION"}})
    for group in groups:
        for a,b in combinations(group,2):
            delta=[key for key in axis_keys if a[key]!=b[key]]
            matrix.append({"experiment_id":a["experiment_id"],"task_a":a["task_id"],"task_b":b["task_id"],"differing_solver_axes":";".join(delta),"distinct":bool(delta)})
    assert all(x["distinct"] for x in matrix)
    write_csv(ART/"NATURAL_LANGUAGE_REQUEST_AUDIT.csv",audit,list(audit[0]))
    (ART/"REQUEST_TO_STRUCTURED_TASK_TRACE.jsonl").write_text("".join(dumps(x)+"\n" for x in trace),encoding="utf-8")
    write_csv(ART/"REQUEST_DISTINCTNESS_MATRIX.csv",matrix,list(matrix[0]))

    support={g[0]["experiment_id"]:sum(r["qlip_representability_status"] in {"SUPPORTED_NOW","SUPPORTED_WITH_CONFIGURATION"} for r in g) for g in groups}
    gate=(support["EXP1_BASIC"]==10 and support["EXP2_COMMON_DESIRES"]>=18 and support["EXP3_HALIDE"]>=18 and support["EXP4_NASICON"]>=28)
    report=["# Task representability report","",f"Generated at: {datetime.now(timezone.utc).isoformat()}","","## Breadth and gate","",f"- Breadth tasks: {len(all_rows)} (10/20/20/32).",f"- Supported now/configuration: EXP1 {support['EXP1_BASIC']}/10; EXP2 {support['EXP2_COMMON_DESIRES']}/20; EXP3 {support['EXP3_HALIDE']}/20; EXP4 {support['EXP4_NASICON']}/32.",f"- Full-campaign representability gate: **{'PASS' if gate else 'FAIL'}**.",f"- Pilot/full execution: **{'eligible' if gate else 'prohibited by benchmark rules'}**.","","## Observed implementation boundary","","The current registry supports fixed idealized prototypes for a limited set of formulas. Variable enumeration is formula-gated and limited to cubic perovskite, halide-perovskite, rocksalt/nitride and fluorite families. No NASICON candidate scaffold is registered. General vacancy occupation, mixed-anion supercells, multi-lattice selection, top-k no-good cuts and StructureMatcher-backed symmetry-equivalent rejection are not present in the generation path.","","## Generic extension plan","","1. Add evidence-backed scaffold records (coordinates, symmetry-closed orbits and provenance), beginning with reusable rhombohedral and monoclinic NASICON families.","2. Generalize orbit domains to species plus an explicit vacancy state with exact composition/charge constraints.","3. Add mixed-species closed-orbit allocation independent of formula-specific conditionals.","4. Add iterative top-k enumeration with no-good constraints and hash/StructureMatcher/symmetry-equivalence rejection.","5. Add multiple retrieved lattice/scaffold candidates and record exhaustion certificates.","","No composition-specific solver was added, and no unsupported task was executed."]
    (ART/"TASK_REPRESENTABILITY_REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    write_csv(FINAL/"FOUR_EXPERIMENT_TASK_MANIFEST.csv",all_rows,FIELDS)
    blocked=[{"task_id":r["task_id"],"experiment_id":r["experiment_id"],"status":"NOT_RUN_REPRESENTABILITY_GATE","representability_status":r["qlip_representability_status"],"generated_cif":"","verdict":"NOT_RUN"} for r in all_rows]
    write_csv(FINAL/"FOUR_EXPERIMENT_RESULTS.csv",blocked,list(blocked[0]))
    status_counts=Counter(r["qlip_representability_status"] for r in all_rows)
    aggregates=[{"metric":"breadth_task_count","value":82},{"metric":"distinct_structured_intents","value":82},{"metric":"pilot_launched","value":0},{"metric":"full_campaign_launched","value":0},*({"metric":f"representability_{k}","value":v} for k,v in sorted(status_counts.items()))]
    write_csv(FINAL/"FOUR_EXPERIMENT_AGGREGATES.csv",aggregates,["metric","value"])
    for name,group in zip(("EXP1_BASIC_RESULTS.csv","EXP2_COMMON_DESIRES_RESULTS.csv","EXP3_HALIDE_RESULTS.csv","EXP4_NASICON_32_RESULTS.csv"),groups):
        ids={r["task_id"] for r in group}; write_csv(FINAL/name,[r for r in blocked if r["task_id"] in ids],list(blocked[0]))
    print(dumps({"tasks":len(all_rows),"sizes":expected,"support":support,"gate_pass":gate,"benchmarks":str(BENCH),"artifacts":str(ART)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
