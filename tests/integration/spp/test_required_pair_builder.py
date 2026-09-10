import hashlib

from ase import Atoms
from ase.io import write

from llm_csp.spp import collect_required_pair_distances, export_required_pair_spp_root


def _write_nacl_corpus(root):
    root.mkdir()
    first = Atoms("NaCl", scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5]], cell=[5.6] * 3, pbc=True)
    second = Atoms("NaCl", scaled_positions=[[0, 0, 0], [0.45, 0.45, 0.45]], cell=[5.8] * 3, pbc=True)
    write(root / "b.cif", second, format="cif")
    write(root / "a.cif", first, format="cif")


def _pot_hashes(root):
    return {
        str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.POT"))
    }


def test_mixed_cif_corpus_accumulates_required_pair_evidence_deterministically(tmp_path):
    corpus = tmp_path / "cifs"
    _write_nacl_corpus(corpus)
    first = collect_required_pair_distances(
        corpus, "NaCl", cutoff=6.0, supercell=(1, 1, 1), max_distances_per_pair=128
    )
    second = collect_required_pair_distances(
        corpus, "NaCl", cutoff=6.0, supercell=(1, 1, 1), max_distances_per_pair=128
    )
    assert first["required_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert first["missing_pairs"] == []
    assert first["corpus_cif_files"] == second["corpus_cif_files"]
    assert first["pair_histograms"] == second["pair_histograms"]
    assert [path.split("\\")[-1] for path in first["corpus_cif_files"]] == ["a.cif", "b.cif"]


def test_fresh_required_pair_export_preserves_source_builder_output(tmp_path):
    corpus = tmp_path / "cifs"
    _write_nacl_corpus(corpus)
    root_a = tmp_path / "first" / "spp_root"
    root_b = tmp_path / "second" / "spp_root"
    kwargs = dict(
        cif_dir=corpus, formula="NaCl", name="nacl", cutoff=6.0,
        supercell=(1, 1, 1), max_distances_per_pair=128,
    )
    first = export_required_pair_spp_root(out_root=root_a, **kwargs)
    second = export_required_pair_spp_root(out_root=root_b, **kwargs)
    assert first["required_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert first["missing_pairs"] == []
    assert first["fitted_pairs"] == first["required_pairs"]
    assert _pot_hashes(root_a) == _pot_hashes(root_b)
