from __future__ import annotations

from sok_llm_orchestrator.verification.qlip_outputs import structure_signature_from_cif_path


def test_structure_signature_stable_for_same_content(workdir) -> None:  # type: ignore[no-untyped-def]
    cif = workdir / "same.cif"
    cif.write_text("data_test\n_cell_length_a 4.0\n_chemical_formula_sum 'Ti O2'\n", encoding="utf-8")
    first = structure_signature_from_cif_path(str(cif))
    second = structure_signature_from_cif_path(str(cif))
    assert first["structure_signature"] == second["structure_signature"]
    assert first["formula_signature"] == second["formula_signature"]
    assert bool(first["path_exists"])


def test_structure_signature_changes_when_content_changes(workdir) -> None:  # type: ignore[no-untyped-def]
    cif_a = workdir / "a.cif"
    cif_b = workdir / "b.cif"
    cif_a.write_text("data_a\n_cell_length_a 4.0\n", encoding="utf-8")
    cif_b.write_text("data_b\n_cell_length_a 5.0\n", encoding="utf-8")
    sig_a = structure_signature_from_cif_path(str(cif_a))
    sig_b = structure_signature_from_cif_path(str(cif_b))
    assert sig_a["structure_signature"] != sig_b["structure_signature"]
