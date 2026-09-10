from ase import Atoms

from llm_csp.spp.export import export_spp_root
from llm_csp.spp.fit_hist import accumulate_histograms
from llm_csp.spp.fit_phi import build_phi_from_hist
from llm_csp.spp.model import load_spp_model
from llm_csp.spp.score import score_atoms


def test_score_atoms_reports_geometry_and_missing_pair_effects(tmp_path):
    reference = Atoms("NaCl", scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5]], cell=[5.6] * 3, pbc=True)
    hist = accumulate_histograms([reference], r_cut=8.0, d_min=0.5, d_max=8.0, bin_width=0.1)
    phi = build_phi_from_hist(hist, alpha=1e-3, shifted=True)
    root = tmp_path / "model"
    export_spp_root(root, phi, name="score-test")
    model = load_spp_model(root)
    original = score_atoms(reference, model, r_cut=8.0, use_bandpass=False)
    perturbed = reference.copy()
    perturbed.set_chemical_symbols(["Na", "Na"])
    changed = score_atoms(perturbed, model, r_cut=8.0, use_bandpass=False)
    assert original.num_edges > 0
    assert original.total != changed.total or original.skipped_missing_pair != changed.skipped_missing_pair
