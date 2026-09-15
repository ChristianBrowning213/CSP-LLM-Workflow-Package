"""Run a hash-frozen table of CIFs through one uniform CHGNet QC protocol."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


REQUIRED_COLUMNS = ("row_id", "formula", "cif_path", "cif_sha256", "protocol_id")
PROTOCOL_ID = "chgnet_0.4.2_fire_fmax0.1_steps200_cell_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_model(model: Any) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode())
        digest.update(tensor.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"missing required columns: {', '.join(missing)}")
        rows = [{str(key): str(value or "").strip() for key, value in row.items()} for row in reader]
    seen: set[str] = set()
    for row in rows:
        if not row["row_id"] or row["row_id"] in seen:
            raise ValueError(f"row_id must be nonempty and unique: {row['row_id']!r}")
        seen.add(row["row_id"])
        source = Path(row["cif_path"]).resolve()
        if not source.is_file():
            raise ValueError(f"CIF does not exist for {row['row_id']}: {source}")
        actual = sha256(source)
        if actual != row["cif_sha256"]:
            raise ValueError(f"CIF hash mismatch for {row['row_id']}: {actual}")
        if row["protocol_id"] != PROTOCOL_ID:
            raise ValueError(f"protocol_id mismatch for {row['row_id']}: {row['protocol_id']}")
        structure = Structure.from_file(source)
        if structure.composition.reduced_composition != Composition(row["formula"]).reduced_composition:
            raise ValueError(f"formula mismatch for {row['row_id']}")
        row["cif_path"] = str(source)
    return rows


def symmetry(structure: Structure) -> tuple[str, str]:
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5)
    return analyzer.get_space_group_symbol(), analyzer.get_crystal_system()


def max_force(values: Any) -> float | None:
    array = np.asarray(values, dtype=float)
    if array.size == 0 or np.isnan(array).all():
        return None
    return float(np.linalg.norm(array, axis=1).max())


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_table(input_path: Path, output_root: Path) -> list[dict[str, Any]]:
    from chgnet.model.dynamics import StructOptimizer
    from chgnet.model.model import CHGNet
    import torch

    rows = load_rows(input_path)
    output = Path(output_root).resolve()
    relaxed_dir = output / "relaxed_cifs"
    relaxed_dir.mkdir(parents=True, exist_ok=True)
    model = CHGNet.load()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    relaxer = StructOptimizer(model=model, optimizer_class="FIRE", use_device=device)
    provenance = {
        "protocol_id": PROTOCOL_ID,
        "package_version": importlib.metadata.version("chgnet"),
        "model_identifier": getattr(model, "model_name", "CHGNet pretrained"),
        "model_parameter_sha256": hash_model(model),
        "device": device,
        "optimizer": "FIRE",
        "force_threshold_eV_per_A": 0.1,
        "maximum_steps": 200,
        "cell_relaxation": True,
        "fresh_run_utc": datetime.now(timezone.utc).isoformat(),
    }
    results: list[dict[str, Any]] = []
    matcher = StructureMatcher(
        ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=False,
        scale=False, attempt_supercell=False,
    )
    for index, row in enumerate(rows, start=1):
        print(f"relax {index}/{len(rows)} {row['row_id']}", flush=True)
        started = time.perf_counter()
        base = {
            "row_id": row["row_id"], "formula": row["formula"],
            "input_cif_path": row["cif_path"], "input_cif_sha256": row["cif_sha256"],
            **provenance,
        }
        try:
            initial = Structure.from_file(row["cif_path"])
            prediction = model.predict_structure(initial)
            relaxed = relaxer.relax(initial, fmax=0.1, steps=200, relax_cell=True, verbose=False)
            final = relaxed.get("final_structure") or relaxed.get("structure")
            if final is None:
                raise RuntimeError("CHGNet returned no final structure")
            trajectory = relaxed.get("trajectory")
            energies = list(getattr(trajectory, "energies", []) or [])
            forces = list(getattr(trajectory, "forces", []) or [])
            predicted_force = prediction.get("f")
            if predicted_force is None:
                predicted_force = prediction.get("forces")
            initial_max = max_force(predicted_force)
            final_max = max_force(forces[-1]) if forces else None
            relaxed_path = relaxed_dir / f"{row['row_id']}.cif"
            CifWriter(final).write_file(relaxed_path)
            before_sg, before_system = symmetry(initial)
            after_sg, after_system = symmetry(final)
            results.append({
                **base, "chgnet_status": "PASS", "converged": final_max is not None and final_max <= 0.1,
                "termination_reason": "force_threshold" if final_max is not None and final_max <= 0.1 else "maximum_steps_or_optimizer_termination",
                "initial_max_force": initial_max, "final_max_force": final_max,
                "relaxation_steps": len(energies), "initial_volume": float(initial.volume),
                "relaxed_volume": float(final.volume),
                "volume_change_percent": 100.0 * (float(final.volume) - float(initial.volume)) / float(initial.volume),
                "initial_space_group": before_sg, "relaxed_space_group": after_sg,
                "initial_crystal_system": before_system, "relaxed_crystal_system": after_system,
                "space_group_retained": before_sg == after_sg,
                "crystal_system_retained": before_system == after_system,
                "initial_relaxed_match": bool(matcher.fit(initial, final)),
                "relaxed_cif_path": str(relaxed_path), "relaxed_cif_sha256": sha256(relaxed_path),
                "runtime_seconds": time.perf_counter() - started, "failure_message": "",
            })
        except Exception as exc:
            results.append({
                **base, "chgnet_status": "CONTROLLED_FAILURE", "converged": False,
                "runtime_seconds": time.perf_counter() - started,
                "failure_message": f"{type(exc).__name__}: {exc}",
            })
    write_csv(output / "SCAFFOLD_CHGNET_RESULTS.csv", results)
    (output / "CHGNET_MODEL_PROVENANCE.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = run_table(args.table, args.output)
    return 0 if all(row["chgnet_status"] == "PASS" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
