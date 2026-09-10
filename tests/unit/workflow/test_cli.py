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
