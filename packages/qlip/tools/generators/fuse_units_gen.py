# fuse_units_gen.py
import itertools, json, numpy as np

OX = {"Sr": +2, "Ti": +4, "O": -2}
# discrete fractional offsets that land on even uniform(g) grids
OFFSETS = {
  "center": [(0,0,0)],
  "axial":  [(+0.5,0,0),(-0.5,0,0),(0,+0.5,0),(0,-0.5,0),(0,0,+0.5),(0,0,-0.5)],
  "face":   [(+0.5,+0.5,0),(+0.5,-0.5,0),(-0.5,+0.5,0),(-0.5,-0.5,0),
             (0,+0.5,+0.5),(0,+0.5,-0.5),(0,-0.5,+0.5),(0,-0.5,-0.5),
             (+0.5,0,+0.5),(+0.5,0,-0.5),(-0.5,0,+0.5),(-0.5,0,-0.5)]
}

# minimal patterns for Sr–Ti–O (extend as needed)
ATOMS = ["Sr","Ti","O"]

def charge_ok(comp, tol=0):
    return abs(sum(OX[a] for a in comp)) <= tol

def plausible(comp):
    # very light filters:
    # - don't allow all-cation or all-anion units unless size 1
    if len(comp) > 1 and all(a != "O" for a in comp): return False
    if len(comp) > 1 and all(a == "O"  for a in comp): return True   # O clusters allowed
    return True

# small geometry libraries keyed by “shape”
SHAPES = {
  "monomer": [[("center", 0)]],
  "dimer_axial": [[("center",0),("axial",i)] for i in range(6)],
  "linear_trimer": [[("center",0),("axial",i),("axial",(i+3)%6)] for i in range(3)],  # ± same axis
  "oct_like": [[("center",0)] + [("axial",i) for i in range(6)]],  # up to 7 sites; we’ll trim by comp size
  "face_square": [[("center",0)] + [("face",i) for i in range(4)]], # 5 sites; trim later
}

def pick_positions(shape, n):
    """Choose first n entries from a shape definition (naive but snaps)."""
    if n == 1: return [("center",0)]
    pattern = SHAPES.get(shape)
    if not pattern: return None
    # take first variant in pattern and then first n positions
    pos = pattern[0][:n]
    return pos

def expand_offsets(pos):
    out = []
    for kind, idx in pos:
        pool = OFFSETS[kind]
        out.append(pool[idx])
    return out

def gen_units(max_atoms=4):
    units = []
    for sz in range(1, max_atoms+1):
        for comp in itertools.combinations_with_replacement(ATOMS, sz):
            if not plausible(comp): continue
            if not charge_ok(comp, tol=0): continue
            # Try a few shapes in priority order
            for shape in ["monomer","dimer_axial","linear_trimer","face_square","oct_like"]:
                pos_spec = pick_positions(shape, len(comp))
                if not pos_spec: continue
                offsets = expand_offsets(pos_spec)
                # Pack as template
                unit = {
                    "name": f"{''.join(comp)}_{shape}_{sz}",
                    "composition": list(comp),
                    "anchor_index": 0,                 # use first atom as anchor
                    "frac_offsets": offsets,           # relative to anchor site
                }
                units.append(unit)
                break
    return units

if __name__ == "__main__":
    units = gen_units(4)
    with open("fuse_units_SrTiO.json", "w") as f:
        json.dump(units, f, indent=2)
    print(f"Wrote {len(units)} unit templates.")
