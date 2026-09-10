from pathlib import Path

from ase import Atoms
from ase.io import write

from llm_csp.spp.io_cif import load_cif, load_cifs_from_dir
from llm_csp.spp.neighbors import build_neighbor_edges, pairwise_mic_distances


def test_cif_loading_and_periodic_neighbors(tmp_path):
    atoms = Atoms("NaCl", scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5]], cell=[5.6] * 3, pbc=True)
    path = tmp_path / "synthetic.cif"
    write(path, atoms, format="cif")
    loaded = load_cif(path)
    assert loaded.atoms.get_chemical_symbols() == ["Na", "Cl"]
    assert [Path(item.path).name for item in load_cifs_from_dir(tmp_path)] == ["synthetic.cif"]
    distances = pairwise_mic_distances(loaded.atoms)
    assert distances.shape == (2, 2)
    edges = build_neighbor_edges(loaded.atoms, r_cut=5.0)
    assert edges and all(edge.i != edge.j for edge in edges)
