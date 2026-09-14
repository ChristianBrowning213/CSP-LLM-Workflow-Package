#!/usr/bin/env python3
"""Inventory POT assets across repositories and identify SHA-256 duplicates.

Read-only: only ever opens scanned files in 'rb' mode. Never copies, moves,
or deletes anything under the scanned root directories.
"""

import csv
import hashlib
import os
import sys
from collections import defaultdict

MANIFEST_COLUMNS = [
    "source_repository",
    "source_path",
    "pair",
    "size",
    "sha256",
    "library_role",
    "runtime_required",
    "generated_or_source",
    "provenance",
    "redistribution_status",
    "duplicate_group",
]


def get_pair_name(filename):
    """Extract the pair name from a POT filename.

    Real POT files use a plain hyphenated species-pair convention with no
    suffix, e.g. 'Cl-Na.POT', 'C-Si.POT' — the pair name is simply the
    filename stem.
    """
    if filename.endswith(".POT"):
        return filename[:-4]
    return filename


def find_pot_files(root_dirs):
    """Find all .POT files in the given root directories.

    Returns (root_dir, filepath) pairs so the source repository name can be
    derived from the root_dir argument itself, independent of whether it is
    relative or absolute and independent of the current working directory.
    """
    pot_files = []
    for root_dir in root_dirs:
        if not os.path.exists(root_dir):
            print("Warning: directory does not exist: {}".format(root_dir))
            continue
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            for filename in filenames:
                if filename.endswith(".POT"):
                    pot_files.append((root_dir, os.path.join(dirpath, filename)))
    return pot_files


def compute_file_hash(filepath):
    """Compute SHA-256 of a file using a streamed, read-only pass."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def process_pot_files(pot_files):
    """Hash every file and group entries by SHA-256."""
    hash_groups = defaultdict(list)
    for root_dir, filepath in pot_files:
        try:
            sha256 = compute_file_hash(filepath)
            size = os.path.getsize(filepath)
        except OSError as exc:
            print("Error processing {}: {}".format(filepath, exc))
            continue
        repo_name = os.path.basename(os.path.normpath(root_dir))
        filename = os.path.basename(filepath)
        hash_groups[sha256].append(
            {
                "source_repository": repo_name,
                "source_path": filepath,
                "pair": get_pair_name(filename),
                "size": size,
                "sha256": sha256,
            }
        )
    return hash_groups


def write_manifest(hash_groups, output_file):
    """Write every file's row to the manifest CSV.

    Every file in a duplicate group gets a row (no data loss), sharing one
    duplicate_group id; singleton files get duplicate_group 0.
    """
    rows = []
    next_group_id = 1
    for sha256, entries in hash_groups.items():
        if len(entries) > 1:
            group_id = next_group_id
            next_group_id += 1
        else:
            group_id = 0
        for entry in entries:
            row = dict(entry)
            row["duplicate_group"] = group_id
            row["library_role"] = ""
            row["runtime_required"] = ""
            row["generated_or_source"] = ""
            row["provenance"] = ""
            row["redistribution_status"] = ""
            rows.append(row)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("Usage: python pot_asset_inventory.py <root_directory1> [root_directory2] ... [root_directoryN]")
        print("Example: python pot_asset_inventory.py SPP-Maker-QLIP Skill-Loop-CSP QLIP")
        return 1

    root_dirs = argv
    pot_files = find_pot_files(root_dirs)
    print("Found {} POT files across {} director{}.".format(
        len(pot_files), len(root_dirs), "y" if len(root_dirs) == 1 else "ies"
    ))
    if not pot_files:
        print("No POT files found.")
        return 0

    hash_groups = process_pot_files(pot_files)
    duplicate_groups = [g for g in hash_groups.values() if len(g) > 1]
    print("Found {} duplicate group(s).".format(len(duplicate_groups)))

    output_file = "docs/fidelity/SPP_POT_ASSET_MANIFEST.csv"
    write_manifest(hash_groups, output_file)
    print("Manifest written to {}".format(output_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
