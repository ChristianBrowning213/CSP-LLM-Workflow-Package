#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, re, shutil
from pathlib import Path
from typing import Optional
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def _san(s:str)->str: return re.sub(r"[^A-Za-z0-9_.-]+","_",s)
def _ensure(p:Path): p.mkdir(parents=True, exist_ok=True)

def _plot_fallback(m:dict, png:Path):
    anchor=np.array([0.0,0.0,0.0],float)
    neigh=[(sp,(np.array(dv,float)%1.0)) for sp,dv in m.get("neighbors",[])]
    fig=plt.figure(figsize=(5.2,5.2)); ax=fig.add_subplot(111,projection="3d")
    for sp,p in neigh:
        dv=(p-anchor+0.5)%1.0-0.5; seg=np.stack([anchor,anchor+dv],0)
        ax.plot(seg[:,0],seg[:,1],seg[:,2],lw=1.4,color="#555")
        ax.scatter([p[0]],[p[1]],[p[2]],s=120,color="tab:green",edgecolor="k",lw=0.3,alpha=.95)
    ax.scatter([0],[0],[0],s=160,color="tab:blue",edgecolor="k",lw=.4)
    ax.set_axis_off(); plt.tight_layout(); png.parent.mkdir(parents=True,exist_ok=True)
    plt.savefig(png,dpi=220,transparent=True); plt.close(fig)

def _call_vesta(vesta_exe:str, cif:Path, out_png:Path, timeout:int=25) -> bool:
    """Use VESTA CLI and auto-close. Works with standard Windows build."""
    exe = shutil.which(vesta_exe) if not Path(vesta_exe).exists() else str(Path(vesta_exe))
    if not exe: return False
    out_png.parent.mkdir(parents=True, exist_ok=True)
    # Most recent VESTA accepts: -open <cif> -export_img <png> -close
    cmd = [exe, "-open", str(cif), "-export_img", str(out_png), "-close"]
    try:
        subprocess.run(cmd, check=False, timeout=timeout)
        return out_png.exists() and out_png.stat().st_size > 0
    except Exception:
        return False

def _write_temp_cif_from_motif(m:dict, out:Path, a:float):
    # anchor at origin; neighbors are canonical disp in (-0.5,0.5], write in smallest cell from miner meta if available
    fpos = [np.array([0.0,0.0,0.0])]
    for _, xyz in m.get("neighbors", []):
        fpos.append((np.array(xyz,float) % 1.0))
    syms = [m["anchor"]] + [s for s,_ in m.get("neighbors", [])]
    lines=[
        "data_motif",
        f"_cell_length_a {a:.6f}",
        f"_cell_length_b {a:.6f}",
        f"_cell_length_c {a:.6f}",
        "_cell_angle_alpha 90","_cell_angle_beta  90","_cell_angle_gamma 90",
        "loop_","_atom_site_label","_atom_site_fract_x","_atom_site_fract_y","_atom_site_fract_z",
    ]
    for i,(s,f) in enumerate(zip(syms, fpos)):
        lines.append(f"{s}{i+1:03d}  {f[0]:.6f}  {f[1]:.6f}  {f[2]:.6f}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines)+"\n", encoding="utf-8")
    return out

def render_gallery(chem:str, motifs_json:Path, out_root:Path, vesta_exe:str):
    doc=json.loads(Path(motifs_json).read_text())
    motifs=doc["motifs"] if isinstance(doc,dict) and "motifs" in doc else doc
    meta =doc.get("_meta",{}) if isinstance(doc,dict) else {}
    a=float(meta.get("a", 3.9))

    artifacts_dir = Path(motifs_json).parent
    motifs_cif_dir = artifacts_dir/"motifs_cif"   # miner writes minimal cells here

    chem_dir = out_root/_san(chem)
    tpl_dir  = chem_dir/"templates"
    _ensure(tpl_dir)

    written=[]
    for m in motifs:
        name=_san(m["name"])
        png = tpl_dir/f"{name}.png"

        # Prefer the miner's minimal-cell CIF; else synth temp CIF at the same a
        cif = motifs_cif_dir/f"{name}.cif"
        if not cif.exists():
            cif = tpl_dir/f"{name}.cif"
            _write_temp_cif_from_motif(m, cif, a=a/(m.get("local_grid_m",1) or 1))

        ok = _call_vesta(vesta_exe, cif, png)
        if not ok:
            _plot_fallback(m, png)

        written.append(str(png))

    return written

def main():
    import argparse
    ap=argparse.ArgumentParser(description="VESTA-first motif renderer (auto-close).")
    ap.add_argument("--chem", required=True)
    ap.add_argument("--motifs", required=True)
    ap.add_argument("--out_dir", default="viz/motifs")
    ap.add_argument("--vesta_exe", required=True, help="Path or name of VESTA executable (e.g. VESTA.exe)")
    args=ap.parse_args()

    out = render_gallery(args.chem, Path(args.motifs), Path(args.out_dir), args.vesta_exe)
    print(f"[viz_all] wrote {len(out)} image(s).")
    for p in out: print(" -", p)

if __name__=="__main__":
    main()
