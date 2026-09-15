from __future__ import annotations

import json
import re
from collections import Counter
from statistics import median
from typing import Any, Mapping

VALIDATOR_VERSION = "v1_robocrys_text_overlap"
LLM_VALIDATOR_VERSION = "v1_llm_robocrys_intent_judge"
LLM_REQUIRED_FIELDS = [
    "score",
    "correct",
    "judgement",
    "explicit_text_matches",
    "alias_text_matches",
    "implicit_condensed_matches",
    "matched_requirements",
    "missing_requirements",
    "contradictions",
    "concerns",
    "explanation",
    "not_physical_validation_notice",
]
WEIGHTS = {
    "family_match": 0.10,
    "coordination_match": 0.30,
    "connectivity_match": 0.25,
    "dimensionality_match": 0.20,
    "motif_match": 0.15,
}
SPECIFICITY_THRESHOLDS = {
    "loose": {"aligned": 0.45, "partial": 0.25},
    "medium": {"aligned": 0.65, "partial": 0.40},
    "specific": {"aligned": 0.75, "partial": 0.50},
}
REQUIREMENT_TYPE_WEIGHTS = {
    "core_structural": 1.0,
    "supporting_label": 0.35,
    "formula_only": 0.0,
    "diagnostic": 0.5,
}
EVIDENCE_STRENGTH_SCORES = {
    "explicit": 1.0,
    "alias": 0.9,
    "implicit": 0.8,
    "none": 0.0,
}

FAMILY_TERMS = [
    "perovskite",
    "spinel",
    "rocksalt",
    "wurtzite",
    "sphalerite",
    "rutile",
    "fluorite",
    "pyrochlore",
    "garnet",
    "olivine",
    "nasicon",
    "pyrite",
    "chalcopyrite",
    "molybdenite",
    "layered",
    "framework",
]

COORDINATION_TERMS = [
    "octahedra",
    "octahedral",
    "tetrahedra",
    "tetrahedral",
    "trigonal planar",
    "trigonal prismatic",
    "cuboctahedra",
    "square planar",
    "bo6",
    "tio6",
    "feo6",
    "coo6",
    "zro6",
    "alo6",
    "po4",
    "sio4",
    "mgo4",
    "fes6",
    "pbi6",
]

CONNECTIVITY_TERMS = [
    "corner-sharing",
    "edge-sharing",
    "face-sharing",
    "sheets",
    "layers",
    "channels",
    "framework",
    "clusters",
    "ribbons",
    "dumbbells",
    "dimer",
    "dimers",
]

DIMENSIONALITY_TERMS = [
    "two-dimensional",
    "three-dimensional",
    "one-dimensional",
    "layered",
    "sheets",
    "framework",
    "channels",
]

BOND_PATTERN = re.compile(r"\b[A-Z][a-z]?-[A-Z][a-z]?\s+bond\s+(?:lengths|distances)\b", re.IGNORECASE)
POLYHEDRA_PATTERN = re.compile(r"\b[A-Z][a-z]?(?:[A-Z][a-z]?)?\d+(?:\b|[^a-z])")
POLYHEDRON_TOKEN_PATTERN = re.compile(r"\b([A-Z][a-z]?)([A-Z][a-z]?)(\d+)\b")
NUMBER_WORDS = {
    4: "four",
    5: "five",
    6: "six",
    8: "eight",
    12: "twelve",
}
LIGAND_WORDS = {
    "oxide": "O",
    "oxygen": "O",
    "nitride": "N",
    "nitrogen": "N",
    "sulfide": "S",
    "sulfur": "S",
    "sulphide": "S",
    "sulphur": "S",
    "iodide": "I",
    "bromide": "Br",
    "chloride": "Cl",
    "fluoride": "F",
    "halide": "",
}
COMMON_LIGAND_ELEMENTS = {"O", "N", "S", "F", "Cl", "Br", "I"}
CORPUS_AUDIT_SUMMARY = (
    "In the Crystal-DB Robocrys corpus, exact polyhedral formula strings such as TiO6, MgO4, and AlO6 "
    "are comparatively rare compared with phrases like bonded in 6-coordinate geometry, bonded to atoms, "
    "bond lengths, octahedra/tetrahedra, and corner-sharing/edge-sharing language."
)


def _normalise(text: str | None) -> str:
    return " ".join(str(text or "").lower().replace("_", "-").split())


