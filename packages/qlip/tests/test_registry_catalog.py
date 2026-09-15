from qlip.plugins.registry import ConstraintRegistry, GuidanceRegistry


def test_constraint_catalog_includes_atomic_radii():
    items = ConstraintRegistry.list()
    ids = {item.id for item in items}
    assert "proximity.atomic_radii" in ids
    entry = next(item for item in items if item.id == "proximity.atomic_radii")
    assert "properties" in entry.params_schema


def test_guidance_catalog_includes_objective_energy():
    items = GuidanceRegistry.list()
    ids = {item.id for item in items}
    assert "objective.energy_spp" in ids
