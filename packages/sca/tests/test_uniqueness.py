from pathlib import Path

from sca.batch import evaluate_folder


FIXTURES = Path(__file__).parent / "fixtures"


def test_uniqueness_groups_duplicate_cifs(tmp_path: Path) -> None:
    for name in ("tiny_valid.cif", "tiny_valid_copy.cif"):
        (tmp_path / name).write_text((FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8")

    records = evaluate_folder(tmp_path, target_formula="NaCl")

    assert len(records) == 2
    assert {record.duplicate_group_id for record in records} == {"dup-0001"}
    assert [record.is_unique_representative for record in records].count(True) == 1
