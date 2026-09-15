from qlip.core.validate import validate_request


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
            "objective": {"type": "spp_energy"},
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }


def test_pot_root_outside_allowed(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(allowed))
    req = _base_request()
    req["context"] = {"pot_root": str(outside)}
    report = validate_request(req, strict=True)
    codes = {err.code for err in report.errors}
    assert "pot_root_outside_allowed_roots" in codes


def test_pot_root_inside_allowed_does_not_flag_path(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(allowed))
    req = _base_request()
    req["context"] = {"pot_root": str(allowed)}
    report = validate_request(req, strict=True)
    codes = {err.code for err in report.errors}
    assert "path_outside_allowed_roots" not in codes


def test_motif_dir_outside_allowed(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(allowed))
    req = _base_request()
    req["constraints"] = [
        {"id": "motif.linking", "params": {"motif_dir": str(outside)}}
    ]
    report = validate_request(req, strict=True)
    codes = {err.code for err in report.errors}
    assert "path_outside_allowed_roots" in codes


def test_missing_pot_root_fails_with_clear_code():
    req = _base_request()
    report = validate_request(req, strict=True)
    codes = {err.code for err in report.errors}
    assert "pot_root_missing" in codes
    assert any(item["code"] == "pot_root_missing" for item in report.path_diagnostics)


def test_nonexistent_pot_root_fails_with_clear_code(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    missing = allowed / "missing"
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(allowed))
    req = _base_request()
    req["context"] = {"pot_root": str(missing)}
    report = validate_request(req, strict=True)
    codes = {err.code for err in report.errors}
    assert "pot_root_missing" in codes


def test_pot_root_with_no_pot_files_fails_clearly(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(allowed))
    req = _base_request()
    req["context"] = {"pot_root": str(allowed)}
    report = validate_request(req, strict=True)
    codes = {err.code for err in report.errors}
    assert "pot_root_no_pot_files" in codes
