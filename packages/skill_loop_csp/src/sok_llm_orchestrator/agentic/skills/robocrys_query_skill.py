from __future__ import annotations

import re
from itertools import combinations_with_replacement
from typing import Any

SKILL_VERSION = "v1_rule_based"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = " ".join(str(item).split()).strip()
        key = value.lower()
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _dedupe_phrases(phrases: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for phrase in phrases:
        cleaned = " ".join(str(phrase).strip().split())
        if not cleaned:
            continue
        key = cleaned.lower().strip(" ;,.")
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _normalise_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def parse_formula_elements(formula: str | None) -> list[str]:
    if not formula:
        return []
    tokens = re.findall(r"[A-Z][a-z]?", formula)
    return _unique(tokens)


def pair_targets_for_formula(formula: str | None) -> list[str]:
    elements = sorted(parse_formula_elements(formula), key=lambda item: item.lower())
    return [f"{left}-{right}" for left, right in combinations_with_replacement(elements, 2)]


def _split_motifs(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = []
        for item in value:
            raw.extend(_split_motifs(str(item)))
        return _unique(raw)
    text = str(value)
    parts = re.split(r";|,|\band\b", text)
    return _unique([part.strip() for part in parts if part.strip()])


def _motif_terms(motifs: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    coordination: list[str] = []
    connectivity: list[str] = []
    dimensionality: list[str] = []
    prototype: list[str] = []
    for motif in motifs:
        lower = motif.lower()
        poly = re.search(r"\b([A-Z][a-z]?)([A-Z][a-z]?)(\d+)\b", motif)
        if "octahed" in lower:
            coordination.append(f"{poly.group(0)} octahedra" if poly else "octahedra")
        if "tetrahed" in lower:
            coordination.append(f"{poly.group(0)} tetrahedra" if poly else "tetrahedra")
        if "geometry" in lower or "coordination" in lower:
            coordination.append(motif)
        if "corner" in lower or "edge" in lower or "face" in lower or "sharing" in lower:
            if "corner" in lower:
                connectivity.append("corner-sharing")
            if "edge" in lower:
                connectivity.append("edge-sharing")
            if "face" in lower:
                connectivity.append("face-sharing")
        if "layer" in lower or "sheet" in lower or "2d" in lower or "two-dimensional" in lower:
            dimensionality.append(motif)
        if "framework" in lower or "channel" in lower or "cluster" in lower or "ribbon" in lower:
            dimensionality.append(motif)
        if any(key in lower for key in ["perovskite", "spinel", "olivine", "pyrite", "nasic", "chalcopyrite"]):
            prototype.append(motif)
    return _unique(coordination), _unique(connectivity), _unique(dimensionality), _unique(prototype)


def _family_template(family: str, formula: str, motifs: list[str]) -> dict[str, list[str]]:
    f = (family or "").strip().lower()
    terms: dict[str, list[str]] = {
        "prototype_terms": [],
        "coordination_terms": [],
        "connectivity_terms": [],
        "dimensionality_terms": [],
        "warnings": [],
    }
    add = terms
    if f == "oxide_perovskite":
        add["prototype_terms"] += ["perovskite structured"]
        add["coordination_terms"] += ["TiO6 octahedra" if formula == "BaTiO3" else "BO6 octahedra"]
        add["connectivity_terms"] += ["corner-sharing", "corner-sharing octahedral tilt angles"]
    elif f == "oxide_spinel":
        add["prototype_terms"] += ["spinel structured"]
        add["coordination_terms"] += ["MgO4 tetrahedra" if formula == "MgAl2O4" else "AO4 tetrahedra", "AlO6 octahedra" if formula == "MgAl2O4" else "BO6 octahedra", "tetrahedral geometry", "octahedral geometry"]
        add["connectivity_terms"] += ["corner-sharing", "edge-sharing"]
    elif f == "layered_oxide":
        add["prototype_terms"] += ["layered"]
        add["coordination_terms"] += ["CoO6 octahedra" if formula == "LiCoO2" else "MO6 octahedra"]
        add["connectivity_terms"] += ["edge-sharing"]
        add["dimensionality_terms"] += ["two-dimensional", "sheets", "Li interlayer", "Li layers"]
    elif f in {"halide_rocksalt", "chalcogenide_rocksalt", "oxide_rocksalt"}:
        add["prototype_terms"] += ["rocksalt structured"]
        add["coordination_terms"] += ["octahedral geometry"]
        add["connectivity_terms"] += ["bond lengths"]
    elif f == "halide_perovskite":
        add["prototype_terms"] += ["perovskite structured"]
        add["coordination_terms"] += ["BX6 octahedra", "cuboctahedral coordination"]
        add["connectivity_terms"] += ["corner-sharing", "octahedral tilt angles"]
    elif f in {"nitride", "nitride_framework"}:
        add["coordination_terms"] += ["bonded to N atoms", "tetrahedral geometry", "octahedral geometry"]
        if "framework" in f:
            add["dimensionality_terms"] += ["framework"]
    elif f in {"sulfide", "sulfide_halide", "sulfide_phosphate"}:
        add["coordination_terms"] += ["bonded to S atoms", "sulfide coordination"]
        add["connectivity_terms"] += ["bond lengths"]
    elif f == "sulfide_chalcopyrite":
        add["prototype_terms"] += ["chalcopyrite-like"]
        add["coordination_terms"] += ["tetrahedral geometry", "Cu-S bond lengths", "Fe-S bond lengths"]
    elif f == "layered_chalcogenide":
        add["prototype_terms"] += ["molybdenite structured" if formula == "MoS2" else "layered chalcogenide"]
        add["coordination_terms"] += ["trigonal coordination", "octahedral coordination"]
        add["connectivity_terms"] += ["edge-sharing"]
        add["dimensionality_terms"] += ["two-dimensional", f"{formula} sheets" if formula else "chalcogenide sheets"]
    elif f == "sulfide_pyrite":
        add["prototype_terms"] += ["pyrite structured"]
        add["coordination_terms"] += ["FeS6 octahedra", "S-S dimer", "S-S dumbbell"]
        add["connectivity_terms"] += ["bond lengths"]
    elif f in {"phosphate_silicate_framework", "phosphate_framework"}:
        add["prototype_terms"] += ["NASICON-like"] if "nasic" in " ".join(motifs).lower() or formula == "Na3Zr2Si2PO12" else []
        add["coordination_terms"] += ["ZrO6 octahedra" if "Zr" in formula else "MO6 octahedra", "SiO4 tetrahedra" if "Si" in formula else "XO4 tetrahedra", "PO4 tetrahedra"]
        add["dimensionality_terms"] += ["three-dimensional framework", "Na channels" if "Na" in formula else "ion channels"]
    elif f == "phosphate_olivine":
        add["prototype_terms"] += ["olivine"]
        add["coordination_terms"] += ["FeO6 octahedra" if "Fe" in formula else "MO6 octahedra", "PO4 tetrahedra"]
        add["dimensionality_terms"] += ["framework", "Li channels" if "Li" in formula else "ion channels"]
    elif f == "mixed_anion_phosphate":
        add["coordination_terms"] += ["PO4 tetrahedra", "mixed-anion coordination"]
        add["dimensionality_terms"] += ["framework"]
    elif f == "silicate":
        add["coordination_terms"] += ["SiO4 tetrahedra"]
        add["dimensionality_terms"] += ["silicate framework"]
    elif f in {"oxide_binary", "rare_earth_oxide"}:
        add["coordination_terms"] += ["bonded to O atoms", "oxide coordination", "bond lengths"]
    elif f in {"oxide_fluorite", "fluoride_fluorite"}:
        add["prototype_terms"] += ["fluorite structured"]
        add["coordination_terms"] += ["cubic coordination", "bonded to anions"]
    elif f == "oxide_garnet":
        add["prototype_terms"] += ["garnet structured"]
        add["coordination_terms"] += ["octahedra", "tetrahedra", "dodecahedral coordination"]
        add["dimensionality_terms"] += ["framework"]
    elif f == "oxide_pyrochlore":
        add["prototype_terms"] += ["pyrochlore structured"]
        add["coordination_terms"] += ["BO6 octahedra", "A-site coordination"]
        add["connectivity_terms"] += ["corner-sharing"]
    elif f == "carbonate":
        add["coordination_terms"] += ["CO3 carbonate groups", "bond lengths"]
    elif f == "boride":
        add["coordination_terms"] += ["bonded to B atoms", "boride framework"]
    elif f == "carbide":
        add["coordination_terms"] += ["bonded to C atoms", "carbide coordination"]
    elif f in {"fluoride_framework", "fluoride", "halide"}:
        add["coordination_terms"] += ["bonded to F atoms" if "fluoride" in f else "bonded to halide atoms", "polyhedral coordination"]
        if "framework" in f:
            add["dimensionality_terms"] += ["framework"]
    elif f == "oxide_wurtzite":
        add["prototype_terms"] += ["wurtzite structured"]
        add["coordination_terms"] += ["tetrahedral geometry"]
    elif f == "oxide_bixbyite":
        add["prototype_terms"] += ["bixbyite structured"]
        add["coordination_terms"] += ["oxide coordination", "distorted octahedra"]
    else:
        add["warnings"].append(f"unknown_chemistry_family:{family or 'missing'}")
    return {key: _unique(value) for key, value in terms.items()}


POLYHEDRON_RE = re.compile(r"\b([A-Z][a-z]?)([A-Z][a-z]?)(\d+)\b")


def _coordination_requirement(term: str) -> dict[str, Any] | None:
    match = POLYHEDRON_RE.search(term)
    if not match:
        return None
    center, ligand, count = match.groups()
    poly = f"{center}{ligand}{count}"
    label = term.strip()
    aliases = _unique(
        [
            label,
            poly,
            f"{center}-{ligand} {count}-coordinate",
            f"{center} bonded to {count} {ligand} atoms",
            f"{center} is bonded to {count} {ligand} atoms",
            f"{center} is bonded to {count.lower() if hasattr(count, 'lower') else count} {ligand} atoms",
        ]
    )
    return {
        "id": f"coordination.{_normalise_key(poly)}",
        "category": "coordination",
        "label": label,
        "aliases": aliases,
        "implicit_condensed_rule": {
            "center_element": center,
            "ligand_element": ligand,
            "coordination_number": int(count),
            "rule": "center element has required ligand nearest-neighbour count in condensed Robocrys JSON",
        },
        "center_element": center,
        "ligand_element": ligand,
        "coordination_number": int(count),
        "strictness": "required",
    }


def _term_requirement(term: str, category: str) -> dict[str, Any]:
    label = term.strip()
    aliases = [label]
    lower = label.lower()
    if "corner" in lower:
        aliases.extend(["corner-sharing", "share corners", "shares corners"])
    if "edge" in lower:
        aliases.extend(["edge-sharing", "share edges", "shares edges"])
    if "face" in lower:
        aliases.extend(["face-sharing", "share faces", "shares faces"])
    if "two-dimensional" in lower:
        aliases.extend(["two-dimensional", "2-dimensional", "2D", "sheets"])
    if "three-dimensional" in lower:
        aliases.extend(["three-dimensional", "3-dimensional", "3D", "framework"])
    if "dumbbell" in lower or "dimer" in lower:
        aliases.extend(["dumbbell", "dumbbells", "dimer", "dimers"])
    return {
        "id": f"{category}.{_normalise_key(label)}",
        "category": category,
        "label": label,
        "aliases": _unique(aliases),
        "strictness": "required" if category in {"coordination", "connectivity", "prototype"} else "supporting",
    }


def _build_validator_requirements(
    prototype_terms: list[str],
    coordination_terms: list[str],
    connectivity_terms: list[str],
    dimensionality_terms: list[str],
    motifs: list[str],
) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for term in prototype_terms:
        requirements.append(_term_requirement(term, "prototype"))
    for term in coordination_terms:
        requirements.append(_coordination_requirement(term) or _term_requirement(term, "coordination"))
    for term in connectivity_terms:
        requirements.append(_term_requirement(term, "connectivity"))
    for term in dimensionality_terms:
        requirements.append(_term_requirement(term, "dimensionality"))
    for motif in motifs:
        lower = motif.lower()
        req = _coordination_requirement(motif)
        if req:
            requirements.append(req)
        if "corner" in lower:
            requirements.append(_term_requirement("corner-sharing", "connectivity"))
        if "edge" in lower:
            requirements.append(_term_requirement("edge-sharing", "connectivity"))
        if "face" in lower:
            requirements.append(_term_requirement("face-sharing", "connectivity"))
        if "channel" in lower:
            requirements.append(_term_requirement("channels", "dimensionality"))
        if "framework" in lower:
            requirements.append(_term_requirement("framework", "dimensionality"))
        if "sheet" in lower or "layer" in lower:
            requirements.append(_term_requirement("layered sheets", "dimensionality"))
        if not req and not any(key in lower for key in ["corner", "edge", "face", "sharing", "dumbbell", "dimer", "channel", "framework", "sheet", "layer"]):
            continue
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for requirement in requirements:
        key = requirement["id"]
        if key not in seen:
            deduped.append(requirement)
            seen.add(key)
    return deduped


def _retrieval_keywords(
    *,
    formula: str,
    chemistry_family: str | None,
    material: list[str],
    pair_targets: list[str],
    prototype_terms: list[str],
    coordination_terms: list[str],
    connectivity_terms: list[str],
    dimensionality_terms: list[str],
    motifs: list[str],
) -> list[str]:
    family = (chemistry_family or "").lower()
    terms: list[str] = [formula]
    if family == "oxide_perovskite":
        terms.extend(["titanate" if "Ti" in material else "oxide", "oxide", "perovskite"])
        terms.extend([pair for pair in pair_targets if "-O" in pair or "O-" in pair])
        terms.extend(["TiO6 octahedra" if "Ti" in material else "BO6 octahedra", "corner-sharing octahedra", "perovskite topology"])
        if formula == "BaTiO3":
            terms.append("A-site Ba")
    elif family == "oxide_spinel":
        terms.extend(["oxide", "spinel", "spinel ferrite" if "Fe" in material else "spinel topology"])
        terms.extend([pair for pair in pair_targets if "-O" in pair or "O-" in pair])
        terms.extend(["tetrahedra", "octahedra", "corner-sharing", "edge-sharing"])
    else:
        terms.extend(str(chemistry_family or "").replace("_", " ").split())
        terms.extend(material)
        terms.extend(pair_targets)
    terms.extend(prototype_terms)
    terms.extend(coordination_terms)
    terms.extend(connectivity_terms)
    terms.extend(dimensionality_terms)
    terms.extend(motifs)
    return _dedupe_phrases(terms)


def build_robocrys_style_crystal_db_query(
    original_query: str,
    target_formula: str | None = None,
    chemistry_family: str | None = None,
    challenge_type: str | None = None,
    expected_motifs_or_priors: str | list[str] | None = None,
    material_system: list[str] | None = None,
) -> dict[str, Any]:
    formula = (target_formula or "").strip()
    motifs = _dedupe_phrases(_split_motifs(expected_motifs_or_priors))
    material = _unique(material_system or parse_formula_elements(formula))
    family_terms = _family_template(chemistry_family or "", formula, motifs)
    motif_coord, motif_conn, motif_dim, motif_proto = _motif_terms(motifs)
    coordination_terms = _unique(family_terms["coordination_terms"] + motif_coord)
    connectivity_terms = _unique(family_terms["connectivity_terms"] + motif_conn)
    dimensionality_terms = _unique(family_terms["dimensionality_terms"] + motif_dim)
    prototype_terms = _unique(family_terms["prototype_terms"] + motif_proto)
    warnings = list(family_terms["warnings"])
    if not formula:
        warnings.append("target_formula_missing")

    pair_targets = pair_targets_for_formula(formula)
    retrieval_terms = _retrieval_keywords(
        formula=formula,
        chemistry_family=chemistry_family,
        material=material,
        pair_targets=pair_targets,
        prototype_terms=prototype_terms,
        coordination_terms=coordination_terms,
        connectivity_terms=connectivity_terms,
        dimensionality_terms=dimensionality_terms,
        motifs=motifs,
    )
    full_query = " ".join(retrieval_terms).strip() or original_query
    compact_terms = _dedupe_phrases([formula, *prototype_terms, *coordination_terms, *connectivity_terms, *dimensionality_terms])
    pair_query = " ".join(_dedupe_phrases([formula, *material, *pair_targets, *coordination_terms[:6], *motifs[:6]]))
    validator_requirements = _build_validator_requirements(
        prototype_terms,
        coordination_terms,
        connectivity_terms,
        dimensionality_terms,
        motifs,
    )

    return {
        "original_query": original_query,
        "crystal_db_retrieval_query": full_query,
        "compact_retrieval_query": " ".join(compact_terms).strip() or original_query,
        "pair_evidence_query": pair_query.strip() or original_query,
        "query_style": "robocrys_descriptive",
        "skill_version": SKILL_VERSION,
        "terms_added": _dedupe_phrases([*prototype_terms, *coordination_terms, *connectivity_terms, *dimensionality_terms]),
        "coordination_terms": coordination_terms,
        "connectivity_terms": connectivity_terms,
        "dimensionality_terms": dimensionality_terms,
        "prototype_terms": prototype_terms,
        "motif_terms_from_input": motifs,
        "material_system": material,
        "pair_evidence_targets": pair_targets,
        "validator_requirements": validator_requirements,
        "requirement_aliases": {item["id"]: item.get("aliases", []) for item in validator_requirements},
        "explicit_text_aliases": {item["id"]: item.get("aliases", []) for item in validator_requirements},
        "implicit_condensed_rules": {
            item["id"]: item.get("implicit_condensed_rule")
            for item in validator_requirements
            if item.get("implicit_condensed_rule")
        },
        "requirement_source": "chemistry_family_and_expected_motifs_or_priors",
        "warnings": warnings,
        "challenge_type": challenge_type or "",
    }


__all__ = [
    "SKILL_VERSION",
    "build_robocrys_style_crystal_db_query",
    "pair_targets_for_formula",
    "parse_formula_elements",
]
