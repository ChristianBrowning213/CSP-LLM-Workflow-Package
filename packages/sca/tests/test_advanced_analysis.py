from pathlib import Path

from sca.advanced_analysis import analyse_crystal_advanced


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_valid.cif"


def test_advanced_analysis_missing_optional_layers():
    result = analyse_crystal_advanced(FIXTURE)
    assert result.dft_status["status"] == "NOT_RUN"
    assert result.formation_energy["status"] == "NOT_COMPUTABLE"
    assert result.energy_above_hull["status"] == "NOT_COMPUTABLE"
    assert result.limitations


def test_advanced_analysis_complete_fixture():
    layers = {
        "topology": {"status": "PASS"},
        "spp_plausibility": {"status": "AVAILABLE", "score": -1.2},
        "mlip_static_analysis": {"status": "SUCCESS"},
        "mlip_agreement": {"status": "AVAILABLE", "consensus_label": "CONSISTENT"},
        "mlip_relaxation": {"status": "SUCCESS"},
        "post_mlip_validation": {"overall_relaxation_status": "ROBUST"},
        "dft_status": {"status": "COMPLETED"},
        "dft_relaxation": {"dft_relaxation_status": "DFT_ROBUST"},
        "formation_energy": {"status": "COMPUTABLE", "formation_energy_eV_atom": -1.0},
        "energy_above_hull": {"hull_status": "COMPUTABLE", "energy_above_hull_eV_atom": 0.0},
        "decomposition": {"status": "COMPUTABLE", "products": {}},
    }
    result = analyse_crystal_advanced(FIXTURE, layers=layers)
    assert result.scientific_quality_dimensions["dft_relaxation_robust"] is True
    assert result.scientific_quality_dimensions["thermodynamic_context_available"] is True

