"""Hash-verified versioned NASICON/NZP scaffold registry.

The registry derives candidate sites and symmetry orbits from frozen source
CIFs.  It never fabricates coordinates and refuses a source whose bytes no
longer match the frozen v3 manifest.
"""

from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from .schema import ScaffoldRecord, ScaffoldValidation


SCAFFOLD_VERSION = "1.0.0"
CORPUS_ENVIRONMENT_VARIABLE = "QLIP_SCAFFOLD_CORPUS_ROOT"
CORPUS_DATASET_NAME = "nasicon_specialist_v3"


@dataclass(frozen=True)
class ScaffoldCorpusResolution:
    resolution_method: str
    qlip_repo_root: str | None
    skill_loop_repo_root: str | None
    corpus_root: str
    attempted_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScaffoldCorpusConfigurationError(RuntimeError):
    """Structured failure raised when no usable scaffold corpus is found."""

    def __init__(self, message: str, *, attempted_paths: Iterable[Path], qlip_repo_root: Path | None) -> None:
        self.resolution_method = "configuration_error"
        self.qlip_repo_root = str(qlip_repo_root) if qlip_repo_root else None
        self.skill_loop_repo_root = None
        self.corpus_root = None
        self.attempted_paths = tuple(str(path) for path in attempted_paths)
        self.details = {
            "resolution_method": self.resolution_method,
            "qlip_repo_root": self.qlip_repo_root,
            "skill_loop_repo_root": self.skill_loop_repo_root,
            "corpus_root": self.corpus_root,
            "attempted_paths": self.attempted_paths,
        }
        super().__init__(f"{message}; attempted_paths={list(self.attempted_paths)!r}")

_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "scaffold_id": "nasicon_na3zr2si2po12_c2_ordered",
        "family": "NASICON/NZP monoclinic ordered",
        "source_structure_id": "nasicon-mp1221148",
        "variable_species_by_source": {"Si": ("Si", "P"), "P": ("Si", "P")},
    },
    {
        "scaffold_id": "nasicon_na3sc2po43_r3c",
        "family": "NASICON/NZP rhombohedral",
        "source_structure_id": "nasicon-mp555608",
        "variable_species_by_source": {"Sc": ("Sc", "Zr"), "P": ("P", "Si")},
    },
    {
        "scaffold_id": "nasicon_na3ti2si2po12_cc",
        "family": "NASICON/NZP Ti silicophosphate",
        "source_structure_id": "nasicon-mp2713692",
        "variable_species_by_source": {"Si": ("Si", "P"), "P": ("Si", "P")},
    },
    {
        "scaffold_id": "nasicon_na3hftisi2po12_p1",
        "family": "NASICON/NZP Hf-bearing low symmetry",
        "source_structure_id": "nasicon-mp2715502",
        "variable_species_by_source": {
            "Hf": ("Hf", "Ti"), "Ti": ("Hf", "Ti"),
            "Si": ("Si", "P"), "P": ("Si", "P"),
        },
    },
    {
        "scaffold_id": "nzp_nazr2po43_r3c",
        "family": "NZP phosphate-only Zr",
        "source_structure_id": "nasicon-mp6475",
        "variable_species_by_source": {},
    },
    {
        "scaffold_id": "nasicon_na3ti2po43_r3",
        "family": "NASICON phosphate-only Ti",
        "source_structure_id": "nasicon-mp761046",
        "variable_species_by_source": {},
    },
    {
        "scaffold_id": "nzp_lizr2po43_p21c",
        "family": "NZP LiZr2(PO4)3 monoclinic polymorph",
        "source_structure_id": "nasicon-mp10499",
        "variable_species_by_source": {},
    },
)


def _find_qlip_repo_root(start: str | Path | None = None) -> Path:
    cursor = Path(start or __file__).expanduser().resolve()
    if cursor.is_file():
        cursor = cursor.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "qlip").is_dir():
            return candidate
    raise ScaffoldCorpusConfigurationError(
        "Unable to discover the QLIP repository root: expected pyproject.toml and src/qlip",
        attempted_paths=(cursor, *cursor.parents),
        qlip_repo_root=None,
    )


def _dataset_root(corpus_root: Path) -> Path:
    direct_manifest = corpus_root / "manifest.jsonl"
    if corpus_root.name == CORPUS_DATASET_NAME and direct_manifest.is_file():
        return corpus_root
    return corpus_root / CORPUS_DATASET_NAME


def _is_valid_corpus_root(corpus_root: Path) -> bool:
    dataset = _dataset_root(corpus_root)
    return (dataset / "manifest.jsonl").is_file() and (dataset / "cifs").is_dir()


