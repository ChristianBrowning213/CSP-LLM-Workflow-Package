from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from sok_llm_orchestrator.workflow.runner import (
    WorkflowConfig,
    WorkflowStageError,
    _qlip_spp_request_adapter,
)


def _pot(root: Path, pair: str) -> None:
    path = root / pair.upper() / f"{pair.upper()}.POT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0.5 0.0\n1.0 0.3\n2.0 0.1\n3.0 0.0\n", encoding="utf-8")


def _rows(modes: dict[str, str]) -> dict:
    pair_results = [{"species_pair": pair, "guidance_mode": mode} for pair, mode in modes.items()]
    return {
        "pair_results": pair_results,
        "request_supported_pairs": [pair for pair, mode in modes.items() if mode == "REQUEST_PLUS_REGULATOR"],
        "regulator_fallback_pairs": [pair for pair, mode in modes.items() if mode.startswith("REGULATOR_ONLY_")],
    }


def test_regulator_only_uses_real_regulator_as_primary_without_attempt_metadata() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); request_root = root / "request"; regulator = root / "regulator"
        request_root.mkdir(); _pot(regulator, "Br-Pb"); _pot(regulator, "Cs-Pb")
        config = WorkflowConfig(output_root=root / "out", run_id="scientific-run", attempt_id="workflow-attempt")
        adapter = _qlip_spp_request_adapter(
            pair_guidance=_rows({"Br-Pb": "REGULATOR_ONLY_LOCAL_MISSING", "Cs-Pb": "REGULATOR_ONLY_LOCAL_MISSING"}),
            request_spp={"pot_root": request_root, "regulator_root": regulator},
            config=config,
        )
        assert adapter["context"] == {"run_id": "scientific-run", "pot_root": str(regulator.resolve())}
        assert "attempt_id" not in adapter["context"]
        assert adapter["guidance"][0]["weight"] == 20.0
        assert adapter["guidance"][0]["params"] == {"pot_root": str(regulator.resolve()), "mode": "complete", "cutoff": 11.0}
        assert adapter["diagnostics"]["request_pot_count"] == 0


def test_mixed_guidance_uses_only_available_request_pots_plus_regulator_fallback() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); request_root = root / "request"; regulator = root / "regulator"
        _pot(request_root, "Br-Cs"); _pot(regulator, "Br-Cs"); _pot(regulator, "Br-Pb")
        adapter = _qlip_spp_request_adapter(
            pair_guidance=_rows({"Br-Cs": "REQUEST_PLUS_REGULATOR", "Br-Pb": "REGULATOR_ONLY_LOCAL_MISSING"}),
            request_spp={"pot_root": request_root, "regulator_root": regulator},
            config=WorkflowConfig(output_root=root / "out", run_id="run", attempt_id="attempt"),
        )
        params = adapter["guidance"][0]["params"]
        assert params["supported_pairs"] == ["Br-Cs"]
        assert params["missing_pairs"] == ["Br-Pb"]
        assert params["missing_pair_policy"] == "fallback"
        assert params["regularisation_spp_dir"] == str(regulator.resolve())
        assert params["regularisation_weight"] == 2.0
        assert adapter["guidance"][0]["weight"] == 10.0


def test_declared_request_support_rejects_empty_request_root_before_qlip() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); request_root = root / "request"; regulator = root / "regulator"
        request_root.mkdir(); _pot(regulator, "Br-Cs")
        with pytest.raises(WorkflowStageError) as caught:
            _qlip_spp_request_adapter(
                pair_guidance=_rows({"Br-Cs": "REQUEST_PLUS_REGULATOR"}),
                request_spp={"pot_root": request_root, "regulator_root": regulator},
                config=WorkflowConfig(output_root=root / "out"),
            )
        assert caught.value.code == "REQUEST_POT_ROOT_EMPTY"


