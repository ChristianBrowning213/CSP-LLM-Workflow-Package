"""CrystaLLM-style pre-DFT evaluation pipeline."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pymatgen.core import Structure

from sca.evaluators.alignn import predict_alignn_formation_energy
from sca.evaluators.bonds import evaluate_bonds
from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.composition import evaluate_composition
from sca.evaluators.geometry import evaluate_geometry
from sca.evaluators.multiplicity import evaluate_multiplicity
from sca.evaluators.novelty import evaluate_novelty
from sca.evaluators.symmetry import evaluate_symmetry
from sca.scoring import compute_pre_dft_valid, compute_rank_score
from sca.schemas import (
    AlignnResult,
    BondResult,
    CompositionResult,
    CrystalEvalRecord,
    GeometryResult,
    MultiplicityResult,
    NoveltyResult,
    SymmetryResult,
)


def evaluate_one_cif(
    cif_path: str | Path,
    target_formula: str | None = None,
    target_space_group: str | None = None,
    method: str | None = None,
    query_id: str | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    reference_structures: dict[str, Structure] | None = None,
    run_id: str | None = None,
) -> tuple[CrystalEvalRecord, Structure | None]:
    path = Path(cif_path)
    run_id = run_id or str(uuid4())
    cif_text = _read_text(path)
    structure, parse = parse_cif(path)

    if structure is None:
        record = CrystalEvalRecord(
            run_id=run_id,
            method=method,
            query_id=query_id,
            input_path=str(path),
            file_name=path.name,
            parse_ok=False,
            chemical_species_valid=parse.chemical_species_valid,
            species=parse.species,
            invalid_species=parse.invalid_species,
            formula=parse.formula,
            reduced_formula=parse.reduced_formula,
            volume=parse.volume,
            density=parse.density,
            density_error=parse.density_error,
            target_formula=target_formula,
            target_space_group=target_space_group,
            error_type=parse.error_type,
            error_message=parse.error_message,
        )
        record = record.model_copy(
            update={
                "pre_dft_valid": compute_pre_dft_valid(record, require_spacegroup),
                "pre_dft_rank_score": compute_rank_score(record),
            }
        )
        return record, None

    composition = evaluate_composition(structure, target_formula)
    symmetry = evaluate_symmetry(structure, cif_text, target_space_group)
    multiplicity = evaluate_multiplicity(structure, cif_text)
    bonds = evaluate_bonds(structure)
    geometry = evaluate_geometry(structure)
    novelty = evaluate_novelty(structure, reference_structures)
    alignn = (
        predict_alignn_formation_energy(path)
        if run_alignn
        else AlignnResult(alignn_ok=False)
    )

    record = _build_record(
        path=path,
        run_id=run_id,
        method=method,
        query_id=query_id,
        parse=parse,
        composition=composition,
        symmetry=symmetry,
        multiplicity=multiplicity,
        bonds=bonds,
        geometry=geometry,
        novelty=novelty,
        alignn=alignn,
    )
    record = record.model_copy(
        update={
            "pre_dft_valid": compute_pre_dft_valid(record, require_spacegroup),
        }
    )
    record = record.model_copy(update={"pre_dft_rank_score": compute_rank_score(record)})
    return record, structure


def _build_record(
    path: Path,
    run_id: str,
    method: str | None,
    query_id: str | None,
    parse,
    composition: CompositionResult,
    symmetry: SymmetryResult,
    multiplicity: MultiplicityResult,
    bonds: BondResult,
    geometry: GeometryResult,
    novelty: NoveltyResult,
    alignn: AlignnResult,
) -> CrystalEvalRecord:
    error_type, error_message = _first_error(parse, composition, symmetry, multiplicity, bonds, geometry, novelty, alignn)
    return CrystalEvalRecord(
        run_id=run_id,
        method=method,
        query_id=query_id,
        input_path=str(path),
        file_name=path.name,
        parse_ok=parse.parse_ok,
        chemical_species_valid=parse.chemical_species_valid,
        species=parse.species,
        invalid_species=parse.invalid_species,
        formula=parse.formula,
        reduced_formula=parse.reduced_formula,
        target_formula=composition.target_formula,
        target_formula_match=composition.target_formula_match,
        declared_space_group=symmetry.declared_space_group,
        detected_space_group=symmetry.detected_space_group,
        target_space_group=symmetry.target_space_group,
        space_group_consistent=symmetry.space_group_consistent,
        multiplicity_checked=multiplicity.multiplicity_checked,
        multiplicity_consistent=multiplicity.multiplicity_consistent,
        bond_reasonableness_score=bonds.bond_reasonableness_score,
        bond_lengths_reasonable=bonds.bond_lengths_reasonable,
        min_distance=bonds.min_distance,
        min_distance_pair=bonds.min_distance_pair,
        num_bad_contacts=bonds.num_bad_contacts,
        volume=geometry.volume,
        volume_per_atom=geometry.volume_per_atom,
        density=geometry.density,
        density_error=geometry.density_error or parse.density_error,
        geometry_ok=geometry.geometry_ok,
        geometry_warning_count=geometry.geometry_warning_count,
        novelty_checked=novelty.novelty_checked,
        nearest_reference_id=novelty.nearest_reference_id,
        known_match=novelty.known_match,
        novel_by_structure_matcher=novelty.novel_by_structure_matcher,
        novelty_error=novelty.novelty_error,
        alignn_ok=alignn.alignn_ok,
        alignn_model=alignn.alignn_model,
        formation_energy_per_atom=alignn.formation_energy_per_atom,
        error_type=error_type,
        error_message=error_message,
    )


def _first_error(*results) -> tuple[str | None, str | None]:
    fields = (
        ("error_type", "error_message"),
        ("composition_error", "composition_error"),
        ("symmetry_error", "symmetry_error"),
        ("multiplicity_error", "multiplicity_error"),
        ("bond_error", "bond_error"),
        ("geometry_error", "geometry_error"),
        ("novelty_error", "novelty_error"),
        ("alignn_error", "alignn_error"),
    )
    for result in results:
        for type_field, message_field in fields:
            message = getattr(result, message_field, None)
            if message:
                error_type = getattr(result, type_field, None)
                return error_type or message.split(":", 1)[0], message
    return None, None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(errors="replace")
    except Exception:
        return None