def resolve_scaffold_corpus_root(corpus_root: str | Path | None = None) -> ScaffoldCorpusResolution:
    """Resolve scaffold corpus data with explicit, environment, packaged precedence."""

    attempted: list[Path] = []
    qlip_repo_root: Path | None = None
    try:
        qlip_repo_root = _find_qlip_repo_root()
    except ScaffoldCorpusConfigurationError:
        # Explicit and packaged installations may work without a source checkout.
        qlip_repo_root = None

    if corpus_root is not None:
        candidate = Path(corpus_root).expanduser().resolve()
        attempted.append(candidate)
        if not _is_valid_corpus_root(candidate):
            raise ScaffoldCorpusConfigurationError(
                "Explicit scaffold corpus root is not a valid corpus",
                attempted_paths=attempted,
                qlip_repo_root=qlip_repo_root,
            )
        return ScaffoldCorpusResolution(
            resolution_method="explicit_argument",
            qlip_repo_root=str(qlip_repo_root) if qlip_repo_root else None,
            skill_loop_repo_root=None,
            corpus_root=str(candidate),
            attempted_paths=tuple(str(path) for path in attempted),
        )

    configured = os.getenv(CORPUS_ENVIRONMENT_VARIABLE)
    if configured:
        candidate = Path(configured).expanduser().resolve()
        attempted.append(candidate)
        if not _is_valid_corpus_root(candidate):
            raise ScaffoldCorpusConfigurationError(
                f"{CORPUS_ENVIRONMENT_VARIABLE} does not identify a valid corpus",
                attempted_paths=attempted,
                qlip_repo_root=qlip_repo_root,
            )
        return ScaffoldCorpusResolution(
            resolution_method="environment_variable",
            qlip_repo_root=str(qlip_repo_root) if qlip_repo_root else None,
            skill_loop_repo_root=None,
            corpus_root=str(candidate),
            attempted_paths=tuple(str(path) for path in attempted),
        )

    packaged = Path(__file__).resolve().parent / "data" / "corpora"
    attempted.append(packaged)
    if _is_valid_corpus_root(packaged):
        return ScaffoldCorpusResolution(
            resolution_method="packaged_data",
            qlip_repo_root=str(qlip_repo_root) if qlip_repo_root else None,
            skill_loop_repo_root=None,
            corpus_root=str(packaged),
            attempted_paths=tuple(str(path) for path in attempted),
        )

    raise ScaffoldCorpusConfigurationError(
        "No valid scaffold corpus was found by explicit, environment, or packaged-data discovery",
        attempted_paths=attempted,
        qlip_repo_root=qlip_repo_root,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(root: Path) -> dict[str, dict[str, str]]:
    artifact = root.parents[2] / "artifacts" / "paper_diversity_v2" / "nasicon_corpus" / "NASICON_V3_RETAINED_MANIFEST.csv"
    if artifact.is_file():
        with artifact.open(encoding="utf-8", newline="") as handle:
            return {row["internal_id"]: row for row in csv.DictReader(handle)}
    manifest: dict[str, dict[str, str]] = {}
    for line in (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        import json
        row = json.loads(line)
        manifest[str(row["internal_id"])] = {key: str(value) for key, value in row.items()}
    return manifest


def _role(symbol: str) -> str:
    if symbol == "O":
        return "oxygen_framework"
    if symbol in {"Na", "Li", "K", "Rb", "Cs"}:
        return "mobile_ion"
    if symbol in {"P", "Si", "S"}:
        return "tetrahedral_framework"
    return "octahedral_framework"


def _orbit_records(structure: Structure, allowed_by_source: dict[str, tuple[str, ...]]) -> tuple[dict[str, Any], ...]:
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
    symmetrized = analyzer.get_symmetrized_structure()
    records: list[dict[str, Any]] = []
    for number, indices in enumerate(symmetrized.equivalent_indices):
        site_indices = tuple(int(value) for value in indices)
        symbols = {structure[index].specie.symbol for index in site_indices}
        if len(symbols) != 1:
            raise ValueError(f"symmetry orbit {number} contains mixed source species: {sorted(symbols)}")
        source_species = next(iter(symbols))
        orbit_id = f"orbit_{number:03d}_{source_species.lower()}"
        allowed = tuple(allowed_by_source.get(source_species, (source_species,)))
        records.append(
            {
                "orbit_id": orbit_id,
                "site_indices": site_indices,
                "source_species": source_species,
                "multiplicity": len(site_indices),
                "coordination_role": _role(source_species),
                "allowed_species": allowed,
                "vacancy_allowed": False,
                "occupation_mode": "VARIABLE_FULL_ORBIT" if len(allowed) > 1 else "FIXED_FULL_ORBIT",
            }
        )
    return tuple(records)


def _build(source: dict[str, Any], corpus_root: Path, manifest: dict[str, dict[str, str]]) -> ScaffoldRecord:
    source_id = str(source["source_structure_id"])
    cif_path = corpus_root / "cifs" / f"{source_id}.cif"
    if not cif_path.is_file():
        raise FileNotFoundError(f"scaffold source CIF missing: {cif_path}")
    frozen = manifest.get(source_id)
    if frozen is None:
        raise KeyError(f"scaffold source absent from frozen v3 manifest: {source_id}")
    digest = _sha256(cif_path)
    if digest != frozen.get("cif_sha256"):
        raise ValueError(f"scaffold source hash mismatch for {source_id}")
    structure = Structure.from_file(cif_path)
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
    orbits = _orbit_records(structure, dict(source["variable_species_by_source"]))
    lattice = structure.lattice
    multiplicities = {item["orbit_id"]: int(item["multiplicity"]) for item in orbits}
    roles = {item["orbit_id"]: str(item["coordination_role"]) for item in orbits}
    fixed = {
        item["orbit_id"]: tuple(item["allowed_species"])
        for item in orbits if item["occupation_mode"] == "FIXED_FULL_ORBIT"
    }
    variable = {
        item["orbit_id"]: tuple(item["allowed_species"])
        for item in orbits if item["occupation_mode"] == "VARIABLE_FULL_ORBIT"
    }
    return ScaffoldRecord(
        scaffold_id=str(source["scaffold_id"]),
        scaffold_version=SCAFFOLD_VERSION,
        family=str(source["family"]),
        source_structure_id=source_id,
        source_cif_path=str(cif_path),
        source_cif_sha256=digest,
        source_formula=structure.composition.reduced_formula,
        source_space_group=analyzer.get_space_group_symbol(),
        lattice={
            "a": float(lattice.a), "b": float(lattice.b), "c": float(lattice.c),
            "alpha": float(lattice.alpha), "beta": float(lattice.beta), "gamma": float(lattice.gamma),
        },
        fractional_candidate_sites=tuple(tuple(float(x) for x in site.frac_coords) for site in structure),
        symmetry_orbits=orbits,
        orbit_multiplicities=multiplicities,
        orbit_coordination_roles=roles,
        fixed_species_allowlist=fixed,
        variable_species_allowlist=variable,
        vacancy_allowed_by_orbit={item["orbit_id"]: bool(item["vacancy_allowed"]) for item in orbits},
        topology_policy="nasicon_ordered_coordination_single_component_rank3_proxy_v1",
        provenance={
            "source": frozen.get("source", "Materials Project"),
            "source_id": frozen.get("source_id", source_id.replace("nasicon-", "")),
            "source_query": frozen.get("source_query", ""),
            "topology_tier": frozen.get("topology_tier", ""),
            "family_assignment_method": frozen.get("family_assignment_method", ""),
            "derivation": "candidate coordinates and symmetry orbits derived directly from hash-verified frozen CIF",
        },
        validation_status="VERIFIED",
    )


@lru_cache(maxsize=4)
def _records(corpus_root_text: str) -> tuple[ScaffoldRecord, ...]:
    root = Path(corpus_root_text)
    manifest = _manifest(root)
    records = tuple(_build(source, root, manifest) for source in _SOURCES)
    ids = [record.scaffold_id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scaffold_id in registry")
    return records


def list_scaffolds(*, corpus_root: str | Path | None = None) -> list[ScaffoldRecord]:
    resolution = resolve_scaffold_corpus_root(corpus_root)
    root = _dataset_root(Path(resolution.corpus_root))
    return list(_records(str(root)))


def get_scaffold(scaffold_id: str, *, corpus_root: str | Path | None = None) -> ScaffoldRecord:
    for record in list_scaffolds(corpus_root=corpus_root):
        if record.scaffold_id == scaffold_id:
            return record
    raise KeyError(f"unknown scaffold_id: {scaffold_id}")


def validate_scaffold(scaffold: str | ScaffoldRecord, *, corpus_root: str | Path | None = None) -> ScaffoldValidation:
    record = get_scaffold(scaffold, corpus_root=corpus_root) if isinstance(scaffold, str) else scaffold
    errors: list[str] = []
    source_path = Path(record.source_cif_path)
    if not source_path.is_file():
        errors.append("source_cif_missing")
    elif _sha256(source_path) != record.source_cif_sha256:
        errors.append("source_cif_sha256_mismatch")
    if sum(record.orbit_multiplicities.values()) != len(record.fractional_candidate_sites):
        errors.append("orbit_multiplicity_site_count_mismatch")
    claimed = [index for orbit in record.symmetry_orbits for index in orbit["site_indices"]]
    if sorted(claimed) != list(range(len(record.fractional_candidate_sites))):
        errors.append("orbit_site_partition_invalid")
    if any(not values for values in record.fixed_species_allowlist.values()):
        errors.append("empty_fixed_species_allowlist")
    if any(not values for values in record.variable_species_allowlist.values()):
        errors.append("empty_variable_species_allowlist")
    return ScaffoldValidation(valid=not errors, errors=tuple(errors))


def registry_as_dicts(records: Iterable[ScaffoldRecord] | None = None) -> list[dict[str, Any]]:
    return [record.to_dict() for record in (records or list_scaffolds())]
