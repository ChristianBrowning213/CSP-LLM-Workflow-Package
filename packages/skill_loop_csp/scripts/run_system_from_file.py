from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class ExitCodeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_src_to_path() -> None:
    src = _repo_root() / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _to_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def _default_regularisation_spp_dir() -> str:
    _add_src_to_path()
    from sok_llm_orchestrator.contracts.spp_regularisation import CONFIG_C_REGULARISATION_SPP_DIR

    return CONFIG_C_REGULARISATION_SPP_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = ExitCodeArgumentParser(description="Run the crystal system from a plain text file.")
    parser.add_argument("input_file", help="Path to a text request file.")
    parser.add_argument("--out-root", default="local_runs", help="Directory for run outputs.")
    parser.add_argument("--batch-id", default=None, help="Optional stable batch directory name.")
    parser.add_argument("--mode", default="live", choices=["stub", "live"])
    parser.add_argument("--config", default=None, help="Optional YAML config path.")
    parser.add_argument("--with-guidance", type=_to_bool, default=True)
    parser.add_argument(
        "--regularisation-spp-dir",
        default=_default_regularisation_spp_dir(),
        help="Global SPP regularisation directory. Pass an empty string to disable the fallback.",
    )
    parser.add_argument("--regularisation-weight", default=2.0, type=float)
    parser.add_argument("--spp-guidance-weight", default=10.0, type=float)
    parser.add_argument("--missing-pair-policy", default="soft_repulsive")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--fail-on-pipeline-failure", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _add_src_to_path()
    from sok_llm_orchestrator.system_entrypoint import parse_prompt_lines, run_text_batch

    args = build_parser().parse_args(argv)
    try:
        prompts = parse_prompt_lines(Path(args.input_file).read_text(encoding="utf-8"))
        summary = run_text_batch(
            prompts,
            out_root=Path(args.out_root),
            batch_id=args.batch_id,
            mode=args.mode,
            config=Path(args.config) if args.config else None,
            with_spp=bool(args.with_guidance),
            stop_on_error=bool(args.stop_on_error),
            regularisation_spp_dir=Path(args.regularisation_spp_dir) if args.regularisation_spp_dir else None,
            regularisation_weight=float(args.regularisation_weight),
            spp_guidance_weight=float(args.spp_guidance_weight),
            missing_pair_policy=str(args.missing_pair_policy),
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    if bool(args.fail_on_pipeline_failure) and int(summary.get("failed", 0)) > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
