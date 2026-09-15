from pathlib import Path
import sys
import tomllib
import types

from typer.testing import CliRunner

from sca.backends import verify_optional_backends
from sca.cli import app


runner = CliRunner()


def test_optional_dependency_groups_are_declared() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]

    assert extras["alignn"] == ["alignn>=2024.0"]
    assert extras["chgnet"] == ["chgnet>=0.3.0"]
    assert extras["matgl"] == ["matgl>=1.1.0"]
    assert extras["mlip"] == ["chgnet>=0.3.0", "matgl>=1.1.0"]
    assert extras["advanced-mlip"] == ["mace-torch>=0.3.0", "sevenn>=0.10.0"]
    assert extras["benchmark-full"] == [
        "alignn>=2024.0",
        "chgnet>=0.3.0",
        "matgl>=1.1.0",
    ]
    assert extras["benchmark-advanced"] == [
        "alignn>=2024.0",
        "chgnet>=0.3.0",
        "matgl>=1.1.0",
        "mace-torch>=0.3.0",
        "sevenn>=0.10.0",
    ]


def test_verify_backends_reports_expected_backends() -> None:
    rows = verify_optional_backends()
    names = {row["backend"] for row in rows}

    assert {"alignn", "chgnet_static", "m3gnet_static", "mace_static", "sevennet_static"} <= names
    assert all("ready" in row for row in rows)
    assert all("install_hint" in row for row in rows)


def test_verify_backends_cli_outputs_json() -> None:
    result = runner.invoke(app, ["verify-backends"])

    assert result.exit_code == 0
    assert "alignn" in result.output
    assert "install_hint" in result.output


def test_verify_backends_does_not_run_functional_check_by_default(monkeypatch) -> None:
    import sca.backends as backends

    def fail_if_called():
        raise AssertionError("functional check should not run by default")

    monkeypatch.setattr(backends, "_functional_check_m3gnet", fail_if_called)

    rows = backends.verify_optional_backends()

    assert rows
    assert "functional_ok" not in rows[0]


def test_verify_backends_cli_passes_functional_flag(monkeypatch) -> None:
    import sca.cli as cli

    calls = []

    def fake_verify_optional_backends(functional=False):
        calls.append(functional)
        return []

    monkeypatch.setattr(cli, "verify_optional_backends", fake_verify_optional_backends)

    result = runner.invoke(app, ["verify-backends", "--functional"])

    assert result.exit_code == 0
    assert calls == [True]


def test_verify_backends_accepts_pretrained_env(monkeypatch) -> None:
    monkeypatch.setenv("SCA_MACE_PRETRAINED", "small")
    rows = {row["backend"]: row for row in verify_optional_backends()}

    assert rows["mace_static"]["pretrained_name"] == "small"
    assert "SCA_MACE_MODEL is not set" not in rows["mace_static"]["notes"]


def test_mace_loader_uses_pretrained_keyword(monkeypatch) -> None:
    import sca.evaluators.mlip as mlip

    calls = {}
    mace_pkg = types.ModuleType("mace")
    calculators = types.ModuleType("mace.calculators")

    def mace_mp(model, device):
        calls["model"] = model
        calls["device"] = device
        return "calculator"

    class MACECalculator:
        def __init__(self, **kwargs):
            calls["kwargs"] = kwargs

    calculators.mace_mp = mace_mp
    calculators.MACECalculator = MACECalculator
    monkeypatch.setitem(sys.modules, "mace", mace_pkg)
    monkeypatch.setitem(sys.modules, "mace.calculators", calculators)
    monkeypatch.setenv("SCA_MLIP_DEVICE", "cpu")

    calculator, label = mlip._load_mace_calculator(model_path=None, pretrained="small")

    assert calculator == "calculator"
    assert label == "pretrained:small"
    assert calls == {"model": "small", "device": "cpu"}


def test_sevennet_loader_uses_pretrained_keyword(monkeypatch) -> None:
    import sca.evaluators.mlip as mlip

    calls = {}
    sevenn_pkg = types.ModuleType("sevenn")
    sevenn_calculator = types.ModuleType("sevenn.sevennet_calculator")

    class SevenNetCalculator:
        def __init__(self, model, device):
            calls["model"] = model
            calls["device"] = device

    sevenn_calculator.SevenNetCalculator = SevenNetCalculator
    monkeypatch.setitem(sys.modules, "sevenn", sevenn_pkg)
    monkeypatch.setitem(sys.modules, "sevenn.sevennet_calculator", sevenn_calculator)
    monkeypatch.setenv("SCA_MLIP_DEVICE", "cpu")

    calculator, label = mlip._load_sevennet_calculator(model_path=None, pretrained="7net-0")

    assert isinstance(calculator, SevenNetCalculator)
    assert label == "pretrained:7net-0"
    assert calls == {"model": "7net-0", "device": "cpu"}


