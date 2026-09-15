from sok_llm_orchestrator.orchestrator.router import plan_call_order


def test_router_is_deterministic() -> None:
    a = plan_call_order(with_spp=True, has_cif=True)
    b = plan_call_order(with_spp=True, has_cif=True)
    assert a == b
    assert a == [
        "crystal.csp_pack",
        "spp.run_pipeline",
        "spp.package_for_qlip",
        "qlip.validate_request",
        "qlip.solve",
        "crystal.novelty_check",
    ]
