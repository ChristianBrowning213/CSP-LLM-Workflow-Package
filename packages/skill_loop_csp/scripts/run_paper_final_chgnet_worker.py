"""Execute the frozen paper_final_v1 CHGNet protocol in the SCA environment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.core import Structure
from pymatgen.io.cif import CifWriter


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_hash(model: Any) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode())
        digest.update(tensor.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def max_force(values: Any) -> float | None:
    array = np.asarray(values, dtype=float)
    if not array.size or not np.isfinite(array).all():
        return None
    return float(np.linalg.norm(array, axis=1).max())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def run(manifest: Path, root: Path) -> None:
    from chgnet.model.dynamics import StructOptimizer
    from chgnet.model.model import CHGNet
    import torch

    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    model = CHGNet.load()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    relaxer = StructOptimizer(model=model, optimizer_class="FIRE", use_device=device)
    provenance = {
        "package": "chgnet",
        "package_version": importlib.metadata.version("chgnet"),
        "model": getattr(model, "model_name", "CHGNet pretrained"),
        "model_parameter_sha256": model_hash(model),
        "device": device,
        "optimizer": "FIRE",
        "fmax_eV_per_A": 0.1,
        "maximum_steps": 80,
        "relax_cell": True,
        "timeout_s": None,
        "timeout_policy": "no wrapper timeout; maximum optimizer steps is the terminal control",
        "stress_treatment": "CHGNet StructOptimizer default cell filter",
    }
    write_json(root / "CHGNET_MODEL_PROVENANCE.json", provenance)
    for index, row in enumerate(rows, start=1):
        task_id = row["task_id"]
        print(f"relax {index}/{len(rows)} {task_id}", flush=True)
        source = Path(row["generated_cif_path"])
        run_root = root / "runs" / task_id / "mlip"
        result_path = run_root / "result.json"
        relaxed_path = run_root / "relaxed.cif"
        if result_path.exists() or relaxed_path.exists():
            raise FileExistsError(f"exactly-once CHGNet guard refuses existing output for {task_id}")
        if sha256(source) != row["generated_cif_sha256"]:
            raise RuntimeError(f"raw generated CIF hash mismatch for {task_id}")
        started = time.perf_counter()
        base = {"task_id": task_id, "formula": row["formula"], **provenance,
                "raw_cif_path": str(source.resolve()), "raw_cif_sha256": row["generated_cif_sha256"]}
        try:
            initial = Structure.from_file(source)
            initial_prediction = model.predict_structure(initial)
            relaxed = relaxer.relax(initial, fmax=0.1, steps=80, relax_cell=True, verbose=False)
            final = relaxed.get("final_structure") or relaxed.get("structure")
            if final is None:
                raise RuntimeError("CHGNet returned no final structure")
            trajectory = relaxed.get("trajectory")
            energies = list(getattr(trajectory, "energies", []) or [])
            forces = list(getattr(trajectory, "forces", []) or [])
            predicted_forces = initial_prediction.get("f")
            if predicted_forces is None:
                predicted_forces = initial_prediction.get("forces")
            initial_energy = initial_prediction.get("e")
            if initial_energy is None:
                initial_energy = initial_prediction.get("energy_per_atom")
            initial_energy = float(np.asarray(initial_energy).reshape(-1)[0])
            final_energy = float(energies[-1]) / len(final) if energies else None
            final_force = max_force(forces[-1]) if forces else None
            converged = final_force is not None and final_force <= 0.1
            run_root.mkdir(parents=True, exist_ok=True)
            CifWriter(final).write_file(relaxed_path)
            result = {
                **base,
                "relaxation_status": "PASS",
                "converged": converged,
                "termination_reason": "force_threshold" if converged else "maximum_steps_or_optimizer_termination",
                "initial_energy_per_atom": initial_energy,
                "final_energy_per_atom": final_energy,
                "energy_change_per_atom": final_energy - initial_energy if final_energy is not None else None,
                "initial_max_force_eV_per_A": max_force(predicted_forces),
                "final_max_force_eV_per_A": final_force,
                "relaxation_steps": len(energies),
                "initial_volume_A3": float(initial.volume),
                "relaxed_volume_A3": float(final.volume),
                "volume_change_percent": 100.0 * (float(final.volume) - float(initial.volume)) / float(initial.volume),
                "relaxed_cif_path": str(relaxed_path.resolve()),
                "relaxed_cif_sha256": sha256(relaxed_path),
                "runtime_s": time.perf_counter() - started,
                "error": "",
            }
        except Exception as exc:
            result = {**base, "relaxation_status": "FAILED_RELAXATION", "converged": False,
                      "runtime_s": time.perf_counter() - started, "error": f"{type(exc).__name__}: {exc}"}
        write_json(result_path, result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    run(args.manifest.resolve(), args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