def test_preblended_common_contract_is_loaded_once_as_complete_root() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); request_root = root / "request"; regulator = root / "regulator"
        _pot(request_root, "Br-Cs"); _pot(request_root, "Br-Pb"); _pot(regulator, "Br-Cs")
        guidance = _rows({"Br-Cs": "REQUEST_PLUS_REGULATOR", "Br-Pb": "REQUEST_PLUS_REGULATOR"})
        adapter = _qlip_spp_request_adapter(
            pair_guidance=guidance,
            request_spp={"pot_root": request_root, "regulator_root": regulator,
                         "blend_mode": "preblended_pair_level", "artifact_contract": "dmytro_gr_v1"},
            config=WorkflowConfig(output_root=root / "out", request_coefficient=0.8),
        )
        assert adapter["guidance"][0]["params"] == {
            "pot_root": str(request_root.resolve()), "mode": "complete", "cutoff": 11.0,
        }
        assert adapter["guidance"][0]["weight"] == 8.0
        assert "regularisation_spp_dir" not in adapter["guidance"][0]["params"]
        assert adapter["diagnostics"]["representation"] == "PREBLENDED_PAIR_LEVEL_COMPLETE"


def test_missing_request_and_regulator_guidance_fails_before_qlip() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); request_root = root / "request"; regulator = root / "regulator"
        request_root.mkdir(); regulator.mkdir()
        with pytest.raises(WorkflowStageError) as caught:
            _qlip_spp_request_adapter(
                pair_guidance=_rows({"Br-Pb": "REGULATOR_ONLY_LOCAL_MISSING"}),
                request_spp={"pot_root": request_root, "regulator_root": regulator},
                config=WorkflowConfig(output_root=root / "out"),
            )
        assert caught.value.code == "GUIDANCE_PAIR_UNSUPPORTED"


def test_qlip_strict_schema_and_allowed_root_validation_remain_active() -> None:
    from qlip.core.validate import validate_request

    with TemporaryDirectory() as directory:
        root = Path(directory); request_root = root / "request"; regulator = root / "regulator"
        request_root.mkdir(); _pot(regulator, "Br-Br")
        adapter = _qlip_spp_request_adapter(
            pair_guidance=_rows({"Br-Br": "REGULATOR_ONLY_LOCAL_MISSING"}),
            request_spp={"pot_root": request_root, "regulator_root": regulator},
            config=WorkflowConfig(output_root=root / "out", run_id="run", attempt_id="attempt"),
        )
        request = {
            "version": "1.0",
            "problem": {
                "chemistry": {"formula": "Br"},
                "design_space": {"template": {"name": "fixture", "lattice": {"a": 4, "b": 4, "c": 4, "alpha": 90, "beta": 90, "gamma": 90, "units": "angstrom"}}, "sites": {"mode": "explicit_fractional_sites", "explicit_fractional_sites": [[0, 0, 0]], "ordered_orbits": [{"orbit_id": "br", "site_indices": [0], "allowed_species": ["Br"], "required_occupancy": True}]}},
                "objective": {"type": "spp_energy"},
            },
            "constraints": [], "guidance": adapter["guidance"], "guidance_mode": "weighted_sum",
            "solver": {"name": "gurobi"}, "artifacts": {}, "runtime": {}, "context": adapter["context"],
        }
        import os
        previous = os.environ.get("QLIP_ALLOWED_PATH_ROOTS")
        os.environ["QLIP_ALLOWED_PATH_ROOTS"] = str(root)
        try:
            report = validate_request(request, strict=True)
            assert report.valid
            request["context"]["attempt_id"] = "not-allowed"
            strict_report = validate_request(request, strict=True)
            assert any("Additional properties" in issue.message for issue in strict_report.errors)
        finally:
            if previous is None: os.environ.pop("QLIP_ALLOWED_PATH_ROOTS", None)
            else: os.environ["QLIP_ALLOWED_PATH_ROOTS"] = previous
