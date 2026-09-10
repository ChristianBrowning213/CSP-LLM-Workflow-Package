import json

from llm_csp.cli import main as cli_module
from llm_csp.schemas import WorkflowResult


def test_cli_json_is_thin_machine_readable_adapter(tmp_path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "request.json"
    config_path.write_text(
        json.dumps(
            {
                "request": {
                    "query": "SrTiO3",
                    "formula": "SrTiO3",
                    "design_space": {"template": {"lattice": {}}, "sites": {"mode": "uniform_grid"}},
                },
                "config": {"output_root": str(tmp_path / "ignored")},
            }
        ),
        encoding="utf-8",
    )
    expected = WorkflowResult("run", "completed", {}, {}, {}, {})
    monkeypatch.setattr(cli_module, "run_csp_workflow", lambda request, config: expected)

    code = cli_module.main(
        ["run", "--config", str(config_path), "--output", str(tmp_path / "runs"), "--json"]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"


def test_cli_invalid_configuration_is_machine_readable(tmp_path, capsys) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"request": {}}', encoding="utf-8")

    code = cli_module.main(["run", "--config", str(path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == cli_module.EXIT_INVALID_INPUT
    assert payload["error"]["code"] == "invalid_input"


def test_cli_exit_codes_distinguish_backend_and_scientific_failures(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps({
        "request": {"query": "x", "formula": "SrTiO3", "design_space": {"x": 1}},
        "config": {"output_root": str(tmp_path / "runs")},
    }), encoding="utf-8")
    unavailable = WorkflowResult(
        "run", "blocked", {}, {}, {}, {}, errors=({"code": "retrieval_backend_unavailable"},)
    )
    monkeypatch.setattr(cli_module, "run_csp_workflow", lambda request, config: unavailable)
    assert cli_module.main(["run", "--config", str(path), "--json"]) == cli_module.EXIT_BACKEND_UNAVAILABLE
    capsys.readouterr()

    failed = WorkflowResult("run", "blocked", {}, {}, {}, {}, errors=({"code": "spp_incomplete"},))
    monkeypatch.setattr(cli_module, "run_csp_workflow", lambda request, config: failed)
    assert cli_module.main(["run", "--config", str(path), "--json"]) == cli_module.EXIT_SCIENTIFIC_FAILURE


def test_help_is_ascii_console_safe() -> None:
    assert all(ord(char) < 128 for char in cli_module._parser().format_help())
