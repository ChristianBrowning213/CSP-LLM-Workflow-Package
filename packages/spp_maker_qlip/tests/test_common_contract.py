from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from spp_maker.common_contract import (
    CONTRACT_ID, blend_contract_roots, choose_pair_blend, rebuild_global_pair_from_rdf,
)
from spp_maker.pot_io import read_pot_like_qlip, write_pot


def test_global_rdf_conversion_uses_unscaled_negative_log_contract() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); pair_dir = root / "reg" / "Fe-O"; pair_dir.mkdir(parents=True)
        r = np.arange(0.025, 10.0, 0.05); g = np.full(r.shape, 0.5)
        np.savetxt(pair_dir / "Fe-O.RDF", np.column_stack((r, g)))
        metadata = rebuild_global_pair_from_rdf(regulator_root=root / "reg", pair="O-Fe", out_root=root / "out")
        _, u = read_pot_like_qlip(Path(metadata["pot_path"]))
        assert metadata["artifact_contract"] == CONTRACT_ID
        assert np.allclose(u, -np.log(0.5 + 1e-12), atol=1e-8)


def test_blend_policy_keeps_local_primary_and_global_only_requires_missing_local() -> None:
    mixed = choose_pair_blend(pair="Li-O", local_valid=True, global_valid=True,
                              structures_contributing=20, observations=20000)
    assert mixed.local_weight == 1.0
    assert mixed.global_weight == 0.05
    fallback = choose_pair_blend(pair="Li-O", local_valid=False, global_valid=True,
                                 structures_contributing=0, observations=0)
    assert fallback.mode == "GLOBAL_ONLY_LOCAL_ABSENT_OR_INVALID"
    assert fallback.local_weight == 0.0 and fallback.global_weight == 1.0


def test_pair_blend_writes_complete_contract_root() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); r = np.arange(0.025, 10.0, 0.05)
        local = root / "local" / "Fe-O" / "Fe-O.POT"
        write_pot(local, r, np.ones(r.shape))
        rdf = root / "reg" / "Fe-O" / "Fe-O.RDF"; rdf.parent.mkdir(parents=True)
        np.savetxt(rdf, np.column_stack((r, np.full(r.shape, np.exp(-2.0)))))
        manifest = blend_contract_roots(local_root=root / "local", regulator_root=root / "reg",
                                        out_root=root / "blend", required_pairs=["Fe-O"],
                                        pair_evidence={"Fe-O": {"structures_contributing": 20, "observations": 20000}},
                                        name="fixture")
        _, u = read_pot_like_qlip(root / "blend" / "Fe-O" / "Fe-O.POT")
        assert np.allclose(u, 1.1, atol=1e-8)
        assert manifest["pairs"][0]["mode"] == "LOCAL_PRIMARY_GLOBAL_WEAK_PRIOR"
