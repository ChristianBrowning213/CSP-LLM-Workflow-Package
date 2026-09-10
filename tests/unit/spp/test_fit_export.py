import json

import numpy as np
from ase import Atoms

from llm_csp.spp.export import export_spp_root
from llm_csp.spp.fit_hist import accumulate_histograms, make_uniform_binning
from llm_csp.spp.fit_phi import build_phi_from_hist
from llm_csp.spp.pot_io import read_pot_like_qlip


def _atoms():
    return Atoms("NaCl", scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5]], cell=[5.6] * 3, pbc=True)


def test_histogram_phi_and_canonical_pot_export_are_deterministic(tmp_path):
    binning = make_uniform_binning(d_min=0.5, d_max=8.0, bin_width=0.1)
    assert binning.nbins == 75
    hist = accumulate_histograms([_atoms()], r_cut=8.0, d_min=0.5, d_max=8.0, bin_width=0.1)
    first = build_phi_from_hist(hist, alpha=1e-3, shifted=True)
    second = build_phi_from_hist(hist, alpha=1e-3, shifted=True)
    assert first.pairs == second.pairs
    assert np.array_equal(first.phi, second.phi)

    root = tmp_path / "pot-root"
    export_spp_root(root, first, name="synthetic")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["pairs"]:
        label = f"{item['A']}-{item['B']}"
        assert item["path"] == f"{label}/{label}.POT"
        r_values, phi_values = read_pot_like_qlip(root / item["path"])
        assert len(r_values) == len(phi_values) == first.binning.nbins
        assert np.all(np.isfinite(phi_values))


def test_qlip_pot_reader_tolerates_legacy_header_encoding(tmp_path):
    path = tmp_path / "legacy.POT"
    path.write_bytes(b"# Born\x96Mayer header\n1.0 2.0\n2.0 3.0\n")

    r_values, u_values = read_pot_like_qlip(path)

    assert r_values.tolist() == [1.0, 2.0]
    assert u_values.tolist() == [2.0, 3.0]
