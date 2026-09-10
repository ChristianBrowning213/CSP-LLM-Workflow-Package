"""Repository package installation smoke tests."""


def test_packages_are_importable() -> None:
    import crystal_db  # noqa: F401
    import llm_csp  # noqa: F401
    import qlip  # noqa: F401

