from crystal_db.ingest import ingest_sample


if __name__ == "__main__":
    ids = ingest_sample()
    print(f"Ingested {len(ids)} synthetic structures.")
