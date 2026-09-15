from __future__ import annotations

import importlib.util
from pathlib import Path

from sok_llm_orchestrator.contracts.qlip_builders_v2 import build_solve_request_v2
from sok_llm_orchestrator.orchestrator.cell_selection import default_cell_candidates
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle
from sok_llm_orchestrator.spp.artifact_schema import SPPArtifactManifest


def _load_realistic_server_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "tests" / "fakes" / "mcp_qlip_server_realistic.py"
    spec = importlib.util.spec_from_file_location("qlip_realistic_test_module", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _retrieval_bundle() -> RetrievalBundle:
    return RetrievalBundle(
        retrieval_id="r-guidance-variation",
        mode="metadata",
        fusion_notes=[],
        items=[
            {
                "structure_id": "mp-1",
                "provenance": "db",
                "scores": {"score": 0.9},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "composition",
            }
        ],
    )


def _artifact_for_variant(variant: str) -> SPPArtifactManifest:
    return SPPArtifactManifest(
        artifact_id=f"artifact-{variant}",
        corpus_hash=f"hash-{variant}",
        weighting_policy="linear",
        bin_policy={},
        smoothing_params={},
        calibration_summary={},
        neighbor_policy="first_shell",
        cutoff_policy="bandpass",
        shrink_protection={},
        metadata={"spp_package_path": f"SPPs/{variant}/bundle"},
    )


def _build_guided_request(
    *,
    variant: str,
    weighting_profile: str,
    structure_perturbation_profile: str,
    template_seed_profile: str,
    lattice_candidate_profile: str,
    ordering_perturbation_profile: str,
    lambda_override: float,
    top_k_breakdown: int,
):
    spec = task_spec_from_query("TiO2 optimize high property x")
    guidance_config = {
        "pairs_policy": "all_available" if variant == "focus" else "task_pairs",
        "oob_policy": "max",
        "missing_pair_policy": "max_global",
        "lambda_override": lambda_override,
        "top_k_breakdown": top_k_breakdown,
        "base_weight_scale": 0.8 if weighting_profile == "property_push_strong" else 1.0,
        "guidance_weight_scale": 1.6 if weighting_profile == "property_push_strong" else 1.0,
    }
    request, _ = build_solve_request_v2(
        task_spec=spec,
        cell_candidates=default_cell_candidates(),
        retrieval_bundle=_retrieval_bundle(),
        spp_artifact=_artifact_for_variant(variant),
        guidance_mode="guidance_only",
        guidance_config=guidance_config,
        weighting_profile=weighting_profile,
        structure_perturbation_profile=structure_perturbation_profile,
        template_seed_profile=template_seed_profile,
        lattice_candidate_profile=lattice_candidate_profile,
        symmetry_relaxation_profile="soft",
        ordering_perturbation_profile=ordering_perturbation_profile,
    )
    return request


def _build_baseline_request():
    spec = task_spec_from_query("TiO2 optimize high property x")
    request, _ = build_solve_request_v2(
        task_spec=spec,
        cell_candidates=default_cell_candidates(),
        retrieval_bundle=_retrieval_bundle(),
        spp_artifact=None,
        guidance_mode="none",
        weighting_profile="balanced",
        structure_perturbation_profile="minimal",
        template_seed_profile="canonical",
        lattice_candidate_profile="narrow",
        symmetry_relaxation_profile="strict",
        ordering_perturbation_profile="none",
    )
    return request


def _solve(module, monkeypatch, workdir: Path, label: str, request: dict):
    run_dir = workdir / label
    monkeypatch.setenv("SOKLLM_RUN_DIR", str(run_dir))
    response = module._handle_tool_call("qlip.solve", {"request": request})
    assert response["ok"] is True
    nested = response["result"]["result"]
    cif_path = Path(nested["outputs"]["cif"])
    return nested, cif_path.read_text(encoding="utf-8")


def test_realistic_qlip_server_guidance_profiles_change_outputs(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    module = _load_realistic_server_module()
    balanced_request = _build_guided_request(
        variant="default",
        weighting_profile="balanced",
        structure_perturbation_profile="moderate",
        template_seed_profile="polymorph_mix",
        lattice_candidate_profile="expanded",
        ordering_perturbation_profile="site_shuffle",
        lambda_override=0.6,
        top_k_breakdown=10,
    )
    push_request = _build_guided_request(
        variant="focus",
        weighting_profile="property_push_strong",
        structure_perturbation_profile="aggressive",
        template_seed_profile="framework_bias",
        lattice_candidate_profile="multibasin",
        ordering_perturbation_profile="cation_swap_bias",
        lambda_override=1.2,
        top_k_breakdown=20,
    )

    balanced_result, balanced_cif = _solve(module, monkeypatch, workdir, "balanced", balanced_request)
    push_result, push_cif = _solve(module, monkeypatch, workdir, "push", push_request)

    assert balanced_result["summary"]["objective_value"] != push_result["summary"]["objective_value"]
    assert balanced_result["summary"]["property_x"] != push_result["summary"]["property_x"]
    assert balanced_result["summary"]["structure_profile"] != push_result["summary"]["structure_profile"]
    assert balanced_result["summary"]["guidance_profile"] != push_result["summary"]["guidance_profile"]
    assert balanced_cif != push_cif


def test_realistic_qlip_server_preserves_baseline_guided_gap(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    module = _load_realistic_server_module()
    baseline_request = _build_baseline_request()
    guided_request = _build_guided_request(
        variant="default",
        weighting_profile="balanced",
        structure_perturbation_profile="moderate",
        template_seed_profile="polymorph_mix",
        lattice_candidate_profile="expanded",
        ordering_perturbation_profile="site_shuffle",
        lambda_override=0.6,
        top_k_breakdown=10,
    )

    baseline_result, baseline_cif = _solve(module, monkeypatch, workdir, "baseline", baseline_request)
    guided_result, guided_cif = _solve(module, monkeypatch, workdir, "guided", guided_request)

    baseline_terms = [item["term"] for item in baseline_result["outputs"]["objective_terms"]]
    guided_terms = [item["term"] for item in guided_result["outputs"]["objective_terms"]]

    assert "SPP" not in baseline_terms
    assert "SPP" in guided_terms
    assert guided_result["summary"]["property_x"] > baseline_result["summary"]["property_x"]
    assert guided_result["summary"]["objective_value"] > baseline_result["summary"]["objective_value"]
    assert baseline_cif != guided_cif
