from qlip.core.validate import validate_request
from qlip.core.solve import solve
import pyomo.environ as pyo
import pytest


def _base_request():
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "SrTiO3"},
            "design_space": {
                "template": {
                    "name": "cubic",
                    "lattice": {
                        "a": 3.9,
                        "b": 3.9,
                        "c": 3.9,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    },
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
            },
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }


def test_unknown_constraint_id_returns_error():
    req = _base_request()
    req["constraints"] = [{"id": "unknown.plugin", "params": {}}]
    report = validate_request(req, strict=True)
    codes = {err.code for err in report.errors}
    assert "unknown_constraint_id" in codes


def test_invalid_constraint_params_returns_error():
    req = _base_request()
    req["constraints"] = [{"id": "proximity.atomic_radii", "params": {}}]
    report = validate_request(req, strict=True)
    codes = {err.code for err in report.errors}
    assert "invalid_constraint_params" in codes


def _write_pot(root, pair: str) -> None:
    path = root / pair / f"{pair}.POT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0.5 0.0\n1.0 0.1\n2.0 0.0\n", encoding="utf-8")


def _write_loadable_pot(root, pair: str) -> None:
    path = root / pair / f"{pair}.POT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0.5 0.0\n1.0 0.3\n2.0 0.1\n3.0 0.0\n", encoding="utf-8")


def _partial_nacl_request(pot_root):
    req = _base_request()
    req["problem"]["chemistry"]["formula"] = "NaCl"
    req["problem"]["design_space"]["template"]["lattice"].update({"a": 5.6, "b": 5.6, "c": 5.6})
    req["guidance"] = [
        {
            "id": "objective.energy_spp",
            "params": {
                "pot_root": str(pot_root),
                "mode": "partial",
                "supported_pairs": ["Cl-Na"],
                "missing_pairs": ["Cl-Cl", "Na-Na"],
                "missing_pair_policy": "neutral",
                "missing_pair_penalty": 0.0,
                "strict_pair_coverage": False,
            },
        }
    ]
    return req


def test_unknown_top_level_request_fields_still_fail_validation():
    req = _base_request()
    req["qlip_guidance_mode"] = "partial_spp"
    report = validate_request(req, strict=True)
    assert any(issue.code == "schema_validation_error" for issue in report.errors)
    assert any("Additional properties" in issue.message for issue in report.errors)


def test_strict_spp_mode_rejects_missing_pot_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    req = _base_request()
    req["problem"]["chemistry"]["formula"] = "NaCl"
    req["context"] = {"pot_root": str(pot_root)}
    req["guidance"] = [{"id": "objective.energy_spp", "params": {}}]
    report = validate_request(req, strict=True)
    assert not report.valid
    assert "pot_pair_missing" in {issue.code for issue in report.errors}


