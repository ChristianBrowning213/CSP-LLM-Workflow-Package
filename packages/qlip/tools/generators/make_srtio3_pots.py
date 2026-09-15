#!/usr/bin/env python3
# make_srtio3_pots.py — generate SPP .POT tables for Sr/Ti/O
# Writes BOTH orders (A-B, B-A) and BOTH casings (Title, UPPER) to match any loader.

import os, math, pathlib

ROOT = pathlib.Path("src/qlip/interactions/SPP/SPP").resolve()
ROOT.mkdir(parents=True, exist_ok=True)

# Born–Mayer (C=0) + Wolf-screened Coulomb (simple, literature-style)
BM = {("Sr","O"): (1769.51, 0.319894),
      ("Ti","O"): (14567.40, 0.197584),
      ("O","O"):  (6249.17, 0.231472)}
Q  = {"Sr": +1.84, "Ti": +2.36, "O": -1.40}
ALPHA, RC = 0.2, 10.0
SCALE_CATION = 0.25  # gentle SR repulsion for Sr–Sr, Ti–Ti, Sr–Ti

def born_mayer(r, A, rho): return 0.0 if r<=1e-12 else A*math.exp(-r/rho)
def coulomb_wolf(r, qi, qj, alpha=ALPHA, rc=RC):
    if r<=1e-12: return 0.0
    v = (qi*qj)* (math.erfc(alpha*r)/r)
    v_rc = (qi*qj)* (math.erfc(alpha*rc)/rc)
    return v - v_rc

def pair_params(a,b):
    if (a,b) in BM: return BM[(a,b)]
    if (b,a) in BM: return BM[(b,a)]
    Aso,rhoso = BM[("Sr","O")]
    return (SCALE_CATION*Aso, rhoso)

def write_pair(a,b, rmin=1.2, rmax=10.0, npts=800):
    qi, qj = Q[a], Q[b]
    A, rho = pair_params(a,b)
    dr = (rmax-rmin)/(npts-1)
    rows = []
    for k in range(npts):
        r = rmin + k*dr
        u = born_mayer(r,A,rho) + coulomb_wolf(r,qi,qj)
        rows.append((r,u))

    # Title Case dir/file (e.g., O-Sr/O-Sr.POT)
    title_dir = ROOT / f"{a}-{b}"
    title_dir.mkdir(parents=True, exist_ok=True)
    with open(title_dir / f"{a}-{b}.POT", "w") as f:
        f.write("# r(Ang)  U(eV)  Born–Mayer + Wolf Coulomb\n")
        f.write(f"# A={A:.6f} rho={rho:.6f} q[{a}]={qi:.2f} q[{b}]={qj:.2f} alpha={ALPHA} rc={RC}\n")
        for r,u in rows: f.write(f"{r:8.4f}  {u: .8f}\n")

    # UPPERCASE mirror (e.g., O-SR/O-SR.POT)
    AU, BU = a.upper(), b.upper()
    upper_dir = ROOT / f"{AU}-{BU}"
    upper_dir.mkdir(parents=True, exist_ok=True)
    with open(upper_dir / f"{AU}-{BU}.POT", "w") as f:
        f.write("# r(Ang)  U(eV)  Born–Mayer + Wolf Coulomb\n")
        f.write(f"# A={A:.6f} rho={rho:.6f} q[{AU}]={qi:.2f} q[{BU}]={qj:.2f} alpha={ALPHA} rc={RC}\n")
        for r,u in rows: f.write(f"{r:8.4f}  {u: .8f}\n")

    print("wrote", title_dir / f"{a}-{b}.POT", "and", upper_dir / f"{AU}-{BU}.POT")

def main():
    elems = ["Sr","Ti","O"]
    pairs = set()
    for i,a in enumerate(elems):
        for b in elems[i:]:
            pairs.add((a,b))
            pairs.add((b,a))  # both orders

    for a,b in sorted(pairs):
        write_pair(a,b)

if __name__ == "__main__":
    main()
