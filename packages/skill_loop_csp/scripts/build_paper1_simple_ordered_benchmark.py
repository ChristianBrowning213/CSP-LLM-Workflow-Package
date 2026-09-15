"""Audit Crystal-DB and freeze the Paper 1 simple ordered benchmark.

This builder is deliberately target-blind: it reads only source corpus records and
crystallographic metadata.  It never reads generation or SCA outputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import subprocess
import warnings
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pymatgen.analysis.prototypes import AflowPrototypeMatcher
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


BENCHMARK_VERSION = "paper1_simple_ordered_v1"
BUILDER_VERSION = "paper1_simple_ordered_builder.v1"
CLASSIFIER_VERSION = "paper1_simple_ordered_aflow.v1"
SELECTION_VERSION = "element_diversity_greedy.v1"
REQUEST_TEMPLATE_VERSION = "paper1_family_explicit.v1"
GENERAL_CORPUS_ID = "mp_stable_10k_v1"
QUOTAS = {
    "rocksalt_b1": 20,
    "cscl_b2": 15,
    "zinc_blende_b3": 15,
    "fluorite_antifluorite": 15,
    "oxide_perovskite": 20,
    "halide_perovskite": 15,
}
FAMILY_ORDER = tuple(QUOTAS)
PROTOTYPE_RULES = {
    "rocksalt_b1": (225, "AB", "B1"),
    "cscl_b2": (221, "AB", "B2"),
    "zinc_blende_b3": (216, "AB", "B3"),
    "fluorite_antifluorite": (225, "AB2", "C1"),
}
REQUEST_TEMPLATES = {
    "rocksalt_b1": "Generate a plausible ordered rocksalt crystal structure with composition {formula}.",
    "cscl_b2": "Generate a plausible ordered CsCl-type crystal structure with composition {formula}.",
    "zinc_blende_b3": "Generate a plausible ordered zinc-blende crystal structure with composition {formula}.",
    "fluorite_antifluorite": (
        "Generate a plausible ordered fluorite or anti-fluorite crystal structure with composition {formula}."
    ),
    "oxide_perovskite": (
        "Generate a plausible ordered cubic oxide perovskite crystal structure with composition {formula}."
    ),
    "halide_perovskite": (
        "Generate a plausible ordered cubic halide perovskite crystal structure with composition {formula}."
    ),
}
CSV_FIELDS = (
    "row_id", "request_text", "database", "retrieval_top_k", "spp_contract",
    "cell_policy", "solver_time_limit_s", "solver_threads", "solver_mip_gap",
    "proximity_scale", "random_seed", "target_reference_id",
    "exclude_target_reference", "notes",
)
CANDIDATE_FIELDS = (
    "record_id", "source_reference_id", "materials_project_id", "formula",
    "reduced_formula", "family", "space_group_symbol", "space_group_number",
    "source_atom_count", "primitive_atom_count", "species_count", "ordered",
    "cif_sha256", "source_corpus", "source_database", "source_provenance",
    "family_assignment_method", "family_assignment_reason", "aflow_strukturbericht",
)
EXCLUSION_FIELDS = (
    "record_id", "source_reference_id", "formula", "source_corpus",
    "source_database", "exclusion_reason", "detail",
)


@dataclass(frozen=True, slots=True)
class Candidate:
    record_id: str
    source_reference_id: str
    materials_project_id: str
    formula: str
    reduced_formula: str
    family: str
    space_group_symbol: str
    space_group_number: int
    source_atom_count: int
    primitive_atom_count: int
    species_count: int
    ordered: bool
    cif_sha256: str
    source_corpus: str
    source_database: str
    source_provenance: str
    family_assignment_method: str
    family_assignment_reason: str
    aflow_strukturbericht: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_bytes(encoded.encode("utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def git_state(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True, stderr=subprocess.STDOUT
        ).strip()

    return {"root": str(root.resolve()), "head": run("rev-parse", "HEAD"), "status_short": run("status", "--short").splitlines()}


def _file_uri(path: Path) -> str:
    return f"file:{path.resolve().as_posix()}?mode=ro"


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if exists else 0


def database_inventory(path: Path) -> dict[str, Any]:
    with sqlite3.connect(_file_uri(path), uri=True) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        counts = {name: _table_count(connection, name) for name in tables}
        formula_count = connection.execute(
            "SELECT COUNT(DISTINCT formula) FROM metadata"
        ).fetchone()[0]
        source_counts = dict(connection.execute(
            "SELECT COALESCE(source, ''), COUNT(*) FROM provenance GROUP BY source"
        ).fetchall())
        restricted = connection.execute(
            "SELECT COUNT(*) FROM structures WHERE COALESCE(license_restricted, 0) != 0"
        ).fetchone()[0]
    return {
        "path": str(path.resolve()), "sha256": sha256_file(path), "size_bytes": path.stat().st_size,
        "tables": tables, "table_counts": counts, "distinct_formulas": int(formula_count),
        "provenance_sources": source_counts, "license_restricted_records": int(restricted),
        "schema_notes": "structure_id is the primary key; family/prototype metadata are not native columns",
    }


def _formula_shape(formula: str) -> tuple[int, tuple[float, ...]] | None:
    try:
        reduced = Composition(formula).reduced_composition
    except Exception:
        return None
    amounts = tuple(sorted(round(float(value), 8) for value in reduced.values()))
    return len(reduced), amounts


def _prototype_tags(matcher: AflowPrototypeMatcher, structure: Structure) -> set[str]:
    matches = matcher.get_prototypes(structure) or []
    return {str(match.get("tags", {}).get("strukturbericht")) for match in matches}


def classify_structure(
    structure: Structure,
    *,
    matcher: AflowPrototypeMatcher | None = None,
    max_primitive_atoms: int = 10,
) -> tuple[dict[str, Any] | None, str, str]:
    """Return family metadata or an explicit exclusion reason."""
    if not structure.is_ordered:
        return None, "DISORDERED_OR_PARTIAL_OCCUPANCY", "Structure.is_ordered is false"
    if len(structure.composition.elements) not in {2, 3}:
        return None, "SPECIES_COUNT_OUT_OF_SCOPE", str(len(structure.composition.elements))
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
    number = int(analyzer.get_space_group_number())
    symbol = str(analyzer.get_space_group_symbol())
    try:
        primitive = analyzer.get_primitive_standard_structure()
    except Exception:
        primitive = structure.get_primitive_structure()
    if len(primitive) > max_primitive_atoms:
        return None, "PRIMITIVE_CELL_TOO_LARGE", str(len(primitive))
    anonymous = str(primitive.composition.anonymized_formula)
    plausible = any((number, anonymous) == rule[:2] for rule in PROTOTYPE_RULES.values())
    plausible = plausible or (number == 221 and anonymous == "ABC3")
    if not plausible:
        return None, "NOT_SUPPORTED_PROTOTYPE", f"SG={number}; anonymous={anonymous}"
    prototype_matcher = matcher or AflowPrototypeMatcher()
    tags = _prototype_tags(prototype_matcher, structure)
    family: str | None = None
    required_tag = ""
    for name, (expected_number, expected_anon, tag) in PROTOTYPE_RULES.items():
        if (number, anonymous) == (expected_number, expected_anon):
            family, required_tag = name, tag
            break
    if number == 221 and anonymous == "ABC3":
        required_tag = "E2_1"
        reduced = primitive.composition.reduced_composition
        if round(float(reduced.get("O", 0)), 8) == 3.0:
            family = "oxide_perovskite"
        elif any(round(float(reduced.get(symbol, 0)), 8) == 3.0 for symbol in ("F", "Cl", "Br", "I")):
            family = "halide_perovskite"
        else:
            return None, "PEROVSKITE_ANION_OUT_OF_SCOPE", str(reduced)
    if required_tag not in tags:
        return None, "AFLOW_PROTOTYPE_MISMATCH", f"required={required_tag}; observed={sorted(tags)}"
    assert family is not None
    reason = f"AFLOW {required_tag}; SG {number} {symbol}; {anonymous}; ordered; primitive_atoms={len(primitive)}"
    return {
        "family": family, "space_group_symbol": symbol, "space_group_number": number,
        "primitive_atom_count": len(primitive), "aflow_strukturbericht": required_tag,
        "family_assignment_reason": reason,
    }, "ELIGIBLE", reason


def scan_database(
    path: Path,
    corpus_id: str,
    *,
    matcher: AflowPrototypeMatcher | None = None,
    retain_all_exclusions: bool = False,
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    prototype_matcher = matcher or AflowPrototypeMatcher()
    with sqlite3.connect(_file_uri(path), uri=True) as connection:
        rows = connection.execute(
            """SELECT s.structure_id, s.cif_text, s.reduced_formula, s.license_restricted,
                      m.formula, p.source, p.source_id, p.allow_cif_return, p.allow_export
               FROM structures s JOIN metadata m USING(structure_id)
               JOIN provenance p USING(structure_id) ORDER BY s.structure_id"""
        ).fetchall()
    candidates: list[Candidate] = []
    exclusions: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for record_id, cif_text, db_formula, restricted, metadata_formula, source, source_id, allow_return, allow_export in rows:
        base = {
            "record_id": str(record_id), "source_reference_id": str(source_id or ""),
            "formula": str(metadata_formula or db_formula or ""), "source_corpus": corpus_id,
            "source_database": str(path.resolve()),
        }

        def exclude(reason: str, detail: str = "") -> None:
            if retain_all_exclusions or reason != "FORMULA_SHAPE_OUT_OF_SCOPE":
                exclusions.append(base | {"exclusion_reason": reason, "detail": detail})

        if not cif_text:
            exclude("MISSING_CIF")
            continue
        # Crystal-DB's supported text-search export is governed by CIF return
        # permission.  The general MP corpus intentionally stores allow_export=0
        # while allow_cif_return=1, and the production retriever exports those CIFs.
        if restricted or allow_return == 0:
            exclude("PROVENANCE_OR_EXPORT_POLICY_INELIGIBLE")
            continue
        shape = _formula_shape(base["formula"])
        if shape not in {(2, (1.0, 1.0)), (2, (1.0, 2.0)), (3, (1.0, 1.0, 3.0))}:
            exclude("FORMULA_SHAPE_OUT_OF_SCOPE", str(shape))
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                structure = Structure.from_str(str(cif_text), fmt="cif")
                decision, reason, detail = classify_structure(structure, matcher=prototype_matcher)
        except Exception as exc:  # parse/symmetry failures are persisted as exclusions
            exclude("CIF_PARSE_OR_CLASSIFICATION_ERROR", f"{type(exc).__name__}: {exc}")
            continue
        if decision is None:
            exclude(reason, detail)
            continue
        cif_hash = sha256_bytes(str(cif_text).encode("utf-8"))
        if cif_hash in seen_hashes:
            exclude("DUPLICATE_CIF_HASH", cif_hash)
            continue
        seen_hashes.add(cif_hash)
        reduced = structure.composition.reduced_formula
        material_id = re.sub(r"\.cif$", "", str(source_id or ""), flags=re.IGNORECASE)
        candidates.append(Candidate(
            record_id=str(record_id), source_reference_id=str(source_id or ""),
            materials_project_id=material_id, formula=reduced, reduced_formula=reduced,
            family=str(decision["family"]), space_group_symbol=str(decision["space_group_symbol"]),
            space_group_number=int(decision["space_group_number"]), source_atom_count=len(structure),
            primitive_atom_count=int(decision["primitive_atom_count"]),
            species_count=len(structure.composition.elements), ordered=True, cif_sha256=cif_hash,
            source_corpus=corpus_id, source_database=str(path.resolve()),
            source_provenance=str(source or ""), family_assignment_method=CLASSIFIER_VERSION,
            family_assignment_reason=str(decision["family_assignment_reason"]),
            aflow_strukturbericht=str(decision["aflow_strukturbericht"]),
        ))
    candidates.sort(key=lambda item: (FAMILY_ORDER.index(item.family), item.formula, item.source_reference_id, item.record_id))
    exclusions.sort(key=lambda item: (item["record_id"], item["exclusion_reason"]))
    return candidates, exclusions


def select_targets(candidates: Sequence[Candidate], quotas: Mapping[str, int] = QUOTAS) -> list[Candidate]:
    """Greedily maximize new element coverage with stable lexical tie-breaking."""
    selected: list[Candidate] = []
    for family in FAMILY_ORDER:
        remaining = [item for item in candidates if item.family == family]
        used_elements: set[str] = set()
        used_formulas: set[str] = set()
        while remaining and sum(item.family == family for item in selected) < int(quotas[family]):
            eligible = [item for item in remaining if item.reduced_formula not in used_formulas]
            if not eligible:
                break
            eligible.sort(
                key=lambda item: (
                    -len({str(element) for element in Composition(item.reduced_formula).elements} - used_elements),
                    item.reduced_formula, item.source_reference_id, item.record_id,
                )
            )
            chosen = eligible[0]
            selected.append(chosen)
            used_formulas.add(chosen.reduced_formula)
            used_elements.update(str(element) for element in Composition(chosen.reduced_formula).elements)
            remaining.remove(chosen)
    return selected


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower()) or "target"


def benchmark_rows(targets: Sequence[Candidate]) -> list[dict[str, Any]]:
    counters: Counter[str] = Counter()
    rows = []
    for target in targets:
        counters[target.family] += 1
        row_id = f"{target.family}_{counters[target.family]:03d}_{_slug(target.reduced_formula)}"
        rows.append({
            "row_id": row_id,
            "request_text": REQUEST_TEMPLATES[target.family].format(formula=target.reduced_formula),
            "database": "general", "retrieval_top_k": "", "spp_contract": "",
            "cell_policy": "", "solver_time_limit_s": "", "solver_threads": "",
            "solver_mip_gap": "", "proximity_scale": "", "random_seed": "",
            "target_reference_id": target.record_id, "exclude_target_reference": "true",
            "notes": (
                f"family={target.family}; source_reference={target.source_reference_id}; "
                f"source_cif_sha256={target.cif_sha256}"
            ),
        })
    return rows


def assert_freeze(
    targets: Sequence[Candidate],
    rows: Sequence[Mapping[str, Any]],
    *,
    required_families: Sequence[str] = (),
) -> dict[str, Any]:
    target_ids = [item.record_id for item in targets]
    row_ids = [str(item["row_id"]) for item in rows]
    hashes = [item.cif_sha256 for item in targets]
    assertions = {
        "row_count_matches_targets": len(rows) == len(targets),
        "unique_row_ids": len(row_ids) == len(set(row_ids)),
        "unique_target_reference_ids": len(target_ids) == len(set(target_ids)),
        "unique_source_cif_hashes": len(hashes) == len(set(hashes)),
        "all_reference_ids_nonempty": all(target_ids),
        "all_exclude_target_reference_true": all(
            str(row["exclude_target_reference"]).lower() == "true" for row in rows
        ),
        "all_database_general": all(row["database"] == "general" for row in rows),
        "target_count_nonzero": len(targets) > 0,
        "all_required_families_present": all(
            any(target.family == family for target in targets) for family in required_families
        ),
    }
    if not all(assertions.values()):
        raise ValueError(f"benchmark freeze assertions failed: {assertions}")
    return assertions


def resolve_registry(skill_root: Path, crystal_root: Path) -> list[dict[str, Any]]:
    registry_path = skill_root / "data" / "corpora" / "registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    records = []
    for corpus_id, raw in sorted(payload["corpora"].items()):
        database_text = str(raw["database"]).replace("\\", "/")
        if raw.get("path_base") == "repository":
            database = skill_root / database_text
        else:
            prefix = "Crystal-DB/"
            relative = database_text[len(prefix):] if database_text.startswith(prefix) else database_text
            database = crystal_root / relative
        records.append({**raw, "corpus_id": corpus_id, "database": database.resolve()})
    discovered = {
        "paper_experiment_3_halide_perovskite_v1": crystal_root / "data" / "paper_experiment_3_halide_perovskite_v1.db",
        "result_common_families": crystal_root / "data" / "result_common_families.db",
        "result_halide_perovskite": crystal_root / "data" / "result_halide_perovskite.db",
        "result_hard_intent": crystal_root / "data" / "result_hard_intent.db",
    }
    known = {str(record["database"]).lower() for record in records}
    for corpus_id, database in discovered.items():
        if database.is_file() and str(database.resolve()).lower() not in known:
            records.append({
                "corpus_id": corpus_id, "database": database.resolve(), "path_base": "Crystal-DB",
                "role": "unregistered_legacy_or_result_dataset", "source": "Materials Project-derived",
            })
    return records


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |" for row in rows)
    return "\n".join(lines)


def build(*, skill_root: Path, crystal_root: Path, output_root: Path, force: bool = False) -> dict[str, Any]:
    benchmark_csv = skill_root / "benchmark_paper1_simple_ordered_v1.csv"
    freeze_root = output_root / "freeze_v1"
    if freeze_root.exists() and not force:
        raise FileExistsError(f"freeze already exists; refusing to overwrite: {freeze_root}")
    matcher = AflowPrototypeMatcher()
    registry = resolve_registry(skill_root, crystal_root)
    scan_cache: dict[str, tuple[list[Candidate], list[dict[str, Any]]]] = {}
    inventory_cache: dict[str, dict[str, Any]] = {}
    audit_records = []
    coverage_rows = []
    for corpus in registry:
        database = Path(corpus["database"])
        if not database.is_file():
            audit_records.append({**{k: str(v) for k, v in corpus.items()}, "status": "MISSING"})
            continue
        key = str(database.resolve()).lower()
        if key not in scan_cache:
            scan_cache[key] = scan_database(database, str(corpus["corpus_id"]), matcher=matcher)
            inventory_cache[key] = database_inventory(database)
        eligible, exclusions = scan_cache[key]
        inventory = inventory_cache[key]
        audit_records.append({
            "corpus_id": corpus["corpus_id"], "database": str(database.resolve()),
            "role": corpus.get("role"), "declared_record_count": corpus.get("record_count"),
            "source": corpus.get("source"), "description_backend": corpus.get("description_backend"),
            "embedding_backend": corpus.get("embedding_backend"), "status": "AUDITED",
            "inventory": inventory, "eligible_positive_domain_count": len(eligible),
            "classification_exclusion_count": len(exclusions),
        })
        for family in FAMILY_ORDER:
            family_items = [item for item in eligible if item.family == family]
            coverage_rows.append({
                "Corpus": corpus["corpus_id"], "Family": family,
                "Candidate records": len(family_items),
                "Unique formulas": len({item.reduced_formula for item in family_items}),
                "Unique CIF hashes": len({item.cif_sha256 for item in family_items}),
                "Ordered usable": len(family_items),
                "Notes": "AFLOW+symmetry derived" if family_items else "No eligible records",
            })
    general_db = crystal_root / "data" / "phase6_mp_10k.db"
    general_key = str(general_db.resolve()).lower()
    eligible, all_exclusions = scan_database(
        general_db, GENERAL_CORPUS_ID, matcher=matcher, retain_all_exclusions=True
    )
    scan_cache[general_key] = (eligible, all_exclusions)
    selected = select_targets(eligible)
    selected_ids = {item.record_id for item in selected}
    excluded_rows = list(all_exclusions)
    for item in eligible:
        if item.record_id not in selected_ids:
            excluded_rows.append({
                "record_id": item.record_id, "source_reference_id": item.source_reference_id,
                "formula": item.reduced_formula, "source_corpus": item.source_corpus,
                "source_database": item.source_database,
                "exclusion_reason": "ELIGIBLE_NOT_SELECTED_FAMILY_QUOTA",
                "detail": f"quota={QUOTAS[item.family]}",
            })
    rows = benchmark_rows(selected)
    assertions = assert_freeze(selected, rows, required_families=FAMILY_ORDER)

    audit_root = output_root / "corpus_audit"
    selection_root = output_root / "selection"
    write_csv(audit_root / "FAMILY_COVERAGE.csv", coverage_rows, (
        "Corpus", "Family", "Candidate records", "Unique formulas", "Unique CIF hashes",
        "Ordered usable", "Notes",
    ))
    decision = {
        "case": "A_EXISTING_CORPUS_SUFFICIENT", "selected_corpus": GENERAL_CORPUS_ID,
        "database_route": "general", "new_corpus_created": False,
        "reason": (
            "The canonical general corpus contains clean AFLOW-confirmed records in every proposed "
            "family and supports 84 unique held-out targets. A derived selection manifest is sufficient."
        ),
    }
    audit_payload = {
        "schema_version": "paper1_crystal_db_corpus_audit.v1", "classifier_version": CLASSIFIER_VERSION,
        "corpora": audit_records, "family_coverage": coverage_rows, "decision": decision,
        "duplicate_handling": "structure_id primary key plus benchmark-level unique CIF SHA256",
        "metadata_findings": {
            "general_space_group_column": "uniform P 1; not used for family assignment",
            "family_labels": "derived from source CIF using AFLOW prototype, symmetry and stoichiometry",
            "primitive_or_conventional": "source representation retained; primitive standardized representation used for <=10 atom eligibility",
        },
    }
    write_json(audit_root / "CRYSTAL_DB_CORPUS_AUDIT.json", audit_payload)
    coverage_summary = Counter(item.family for item in eligible)
    audit_md = [
        "# Crystal-DB corpus audit", "", f"Classifier: `{CLASSIFIER_VERSION}`.", "",
        "Decision: reuse `mp_stable_10k_v1` through the existing `general` route; no new corpus is required.", "",
        "The native general-corpus space-group column is uniformly `P 1`, so it was not used. Family labels were derived from each CIF using an AFLOW Strukturbericht match, recomputed space group, reduced stoichiometry, ordering, and primitive-cell size.", "",
        "## General-corpus eligible pool", "",
        markdown_table(["Family", "Eligible", "Quota", "Selected"], [
            [family, coverage_summary[family], QUOTAS[family], sum(item.family == family for item in selected)]
            for family in FAMILY_ORDER
        ]), "", "## Corpus inventory", "",
        markdown_table(["Corpus", "Rows", "Eligible", "Database"], [
            [record["corpus_id"], record.get("inventory", {}).get("table_counts", {}).get("structures", "missing"),
             record.get("eligible_positive_domain_count", ""), record.get("database", "")]
            for record in audit_records
        ]), "",
        "Specialist layered, spinel, and NASICON corpora remain scientifically separate and were not repurposed for this benchmark. Legacy result corpora are small target-oriented demonstrations and are not suitable as the main evidence corpus.", "",
    ]
    (audit_root / "CRYSTAL_DB_CORPUS_AUDIT.md").write_text("\n".join(audit_md), encoding="utf-8")

    candidate_dicts = [asdict(item) for item in eligible]
    target_dicts = [asdict(item) for item in selected]
    write_csv(selection_root / "ELIGIBLE_TARGETS.csv", candidate_dicts, CANDIDATE_FIELDS)
    write_csv(selection_root / "EXCLUDED_TARGETS.csv", excluded_rows, EXCLUSION_FIELDS)
    write_csv(selection_root / "BENCHMARK_TARGETS.csv", target_dicts, CANDIDATE_FIELDS)
    write_json(selection_root / "BENCHMARK_TARGETS.json", {
        "schema_version": "paper1_benchmark_targets.v1", "targets": target_dicts,
    })
    selection_manifest = {
        "schema_version": "paper1_selection_manifest.v1", "benchmark_version": BENCHMARK_VERSION,
        "classifier_version": CLASSIFIER_VERSION, "selection_version": SELECTION_VERSION,
        "family_order": FAMILY_ORDER, "family_quotas": QUOTAS,
        "rule": "filter eligibility; deduplicate CIF hashes; one record per formula; greedily maximize new elements with lexical tie-breaks; take up to quota",
        "eligible_count": len(eligible), "selected_count": len(selected),
        "eligible_family_counts": dict(coverage_summary),
        "selected_family_counts": dict(Counter(item.family for item in selected)),
        "targets": target_dicts,
    }
    selection_manifest["manifest_sha256"] = canonical_json_hash(selection_manifest)
    write_json(selection_root / "BENCHMARK_PROVENANCE.json", selection_manifest)
    selection_md = [
        "# Paper 1 benchmark selection", "", f"Eligible: {len(eligible)}. Selected: {len(selected)}.", "",
        "Selection was completed without reading generation or SCA outputs. Each family uses a deterministic element-diversity greedy selection with lexical tie-breaks, unique formulas, and the frozen family quota.", "",
        markdown_table(["Family", "Eligible", "Selected"], [
            [family, coverage_summary[family], sum(item.family == family for item in selected)]
            for family in FAMILY_ORDER
        ]), "",
    ]
    (selection_root / "SELECTION_REPORT.md").write_text("\n".join(selection_md), encoding="utf-8")
    write_csv(benchmark_csv, rows, CSV_FIELDS)

    source_hashes = {
        "general_database": sha256_file(general_db),
        "corpus_registry": sha256_file(skill_root / "data" / "corpora" / "registry.json"),
        "workflow_config": sha256_file(skill_root / "config" / "final_workflow_v1.json"),
        "builder": sha256_file(Path(__file__)),
        "design_document": sha256_file(skill_root / "Paper%201%20SPP%20Corpus%20Dataset%20Design.docx"),
    }
    freeze = {
        "schema_version": "paper1_benchmark_freeze.v1", "benchmark_version": BENCHMARK_VERSION,
        "builder_version": BUILDER_VERSION, "builder_sha256": source_hashes["builder"],
        "request_template_version": REQUEST_TEMPLATE_VERSION,
        "methodology": {
            "workflow_version": "csv_workflow_v1", "spp_contract": "dmytro_gr_v1",
            "cell_policy": "retrieval_feasible_cell_v1", "grid": [4, 4, 4],
            "solver_time_limit_s": 300, "solver_threads": 1, "solver_mip_gap": 0.0,
            "random_seed": 0, "proximity_scale": 1.0,
        },
        "leakage_policy": {
            "target_reference_exclusion": True, "composition_exclusion": False,
            "claim": "The exact Crystal-DB structure_id is excluded by assemble_spp_evidence; composition-level exclusion is not implemented by csv_workflow_v1.",
        },
        "database_route": "general", "corpus_id": GENERAL_CORPUS_ID,
        "target_count": len(selected), "family_counts": dict(Counter(item.family for item in selected)),
        "target_ids": [item.record_id for item in selected],
        "source_reference_ids": [item.source_reference_id for item in selected],
        "source_cif_hashes": [item.cif_sha256 for item in selected],
        "selection_manifest_sha256": selection_manifest["manifest_sha256"],
        "benchmark_csv": str(benchmark_csv.resolve()), "benchmark_csv_sha256": sha256_file(benchmark_csv),
        "source_hashes": source_hashes, "freeze_assertions": assertions,
        "repositories": {"Skill-Loop-CSP": git_state(skill_root), "Crystal-DB": git_state(crystal_root)},
        "generation_started": False, "frozen_before_generation": True,
        "targets": [{"row_id": row["row_id"], **asdict(target)} for row, target in zip(rows, selected)],
    }
    freeze["freeze_payload_sha256"] = canonical_json_hash(freeze)
    write_json(freeze_root / "FROZEN_BENCHMARK_MANIFEST.json", freeze)
    write_json(freeze_root / "REFERENCE_EXCLUSION_AUDIT.json", {
        "schema_version": "paper1_reference_exclusion_audit.v1",
        "phase": "freeze_pre_retrieval", "assertions": assertions,
        "rows": [{"row_id": row["row_id"], "target_reference_id": row["target_reference_id"],
                  "exclude_target_reference": True, "retrieval_absence": "PENDING_PREFLIGHT"} for row in rows],
    })
    freeze_md = [
        "# Paper 1 benchmark freeze v1", "", f"Targets: {len(selected)}.", "",
        f"CSV SHA256: `{freeze['benchmark_csv_sha256']}`", "",
        "All target IDs, family labels, prompts, source CIF hashes, reference exclusions, workflow settings, and selection rules were frozen before generation. Retrieval-absence checks remain pending until scientific preflight.", "",
        markdown_table(["Family", "Count"], [[family, freeze["family_counts"].get(family, 0)] for family in FAMILY_ORDER]), "",
    ]
    (freeze_root / "FREEZE_REPORT.md").write_text("\n".join(freeze_md), encoding="utf-8")
    return {
        "status": "FROZEN", "benchmark_csv": str(benchmark_csv), "target_count": len(selected),
        "family_counts": freeze["family_counts"], "freeze_manifest": str(freeze_root / "FROZEN_BENCHMARK_MANIFEST.json"),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--crystal-db-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    skill_root = args.skill_root.resolve()
    output_root = (args.output_root or skill_root / "artifacts" / "paper1_spp_positive_domain").resolve()
    result = build(
        skill_root=skill_root, crystal_root=args.crystal_db_root.resolve(),
        output_root=output_root, force=args.force,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
