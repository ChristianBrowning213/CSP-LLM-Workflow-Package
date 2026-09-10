import pytest


@pytest.mark.skip(
    reason=(
        "Production Crystal-DB text_search currently calls schema initialization; "
        "no verified strictly read-only 10k-index integration path is available"
    )
)
def test_external_crystal_db_retrieval_read_only_contract() -> None:
    """Enable only after Crystal-DB exposes a verified non-mutating retrieval connection."""
