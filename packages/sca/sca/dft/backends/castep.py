"""Deterministic CASTEP input adapter and conservative text-output parser."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from pymatgen.core import Structure

from sca.dft.backends.base import DFTBackend
from sca.dft.io import write_json
from sca.dft.schema import DFTCalculationSpec, DFTFailureType, DFTResult, DFTStatus


class CastepBackend(DFTBackend):
    name = "castep"
    default_executable = "castep.mpi"

    def prepare(self, spec: DFTCalculationSpec, out_dir: str | Path) -> Path:
        problems = _validate_source(spec)
        if problems:
            raise ValueError("; ".join(problems))
        source = Path(spec.input_cif_path)
        target = Path(out_dir) / spec.calculation_id
        target.mkdir(parents=True, exist_ok=True)
        input_cif = target / "input.cif"
        shutil.copyfile(source, input_cif)
        (target / "input.sha256").write_text(spec.input_cif_sha256 + "\n", encoding="ascii")
        write_json(target / "calculation.json", spec)
        write_json(
            target / "environment.json",
            {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "backend": self.name,
                "executable_available": self.executable_available(),
                "environment_keys_recorded": ["CASTEP_COMMAND"],
                "CASTEP_COMMAND": os.environ.get("CASTEP_COMMAND"),
            },
        )
        fingerprint = spec.compatibility_fingerprint
        write_json(
            target / "settings_fingerprint.json",
            {"sha256": fingerprint.digest(), "compatibility": fingerprint.model_dump(mode="json")},
        )
        structure = Structure.from_file(source)
        seed = _safe_seed(spec.calculation_id)
        (target / f"{seed}.cell").write_text(_render_cell(structure, spec), encoding="utf-8")
        (target / f"{seed}.param").write_text(_render_param(spec), encoding="utf-8")
        return target

    def validate_inputs(self, calculation_dir: str | Path) -> list[str]:
        root = Path(calculation_dir)
        required = ["calculation.json", "input.cif", "input.sha256", "environment.json", "settings_fingerprint.json"]
        problems = [f"missing {name}" for name in required if not (root / name).is_file()]
        if not list(root.glob("*.cell")):
            problems.append("missing CASTEP .cell file")
        if not list(root.glob("*.param")):
            problems.append("missing CASTEP .param file")
        if not problems:
            spec = DFTCalculationSpec.model_validate_json((root / "calculation.json").read_text(encoding="utf-8"))
            actual = hashlib.sha256((root / "input.cif").read_bytes()).hexdigest()
            if actual != spec.input_cif_sha256:
                problems.append("input.cif SHA256 does not match calculation.json")
        return problems

    def parse(self, calculation_dir: str | Path) -> DFTResult:
        root = Path(calculation_dir)
        try:
            spec = DFTCalculationSpec.model_validate_json((root / "calculation.json").read_text(encoding="utf-8"))
        except Exception as exc:
            return _failure(root, None, DFTFailureType.PARSER_ERROR, str(exc))
        outputs = sorted(root.glob("*.castep"))
        if not outputs:
            return _failure(root, spec, DFTFailureType.MISSING_OUTPUT, "No .castep output found")
        output = outputs[-1]
        text = output.read_text(encoding="utf-8", errors="replace")
        failure = _classify_failure(text)
        converged = bool(re.search(r"Geometry optimization completed successfully|SCF converged", text, re.I))
        if failure is None and not converged:
            failure = DFTFailureType.IONIC_NOT_CONVERGED if spec.calculation_type == "RELAX" else DFTFailureType.SCF_NOT_CONVERGED
        total_energy = _last_float(text, (r"Final energy\s*[=:]\s*([-+\d.Ee]+)", r"Final free energy[^=]*=\s*([-+\d.Ee]+)"))
        max_force = _last_float(text, (r"Max(?:imum)? force\s*[=:]\s*([-+\d.Ee]+)",))
        ionic_steps = _last_int(text, (r"(?:BFGS|Geometry) iteration\s+(\d+)",))
        scf_iterations = len(re.findall(r"(?:SCF|Iteration)\s+\d+", text, re.I)) or None
        runtime = _last_float(text, (r"Total time\s*[=:]\s*([-+\d.Ee]+)",))
        relaxed = _find_relaxed_cif(root)
        final_volume = None
        if relaxed:
            try:
                final_volume = float(Structure.from_file(relaxed).volume)
            except Exception:
                pass
        count = len(Structure.from_file(root / "input.cif"))
        return DFTResult(
            calculation_id=spec.calculation_id,
            candidate_id=spec.candidate_id,
            status=DFTStatus.COMPLETED if converged and failure is None else (DFTStatus.TIMEOUT if failure == DFTFailureType.WALLTIME else DFTStatus.NOT_CONVERGED),
            converged=converged and failure is None,
            failure_type=failure,
            failure_message=None if failure is None else f"CASTEP output classified as {failure.value}",
            initial_cif=str(root / "input.cif"),
            relaxed_cif=str(relaxed) if relaxed else None,
            total_energy_eV=total_energy,
            energy_per_atom_eV=total_energy / count if total_energy is not None and count else None,
            max_force_eV_A=max_force,
            num_ionic_steps=ionic_steps,
            num_scf_iterations=scf_iterations,
            final_volume=final_volume,
            runtime_seconds=runtime,
            stdout_path=str(output),
            stderr_path=str(root / "stderr.txt") if (root / "stderr.txt").exists() else None,
            engine_version=_first_match(text, r"CASTEP version\s+([^\s]+)"),
            compatibility_fingerprint=spec.compatibility_fingerprint,
        )

    def validate_outputs(self, calculation_dir: str | Path) -> list[str]:
        return [] if list(Path(calculation_dir).glob("*.castep")) else ["missing CASTEP .castep output"]

    def executable_available(self, executable: str | None = None) -> bool:
        command = executable or os.environ.get("CASTEP_COMMAND") or self.default_executable
        return shutil.which(command) is not None

    def version(self, executable: str | None = None) -> str | None:
        command = executable or os.environ.get("CASTEP_COMMAND") or self.default_executable
        if shutil.which(command) is None:
            return None
        try:
            result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return (result.stdout or result.stderr).strip().splitlines()[0] or None


def _validate_source(spec: DFTCalculationSpec) -> list[str]:
    source = Path(spec.input_cif_path)
    if not source.is_file():
        return [f"input CIF does not exist: {source}"]
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    return [] if actual == spec.input_cif_sha256 else ["input CIF SHA256 mismatch"]


def _render_cell(structure: Structure, spec: DFTCalculationSpec) -> str:
    lines = ["# Generated by SCA; scientific settings are in calculation.json", "%BLOCK LATTICE_CART", "ang"]
    lines.extend("  " + "  ".join(f"{value:.12f}" for value in vector) for vector in structure.lattice.matrix)
    lines.extend(["%ENDBLOCK LATTICE_CART", "", "%BLOCK POSITIONS_FRAC"])
    lines.extend(f"  {site.specie.symbol}  " + "  ".join(f"{value:.12f}" for value in site.frac_coords) for site in structure)
    lines.extend(["%ENDBLOCK POSITIONS_FRAC", "", f"KPOINT_MP_SPACING {spec.kpoint_spacing}", f"FIX_ALL_CELL {'false' if spec.calculation_type == 'RELAX' else 'true'}", ""])
    return "\n".join(lines)


def _render_param(spec: DFTCalculationSpec) -> str:
    task = "GeometryOptimization" if spec.calculation_type == "RELAX" else "SinglePoint"
    lines = [
        "# Generated by SCA; no hidden scientific settings",
        f"task : {task}",
        f"xc_functional : {spec.xc_functional}",
        f"cut_off_energy : {spec.cutoff_energy} eV",
        f"elec_energy_tol : {spec.energy_tolerance} eV",
        f"max_scf_cycles : {spec.max_steps}",
        f"spin_polarized : {str(spec.spin_polarized).lower()}",
        f"charge : {spec.charge}",
    ]
    if spec.force_tolerance is not None:
        lines.append(f"geom_force_tol : {spec.force_tolerance} eV/Ang")
    if spec.stress_tolerance is not None:
        lines.append(f"geom_stress_tol : {spec.stress_tolerance} GPa")
    if spec.dispersion:
        lines.append(f"sedc_apply : true\n# dispersion convention: {spec.dispersion}")
    return "\n".join(lines) + "\n"


def _failure(root: Path, spec: DFTCalculationSpec | None, failure: DFTFailureType, message: str) -> DFTResult:
    return DFTResult(
        calculation_id=spec.calculation_id if spec else root.name,
        candidate_id=spec.candidate_id if spec else "UNKNOWN",
        status=DFTStatus.FAILED,
        converged=False,
        failure_type=failure,
        failure_message=message,
        initial_cif=str(root / "input.cif") if (root / "input.cif").exists() else None,
        compatibility_fingerprint=spec.compatibility_fingerprint if spec else None,
    )


def _classify_failure(text: str) -> DFTFailureType | None:
    patterns = (
        (r"wall ?time|time limit", DFTFailureType.WALLTIME),
        (r"out of memory|oom-kill", DFTFailureType.MEMORY),
        (r"pseudopotential.*(?:missing|error|failed)", DFTFailureType.BAD_PSEUDOPOTENTIAL),
        (r"SCF.*not converge|electronic minimization.*failed", DFTFailureType.SCF_NOT_CONVERGED),
        (r"geometry optimization.*not converge|maximum.*geometry.*iterations", DFTFailureType.IONIC_NOT_CONVERGED),
        (r"segmentation fault|fatal error|aborted", DFTFailureType.ENGINE_CRASH),
    )
    return next((failure for pattern, failure in patterns if re.search(pattern, text, re.I)), None)


def _last_float(text: str, patterns: tuple[str, ...]) -> float | None:
    values: list[str] = []
    for pattern in patterns:
        values.extend(re.findall(pattern, text, re.I))
    try:
        return float(values[-1]) if values else None
    except ValueError:
        return None


def _last_int(text: str, patterns: tuple[str, ...]) -> int | None:
    value = _last_float(text, patterns)
    return int(value) if value is not None else None


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.I)
    return match.group(1) if match else None


def _find_relaxed_cif(root: Path) -> Path | None:
    for name in ("relaxed.cif", "final.cif"):
        if (root / name).is_file():
            return root / name
    return None


def _safe_seed(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "calculation"
