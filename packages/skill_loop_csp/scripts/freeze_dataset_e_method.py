"""Freeze the Dataset E scaffold and validator before final-row selection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow.dataset_e_validation import (  # noqa: E402
    MATCHER_SETTINGS,
    SYMMETRY_TOLERANCE,
    VALIDATOR_VERSION,
    load_development_references,
    validate_dataset_e_topology,
)
from sok_llm_orchestrator.workflow.paper_scaffolds_dataset_e import (  # noqa: E402
    SCAFFOLD_LIBRARY_VERSION,
    SUPPORTED_SUBTYPES,
)


ARTIFACT = (
    REPO / "artifacts" / "Paper_scaffolds_september" / "Dataset_E_complex_topology_showcase"
)
TEMPLATES = ARTIFACT / "DEVELOPMENT_SCAFFOLD_TEMPLATES.json"
DEVELOPMENT_FREEZE = ARTIFACT / "DEVELOPMENT_ROSTER_FREEZE.json"
SCAFFOLD_SOURCE = REPO / "src" / "sok_llm_orchestrator" / "workflow" / "paper_scaffolds_dataset_e.py"
VALIDATOR_SOURCE = REPO / "src" / "sok_llm_orchestrator" / "workflow" / "dataset_e_validation.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    positive = []
    for subtype in sorted(SUPPORTED_SUBTYPES):
        for reference_id, structure in load_development_references(subtype):
            result = validate_dataset_e_topology(structure, subtype)
            positive.append(
                {
                    "subtype": subtype,
                    "development_structure_id": reference_id,
                    "status": result["status"],
                    "match_count": result["match_count"],
                }
            )
    negative_pairs = [
        ("RP_N1", "RP_N2"),
        ("RP_N2", "RP_N1"),
        ("GARNET_IA3D", "GARNET_I41ACD"),
        ("GARNET_I41ACD", "GARNET_IA3D"),
        ("ARGYRODITE_F43M", "ARGYRODITE_PNA21"),
        ("ARGYRODITE_PNA21", "ARGYRODITE_CC"),
        ("ARGYRODITE_CC", "ARGYRODITE_F43M"),
        ("NASICON_R3_PHOSPHATE", "GARNET_IA3D"),
    ]
    negative = []
    for source_subtype, tested_as in negative_pairs:
        reference_id, structure = load_development_references(source_subtype)[0]
        result = validate_dataset_e_topology(structure, tested_as)
        negative.append(
            {
                "source_subtype": source_subtype,
                "tested_as": tested_as,
                "development_structure_id": reference_id,
                "status": result["status"],
            }
        )
    if any(row["status"] != "PASS" for row in positive):
        raise RuntimeError("validator positive calibration failed")
    if any(row["status"] != "FAIL" for row in negative):
        raise RuntimeError("validator cross-topology negative calibration failed")

    validation = {
        "schema_version": "dataset_e.validation_method_freeze.v1",
        "validator_version": VALIDATOR_VERSION,
        "criterion": "ordered AND anonymous StructureMatcher match to same-subtype development reference",
        "matcher_settings": MATCHER_SETTINGS,
        "symmetry_tolerance": SYMMETRY_TOLERANCE,
        "verdicts": ["PASS", "FAIL"],
        "partial_is_not_pass": True,
        "retuning_after_final_roster_freeze_prohibited": True,
        "development_templates_sha256": sha256(TEMPLATES),
        "validator_source_sha256": sha256(VALIDATOR_SOURCE),
        "positive_calibration": positive,
        "cross_topology_negative_calibration": negative,
    }
    validation_path = ARTIFACT / "VALIDATION_METHOD_FREEZE.json"
    write_json(validation_path, validation)
    development = json.loads(DEVELOPMENT_FREEZE.read_text(encoding="utf-8"))
    method = {
        "schema_version": "dataset_e.method_freeze.v1",
        "frozen_before_final_showcase_selection": True,
        "scaffold_library_version": SCAFFOLD_LIBRARY_VERSION,
        "scaffold_source_sha256": sha256(SCAFFOLD_SOURCE),
        "development_roster_freeze_sha256": sha256(DEVELOPMENT_FREEZE),
        "development_templates_sha256": sha256(TEMPLATES),
        "validation_method_freeze_sha256": sha256(validation_path),
        "corpus_database_hashes": development["database_hashes"],
        "supported_subtypes": sorted(SUPPORTED_SUBTYPES),
        "geometry_policy": {
            "fractional_topology": "same-subtype hash-frozen development prototypes",
            "cell_shape": "same-subtype hash-frozen development prototypes",
            "absolute_volume": "unchanged v2 target-excluded retrieval VPA quartiles or frozen global fallback",
            "alternative_selection": "minimum unchanged QLIP/SPP solver objective with parity check",
        },
        "scientific_semantics": {
            "fully_ordered": True,
            "partial_occupancy": False,
            "disorder_enumeration": False,
            "target_coordinates": False,
            "target_lattice_constants": False,
            "target_cif_substitution": False,
            "spp_retuning": False,
            "qlip_objective_change": False,
        },
        "spp_protocol": {
            "bins": 200,
            "range_angstrom": [0.0, 10.0],
            "spacing_angstrom": 0.05,
            "gaussian_sigma_angstrom": 0.1,
            "statistical_transform": "dmytro_gr_v1",
            "regulator_and_blend": "unchanged frozen paper workflow",
            "periodic_multiplicity": "corrected frozen implementation",
        },
        "final_denominator_changes_after_freeze_prohibited": True,
        "failed_rows_may_not_be_replaced": True,
    }
    write_json(ARTIFACT / "METHOD_FREEZE.json", method)
    print(json.dumps(method, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
