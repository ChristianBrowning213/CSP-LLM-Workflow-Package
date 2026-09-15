import pytest

from qlip.mcp import server


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"ids": {}},
        {"tags_any": {}},
        {"ids": {"ids": []}},
        {"tags_any": {"tags_any": []}},
        {"ids": [], "tags_any": []},
    ],
)
def test_list_constraints_accepts_mis_shapes(payload):
    result = server.list_constraints(**payload)
    assert "items" in result
    assert isinstance(result["items"], list)
    assert "is not of type" not in str(result)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"ids": {}},
        {"tags_any": {}},
        {"ids": {"ids": []}},
        {"tags_any": {"tags_any": []}},
        {"ids": [], "tags_any": []},
    ],
)
def test_list_guidance_accepts_mis_shapes(payload):
    result = server.list_guidance(**payload)
    assert "items" in result
    assert isinstance(result["items"], list)
    assert "is not of type" not in str(result)
