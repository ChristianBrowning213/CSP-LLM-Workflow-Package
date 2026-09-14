from crystal_db.eval import run_eval


if __name__ == "__main__":
    results = run_eval("data/crystal_phase0.db")
    print("Eval run IDs:")
    for key, run_id in results.items():
        print(f"{key}: {run_id}")