def test_partial_spp_neutral_policy_accepts_missing_pairs_without_pots(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    report = validate_request(_partial_nacl_request(pot_root), strict=True)
    assert report.valid
    assert report.capabilities["pot_root_resolved"] is True
    partial = report.capabilities["spp_partial_guidance"]
    assert partial["enabled"] is True
    assert partial["mode"] == "partial"
    assert partial["missing_pair_policy"] == "neutral"
    assert partial["strict_pair_coverage"] is False
    assert partial["missing_pairs_require_pots"] is False
    assert partial["missing_pairs_are_neutral"] is True
    assert partial["supported_pairs"] == ["Cl-Na"]
    assert partial["missing_pairs"] == ["Cl-Cl", "Na-Na"]
    assert report.capabilities["spp_supported_pairs_used"] == ["Cl-Na"]
    assert report.capabilities["spp_missing_pairs_unguided"] == ["Cl-Cl", "Na-Na"]


def test_partial_spp_neutral_policy_derives_unlisted_missing_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    request = _partial_nacl_request(pot_root)
    request["guidance"][0]["params"]["missing_pairs"] = ["Na-Na"]

    report = validate_request(request, strict=True)

    assert report.valid
    assert report.capabilities["spp_partial_guidance"]["supported_pairs"] == ["Cl-Na"]
    assert report.capabilities["spp_partial_guidance"]["missing_pairs"] == ["Cl-Cl", "Na-Na"]
    assert report.capabilities["spp_missing_pairs_unguided"] == ["Cl-Cl", "Na-Na"]


def test_partial_spp_block_policy_rejects_missing_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    req = _partial_nacl_request(pot_root)
    req["guidance"][0]["params"]["missing_pair_policy"] = "block"
    report = validate_request(req, strict=True)
    assert not report.valid
    assert "pot_pair_missing" in {issue.code for issue in report.errors}


def test_partial_spp_non_neutral_missing_pair_policies_require_real_pots(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")

    fallback_req = _partial_nacl_request(pot_root)
    fallback_req["guidance"][0]["params"]["missing_pair_policy"] = "fallback"
    fallback_report = validate_request(fallback_req, strict=True)

    max_global_req = _partial_nacl_request(pot_root)
    max_global_req["guidance"][0]["params"]["missing_pair_policy"] = "max_global"
    max_global_report = validate_request(max_global_req, strict=True)

    assert not fallback_report.valid
    assert "pot_pair_missing" in {issue.code for issue in fallback_report.errors}
    assert not max_global_report.valid
    assert "invalid_guidance_params" in {issue.code for issue in max_global_report.errors}


def test_partial_spp_fallback_accepts_exact_loadable_regulator_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    regularisation_root = tmp_path / "regularisation_spp"
    _write_pot(pot_root, "Cl-Na")
    _write_loadable_pot(regularisation_root, "CL-CL")
    _write_loadable_pot(regularisation_root, "NA-NA")
    req = _partial_nacl_request(pot_root)
    params = req["guidance"][0]["params"]
    params["missing_pair_policy"] = "fallback"
    params["regularisation_spp_dir"] = str(regularisation_root)
    params["regularisation_weight"] = 2.0

    report = validate_request(req, strict=True)

    assert report.valid
    partial = report.capabilities["spp_partial_guidance"]
    assert partial["missing_pairs_use_regulator_fallback"] is True
    assert partial["missing_pairs"] == ["Cl-Cl", "Na-Na"]
    available = [
        item for item in report.available_data
        if item.get("code") == "pot_pair_regulator_fallback"
    ]
    assert {item["pair"] for item in available} == {"Cl-Cl", "Na-Na"}
    assert all(item["regulator_path"].endswith(".POT") for item in available)


def test_partial_spp_fallback_rejects_missing_exact_regulator_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    regularisation_root = tmp_path / "regularisation_spp"
    _write_pot(pot_root, "Cl-Na")
    _write_loadable_pot(regularisation_root, "CL-CL")
    req = _partial_nacl_request(pot_root)
    params = req["guidance"][0]["params"]
    params["missing_pair_policy"] = "fallback"
    params["regularisation_spp_dir"] = str(regularisation_root)
    params["regularisation_weight"] = 2.0

    report = validate_request(req, strict=True)

    assert not report.valid
    errors = [issue for issue in report.errors if issue.code == "spp_regulator_pair_missing"]
    assert len(errors) == 1
    assert errors[0].details["pair"] == "Na-Na"


def test_partial_spp_soft_repulsive_policy_accepts_missing_pairs_without_pots(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    req = _partial_nacl_request(pot_root)
    req["guidance"][0]["params"]["missing_pair_policy"] = "soft_repulsive"

    report = validate_request(req, strict=True)

    assert report.valid
    partial = report.capabilities["spp_partial_guidance"]
    assert partial["enabled"] is True
    assert partial["missing_pair_policy"] == "soft_repulsive"
    assert partial["missing_pairs_require_pots"] is False
    assert partial["missing_pairs_are_neutral"] is False
    assert partial["missing_pairs_use_soft_repulsive"] is True
    assert partial["supported_pairs"] == ["Cl-Na"]
    assert partial["missing_pairs"] == ["Cl-Cl", "Na-Na"]
    assert report.capabilities["spp_missing_pairs_soft_repulsive"] == ["Cl-Cl", "Na-Na"]


def test_spp_regularisation_accepts_explicit_loadable_pot_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    regularisation_root = tmp_path / "regularisation_spp"
    _write_pot(pot_root, "Cl-Na")
    _write_loadable_pot(regularisation_root, "CL-CL")
    req = _partial_nacl_request(pot_root)
    req["guidance"][0]["params"]["regularisation_spp_dir"] = str(regularisation_root)
    req["guidance"][0]["params"]["regularisation_weight"] = 0.25

    report = validate_request(req, strict=True)

    assert report.valid
    regularisation = report.capabilities["spp_regularisation"]
    assert regularisation["enabled"] is True
    assert regularisation["regularisation_spp_dir"] == str(regularisation_root.resolve())
    assert regularisation["regularisation_weight"] == 0.25
    assert regularisation["regularisation_pairs_loaded"] == 1


def test_spp_regularisation_alias_and_env_dir_are_supported(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    regularisation_root = tmp_path / "regularization_spp"
    _write_pot(pot_root, "Cl-Na")
    _write_loadable_pot(regularisation_root, "NA-NA")
    monkeypatch.setenv("QLIP_SPP_REGULARIZATION_DIR", str(regularisation_root))
    req = _partial_nacl_request(pot_root)
    req["guidance"][0]["params"]["regularization_weight"] = 0.5

    report = validate_request(req, strict=True)

    assert report.valid
    assert report.capabilities["spp_regularisation"]["enabled"] is True
    assert report.capabilities["spp_regularisation"]["regularisation_pairs_loaded"] == 1


def test_spp_regularisation_weight_zero_does_not_require_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    req = _partial_nacl_request(pot_root)
    req["guidance"][0]["params"]["regularisation_weight"] = 0.0

    report = validate_request(req, strict=True)

    assert report.valid
    assert report.capabilities["spp_regularisation"]["enabled"] is False


def test_spp_regularisation_positive_weight_requires_valid_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    req = _partial_nacl_request(pot_root)
    req["guidance"][0]["params"]["regularisation_spp_dir"] = str(tmp_path / "missing_regularisation")
    req["guidance"][0]["params"]["regularisation_weight"] = 1.0

    report = validate_request(req, strict=True)

    assert not report.valid
    assert "spp_regularisation_dir_missing" in {issue.code for issue in report.errors}


def test_spp_regularisation_rejects_negative_weight(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    req = _partial_nacl_request(pot_root)
    req["guidance"][0]["params"]["regularisation_weight"] = -1.0

    report = validate_request(req, strict=True)

    assert not report.valid
    assert "invalid_guidance_params" in {issue.code for issue in report.errors}


def test_partial_spp_rejects_unknown_missing_pair_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    req = _partial_nacl_request(pot_root)
    req["guidance"][0]["params"]["missing_pair_policy"] = "definitely_not_real"

    report = validate_request(req, strict=True)

    assert not report.valid
    assert "invalid_guidance_params" in {issue.code for issue in report.errors}


def test_partial_spp_solve_reaches_solver_or_skips_without_gurobi(tmp_path, monkeypatch):
    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        pytest.skip("Gurobi not available")
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    pot_root = tmp_path / "partial_spp_root"
    _write_pot(pot_root, "Cl-Na")
    result = solve(_partial_nacl_request(pot_root))
    diagnostics = result.certificates.get("diagnostics", {})
    assert diagnostics["spp_guidance"]["mode"] == "partial"
    assert diagnostics["spp_guidance"]["missing_pair_policy"] == "neutral"
    assert diagnostics["spp_guidance"]["partial_guidance"] is True
    assert diagnostics["spp_guidance"]["terms_added_count"] == 1
    assert diagnostics["spp_guidance"]["terms_skipped_missing_pair_count"] == 2
    assert diagnostics["spp_guidance"]["missing_pairs_are_neutral"] is True
    assert result.summary.termination != "validation_failed"
