from __future__ import annotations


def plan_call_order(with_spp: bool, has_cif: bool) -> list[str]:
    order = ["crystal.csp_pack"]
    if with_spp:
        order.extend(["spp.run_pipeline", "spp.package_for_qlip"])
    order.extend(["qlip.validate_request", "qlip.solve"])
    if has_cif:
        order.append("crystal.novelty_check")
    return order
