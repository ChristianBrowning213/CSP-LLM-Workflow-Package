# src/qlip/visualization/vesta.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, Sequence, Tuple
import subprocess
import shutil

from ase.io import write
from ase import Atoms

# we reuse your placement extraction + CIF writer logic
from .plot import save_cif, save_poscar, _extract_placements, _placements_to_atoms


def _resolve_vesta(exe_hint: Optional[str]) -> str:
    """Resolve the VESTA executable path. If not provided, try PATH."""
    if exe_hint:
        p = Path(exe_hint)
        if p.exists():
            return str(p.resolve())
    for name in ("VESTA", "VESTA.exe"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError("VESTA executable not found. Pass vesta_exe=... or add VESTA to PATH.")


def _norm(p: Path) -> str:
    """VESTA CLI on Windows prefers absolute paths with forward slashes."""
    return str(Path(p).resolve()).replace("\\", "/")


def _write_cell_cif(task, out_cif: str = "viz/structure.cif") -> str:
    """Write a CIF for the primitive cell (what your solver produced)."""
    return save_cif(task, path=out_cif)


def _write_supercell_cif(task,
                         reps: Tuple[int,int,int],
                         out_cif: str = "viz/structure_supercell.cif") -> str:
    """Build a supercell from the solved placements and write to CIF."""
    # Rebuild Atoms for primitive cell
    placements = _extract_placements(task)
    A, B, C = task.positions.cell.lengths()
    base = _placements_to_atoms(placements, (A, B, C))
    # Make supercell
    sc = base.repeat(reps)
    out = Path(out_cif); out.parent.mkdir(parents=True, exist_ok=True)
    write(str(out), sc)
    return str(out.resolve())


def _vesta_export_and_open(cif_path: str,
                           out_png: str,
                           vesta_exe: Optional[str],
                           template_vesta: Optional[str],
                           scale: Optional[int],
                           leave_open: bool = True) -> str:
    """Common runner: export PNG and (optionally) keep VESTA open."""
    exe = _resolve_vesta(vesta_exe)
    out = Path(out_png); out.parent.mkdir(parents=True, exist_ok=True)

    # Build a GUI command (no -nogui so the window stays up)
    if template_vesta:
        tpl = Path(template_vesta)
        if not tpl.exists():
            raise FileNotFoundError(f"VESTA template not found: {tpl}")
        cmd = [exe, "-i", _norm(tpl), "-reopen", _norm(Path(cif_path)), "-flush", "-export_img"]
    else:
        cmd = [exe, "-open", _norm(Path(cif_path)), "-export_img"]

    if scale is not None:
        cmd += [f"scale={scale}", _norm(out)]
    else:
        cmd += [_norm(out)]

    # If you *did* want to close: cmd += ["-close", _norm(Path(cif_path))]
    # But per your preference, we leave it open:
    subprocess.Popen(cmd)   # return immediately; app continues running
    return str(out.resolve())


# ------------------------- Public APIs -------------------------

def open_in_vesta(task,
                  vesta_exe: Optional[str] = None,
                  also_write_poscar: bool = False) -> None:
    """Open the primitive cell in the VESTA GUI (no export)."""
    cif_path = _write_cell_cif(task, "viz/structure.cif")
    if also_write_poscar:
        save_poscar(task, "viz/POSCAR")
    exe = _resolve_vesta(vesta_exe)
    subprocess.Popen([exe, "-open", _norm(Path(cif_path))])


def render_cell_with_vesta(task,
                           out_png: str = "viz/vesta_cell.png",
                           vesta_exe: Optional[str] = None,
                           template_vesta: Optional[str] = None,
                           scale: Optional[int] = None,
                           write_poscar: bool = False,
                           leave_open: bool = True) -> str:
    """
    Export + open a single primitive cell in VESTA.
    """
    cif_path = _write_cell_cif(task, "viz/structure.cif")
    if write_poscar:
        save_poscar(task, "viz/POSCAR")
    return _vesta_export_and_open(cif_path, out_png, vesta_exe, template_vesta, scale, leave_open)


def render_supercell_with_vesta(task,
                                reps: Tuple[int,int,int] = (2,2,2),
                                out_png: str = "viz/vesta_supercell.png",
                                vesta_exe: Optional[str] = None,
                                template_vesta: Optional[str] = None,
                                scale: Optional[int] = None,
                                write_poscar: bool = False,
                                leave_open: bool = True) -> str:
    """
    Export + open a supercell (e.g., reps=(2,2,2)) in VESTA.
    """
    cif_path = _write_supercell_cif(task, reps, "viz/structure_supercell.cif")
    if write_poscar:
        save_poscar(task, "viz/POSCAR")
    return _vesta_export_and_open(cif_path, out_png, vesta_exe, template_vesta, scale, leave_open)
