import argparse
import json

from crystal_db.api import make_csp_pack, retrieve_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Crystal-DB library API demo")
    parser.add_argument("--db", dest="db_path", required=True)
    parser.add_argument("--query", dest="query", required=True)
    parser.add_argument("--k", dest="k", type=int, default=5)
    parser.add_argument("--pack-out", dest="pack_out", default=None)
    args = parser.parse_args()

    text_payload = retrieve_text(
        args.db_path,
        args.query,
        k=args.k,
        embed_engine="hash",
        model="hash-embed",
        model_version="v1",
        text_engine="caption",
        text_view="caption",
        hybrid=False,
        w_text=1.0,
        w_fp=0.0,
        redacted=True,
        show_text_top=1,
        demo_export=False,
    )
    print(json.dumps({"retrieve_text": text_payload}, indent=2))

    if args.pack_out:
        pack_payload = make_csp_pack(
            args.db_path,
            query=args.query,
            out_dir=args.pack_out,
            export_top=min(args.k, 3),
            redacted=True,
            demo_export=False,
            k=args.k,
            embed_engine="hash",
            model="hash-embed",
            model_version="v1",
            text_engine="caption",
            text_view="caption",
            hybrid=True,
            w_text=0.7,
            w_fp=0.3,
        )
        print(json.dumps({"make_csp_pack": pack_payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
