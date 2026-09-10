import hashlib

from llm_csp.spp import export_required_pot_subset


def _write_pair(root, label, content):
    path = root / label / f"{label}.POT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_reverse_name_is_resolved_but_exported_canonically(tmp_path):
    source = tmp_path / "source"
    _write_pair(source, "O-O", b"same\n")
    reverse = _write_pair(source, "Sr-O", b"reverse-cross\n")
    _write_pair(source, "Sr-Sr", b"same\n")
    result = export_required_pot_subset(
        formula="SrO", source_pot_root=source, output_root=tmp_path / "output"
    )
    assert result["complete"] is True
    assert result["required_pairs"] == ["O-O", "O-Sr", "Sr-Sr"]
    cross = next(item for item in result["resolved_files"] if item["pair"] == "O-Sr")
    assert cross["source_file"] == str(reverse)
    assert cross["source_name_was_reversed"] is True
    exported = tmp_path / "output" / "O-Sr" / "O-Sr.POT"
    assert exported.read_bytes() == reverse.read_bytes()


def test_canonical_source_wins_when_reverse_duplicate_exists(tmp_path):
    source = tmp_path / "source"
    canonical = _write_pair(source, "O-Sr", b"canonical\n")
    _write_pair(source, "Sr-O", b"reverse\n")
    result = export_required_pot_subset(
        elements=["O", "Sr"], source_pot_root=source, output_root=tmp_path / "output"
    )
    cross = next(item for item in result["resolved_files"] if item["pair"] == "O-Sr")
    assert cross["source_file"] == str(canonical)
    assert (tmp_path / "output" / "O-Sr" / "O-Sr.POT").read_bytes() == b"canonical\n"


def test_missing_pair_is_machine_readable_and_root_is_not_complete(tmp_path):
    source = tmp_path / "source"
    _write_pair(source, "A-A", b"a\n")
    _write_pair(source, "B-B", b"b\n")
    result = export_required_pot_subset(
        elements=["A", "B"], source_pot_root=source, output_root=tmp_path / "output"
    )
    assert result["status"] == "incomplete"
    assert result["complete"] is False
    assert result["missing_pairs"] == ["A-B"]
    assert not (tmp_path / "output" / "A-B" / "A-B.POT").exists()


def test_export_preserves_pot_content_hashes(tmp_path):
    source = tmp_path / "source"
    original = _write_pair(source, "A-A", b"exact POT bytes\r\n1 2\r\n")
    result = export_required_pot_subset(
        elements=["A"], source_pot_root=source, output_root=tmp_path / "output"
    )
    exported = tmp_path / "output" / "A-A" / "A-A.POT"
    expected = hashlib.sha256(original.read_bytes()).hexdigest()
    assert result["resolved_files"][0]["sha256"] == expected
    assert hashlib.sha256(exported.read_bytes()).hexdigest() == expected
