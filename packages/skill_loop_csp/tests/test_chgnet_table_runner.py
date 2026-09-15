from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
from pathlib import Path

from pymatgen.core import Lattice, Structure


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_chgnet_table.py"
SPEC = importlib.util.spec_from_file_location("_test_chgnet_table_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_hash_frozen_chgnet_input_table_validates_without_model_execution() -> None:
    parent = Path.cwd() / "test_workdir" / "chgnet_table_runner"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as temporary:
        root = Path(temporary)
        cif = root / "input.cif"
        Structure(Lattice.cubic(4), ["Na", "Cl"], [(0, 0, 0), (0.5, 0.5, 0.5)]).to(filename=cif)
        table = root / "inputs.csv"
        with table.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MODULE.REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerow({
                "row_id": "qc-1", "formula": "NaCl", "cif_path": str(cif),
                "cif_sha256": MODULE.sha256(cif), "protocol_id": MODULE.PROTOCOL_ID,
            })
        rows = MODULE.load_rows(table)
        assert len(rows) == 1
        assert rows[0]["row_id"] == "qc-1"
