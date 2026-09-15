# motif_extract.py
import json, numpy as np

def perovskite_TiO6_motif():
    return {
        "name": "TiO6",
        "anchor": "Ti",
        "anchor_frac": [0.5, 0.5, 0.5],  # B site
        "neighbors": [["O",[+0.5,0,0]],["O",[-0.5,0,0]],
                      ["O",[0,+0.5,0]],["O",[0,-0.5,0]],
                      ["O",[0,0,+0.5]],["O",[0,0,-0.5]]],
        "orientations": [[[1,0,0],[0,1,0],[0,0,1]]]
    }

def perovskite_SrO12_motif():
    # 12 O at face centers around A at 000 (use minimal rep; your placer will create all symmetry-equiv)
    face = [(+0.5,+0.5,0),(+0.5,-0.5,0),(-0.5,+0.5,0),(-0.5,-0.5,0),
            (0,+0.5,+0.5),(0,+0.5,-0.5),(0,-0.5,+0.5),(0,-0.5,-0.5),
            (+0.5,0,+0.5),(+0.5,0,-0.5),(-0.5,0,+0.5),(-0.5,0,-0.5)]
    return {
        "name": "SrO12", "anchor":"Sr", "anchor_frac":[0,0,0],
        "neighbors": [["O",v] for v in face], "orientations":[np.eye(3).tolist()]
    }

def write_motifs(path="motifs.json"):
    motifs = [perovskite_TiO6_motif(), perovskite_SrO12_motif()]
    with open(path,"w") as f: json.dump(motifs,f,indent=2)
