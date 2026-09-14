import json

from crystal_db.ingest import ingest_sample
from crystal_db.query import get_structure, query_structures


DB_PATH = "data/crystal_phase0.db"


def main() -> None:
    ingest_sample(db_path=DB_PATH, count=100)

    query_filter = {
        "elements_include": ["Li", "O"],
        "band_gap_eV_min": 2.0,
        "limit": 3,
        "order_by": "structure_id",
    }
    query_result = query_structures(query_filter, db_path=DB_PATH)
    print("Query result:")
    print(json.dumps(query_result, indent=2))

    if query_result["results"]:
        structure_id = query_result["results"][0]["structure_id"]
        structure = get_structure(structure_id, db_path=DB_PATH)
        print("\nGet structure:")
        print(json.dumps(structure, indent=2))


if __name__ == "__main__":
    main()
