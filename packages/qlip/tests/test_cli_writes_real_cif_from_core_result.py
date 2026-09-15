import argparse

from qlip import __main__ as cli_mod
from qlip.core.models import SolveOutputs, SolveResult, SolveSummary
from tests.helpers.solve_test_support import make_real_cif_text


def test_cli_writes_real_cif_from_core_result(monkeypatch, tmp_path):
    real_cif = make_real_cif_text()

    monkeypatch.setattr(
        cli_mod,
        "_parse_args",
        lambda: argparse.Namespace(
            chem="SrTiO3",
            grid=2,
            use_motifs=False,
            motif_dir=tmp_path,
            motif_include=None,
            spp_pot_dir=None,
            solver="gurobi",
        ),
    )
    monkeypatch.setattr(
        cli_mod,
        "core_solve",
        lambda request: SolveResult(
            status="OPTIMAL",
            summary=SolveSummary(solver="gurobi", timing_ms=1, termination="optimal"),
            outputs=SolveOutputs(cif=real_cif),
        ),
    )
    monkeypatch.setattr(cli_mod, "REPO_ROOT", tmp_path)

    cli_mod.main()

    out = tmp_path / "viz" / "structure.cif"
    assert out.exists()
    assert out.read_text(encoding="utf-8").replace("\r\n", "\n") == real_cif.replace("\r\n", "\n")
