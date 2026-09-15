"""CLI discovery for versioned scaffolds."""

from __future__ import annotations

import argparse
import json

from .registry import get_scaffold, list_scaffolds, validate_scaffold


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m qlip.scaffolds")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list_scaffolds")
    get_parser = sub.add_parser("get_scaffold")
    get_parser.add_argument("scaffold_id")
    validate_parser = sub.add_parser("validate_scaffold")
    validate_parser.add_argument("scaffold_id")
    args = parser.parse_args()
    if args.command == "list_scaffolds":
        payload = [record.to_dict() for record in list_scaffolds()]
    elif args.command == "get_scaffold":
        payload = get_scaffold(args.scaffold_id).to_dict()
    else:
        payload = validate_scaffold(args.scaffold_id).to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