def _split_motifs(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw: list[str] = []
        for item in value:
            raw.extend(_split_motifs(str(item)))
        return _unique(raw)
    return _unique([part.strip() for part in re.split(r";|,|\band\b", str(value)) if part.strip()])


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = " ".join(str(value).split()).strip()
        key = item.lower()
        if item and key not in seen:
            result.append(item)
            seen.add(key)
    return result


def _contains_term(text: str, term: str) -> bool:
    term_norm = _normalise(term)
    if not term_norm:
        return False
    return term_norm in text


def _extract_known_terms(text: str, vocabulary: list[str]) -> list[str]:
    norm = _normalise(text)
    return [term for term in vocabulary if _contains_term(norm, term)]


def _extract_polyhedra_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in POLYHEDRA_PATTERN.finditer(str(text or "")):
        term = match.group(0).strip(" ,.;:()[]{}").upper()
        if any(ch.isdigit() for ch in term) and len(term) <= 8:
            terms.append(term)
    return _unique(terms)


def _extract_bond_terms(text: str) -> list[str]:
    return _unique([match.group(0) for match in BOND_PATTERN.finditer(str(text or ""))])


def _query_terms(
    original_query: str,
    crystal_db_retrieval_query: str,
    expected_motifs_or_priors: str | list[str] | None,
) -> dict[str, list[str]]:
    combined = " ".join([original_query or "", crystal_db_retrieval_query or "", " ".join(_split_motifs(expected_motifs_or_priors))])
    motifs = _split_motifs(expected_motifs_or_priors)
    coordination = _unique(_extract_known_terms(combined, COORDINATION_TERMS) + _extract_polyhedra_terms(combined))
    connectivity = _extract_known_terms(combined, CONNECTIVITY_TERMS)
    dimensionality = _extract_known_terms(combined, DIMENSIONALITY_TERMS)
    family = _extract_known_terms(combined, FAMILY_TERMS)
    motif_terms = _unique(
        [
            *_extract_known_terms(" ".join(motifs), FAMILY_TERMS + COORDINATION_TERMS + CONNECTIVITY_TERMS + DIMENSIONALITY_TERMS),
            *_extract_polyhedra_terms(" ".join(motifs)),
            *_extract_bond_terms(" ".join(motifs)),
        ]
    )
    return {
        "family_terms": family,
        "coordination_terms": coordination,
        "connectivity_terms": connectivity,
        "dimensionality_terms": dimensionality,
        "motif_terms": motif_terms,
    }


def _description_terms(description: str) -> dict[str, list[str]]:
    return {
        "family_terms": _extract_known_terms(description, FAMILY_TERMS),
        "coordination_terms": _unique(_extract_known_terms(description, COORDINATION_TERMS) + _extract_polyhedra_terms(description)),
        "connectivity_terms": _extract_known_terms(description, CONNECTIVITY_TERMS),
        "dimensionality_terms": _extract_known_terms(description, DIMENSIONALITY_TERMS),
        "motif_terms": _unique(
            _extract_known_terms(description, FAMILY_TERMS + COORDINATION_TERMS + CONNECTIVITY_TERMS + DIMENSIONALITY_TERMS)
            + _extract_polyhedra_terms(description)
            + _extract_bond_terms(description)
        ),
    }


def extract_robocrys_vocabulary_features(text: str) -> dict[str, Any]:
    description = str(text or "")
    return {
        "family_terms": _extract_known_terms(description, FAMILY_TERMS),
        "coordination_terms": _unique(_extract_known_terms(description, COORDINATION_TERMS) + _extract_polyhedra_terms(description)),
        "connectivity_terms": _extract_known_terms(description, CONNECTIVITY_TERMS),
        "dimensionality_terms": _extract_known_terms(description, DIMENSIONALITY_TERMS),
        "bond_terms": _extract_bond_terms(description),
        "polyhedra_terms": _extract_polyhedra_terms(description),
        "has_bond_length_language": bool(re.search(r"\bbond length|\bbond distance|distances ranging from", description, re.IGNORECASE)),
        "has_space_group_language": "space group" in _normalise(description),
    }


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _condensed_sites(condensed_structure: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not isinstance(condensed_structure, Mapping):
        return {}
    sites = condensed_structure.get("sites")
    if not isinstance(sites, Mapping):
        return {}
    return {str(key): value for key, value in sites.items() if isinstance(value, Mapping)}


def _site_element(site: Mapping[str, Any]) -> str:
    return str(site.get("element") or site.get("species") or site.get("specie") or "")


def _coordination_from_condensed(
    condensed_structure: Mapping[str, Any] | None,
    *,
    center_element: str,
    ligand_element: str,
    coordination_number: int,
) -> tuple[bool, list[str]]:
    sites = _condensed_sites(condensed_structure)
    if not sites:
        return False, []
    evidence: list[str] = []
    for site_id, site in sites.items():
        if _site_element(site).lower() != center_element.lower():
            continue
        nn = site.get("nn")
        if not isinstance(nn, list):
            continue
        ligand_count = 0
        for neighbor in nn:
            neighbor_site = sites.get(str(neighbor))
            if neighbor_site and _site_element(neighbor_site).lower() == ligand_element.lower():
                ligand_count += 1
        geom = site.get("geometry") if isinstance(site.get("geometry"), Mapping) else {}
        geom_text = str(geom.get("type") or "")
        if ligand_count >= coordination_number:
            evidence.append(
                f"condensed site {site_id}: {center_element} has {ligand_count} {ligand_element} nearest neighbours"
            )
            return True, evidence
        if str(coordination_number) in geom_text and ligand_count:
            evidence.append(
                f"condensed site {site_id}: {center_element} geometry={geom_text}, {ligand_count} {ligand_element} neighbours"
            )
            return True, evidence
    return False, evidence


def _connectivity_from_condensed(condensed_structure: Mapping[str, Any] | None, label: str) -> tuple[bool, list[str]]:
    if not isinstance(condensed_structure, Mapping):
        return False, []
    text = _normalise(_json_text(condensed_structure))
    checks = {
        "corner": ["corner"],
        "edge": ["edge"],
        "face": ["face"],
        "sheet": ["dimensionality\": \"2", "dimensionality': '2", "two-dimensional"],
        "layer": ["dimensionality\": \"2", "dimensionality': '2", "two-dimensional"],
        "framework": ["dimensionality\": \"3", "dimensionality': '3", "three-dimensional"],
        "channel": ["channel"],
        "dimer": ["dimer", "dumbbell"],
        "dumbbell": ["dimer", "dumbbell"],
    }
    lower = label.lower()
    needles: list[str] = []
    for key, values in checks.items():
        if key in lower:
            needles.extend(values)
    if not needles:
        return False, []
    for needle in needles:
        if _normalise(needle) in text:
            return True, [f"condensed structure contains {needle!r} evidence for {label!r}"]
    return False, []


def _extract_expected_ligand_elements(requirement_text: str) -> set[str]:
    text = str(requirement_text or "")
    ligands: set[str] = set()
    for match in POLYHEDRON_TOKEN_PATTERN.finditer(text):
        _center, ligand, _count = match.groups()
        ligands.add(ligand)
    for match in re.finditer(r"\bbonded\s+to\s+(?:\w+\s+)?([A-Z][a-z]?)\s+atoms?\b", text):
        ligands.add(match.group(1))
    for match in re.finditer(r"\b([A-Z][a-z]?)\s+coordination\b", text):
        ligands.add(match.group(1))
    lowered = _normalise(text)
    for word, element in LIGAND_WORDS.items():
        if element and word in lowered:
            ligands.add(element)
    return ligands


def _observed_coordination_environments(description: str, coordination_number: int) -> list[tuple[str, set[str]]]:
    environments: list[tuple[str, set[str]]] = []
    coord_pattern = rf"(?:{coordination_number}[- ]coordinate|{NUMBER_WORDS.get(coordination_number, coordination_number)}[- ]coordinate)"
    for sentence in re.split(r"(?<=[.;])\s+", str(description or "")):
        if not re.search(coord_pattern, sentence, re.IGNORECASE):
            continue
        center_match = re.search(r"\b([A-Z][a-z]?)(?:\(\d+\))?\s+is\s+bonded\b", sentence)
        center = center_match.group(1) if center_match else ""
        observed: set[str] = set()
        tail = sentence.split(" to ", 1)[-1] if " to " in sentence else sentence
        for match in re.finditer(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)?\s*(?:equivalent\s+)?([A-Z][a-z]?)\s+atoms?\b", tail):
            observed.add(match.group(1))
        for match in re.finditer(r"\b([A-Z][a-z]?)-[A-Z][a-z]?\s+bond", sentence):
            observed.add(match.group(1))
        environments.append((center, observed))
    return environments


def _observed_ligand_elements_for_coordination(description: str, coordination_number: int) -> set[str]:
    observed: set[str] = set()
    for _center, ligands in _observed_coordination_environments(description, coordination_number):
        observed.update(ligands)
    return observed


def _neighbour_elements_match(expected: set[str], observed: set[str]) -> bool:
    if not expected:
        return True
    return bool(expected & observed)


def _has_generic_cation_centered_coordination(description: str, coordination_number: int) -> bool:
    for center, _ligands in _observed_coordination_environments(description, coordination_number):
        if not center or center not in COMMON_LIGAND_ELEMENTS:
            return True
    return False


def _requirement_from_term(term: str, category: str = "motif") -> dict[str, Any]:
    label = str(term).strip()
    aliases = [label]
    poly = POLYHEDRON_TOKEN_PATTERN.search(label)
    requirement_type, penalty_weight = _requirement_type_and_penalty(label, category)
    payload: dict[str, Any] = {
        "id": f"{category}.{_normalise(label)}",
        "category": category,
        "label": label,
        "aliases": aliases,
        "strictness": "required",
        "requirement_type": requirement_type,
        "penalty_weight": penalty_weight,
    }
    if poly:
        center, ligand, count = poly.groups()
        payload.update(
            {
                "id": f"coordination.{center.lower()}{ligand.lower()}{count}",
                "category": "coordination",
                "center_element": center,
                "ligand_element": ligand,
                "coordination_number": int(count),
                "aliases": _unique([label, f"{center}{ligand}{count}", f"{center} bonded to {count} {ligand} atoms"]),
                "requirement_type": "core_structural",
                "penalty_weight": "high",
            }
        )
    return payload


def _requirement_type_and_penalty(label: str, category: str) -> tuple[str, str]:
    lowered = str(label or "").lower()
    category = str(category or "").lower()
    family_label_terms = [
        "perovskite",
        "spinel",
        "rocksalt",
        "wurtzite",
        "sphalerite",
        "rutile",
        "fluorite",
        "pyrochlore",
        "garnet",
        "olivine",
        "nasicon",
        "pyrite",
        "chalcopyrite",
        "molybdenite",
    ]
    if category == "formula":
        return "formula_only", "low"
    if category == "prototype" or any(term in lowered for term in family_label_terms):
        return "supporting_label", "low"
    if any(term in lowered for term in ["bond length", "bond distance", "space group"]):
        return "diagnostic", "medium"
    if category in {"coordination", "connectivity", "dimensionality"}:
        return "core_structural", "high"
    if any(term in lowered for term in ["octa", "tetra", "coordinate", "corner", "edge", "face", "sharing", "layer", "sheet", "channel", "framework"]):
        return "core_structural", "high"
    return "diagnostic", "medium"


def _evidence_strength(evidence_level: str) -> str:
    if evidence_level == "explicit_text_match":
        return "explicit"
    if evidence_level == "alias_text_match":
        return "alias"
    if evidence_level == "implicit_condensed_match":
        return "implicit"
    return "none"


def _infer_requirement_category(term: str) -> str:
    lowered = str(term or "").lower()
    if any(x in lowered for x in ["corner", "edge", "face", "sharing", "framework", "layer", "sheet", "channel"]):
        return "connectivity"
    if any(x in lowered for x in ["octa", "tetra", "coordinate", "coordination", "tio6", "alo6", "mgo4", "po4", "sio4"]):
        return "coordination"
    if any(x in lowered for x in ["perovskite", "spinel", "rocksalt", "rutile", "fluorite", "garnet", "pyrochlore", "olivine"]):
        return "prototype"
    if any(x in lowered for x in ["two-dimensional", "three-dimensional", "one-dimensional", "dimensional"]):
        return "dimensionality"
    return "motif"


def decompose_requirement_phrase(phrase: str) -> list[dict[str, Any]]:
    text = str(phrase or "").strip()
    if not text:
        return []
    requirements: list[dict[str, Any]] = []
    poly = POLYHEDRON_TOKEN_PATTERN.search(text)
    if poly:
        requirements.append(_requirement_from_term(poly.group(0), "coordination"))
    lower = text.lower()
    if "corner" in lower:
        requirements.append(_requirement_from_term("corner-sharing", "connectivity"))
    if "edge" in lower:
        requirements.append(_requirement_from_term("edge-sharing", "connectivity"))
    if "face" in lower:
        requirements.append(_requirement_from_term("face-sharing", "connectivity"))
    if "perovskite" in lower:
        requirements.append(_requirement_from_term("perovskite topology", "prototype"))
    if "layer" in lower or "sheet" in lower:
        requirements.append(_requirement_from_term("layered sheets", "dimensionality"))
    if "channel" in lower:
        requirements.append(_requirement_from_term("channels", "dimensionality"))
    if not requirements:
        requirements.append(_requirement_from_term(text, _infer_requirement_category(text)))
    return requirements


def _requirements_from_expected_terms(expected: Mapping[str, list[str]]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for key, category in [
        ("family_terms", "prototype"),
        ("coordination_terms", "coordination"),
        ("connectivity_terms", "connectivity"),
        ("dimensionality_terms", "dimensionality"),
        ("motif_terms", "motif"),
    ]:
        for term in expected.get(key, []):
            requirements.extend(decompose_requirement_phrase(term) if category == "motif" else [_requirement_from_term(term, category)])
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in requirements:
        key = str(item.get("id") or item.get("label"))
        if key and key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def evaluate_validator_requirements(
    requirements: list[Mapping[str, Any]],
    description: str,
    condensed_structure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    desc_norm = _normalise(description)
    evidence_rows: list[dict[str, Any]] = []
    explicit = 0
    alias = 0
    implicit = 0
    missing = 0
    matched_labels: list[str] = []
    missing_labels: list[str] = []
    weighted_numerator = 0.0
    weighted_denominator = 0.0
    core_numerator = 0.0
    core_denominator = 0.0
    supporting_numerator = 0.0
    supporting_denominator = 0.0
    for requirement in requirements:
        label = str(requirement.get("label") or requirement.get("id") or "")
        requirement_type = str(requirement.get("requirement_type") or "")
        if not requirement_type:
            requirement_type, _ = _requirement_type_and_penalty(label, str(requirement.get("category") or ""))
        penalty_weight = str(requirement.get("penalty_weight") or _requirement_type_and_penalty(label, str(requirement.get("category") or ""))[1])
        aliases = _unique([label, *[str(item) for item in requirement.get("aliases", []) if str(item).strip()]])
        exact_match = bool(label and _contains_term(desc_norm, label))
        matched_aliases = [] if exact_match else _alias_matches(requirement, description, aliases)
        implicit_evidence: list[str] = []
        evidence_level = "missing"
        if exact_match:
            evidence_level = "explicit_text_match"
            explicit += 1
            matched_labels.append(label)
        elif matched_aliases:
            evidence_level = "alias_text_match"
            alias += 1
            matched_labels.append(label)
        else:
            center = str(requirement.get("center_element") or "")
            ligand = str(requirement.get("ligand_element") or "")
            coord = requirement.get("coordination_number")
            if center and ligand and isinstance(coord, int):
                ok, implicit_evidence = _coordination_from_condensed(
                    condensed_structure,
                    center_element=center,
                    ligand_element=ligand,
                    coordination_number=coord,
                )
            else:
                ok, implicit_evidence = _connectivity_from_condensed(condensed_structure, label)
            if ok:
                evidence_level = "implicit_condensed_match"
                implicit += 1
                matched_labels.append(label)
        if evidence_level == "missing":
            missing += 1
            missing_labels.append(label)
        evidence_strength = _evidence_strength(evidence_level)
        requirement_weight = REQUIREMENT_TYPE_WEIGHTS.get(requirement_type, 0.5)
        evidence_score = EVIDENCE_STRENGTH_SCORES[evidence_strength]
        weighted_numerator += requirement_weight * evidence_score
        weighted_denominator += requirement_weight
        if requirement_type == "core_structural":
            core_numerator += evidence_score
            core_denominator += 1.0
        elif requirement_type == "supporting_label":
            supporting_numerator += evidence_score
            supporting_denominator += 1.0
        evidence_rows.append(
            {
                "id": requirement.get("id", ""),
                "label": label,
                "category": requirement.get("category", ""),
                "requirement_type": requirement_type,
                "penalty_weight": penalty_weight,
                "evidence_level": evidence_level,
                "evidence_strength": evidence_strength,
                "matched_aliases": [label] if exact_match else matched_aliases,
                "implicit_evidence": implicit_evidence,
            }
        )
    total = len(evidence_rows)
    core_score = core_numerator / core_denominator if core_denominator else 0.0
    supporting_score = supporting_numerator / supporting_denominator if supporting_denominator else 0.0
    weighted_score = weighted_numerator / weighted_denominator if weighted_denominator else 0.0
    return {
        "requirements": evidence_rows,
        "total_count": total,
        "explicit_text_match_count": explicit,
        "alias_text_match_count": alias,
        "implicit_condensed_match_count": implicit,
        "missing_count": missing,
        "core_structural_count": int(core_denominator),
        "core_structural_score": round(core_score, 3),
        "supporting_label_count": int(supporting_denominator),
        "supporting_label_score": round(supporting_score, 3),
        "weighted_requirement_match_score": round(weighted_score, 3),
        "matched_requirement_labels": matched_labels,
        "missing_requirement_labels": missing_labels,
        "requirement_match_score": round((explicit + alias + implicit) / total, 3) if total else 0.0,
    }


def _alias_matches(requirement: Mapping[str, Any], description: str, aliases: list[str]) -> list[str]:
    desc_norm = _normalise(description)
    matches = [alias for alias in aliases if alias != requirement.get("label") and _contains_term(desc_norm, alias)]
    label_norm = _normalise(str(requirement.get("label") or ""))
    expected_ligands = _extract_expected_ligand_elements(" ".join([str(requirement.get("label") or ""), *[str(alias) for alias in aliases]]))
    if requirement.get("ligand_element"):
        expected_ligands.add(str(requirement["ligand_element"]))
    observed_four_ligands = _observed_ligand_elements_for_coordination(description, 4)
    observed_six_ligands = _observed_ligand_elements_for_coordination(description, 6)
    if any(term in label_norm for term in ["tetrahedral", "tetrahedra"]) and re.search(
        r"\bbonded\s+in\s+a\s+[^.]*4[- ]coordinate\s+geometry\b|\b4[- ]coordinate\s+geometry\b",
        description,
        re.IGNORECASE,
    ) and _neighbour_elements_match(expected_ligands, observed_four_ligands) and (expected_ligands or _has_generic_cation_centered_coordination(description, 4)):
        matches.append("4-coordinate geometry")
    if any(term in label_norm for term in ["octahedral", "octahedra"]) and re.search(
        r"\bbonded\s+in\s+a\s+[^.]*6[- ]coordinate\s+geometry\b|\b6[- ]coordinate\s+geometry\b",
        description,
        re.IGNORECASE,
    ) and _neighbour_elements_match(expected_ligands, observed_six_ligands) and (expected_ligands or _has_generic_cation_centered_coordination(description, 6)):
        matches.append("6-coordinate geometry")
    center = str(requirement.get("center_element") or "")
    ligand = str(requirement.get("ligand_element") or "")
    coord = requirement.get("coordination_number")
    if center and ligand and isinstance(coord, int):
        coord_word = NUMBER_WORDS.get(coord, str(coord))
        patterns = [
            rf"\b{re.escape(center)}(?:\(\d+\))?\s+is\s+bonded\s+in\s+a\s+[^.]*{coord}[- ]coordinate\s+geometry\s+to\s+[^.]*\b{re.escape(ligand)}",
            rf"\b{re.escape(center)}(?:\(\d+\))?\s+is\s+bonded\s+to\s+{coord_word}\s+(?:equivalent\s+)?{re.escape(ligand)}",
            rf"\b{re.escape(center)}(?:\(\d+\))?[- ]{re.escape(ligand)}(?:\(\d+\))?\s+bond length",
            rf"\b{re.escape(center)}(?:\(\d+\))?[- ]{re.escape(ligand)}(?:\(\d+\))?\s+bond distances",
        ]
        for pattern in patterns:
            if re.search(pattern, description, re.IGNORECASE):
                matches.append(pattern)
    if not matches:
        for alias in aliases:
            if _contains_term(desc_norm, alias):
                matches.append(alias)
    return _unique(matches)


def _score_terms(expected: list[str], observed: list[str]) -> tuple[float, list[str], list[str]]:
    if not expected:
        return 1.0, [], []
    observed_norm = {_normalise(term) for term in observed}
    matched = [term for term in expected if _normalise(term) in observed_norm]
    missing = [term for term in expected if _normalise(term) not in observed_norm]
    return len(matched) / len(expected), matched, missing


def _formula_score(target_formula: str | None, description: str) -> tuple[float, list[str]]:
    formula = str(target_formula or "").strip()
    if not formula:
        return 0.0, []
    compact_description = re.sub(r"\s+", "", str(description or "")).lower()
    compact_formula = re.sub(r"\s+", "", formula).lower()
    if compact_formula and compact_formula in compact_description:
        return 1.0, [formula]
    elements = re.findall(r"[A-Z][a-z]?", formula)
    if not elements:
        return 0.0, []
    observed = [element for element in elements if element.lower() in _normalise(description)]
    return len(set(observed)) / len(set(elements)), sorted(set(observed))


def _specificity(value: str | None) -> str:
    candidate = str(value or "medium").strip().lower()
    return candidate if candidate in SPECIFICITY_THRESHOLDS else "medium"


def _judgement(score: float, intent_specificity: str | None = None) -> str:
    thresholds = SPECIFICITY_THRESHOLDS[_specificity(intent_specificity)]
    if score >= thresholds["aligned"]:
        return "aligned"
    if score >= thresholds["partial"]:
        return "partially_aligned"
    return "not_aligned"


def _calibrated_judgement(
    overall: float,
    evidence: Mapping[str, Any],
    formula_match: float,
    intent_specificity: str | None = None,
) -> str:
    specificity = _specificity(intent_specificity)
    thresholds = SPECIFICITY_THRESHOLDS[specificity]
    core_count = int(evidence.get("core_structural_count") or 0)
    core_score = float(evidence.get("core_structural_score") or 0.0)
    weighted = float(evidence.get("weighted_requirement_match_score") or evidence.get("requirement_match_score") or 0.0)
    structural_evidence_count = int(evidence.get("explicit_text_match_count") or 0) + int(evidence.get("alias_text_match_count") or 0) + int(evidence.get("implicit_condensed_match_count") or 0)
    if specificity == "loose" and structural_evidence_count == 0 and formula_match > 0:
        return "partially_aligned"
    if core_count == 0 and structural_evidence_count == 0:
        return "not_aligned"
    if structural_evidence_count == 0 and formula_match > 0:
        return "not_aligned"
    if core_count and core_score >= 0.75 and weighted >= thresholds["aligned"] and overall >= max(0.45, thresholds["aligned"] - 0.07):
        return "aligned"
    if core_count and core_score >= max(0.25, thresholds["partial"] - 0.10):
        return "partially_aligned"
    if not core_count and weighted >= thresholds["aligned"] and structural_evidence_count >= 2:
        return "partially_aligned"
    return _judgement(overall, specificity)


def validate_generated_cif_against_query(
    original_query: str,
    crystal_db_retrieval_query: str,
    generated_cif_robocrys_description: str | None,
    target_formula: str | None = None,
    chemistry_family: str | None = None,
    expected_motifs_or_priors: str | list[str] | None = None,
    retrieved_neighbor_descriptions: list[str] | None = None,
    llm_judge: bool = False,
    generated_cif_condensed_structure: Mapping[str, Any] | None = None,
    validator_requirements: list[Mapping[str, Any]] | None = None,
    requirement_aliases: Mapping[str, list[str]] | None = None,
    intent_specificity: str | None = "medium",
) -> dict[str, Any]:
    warnings: list[str] = []
    if llm_judge:
        warnings.append("llm_judge_requested_but_rule_based_validator_only")
    if not (original_query or crystal_db_retrieval_query):
        return _not_scored("missing_query", target_formula, chemistry_family, warnings)
    if not generated_cif_robocrys_description:
        return _not_scored("robocrys_output_unavailable", target_formula, chemistry_family, warnings)

    description = str(generated_cif_robocrys_description)
    expected = _query_terms(original_query, crystal_db_retrieval_query, expected_motifs_or_priors)
    observed = _description_terms(description)
    requirements = [dict(item) for item in (validator_requirements or _requirements_from_expected_terms(expected))]
    if requirement_aliases:
        for requirement in requirements:
            rid = str(requirement.get("id") or "")
            aliases = requirement_aliases.get(rid)
            if aliases:
                requirement["aliases"] = _unique([*(requirement.get("aliases") or []), *aliases])
    requirement_evidence = evaluate_validator_requirements(requirements, description, generated_cif_condensed_structure)
    formula_match, formula_terms = _formula_score(target_formula, description)
    scores: dict[str, float] = {"formula_match": round(formula_match, 3)}
    matched_terms: dict[str, list[str]] = {"formula_terms": formula_terms}
    missing_terms: dict[str, list[str]] = {}
    score_map = {
        "family_match": ("family_terms", "family_terms"),
        "coordination_match": ("coordination_terms", "coordination_terms"),
        "connectivity_match": ("connectivity_terms", "connectivity_terms"),
        "dimensionality_match": ("dimensionality_terms", "dimensionality_terms"),
        "motif_match": ("motif_terms", "motif_terms"),
    }
    for score_key, (expected_key, observed_key) in score_map.items():
        score, matched, missing = _score_terms(expected[expected_key], observed[observed_key])
        scores[score_key] = round(score, 3)
        matched_terms[expected_key] = matched
        missing_terms[expected_key] = missing
    structural_expected_count = sum(len(expected[key]) for key in ["family_terms", "coordination_terms", "connectivity_terms", "dimensionality_terms", "motif_terms"])
    if structural_expected_count == 0 and not requirements:
        warnings.append("no_structural_requirements_to_score")
        overall = 0.0
    else:
        overlap_overall = sum(scores[key] * weight for key, weight in WEIGHTS.items())
        if requirements:
            scores["requirement_match"] = requirement_evidence["requirement_match_score"]
            scores["weighted_requirement_match"] = requirement_evidence["weighted_requirement_match_score"]
            scores["core_structural_match"] = requirement_evidence["core_structural_score"]
            scores["supporting_label_match"] = requirement_evidence["supporting_label_score"]
            overall = 0.3 * overlap_overall + 0.7 * float(scores["weighted_requirement_match"])
        else:
            overall = overlap_overall
    scores["overall_intent_alignment"] = round(overall, 3)
    specificity = _specificity(intent_specificity)
    judgement = _calibrated_judgement(overall, requirement_evidence, formula_match, specificity)
    explanation = (
        f"Rule-based robocrys text overlap judged the generated description as {judgement} "
        f"with overall score {scores['overall_intent_alignment']}. "
        "Core structural evidence is weighted above supporting prototype/family labels; formula-only evidence is insufficient."
    )
    if retrieved_neighbor_descriptions:
        warnings.append("retrieved_neighbor_descriptions_not_scored_in_v1")
    return {
        "validator_version": VALIDATOR_VERSION,
        "available": True,
        "skip_reason": None,
        "target_formula": target_formula or "",
        "chemistry_family": chemistry_family or "",
        "intent_specificity": specificity,
        "specificity_thresholds": SPECIFICITY_THRESHOLDS[specificity],
        "scores": scores,
        "matched_terms": matched_terms,
        "missing_terms": missing_terms,
        "requirement_evidence": requirement_evidence,
        "judgement": judgement,
        "explanation": explanation,
        "warnings": warnings,
    }


def build_llm_intent_judge_prompt(
    *,
    original_query: str,
    crystal_db_retrieval_query: str,
    generated_cif_robocrys_description: str,
    target_formula: str | None = None,
    chemistry_family: str | None = None,
    expected_motifs_or_priors: str | list[str] | None = None,
    validator_requirements: list[Mapping[str, Any]] | None = None,
    requirement_evidence: Mapping[str, Any] | None = None,
    generated_cif_condensed_structure: Mapping[str, Any] | None = None,
    intent_specificity: str | None = "medium",
) -> str:
    specificity = _specificity(intent_specificity)
    payload = {
        "task": "Judge whether the generated crystal structurally achieved the requested Robocrys-style intent.",
        "strict_rules": [
            CORPUS_AUDIT_SUMMARY,
            "Compare requested structural motif, coordination, dimensionality, and family intent with the final Robocrys description.",
            "Do not judge thermodynamic stability, DFT energy, novelty, synthesizability, or experimental validity.",
            "Judge only semantic structural-intent alignment.",
            "Be strict about missing key motifs.",
            "Prioritize core structural evidence: coordination, nearest-neighbour chemistry, connectivity, and dimensionality.",
            "Prototype/family labels such as perovskite structured, spinel structured, rocksalt structured, layered, and wurtzite are supporting evidence, not automatic hard failures.",
            "Missing prototype/family words should be a minor/supporting penalty when alias text evidence or condensed JSON evidence supports the requested structure family.",
            "Missing prototype/family words should be a major penalty only when the requested family/prototype is the main requirement and no core structural evidence supports it.",
            "Count calibrated aliases and condensed-structure implicit evidence as valid structural evidence when they directly support the requirement.",
            "Do not require exact idealized query phrases when Robocrys-style aliases support the same motif.",
            "Robocrys prose often says bonded in 6-coordinate geometry rather than exact polyhedron formula strings such as TiO6; count these calibrated aliases.",
            "Count alias text evidence separately from exact text evidence.",
            "Count condensed JSON evidence as implicit support.",
            "If most core structural requirements are supported by explicit text, alias text, or implicit condensed evidence, do not mark incorrect solely because exact wording or prototype labels are absent.",
            "Do not mark a case correct from formula match alone.",
            "Formula-only matches are never sufficient for correct.",
            "Correct: most core structural requirements supported by explicit, alias, or implicit condensed evidence, with no major contradictions; prototype/family words may be absent if structural evidence supports them.",
            "Partially correct: some core requirements supported, but important coordination/connectivity/dimensionality evidence is missing or weak.",
            "Coordination-number evidence without exact geometry wording often belongs in partially_correct rather than incorrect.",
            "Do not mark incorrect merely because exact geometry words like tetrahedral geometry, octahedral geometry, or spinel structured are absent when coordination-number evidence or condensed evidence partially supports the requirement.",
            "Incorrect: core structural requirements are mostly missing or contradicted, or only formula/prototype labels match without structural evidence.",
            "Not scored: missing Robocrys description/condensed evidence or judge unavailable.",
            "Return JSON only.",
            "Do not use markdown fences.",
            "Do not include reasoning outside the JSON object.",
            "Include every required key exactly once.",
            "The score must be a number from 0.0 to 1.0.",
        ],
        "required_json_schema": {
            "validator_version": LLM_VALIDATOR_VERSION,
            "available": True,
            "score": 0.0,
            "correct": False,
            "judgement": "correct|partially_correct|incorrect|not_scored",
            "explicit_text_matches": [],
            "alias_text_matches": [],
            "implicit_condensed_matches": [],
            "matched_requirements": [],
            "missing_requirements": [],
            "contradictions": [],
            "concerns": [],
            "explanation": "",
            "not_physical_validation_notice": True,
        },
        "minimal_valid_json_example": {
            "validator_version": LLM_VALIDATOR_VERSION,
            "available": True,
            "score": 0.72,
            "correct": True,
            "judgement": "correct",
            "matched_requirements": ["perovskite", "TiO6 octahedra"],
            "explicit_text_matches": ["perovskite"],
            "alias_text_matches": [],
            "implicit_condensed_matches": ["Ti/O 6-coordinate environment"],
            "missing_requirements": [],
            "contradictions": [],
            "concerns": [],
            "explanation": "The Robocrys description contains the requested perovskite family and TiO6 octahedra.",
            "not_physical_validation_notice": True,
        },
        "case": {
            "target_formula": target_formula or "",
            "chemistry_family": chemistry_family or "",
            "intent_specificity": specificity,
            "specificity_thresholds": SPECIFICITY_THRESHOLDS[specificity],
            "expected_motifs_or_priors": expected_motifs_or_priors or "",
            "original_query": original_query,
            "crystal_db_retrieval_query": crystal_db_retrieval_query,
            "final_generated_cif_robocrys_description": generated_cif_robocrys_description,
            "calibrated_validator_requirements": validator_requirements or [],
            "calibrated_requirement_evidence": requirement_evidence or {},
            "generated_cif_condensed_structure_excerpt": _condensed_excerpt(generated_cif_condensed_structure),
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _condensed_excerpt(condensed_structure: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(condensed_structure, Mapping):
        return {}
    return {
        "formula": condensed_structure.get("formula") or _first_component_formula(condensed_structure),
        "dimensionality": condensed_structure.get("dimensionality"),
        "sites": condensed_structure.get("sites", {}),
        "has_corner_connectivity": "corner" in _normalise(_json_text(condensed_structure)),
        "has_edge_connectivity": "edge" in _normalise(_json_text(condensed_structure)),
    }


def _first_component_formula(condensed_structure: Mapping[str, Any]) -> str:
    components = condensed_structure.get("components")
    if isinstance(components, Mapping):
        for component in components.values():
            if isinstance(component, Mapping) and component.get("formula"):
                return str(component.get("formula"))
    return ""


def _strip_json_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = _strip_json_fence(text)
    candidates = [stripped]
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        candidates.append(stripped[first : last + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"parse_error:{last_error}")


def _normalise_llm_judge_payload(payload: Mapping[str, Any], *, prompt: str, raw_response: str) -> dict[str, Any]:
    missing = [field for field in LLM_REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"llm_json_schema_error:missing_required_fields:{','.join(missing)}")
    for field in ["explicit_text_matches", "alias_text_matches", "implicit_condensed_matches", "matched_requirements", "missing_requirements", "contradictions", "concerns"]:
        if not isinstance(payload.get(field), list):
            raise ValueError(f"llm_json_schema_error:{field}_not_list")
    score_raw = payload.get("score", payload.get("overall_intent_alignment"))
    try:
        score = max(0.0, min(1.0, float(score_raw)))
    except (TypeError, ValueError):
        raise ValueError("llm_json_schema_error:score_not_number") from None
    if not isinstance(payload.get("correct"), bool):
        raise ValueError("llm_json_schema_error:correct_not_boolean")
    if score >= 0.70:
        judgement = "correct"
    elif score >= 0.40:
        judgement = "partially_correct"
    else:
        judgement = "incorrect"
    requested_judgement = str(payload.get("judgement") or "").strip()
    alias_map = {
        "aligned": "correct",
        "partially_aligned": "partially_correct",
        "not_aligned": "incorrect",
    }
    requested_judgement = alias_map.get(requested_judgement, requested_judgement)
    if requested_judgement in {"correct", "partially_correct", "incorrect", "not_scored"}:
        judgement = requested_judgement
    else:
        raise ValueError(f"llm_json_schema_error:unknown_judgement:{requested_judgement}")
    return {
        "validator_version": LLM_VALIDATOR_VERSION,
        "available": True,
        "skip_reason": None,
        "score": round(score, 3),
        "correct": bool(score >= 0.70 and judgement == "correct"),
        "judgement": judgement,
        "explicit_text_matches": _string_list(payload.get("explicit_text_matches")),
        "alias_text_matches": _string_list(payload.get("alias_text_matches")),
        "implicit_condensed_matches": _string_list(payload.get("implicit_condensed_matches")),
        "matched_requirements": _string_list(payload.get("matched_requirements")),
        "missing_requirements": _string_list(payload.get("missing_requirements")),
        "contradictions": _string_list(payload.get("contradictions")),
        "concerns": _string_list(payload.get("concerns")),
        "explanation": str(payload.get("explanation") or ""),
        "not_physical_validation_notice": True,
        "prompt": prompt,
        "raw_response": raw_response,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _llm_not_scored(skip_reason: str, *, prompt: str = "", raw_response: str = "", error: str = "") -> dict[str, Any]:
    return {
        "validator_version": LLM_VALIDATOR_VERSION,
        "available": False,
        "skip_reason": skip_reason,
        "score": None,
        "correct": None,
        "judgement": "not_scored",
        "explicit_text_matches": [],
        "alias_text_matches": [],
        "implicit_condensed_matches": [],
        "matched_requirements": [],
        "missing_requirements": [],
        "contradictions": [],
        "concerns": [],
        "explanation": error or f"LLM Robocrys intent judge was not scored: {skip_reason}.",
        "parse_error": error if "json" in skip_reason or "parse" in skip_reason else "",
        "not_physical_validation_notice": True,
        "prompt": prompt,
        "raw_response": raw_response,
    }


def judge_robocrys_intent_alignment_with_llm(
    original_query: str,
    crystal_db_retrieval_query: str,
    generated_cif_robocrys_description: str,
    target_formula: str | None = None,
    chemistry_family: str | None = None,
    expected_motifs_or_priors: str | list[str] | None = None,
    model_config: dict | None = None,
    validator_requirements: list[Mapping[str, Any]] | None = None,
    requirement_evidence: Mapping[str, Any] | None = None,
    generated_cif_condensed_structure: Mapping[str, Any] | None = None,
    intent_specificity: str | None = "medium",
) -> dict[str, Any]:
    prompt = build_llm_intent_judge_prompt(
        original_query=original_query,
        crystal_db_retrieval_query=crystal_db_retrieval_query,
        generated_cif_robocrys_description=generated_cif_robocrys_description,
        target_formula=target_formula,
        chemistry_family=chemistry_family,
        expected_motifs_or_priors=expected_motifs_or_priors,
        validator_requirements=validator_requirements,
        requirement_evidence=requirement_evidence,
        generated_cif_condensed_structure=generated_cif_condensed_structure,
        intent_specificity=intent_specificity,
    )
    if not generated_cif_robocrys_description:
        return _llm_not_scored("robocrys_output_unavailable", prompt=prompt)
    config = dict(model_config or {})
    client = config.get("client")
    if client is None:
        return _llm_not_scored("llm_judge_unavailable", prompt=prompt)
    messages = [
        {
            "role": "system",
            "content": "You are a strict JSON-only evaluator for structural intent alignment. Return one JSON object only. Do not evaluate physical stability.",
        },
        {"role": "user", "content": prompt},
    ]
    raw = ""
    try:
        response = client.chat(
            messages=messages,
            temperature=0.0,
            max_tokens=1200,
            response_format={"type": "json_object"},
        )
        choices = response.get("choices") if isinstance(response, Mapping) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
            message = choices[0].get("message")
            if isinstance(message, Mapping):
                raw = str(message.get("content") or "")
        parsed = _extract_json_object(raw)
        return _normalise_llm_judge_payload(parsed, prompt=prompt, raw_response=raw)
    except Exception as exc:  # noqa: BLE001
        text = str(exc).lower()
        skip_reason = "llm_json_parse_error" if "json" in text or "parse" in text or "schema" in text else "llm_judge_unavailable"
        return _llm_not_scored(skip_reason, prompt=prompt, raw_response=raw, error=f"{type(exc).__name__}: {exc}")


def combine_rule_based_and_llm_validation(rule_based: Mapping[str, Any], llm_judge: Mapping[str, Any] | None = None) -> dict[str, Any]:
    llm = dict(llm_judge or _llm_not_scored("llm_judge_not_requested"))
    if llm.get("available"):
        decision_judgement = llm.get("judgement")
        decision_score = llm.get("score")
        decision_source = "llm_judge"
        requirement_evidence = rule_based.get("requirement_evidence") if isinstance(rule_based.get("requirement_evidence"), Mapping) else {}
        core_score = float(requirement_evidence.get("core_structural_score") or 0.0)
        structural_evidence_count = (
            int(requirement_evidence.get("explicit_text_match_count") or 0)
            + int(requirement_evidence.get("alias_text_match_count") or 0)
            + int(requirement_evidence.get("implicit_condensed_match_count") or 0)
        )
        contradictions = _string_list(llm.get("contradictions"))
        if (
            decision_judgement == "incorrect"
            and decision_score is not None
            and structural_evidence_count > 0
            and (
                (float(decision_score) >= 0.40 and core_score >= 0.45)
                or (core_score >= 0.30 and structural_evidence_count >= 2)
            )
            and not contradictions
        ):
            decision_judgement = "partially_correct"
            decision_source = "llm_judge_calibrated_with_rule_based"
        final = {
            "correct": bool(decision_judgement == "correct" and float(decision_score or 0.0) >= 0.70),
            "decision_source": decision_source,
            "score": decision_score,
            "judgement": decision_judgement,
            "not_physical_validation_notice": True,
        }
    elif rule_based.get("available"):
        score = float((rule_based.get("scores") or {}).get("overall_intent_alignment", 0.0))
        final = {
            "correct": score >= 0.75,
            "decision_source": "rule_based",
            "score": round(score, 3),
            "judgement": rule_based.get("judgement"),
            "not_physical_validation_notice": True,
        }
    else:
        final = {
            "correct": None,
            "decision_source": "not_scored",
            "score": None,
            "judgement": "not_scored",
            "not_physical_validation_notice": True,
        }
    return {
        "available": bool(rule_based.get("available") or llm.get("available")),
        "rule_based": dict(rule_based),
        "llm_judge": llm,
        "final_decision": final,
    }


def _not_scored(skip_reason: str, target_formula: str | None, chemistry_family: str | None, warnings: list[str]) -> dict[str, Any]:
    return {
        "validator_version": VALIDATOR_VERSION,
        "available": False,
        "skip_reason": skip_reason,
        "target_formula": target_formula or "",
        "chemistry_family": chemistry_family or "",
        "scores": {
            "formula_match": 0.0,
            "family_match": 0.0,
            "coordination_match": 0.0,
            "connectivity_match": 0.0,
            "dimensionality_match": 0.0,
            "motif_match": 0.0,
            "overall_intent_alignment": 0.0,
        },
        "matched_terms": {
            "formula_terms": [],
            "family_terms": [],
            "coordination_terms": [],
            "connectivity_terms": [],
            "dimensionality_terms": [],
            "motif_terms": [],
        },
        "missing_terms": {
            "coordination_terms": [],
            "connectivity_terms": [],
            "dimensionality_terms": [],
            "motif_terms": [],
        },
        "judgement": "not_scored",
        "explanation": f"Robocrys intent alignment was not scored: {skip_reason}.",
        "warnings": warnings,
    }


def summarize_intent_validation_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [_normalise_summary_row(row) for row in rows]
    scored = [row for row in normalized if row.get("available")]
    rule_scored = [row for row in normalized if row.get("rule_based_available")]
    llm_scored = [row for row in normalized if row.get("llm_available")]
    scores = [float(row.get("score") or 0.0) for row in scored if row.get("score") is not None]
    rule_scores = [float(row.get("rule_based_score") or 0.0) for row in rule_scored if row.get("rule_based_score") is not None]
    llm_scores = [float(row.get("llm_score") or 0.0) for row in llm_scored if row.get("llm_score") is not None]
    missing_counter: Counter[str] = Counter()
    matched_counter: Counter[str] = Counter()
    llm_missing_counter: Counter[str] = Counter()
    llm_matched_counter: Counter[str] = Counter()
    evidence_counter: Counter[str] = Counter()
    for row in normalized:
        for values in (row.get("missing_terms") or {}).values():
            if isinstance(values, list):
                missing_counter.update(str(item) for item in values)
        for values in (row.get("matched_terms") or {}).values():
            if isinstance(values, list):
                matched_counter.update(str(item) for item in values)
        llm_missing_counter.update(str(item) for item in row.get("llm_missing_requirements", []))
        llm_matched_counter.update(str(item) for item in row.get("llm_matched_requirements", []))
        for key in ["explicit_text_match_count", "alias_text_match_count", "implicit_condensed_match_count"]:
            evidence_counter[key] += int(row.get(key) or 0)
    correct_count = sum(1 for row in scored if row.get("correct") is True)
    llm_skip_reasons = Counter(
        str((row.get("llm_skip_reason") or row.get("skip_reason") or ""))
        for row in normalized
        if row.get("llm_skip_reason") or (not row.get("llm_available") and row.get("skip_reason"))
    )
    source_counts = Counter(str(row.get("decision_source") or "not_scored") for row in normalized)
    grouped_counts: dict[str, dict[str, dict[str, int]]] = {}
    for group_key in ["intent_specificity", "benchmark_split", "decision_source", "judgement"]:
        grouped_counts[group_key] = {}
        for row in normalized:
            group_value = str(row.get(group_key) or "unknown")
            judgement = str(row.get("judgement") or "not_scored")
            grouped_counts[group_key].setdefault(group_value, {})
            grouped_counts[group_key][group_value][judgement] = grouped_counts[group_key][group_value].get(judgement, 0) + 1
    if llm_scored and source_counts.get("rule_based"):
        score_basis = "mixed"
    elif llm_scored:
        score_basis = "llm_judge"
    elif rule_scored:
        score_basis = "rule_based_fallback"
    else:
        score_basis = "not_scored"
    return {
        "validator_version": f"{VALIDATOR_VERSION}+{LLM_VALIDATOR_VERSION}",
        "total_rows": len(rows),
        "total_cases_attempted": len(rows),
        "total_cases": len(rows),
        "cases_scored": len(scored),
        "scored_count": len(scored),
        "rule_based_scored": len(rule_scored),
        "rule_based_scored_count": len(rule_scored),
        "llm_judged": len(llm_scored),
        "llm_judged_count": len(llm_scored),
        "correct_count": correct_count,
        "partially_correct_count": sum(1 for row in scored if str(row.get("judgement")) in {"partially_correct", "partially_aligned"}),
        "incorrect_count": sum(1 for row in scored if str(row.get("judgement")) in {"incorrect", "not_aligned"}),
        "not_scored_count": sum(1 for row in normalized if str(row.get("judgement")) == "not_scored"),
        "score_basis": score_basis,
        "judgement_counts": dict(Counter(str(row.get("judgement", "not_scored")) for row in normalized)),
        "decision_source_counts": dict(source_counts),
        "grouped_counts": grouped_counts,
        "intent_specificity_counts": grouped_counts["intent_specificity"],
        "benchmark_split_counts": grouped_counts["benchmark_split"],
        "skip_reason_counts": dict(Counter(str(row.get("skip_reason") or "") for row in normalized if row.get("skip_reason"))),
        "llm_skip_reasons": dict(llm_skip_reasons),
        "mean_alignment_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "median_alignment_score": round(float(median(scores)), 3) if scores else 0.0,
        "mean_rule_based_score": round(sum(rule_scores) / len(rule_scores), 3) if rule_scores else 0.0,
        "median_rule_based_score": round(float(median(rule_scores)), 3) if rule_scores else 0.0,
        "mean_llm_score": round(sum(llm_scores) / len(llm_scores), 3) if llm_scores else None,
        "median_llm_score": round(float(median(llm_scores)), 3) if llm_scores else None,
        "common_missing_terms": missing_counter.most_common(20),
        "common_matched_terms": matched_counter.most_common(20),
        "common_missing_requirements": llm_missing_counter.most_common(20),
        "common_matched_requirements": llm_matched_counter.most_common(20),
        "explicit_text_match_count": evidence_counter["explicit_text_match_count"],
        "alias_text_match_count": evidence_counter["alias_text_match_count"],
        "implicit_condensed_match_count": evidence_counter["implicit_condensed_match_count"],
        "strongest_aligned_cases": sorted(
            scored,
            key=lambda row: float(row.get("score") or 0.0),
            reverse=True,
        )[:10],
        "weakest_aligned_cases": sorted(
            scored,
            key=lambda row: float(row.get("score") or 0.0),
        )[:10],
        "incorrect_cases": [row for row in scored if str(row.get("judgement")) in {"incorrect", "not_aligned"}][:20],
    }


def _normalise_summary_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("final_decision"), Mapping):
        final = row.get("final_decision") or {}
        rule = row.get("rule_based") if isinstance(row.get("rule_based"), Mapping) else {}
        llm = row.get("llm_judge") if isinstance(row.get("llm_judge"), Mapping) else {}
        judgement = str(final.get("judgement") or "not_scored")
        rule_score = (rule.get("scores") or {}).get("overall_intent_alignment") if isinstance(rule.get("scores"), Mapping) else None
        requirement_evidence = rule.get("requirement_evidence") if isinstance(rule.get("requirement_evidence"), Mapping) else {}
        llm_score = llm.get("score")
        skip_reason = rule.get("skip_reason") or llm.get("skip_reason") or ""
        return {
            "case_id": row.get("case_id", ""),
            "short_name": row.get("short_name", ""),
            "target_formula": row.get("target_formula", ""),
            "intent_specificity": _specificity(str(row.get("intent_specificity") or "")),
            "benchmark_split": str(row.get("benchmark_split") or "mixed_specificity"),
            "available": final.get("decision_source") != "not_scored" and final.get("score") is not None,
            "score": final.get("score"),
            "correct": final.get("correct"),
            "judgement": judgement,
            "decision_source": final.get("decision_source", "not_scored"),
            "skip_reason": skip_reason,
            "rule_based_available": bool(rule.get("available")),
            "rule_based_score": rule_score,
            "llm_available": bool(llm.get("available")),
            "llm_score": llm_score,
            "llm_skip_reason": llm.get("skip_reason") or "",
            "matched_terms": rule.get("matched_terms") if isinstance(rule.get("matched_terms"), Mapping) else {},
            "missing_terms": rule.get("missing_terms") if isinstance(rule.get("missing_terms"), Mapping) else {},
            "llm_matched_requirements": _string_list(llm.get("matched_requirements")),
            "llm_missing_requirements": _string_list(llm.get("missing_requirements")),
            "explicit_text_match_count": requirement_evidence.get("explicit_text_match_count", 0),
            "alias_text_match_count": requirement_evidence.get("alias_text_match_count", 0),
            "implicit_condensed_match_count": requirement_evidence.get("implicit_condensed_match_count", 0),
        }
    score = (row.get("scores") or {}).get("overall_intent_alignment") if isinstance(row.get("scores"), Mapping) else row.get("alignment_score")
    available = bool(row.get("available"))
    judgement = str(row.get("judgement") or ("not_scored" if not available else ""))
    return {
        "case_id": row.get("case_id", ""),
        "short_name": row.get("short_name", ""),
        "target_formula": row.get("target_formula", ""),
        "intent_specificity": _specificity(str(row.get("intent_specificity") or "")),
        "benchmark_split": str(row.get("benchmark_split") or "mixed_specificity"),
        "available": available,
        "score": score if available else None,
        "correct": (float(score) >= 0.75) if available and score not in {None, ""} else None,
        "judgement": judgement,
        "decision_source": "rule_based" if available else "not_scored",
        "skip_reason": row.get("skip_reason") or "",
        "rule_based_available": available,
        "rule_based_score": score if available else None,
        "llm_available": False,
        "llm_score": None,
        "llm_skip_reason": "",
        "matched_terms": row.get("matched_terms") if isinstance(row.get("matched_terms"), Mapping) else {},
        "missing_terms": row.get("missing_terms") if isinstance(row.get("missing_terms"), Mapping) else {},
        "llm_matched_requirements": [],
        "llm_missing_requirements": [],
        "explicit_text_match_count": ((row.get("requirement_evidence") or {}).get("explicit_text_match_count", 0) if isinstance(row.get("requirement_evidence"), Mapping) else 0),
        "alias_text_match_count": ((row.get("requirement_evidence") or {}).get("alias_text_match_count", 0) if isinstance(row.get("requirement_evidence"), Mapping) else 0),
        "implicit_condensed_match_count": ((row.get("requirement_evidence") or {}).get("implicit_condensed_match_count", 0) if isinstance(row.get("requirement_evidence"), Mapping) else 0),
    }


__all__ = [
    "LLM_VALIDATOR_VERSION",
    "VALIDATOR_VERSION",
    "build_llm_intent_judge_prompt",
    "combine_rule_based_and_llm_validation",
    "decompose_requirement_phrase",
    "evaluate_validator_requirements",
    "extract_robocrys_vocabulary_features",
    "judge_robocrys_intent_alignment_with_llm",
    "validate_generated_cif_against_query",
    "summarize_intent_validation_results",
]
