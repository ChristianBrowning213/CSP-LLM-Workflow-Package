from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import tempfile

from crystal_db.db import init_db


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_paper_scaffolds_specialist_corpora.py"
SPEC = importlib.util.spec_from_file_location("build_paper_scaffolds_specialist_corpora", SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(builder)


def test_copy_condensed_preserves_structured_robocrys_row():
    with tempfile.TemporaryDirectory() as temporary_directory:
        source = sqlite3.connect(Path(temporary_directory) / "source.db")
        source.row_factory = sqlite3.Row
        destination = sqlite3.connect(Path(temporary_directory) / "destination.db")
        destination.row_factory = sqlite3.Row
        init_db(source)
        init_db(destination)
        source.execute(
            "INSERT INTO robocrys_condensed VALUES (?,?,?,?,?,?)",
            ("one", "robocrys.v1", "{}", "condensed-hash", "description-hash", "2026-01-01"),
        )
        source.commit()

        builder.copy_condensed(source, destination, "one")
        destination.commit()

        assert destination.execute(
            "SELECT condensed_sha256 FROM robocrys_condensed WHERE structure_id='one'"
        ).fetchone()[0] == "condensed-hash"
        source.close()
        destination.close()


def test_nasicon_selection_uses_only_tier_one_proxy_records(monkeypatch):
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        corpus = root / "data/corpora/nasicon_specialist_v3"
        corpus.mkdir(parents=True)
        connection = sqlite3.connect(corpus / "crystaldb.sqlite")
        connection.row_factory = sqlite3.Row
        init_db(connection)
        for structure_id, source_id in (("one", "tier-one.cif"), ("two", "tier-two.cif")):
            connection.execute(
                "INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?,?,?)",
                (structure_id, "fixture", source_id, "2026", "", "local_cif", 1, 1, 1, 0),
            )
        connection.commit()
        connection.close()
        (corpus / "manifest.jsonl").write_text(
            '{"internal_id":"tier-one","topology_tier":"TIER_1_TOPOLOGY_PROXY","family_assignment_evidence":{"rank":3}}\n'
            '{"internal_id":"tier-two","topology_tier":"TIER_2_CHEMICAL_FRAMEWORK"}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(builder, "SKILL_LOOP_ROOT", root)

        _, selected, _ = builder.nasicon_selection()

        assert selected == [
            {
                "structure_id": "one",
                "topology_tier": "TIER_1_TOPOLOGY_PROXY",
                "evidence": {"rank": 3},
            }
        ]
