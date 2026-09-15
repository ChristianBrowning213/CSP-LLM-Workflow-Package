from __future__ import annotations

from pathlib import Path
import json

from qlip.core.validate import validate_request
from qlip.data.registry import default_registry


class _AvailableSolver:
    def available(self, exception_flag=False):
        return True


def _request(formula: str = "CoAs2", objective: dict | None = None) -> dict:
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": formula},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 5.0,
                        "b": 5.0,
                        "c": 5.0,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    }
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
            },
            "objective": objective or {"type": "spp_energy"},
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
        "context": {},
    }


def _write_pot(root: Path, pair: str) -> None:
    path = root / pair.upper() / f"{pair.upper()}.POT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0.1 1.0\n0.2 0.5\n", encoding="utf-8")


def test_missing_pot_root_when_spp_energy_requested(monkeypatch):
    monkeypatch.setattr("qlip.core.validate.pyo.SolverFactory", lambda name: _AvailableSolver())
    req = _request()
    report = validate_request(req, strict=True)

    assert "pot_root_missing" in {err.code for err in report.errors}
    assert any(item["code"] == "pot_root_missing" for item in report.missing_data)
    assert report.data_diagnostics["ready"] is False


def test_pot_root_exists_but_has_no_pot_files(monkeypatch, tmp_path):
    monkeypatch.setattr("qlip.core.validate.pyo.SolverFactory", lambda name: _AvailableSolver())
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    req = _request()
    req["context"] = {"pot_root": str(tmp_path)}

    report = validate_request(req, strict=True)

    assert "pot_root_no_pot_files" in {err.code for err in report.errors}
    assert any(item["code"] == "pot_root_no_pot_files" for item in report.missing_data)


def test_pot_root_reports_missing_cross_pair(monkeypatch, tmp_path):
    monkeypatch.setattr("qlip.core.validate.pyo.SolverFactory", lambda name: _AvailableSolver())
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    _write_pot(tmp_path, "As-As")
    _write_pot(tmp_path, "Co-Co")
    req = _request()
    req["context"] = {"pot_root": str(tmp_path)}

    report = validate_request(req, strict=True)

    missing = [item for item in report.missing_data if item["code"] == "pot_pair_missing"]
    assert len(missing) == 1
    assert missing[0]["details"]["pair"] == "As-Co"
    assert missing[0]["details"]["required_pairs"] == ["As-As", "As-Co", "Co-Co"]
    assert set(missing[0]["details"]["available_pairs"]) == {"As-As", "Co-Co"}
    assert missing[0]["details"]["attempted_paths"]


def test_proximity_atomic_radii_reports_missing_base_data_element(monkeypatch, tmp_path):
    monkeypatch.setattr("qlip.core.validate.pyo.SolverFactory", lambda name: _AvailableSolver())
    source = Path(__file__).resolve().parents[1] / "data" / "base"
    target = tmp_path / "base"
    target.mkdir()
    for path in source.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "radii.json":
            payload["records"].pop("Fe")
        (target / path.name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("QLIP_BASE_DATA_DIR", str(target))
    default_registry.cache_clear()

    req = _request(formula="FeO", objective={"type": "none"})
    req["constraints"] = [{"id": "proximity.atomic_radii", "params": {"scale": 1.0}}]

    report = validate_request(req, strict=True)

    assert "radii_data_missing" in {err.code for err in report.errors}
    assert any(
        item["code"] == "radii_data_missing" and item["details"]["element"] == "Fe"
        for item in report.missing_data
    )
    default_registry.cache_clear()


def test_motif_linking_without_motif_root_reports_missing_artifacts(monkeypatch):
    monkeypatch.setattr("qlip.core.validate.pyo.SolverFactory", lambda name: _AvailableSolver())
    req = _request(objective={"type": "none"})
    req["constraints"] = [{"id": "motif.linking", "params": {}}]

    report = validate_request(req, strict=True)

    assert {"motif_root_missing", "motif_artifacts_missing"} & {err.code for err in report.errors}
    assert {"motif_root_missing", "motif_artifacts_missing"} & {
        item["code"] for item in report.missing_data
    }


def test_complete_coas2_pot_root_has_no_missing_pair(monkeypatch, tmp_path):
    monkeypatch.setattr("qlip.core.validate.pyo.SolverFactory", lambda name: _AvailableSolver())
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    for pair in ("As-As", "As-Co", "Co-Co"):
        _write_pot(tmp_path, pair)
    req = _request()
    req["context"] = {"pot_root": str(tmp_path)}

    report = validate_request(req, strict=True)

    assert "pot_pair_missing" not in {err.code for err in report.errors}
    assert not [item for item in report.missing_data if item["code"] == "pot_pair_missing"]


def test_atomic_radii_supported_for_non_legacy_element(monkeypatch):
    monkeypatch.setattr("qlip.core.validate.pyo.SolverFactory", lambda name: _AvailableSolver())
    default_registry.cache_clear()
    req = _request(formula="FeO", objective={"type": "none"})
    req["constraints"] = [{"id": "proximity.atomic_radii", "params": {"scale": 1.0}}]

    report = validate_request(req, strict=True)

    assert "radii_data_missing" not in {err.code for err in report.errors}
    assert all(item["code"] != "radii_data_missing" for item in report.missing_data)