def test_m3gnet_loader_prefers_matpes_foundation_model() -> None:
    import sca.evaluators.mlip as mlip

    calls = []

    class FakeMatgl:
        @staticmethod
        def get_available_pretrained_models():
            return [
                "M3GNet-PES-ANI-1x-Subset",
                "M3GNet-MP-2021.2.8-PES",
                "M3GNet-PES-MatPES-PBE-2025.2",
            ]

        @staticmethod
        def load_model(name):
            calls.append(name)
            if name == "M3GNet-PES-MatPES-PBE-2025.2":
                return "potential"
            raise ValueError("Bad serialized model or bad model name")

    potential, label = mlip._load_m3gnet_potential(FakeMatgl, model_name=None, pretrained=None)

    assert potential == "potential"
    assert label == "M3GNet-PES-MatPES-PBE-2025.2"
    assert calls == ["M3GNet-PES-MatPES-PBE-2025.2"]
    assert "M3GNet-PES-ANI-1x-Subset" not in mlip._m3gnet_model_candidates(FakeMatgl, None, None)


def test_m3gnet_loader_honors_explicit_pretrained_name() -> None:
    import sca.evaluators.mlip as mlip

    calls = []

    class FakeMatgl:
        @staticmethod
        def get_available_pretrained_models():
            raise AssertionError("explicit model should skip model discovery")

        @staticmethod
        def load_model(name):
            calls.append(name)
            return "potential"

    potential, label = mlip._load_m3gnet_potential(FakeMatgl, model_name=None, pretrained="custom-m3gnet")

    assert potential == "potential"
    assert label == "custom-m3gnet"
    assert calls == ["custom-m3gnet"]


def test_m3gnet_key_error_becomes_actionable_message(monkeypatch) -> None:
    import pymatgen.io.ase as pymatgen_ase
    import sca.evaluators.mlip as mlip

    class FakeAtoms:
        calc = None

        def __len__(self):
            return 2

        def get_potential_energy(self):
            raise KeyError("Ba")

    class FakeAdaptor:
        @staticmethod
        def get_atoms(structure):
            return FakeAtoms()

    monkeypatch.setattr(mlip, "parse_cif", lambda path: (object(), object()))
    monkeypatch.setattr(pymatgen_ase, "AseAtomsAdaptor", FakeAdaptor)

    result = mlip._ase_calculator_result(
        "m3gnet_static",
        "m3gnet",
        "dummy.cif",
        lambda model_path, pretrained: (
            "calculator",
            "M3GNet-MP-2021.2.8-PES",
            {"supported_elements": ["O", "Ti"]},
        ),
        model_path=None,
        pretrained=None,
    )

    assert result.ok is False
    assert result.error_type == "KeyError"
    assert "MatGL model M3GNet-MP-2021.2.8-PES does not support element Ba" in result.error_message
    assert "Supported elements: O, Ti" in result.error_message
    assert result.metrics["m3gnet_error"] == result.error_message


def test_m3gnet_success_path_populates_energy_and_force_fields(monkeypatch) -> None:
    import pymatgen.io.ase as pymatgen_ase
    import sca.evaluators.mlip as mlip

    class FakeAtoms:
        calc = None

        def __len__(self):
            return 2

        def get_potential_energy(self):
            return -4.0

        def get_forces(self):
            return [[0.0, 0.0, 0.0], [1.0, 2.0, 2.0]]

    class FakeAdaptor:
        @staticmethod
        def get_atoms(structure):
            return FakeAtoms()

    monkeypatch.setattr(mlip, "parse_cif", lambda path: (object(), object()))
    monkeypatch.setattr(pymatgen_ase, "AseAtomsAdaptor", FakeAdaptor)

    result = mlip._ase_calculator_result(
        "m3gnet_static",
        "m3gnet",
        "dummy.cif",
        lambda model_path, pretrained: (
            "calculator",
            "M3GNet-MP-2021.2.8-PES",
            {"supported_elements": ["Na", "Cl"]},
        ),
        model_path=None,
        pretrained=None,
    )

    assert result.ok is True
    assert result.metrics["m3gnet_energy_per_atom"] == -2.0
    assert result.metrics["m3gnet_forces_max"] == 3.0
    assert result.details["supported_elements"] == ["Na", "Cl"]
