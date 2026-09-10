import pytest

from llm_csp.spp.covalent_filter import load_covalent_rules
from llm_csp.spp.library import resolve_source_pot_root


def test_source_pot_root_argument_then_environment(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    configured = tmp_path / "configured"
    explicit.mkdir()
    configured.mkdir()
    monkeypatch.setenv("SPP_SOURCE_POT_ROOT", str(configured))
    assert resolve_source_pot_root(explicit) == explicit.resolve()
    assert resolve_source_pot_root() == configured.resolve()
    monkeypatch.delenv("SPP_SOURCE_POT_ROOT")
    with pytest.raises(ValueError, match="SPP_SOURCE_POT_ROOT"):
        resolve_source_pot_root()


def test_yaml_dependency_is_declared_and_available_outside_checkout(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "rules:\n  - elem1: S\n    elem2: O\n    min_dist: 1.6\n",
        encoding="utf-8",
    )
    rules = load_covalent_rules(rules_path)
    assert rules
