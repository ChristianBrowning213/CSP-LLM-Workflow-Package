"""Write local Crystal-DB capability audit reports for the v2 challenge CSV."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_paper_evidence_pack_v2 import (  # noqa: E402
    _default_crystal_db_path,
    _load_csv,
    _rel,
    _write_capability_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="challenge_queries_100.csv")
    parser.add_argument("--out-root", default=str(Path("test_workdir") / "paper_evidence_pack_v2"))
    parser.add_argument("--crystal-db-path", default=None)
    args = parser.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = REPO_ROOT / csv_path
    out_root = Path(args.out_root)
    if not out_root.is_absolute():
        out_root = REPO_ROOT / out_root
    db_path = Path(args.crystal_db_path) if args.crystal_db_path else _default_crystal_db_path()
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path

    rows, _failures, _missing = _load_csv(csv_path)
    audit = _write_capability_audit(out_root, rows, db_path=db_path)
    print(
        json.dumps(
            {
                "out_root": _rel(out_root),
                "db_path": _rel(db_path),
                "total_structures": audit["corpus_counts"]["total_structures"],
                "exportable_cif_structures": audit["corpus_counts"]["exportable_cif_structures"],
                "challenge_rows": len(audit["challenge_support"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
