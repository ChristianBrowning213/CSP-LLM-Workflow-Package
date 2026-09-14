import json

from crystal_db.describe import describe_structure
from crystal_db.fingerprint import fingerprint_structure
from crystal_db.ingest import ingest_sample
from crystal_db.similarity import similar_structures


DB_PATH = "data/crystal_phase0.db"


def main() -> None:
    ingest_sample(db_path=DB_PATH, count=100)

    desc = describe_structure(structure_id="crystal-0001", db_path=DB_PATH, store=True)
    print("Descriptor:")
    print(json.dumps(desc, indent=2))

    fp = fingerprint_structure(structure_id="crystal-0001", db_path=DB_PATH, store=True)
    print("\nFingerprint:")
    print(json.dumps(fp, indent=2))

    # Backfill fingerprints for similarity
    for i in range(2, 101):
        fingerprint_structure(structure_id=f"crystal-{i:04d}", db_path=DB_PATH, store=True)

    neighbors = similar_structures(structure_id="crystal-0001", db_path=DB_PATH, k=5)
    print("\nSimilar structures:")
    print(json.dumps(neighbors, indent=2))


if __name__ == "__main__":
    main()
