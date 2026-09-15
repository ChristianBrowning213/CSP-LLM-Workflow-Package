"""Command line interface for SCA."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import typer
from click import ClickException
from rich.console import Console

from sca.backends import verify_optional_backends
from sca.advanced_analysis import analyse_crystal_advanced, write_advanced_report
from sca.benchmark import benchmark_folder, benchmark_manifest, benchmark_one
from sca.benchmark_protocols.direct import protocol_rows_with_computability, run_direct_cif_benchmark
from sca.benchmark_protocols.e2e import run_e2e_text_benchmark
from sca.benchmark_protocols.e2e_intent_runner import (
    run_full_intent_benchmark_evaluation,
    run_full_skill_loop_intent_benchmark,
    run_skill_loop_intent_benchmark,
)
from sca.benchmark_protocols.intent_prompts import build_intent_prompt_manifest
from sca.benchmark_protocols.literature_comparison import build_literature_comparison_report
from sca.benchmark_protocols.sun import build_reference_manifest, run_sun_benchmark
from sca.benchmark_protocols.symmetry_intent import run_symmetry_intent_benchmark
from sca.batch import evaluate_folder, evaluate_manifest, evaluate_many, evaluate_one
from sca.evaluators.alignn import AlignnEvaluator, DEFAULT_ALIGNN_MODEL
from sca.evaluators.novelty import load_reference_structures_with_stats
from sca.evaluators.registry import get_evaluator_spec, list_evaluator_specs
from sca.dft.backends import get_backend
from sca.dft.io import write_json as write_dft_json
from sca.dft.workflow import collect_results, prepare_manifest, status_prepared, submit_prepared
from sca.electronic_stack import (
    build_raw_baseline,
    run_chgnet_relaxation_campaign,
    run_static_campaign,
    validate_paper_manifest,
    write_backend_readiness,
)
from sca.io import discover_cif_files, load_manifest, write_csv, write_jsonl, write_single_json, write_summary_csv
from sca.paper_benchmarks.diagnostics import (
    build_paper_target_diagnostics,
    write_diagnostics_outputs,
)
from sca.paper_benchmarks.manifest_builder import build_paper_run_manifest
from sca.paper_benchmarks.summary import build_paper_benchmark_summary, write_summary_outputs
from sca.pipelines.crystallm_style import evaluate_one_cif
from sca.schemas import AggregateSummary
from sca.traceability.io import inspect_run_bundle
from sca.traceability.adapters.llm_csp_archive import (
    detect_llm_csp_archive,
    load_llm_csp_archive,
    write_traceable_bundle,
)
from sca.traceability.reports import write_bundle_inspection_outputs
from sca.unique_benchmarks.repairability import run_repairability_benchmark
from sca.unique_benchmarks.retrieval_ablation import run_retrieval_ablation_benchmark
from sca.unique_benchmarks.summary import build_unique_csp_summary

app = typer.Typer(help="Structured Crystal Analyser.")
crystallm_app = typer.Typer(help="CrystaLLM-style pre-DFT crystal evaluation.")
alignn_app = typer.Typer(help="ALIGNN-based crystal structure evaluation.")
benchmark_app = typer.Typer(help="Modular generated-crystal benchmarking.")
dft_app = typer.Typer(help="Prepare, submit, track, and collect external DFT calculations.")
app.add_typer(crystallm_app, name="crystallm-eval")
app.add_typer(alignn_app, name="alignn")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(dft_app, name="dft")
console = Console()


def _parse_bool(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise typer.BadParameter(f"Expected true or false, got '{value}'")


def _parse_evaluators(value: str) -> list[str]:
    names = [name.strip() for name in value.split(",") if name.strip()]
    if not names:
        raise typer.BadParameter("At least one evaluator name is required")
    for name in names:
        try:
            get_evaluator_spec(name)
        except KeyError as exc:
            raise typer.BadParameter(str(exc)) from exc
    return names


@app.command("list-evaluators")
def list_evaluators() -> None:
    """List registered benchmark evaluators and optional dependency status."""

    rows = []
    for spec in list_evaluator_specs():
        rows.append(
            {
                "name": spec.name,
                "available": spec.available,
                "optional_dependencies": ",".join(spec.optional_dependencies),
                "missing_dependencies": ",".join(spec.missing_dependencies),
                "description": spec.description,
            }
        )
    console.print_json(data=rows)


@app.command("verify-backends")
def verify_backends(
    functional: bool = typer.Option(False, "--functional", help="Run tiny functional smoke checks where available."),
    csv_out: Path | None = typer.Option(None, "--csv", help="Optional CSV output path."),
    json_out: Path | None = typer.Option(None, "--json", help="Optional JSON output path."),
    markdown: Path | None = typer.Option(None, "--markdown", help="Optional Markdown output path."),
) -> None:
    """Check optional benchmark backend imports and local model configuration."""

    rows = verify_optional_backends(functional=functional)
    if csv_out:
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(csv_out, index=False)
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8")
    if markdown:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text("# MLIP backend readiness\n\n" + pd.DataFrame(rows).to_markdown(index=False) + "\n", encoding="utf-8")
    console.print_json(data=rows)


@app.command("validate-paper16-manifest")
def validate_paper16_manifest_cli(
    manifest: Path = typer.Option(
        Path("benchmarks/paper_advanced_validation/PAPER_16_MANIFEST.csv"),
        "--manifest",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
) -> None:
    """Validate the immutable paper-16 paths, hashes, roster, and intent provenance."""

    result = validate_paper_manifest(manifest)
    console.print_json(data=result)
    if not result["valid"]:
        raise typer.Exit(1)


@app.command("build-paper16-baseline")
def build_paper16_baseline_cli(
    manifest: Path = typer.Option(
        Path("benchmarks/paper_advanced_validation/PAPER_16_MANIFEST.csv"), "--manifest"
    ),
    out_dir: Path = typer.Option(Path("artifacts/electronic_stack/paper16"), "--out-dir"),
) -> None:
    """Build the immutable raw paper-16 baseline and MLIP readiness files."""

    rows = build_raw_baseline(manifest, out_dir)
    write_backend_readiness(out_dir)
    console.print(f"[green]Wrote {len(rows)} raw paper baseline rows[/green] to {out_dir}")


@app.command("run-paper16-mlip")
def run_paper16_mlip_cli(
    manifest: Path = typer.Option(
        Path("benchmarks/paper_advanced_validation/PAPER_16_MANIFEST.csv"), "--manifest"
    ),
    out_dir: Path = typer.Option(Path("artifacts/electronic_stack/paper16"), "--out-dir"),
    static_only: bool = typer.Option(False, "--static-only"),
) -> None:
    """Run available real paper-16 MLIP models with structured optional-backend skips."""

    static_rows = run_static_campaign(manifest, out_dir)
    if not static_only:
        run_chgnet_relaxation_campaign(manifest, out_dir)
    console.print(f"[green]Wrote {len(static_rows)} MLIP static records[/green] to {out_dir}")


@app.command("analyse-crystal")
def analyse_crystal_cli(
    cif: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    intent: Path | None = typer.Option(None, "--intent", exists=True, file_okay=True, dir_okay=False),
    level: str = typer.Option("advanced", "--level"),
    layers: Path | None = typer.Option(None, "--layers", exists=True, file_okay=True, dir_okay=False),
    out_dir: Path = typer.Option(Path("reports/advanced_analysis"), "--out-dir"),
) -> None:
    """Build a unified report whose unavailable optional evidence remains explicit."""

    if level.lower() != "advanced":
        raise typer.BadParameter("Only --level advanced is currently supported")
    intent_data = json.loads(intent.read_text(encoding="utf-8")) if intent else None
    layer_data = json.loads(layers.read_text(encoding="utf-8")) if layers else None
    result = analyse_crystal_advanced(cif, intent=intent_data, layers=layer_data)
    paths = write_advanced_report(result, out_dir)
    console.print_json(data={"scientific_quality_dimensions": result.scientific_quality_dimensions, "outputs": paths})


@dft_app.command("backends")
def dft_backends_cli() -> None:
    """Report DFT adapter and executable readiness without claiming execution."""

    backend = get_backend("castep")
    console.print_json(
        data=[
            {
                "backend": "castep",
                "adapter_available": True,
                "executable_available": backend.executable_available(),
                "engine_version": backend.version(),
                "status": "READY" if backend.executable_available() else "BLOCKED_ENVIRONMENT",
            }
        ]
    )


@dft_app.command("prepare")
def dft_prepare_cli(
    manifest: Path = typer.Option(..., "--manifest", exists=True, file_okay=True, dir_okay=False),
    backend: str = typer.Option(..., "--backend"),
    config: Path = typer.Option(..., "--config", exists=True, file_okay=True, dir_okay=False),
    out_dir: Path = typer.Option(..., "--out-dir"),
    slurm_config: Path | None = typer.Option(None, "--slurm-config", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Prepare reproducible external-engine inputs without launching calculations."""

    try:
        prepared = prepare_manifest(manifest, backend, config, out_dir, slurm_config_path=slurm_config)
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print_json(data={"status": "PREPARED", "calculations": [str(path) for path in prepared]})


@dft_app.command("submit")
def dft_submit_cli(
    calculations: Path = typer.Option(..., "--calculations", exists=True, file_okay=False, dir_okay=True),
) -> None:
    """Submit prepared calculations through Slurm and persist real returned job IDs."""

    rows = submit_prepared(calculations)
    console.print_json(data=[row.model_dump(mode="json") for row in rows])


@dft_app.command("status")
def dft_status_cli(
    calculations: Path = typer.Option(..., "--calculations", exists=True, file_okay=False, dir_okay=True),
    json_out: Path | None = typer.Option(None, "--json"),
) -> None:
    """Normalize Slurm states without inferring convergence."""

    rows = status_prepared(calculations)
    data = [row.model_dump(mode="json") for row in rows]
    if json_out:
        write_dft_json(json_out, {"rows": data})
    console.print_json(data=data)


@dft_app.command("collect")
def dft_collect_cli(
    calculations: Path = typer.Option(..., "--calculations", exists=True, file_okay=False, dir_okay=True),
    out_dir: Path = typer.Option(..., "--out-dir"),
) -> None:
    """Parse backend outputs into structured DFT results and failures."""

    rows = collect_results(calculations, out_dir)
    console.print_json(data={"rows": len(rows), "out_dir": str(out_dir)})


@app.command("list-benchmark-protocols")
def list_benchmark_protocols(
    json_out: Path | None = typer.Option(None, "--json", help="Optional JSON output path."),
    results: Path | None = typer.Option(None, "--results", exists=True, file_okay=True, dir_okay=False, readable=True, help="Optional results CSV used to mark computability."),
) -> None:
    """List built-in literature benchmark protocols."""

    rows = protocol_rows_with_computability(results)
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    console.print_json(data=rows)


@app.command("build-intent-benchmark-manifest")
def build_intent_benchmark_manifest_cli(
    out: Path = typer.Option(..., "--out", help="Output CSV prompt manifest."),
    json_out: Path | None = typer.Option(None, "--json", help="Output JSON prompt manifest."),
    seed: int = typer.Option(..., "--seed"),
    num_prompts: int = typer.Option(100, "--num-prompts", min=1),
) -> None:
    """Build a seeded natural-language intent prompt manifest."""

    try:
        result = build_intent_prompt_manifest(out_csv=out, out_json=json_out, seed=seed, num_prompts=num_prompts)
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Wrote {result['rows']} intent prompts[/green] to {result['csv']}")


@app.command("run-skill-loop-intent-benchmark")
def run_skill_loop_intent_benchmark_cli(
    prompts: Path = typer.Option(..., "--prompts", exists=True, file_okay=True, dir_okay=False, readable=True),
    skill_loop_command: str = typer.Option(..., "--skill-loop-command"),
    out_root: Path = typer.Option(..., "--out-root"),
    seed: int = typer.Option(..., "--seed"),
    num_attempts: int = typer.Option(1, "--num-attempts", min=1),
) -> None:
    """Run Skill-Loop-CSP for each intent prompt and collect CIF outputs."""

    try:
        result = run_skill_loop_intent_benchmark(
            prompts=prompts,
            skill_loop_command=skill_loop_command,
            out_root=out_root,
            seed=seed,
            num_attempts=num_attempts,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(
        f"[green]Ran {result['prompts']} intent prompts[/green]; "
        f"collected {result['generated_cifs']} CIFs into {result['manifest']}"
    )


@app.command("run-full-intent-benchmark-evaluation")
def run_full_intent_benchmark_evaluation_cli(
    run_root: Path = typer.Option(..., "--run-root", exists=True, file_okay=False, dir_okay=True, readable=True),
    manifest: Path = typer.Option(..., "--manifest", exists=True, file_okay=True, dir_okay=False, readable=True),
    seed: int = typer.Option(..., "--seed"),
) -> None:
    """Run direct, intent, unique-traceability, diagnostics, and final reports."""

    try:
        result = run_full_intent_benchmark_evaluation(run_root=run_root, manifest=manifest, seed=seed)
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Wrote full intent benchmark report[/green] to {result['report']}")


@app.command("run-full-skill-loop-intent-benchmark")
def run_full_skill_loop_intent_benchmark_cli(
    skill_loop_command: str = typer.Option(..., "--skill-loop-command"),
    out_root: Path = typer.Option(..., "--out-root"),
    seed: int = typer.Option(..., "--seed"),
    num_prompts: int = typer.Option(100, "--num-prompts", min=1),
    num_attempts: int = typer.Option(1, "--num-attempts", min=1),
    skip_generation: bool = typer.Option(False, "--skip-generation"),
    skip_evaluation: bool = typer.Option(False, "--skip-evaluation"),
) -> None:
    """Build prompts, run Skill-Loop-CSP, evaluate, and write final reports."""

    try:
        result = run_full_skill_loop_intent_benchmark(
            skill_loop_command=skill_loop_command,
            out_root=out_root,
            seed=seed,
            num_prompts=num_prompts,
            num_attempts=num_attempts,
            skip_generation=skip_generation,
            skip_evaluation=skip_evaluation,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Full intent benchmark completed[/green]; prompts={result['prompts']}")


@app.command("run-sun-benchmark")
def run_sun_benchmark_cli(
    manifest: Path = typer.Option(..., "--manifest", exists=True, file_okay=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(..., "--out-dir"),
    reference_folder: Path | None = typer.Option(None, "--reference-folder", exists=True, file_okay=False, dir_okay=True, readable=True),
    reference_manifest: Path | None = typer.Option(None, "--reference-manifest", exists=True, file_okay=True, dir_okay=False, readable=True),
    path_col: str = typer.Option("cif_path", "--path-col"),
    reference_path_col: str = typer.Option("cif_path", "--reference-path-col"),
    reference_id_col: str | None = typer.Option(None, "--reference-id-col"),
    anonymous: bool = typer.Option(False, "--anonymous", help="Use anonymous StructureMatcher novelty matching."),
) -> None:
    """Run evaluation-only Stability, Uniqueness, Novelty benchmarking."""

    try:
        result = run_sun_benchmark(
            manifest=manifest,
            out_dir=out_dir,
            reference_folder=reference_folder,
            reference_manifest=reference_manifest,
            path_col=path_col,
            reference_path_col=reference_path_col,
            reference_id_col=reference_id_col,
            anonymous=anonymous,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(
        f"[green]Wrote S.U.N. benchmark outputs[/green] "
        f"({result['rows']} rows) to {result['results_csv']}"
    )


@app.command("build-literature-comparison-report")
def build_literature_comparison_report_cli(
    run_root: Path = typer.Option(..., "--run-root", exists=True, file_okay=False, dir_okay=True, readable=True),
    comparators: Path = typer.Option(..., "--comparators", exists=True, file_okay=True, dir_okay=False, readable=True),
    out_markdown: Path = typer.Option(..., "--out-markdown", help="Output Markdown report."),
    out_json: Path = typer.Option(..., "--out-json", help="Output JSON report."),
) -> None:
    """Build a literature-aware comparison report for a completed intent run."""

    try:
        result = build_literature_comparison_report(
            run_root=run_root,
            comparators=comparators,
            out_markdown=out_markdown,
            out_json=out_json,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(
        f"[green]Wrote literature comparison report[/green] "
        f"with {result['comparators']} comparator rows to {result['markdown']}"
    )


@app.command("run-symmetry-intent-benchmark")
def run_symmetry_intent_benchmark_cli(
    manifest: Path = typer.Option(..., "--manifest", exists=True, file_okay=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(..., "--out-dir"),
    symprec: str = typer.Option("0.01", "--symprec", help="One value or comma-separated values, e.g. 0.001,0.01,0.1."),
    angle_tolerance: float = typer.Option(5.0, "--angle-tolerance"),
    path_col: str = typer.Option("cif_path", "--path-col"),
) -> None:
    """Run dedicated space-group/crystal-system intent checks."""

    try:
        result = run_symmetry_intent_benchmark(
            manifest=manifest,
            out_dir=out_dir,
            symprec=symprec,
            angle_tolerance=angle_tolerance,
            path_col=path_col,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(
        f"[green]Wrote symmetry intent benchmark outputs[/green] "
        f"({result['rows']} rows) to {result['results_csv']}"
    )


@app.command("build-reference-manifest")
def build_reference_manifest_cli(
    cif_dir: Path = typer.Option(..., "--cif-dir", exists=True, file_okay=False, dir_okay=True, readable=True),
    out: Path = typer.Option(..., "--out"),
    reference_set_name: str = typer.Option(..., "--reference-set-name"),
) -> None:
    """Build an evaluation-only reference manifest from a CIF folder."""

    try:
        result = build_reference_manifest(
            cif_dir=cif_dir,
            out=out,
            reference_set_name=reference_set_name,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Wrote {result['rows']} reference rows[/green] to {result['out']}")


@app.command("benchmark-cif-set")
def benchmark_cif_set(
    cif_folder: Path | None = typer.Option(None, "--cif-folder", exists=True, file_okay=False, dir_okay=True, readable=True),
    manifest: Path | None = typer.Option(None, "--manifest", exists=True, file_okay=True, dir_okay=False, readable=True),
    protocols: str = typer.Option("all", "--protocols"),
    out: Path = typer.Option(..., "--out", help="Output direct CIF benchmark result CSV."),
    summary: Path = typer.Option(..., "--summary", help="Output comparator summary CSV."),
    json_out: Path = typer.Option(..., "--json", help="Output comparator summary JSON."),
    markdown: Path = typer.Option(..., "--markdown", help="Output Markdown report."),
    evaluators: str = typer.Option("auto", "--evaluators"),
    include_relaxation: bool = typer.Option(False, "--include-relaxation"),
    relax_backend: str = typer.Option("chgnet", "--relax-backend"),
    hull_reference: Path | None = typer.Option(None, "--hull-reference", exists=True, file_okay=True, dir_okay=False),
    reference_corpus: Path | None = typer.Option(None, "--reference-corpus", exists=True),
    protocol_match_level: str = typer.Option("contextual_only", "--protocol-match-level"),
    path_col: str = typer.Option("cif_path", "--path-col"),
    attempt_col: str = typer.Option("attempt_id", "--attempt-col"),
    target_col: str = typer.Option("benchmark_id", "--target-col"),
    method_col: str = typer.Option("method", "--method-col"),
) -> None:
    """Run direct CIF-set benchmark and literature comparator report."""

    try:
        result = run_direct_cif_benchmark(
            cif_folder=cif_folder,
            manifest=manifest,
            protocols=protocols,
            out_csv=out,
            summary_csv=summary,
            json_out=json_out,
            markdown=markdown,
            evaluators=evaluators,
            include_relaxation=include_relaxation,
            relax_backend=relax_backend,
            hull_reference=hull_reference,
            reference_corpus=reference_corpus,
            protocol_match_level=protocol_match_level,
            path_col=path_col,
            attempt_col=attempt_col,
            target_col=target_col,
            method_col=method_col,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(
        f"[green]Wrote {result['records']} direct CIF benchmark records[/green] "
        f"to {result['results_csv']} and {result['summary_csv']}"
    )


@app.command("run-e2e-text-benchmark")
def run_e2e_text_benchmark_cli(
    prompts: Path = typer.Option(..., "--prompts", exists=True, file_okay=True, dir_okay=False, readable=True),
    generator_command: str = typer.Option(..., "--generator-command"),
    out_dir: Path = typer.Option(..., "--out-dir"),
    num_attempts: int = typer.Option(20, "--num-attempts", min=1),
    protocols: str = typer.Option("all", "--protocols"),
    summary: Path = typer.Option(..., "--summary"),
    markdown: Path = typer.Option(..., "--markdown"),
    results: Path | None = typer.Option(None, "--results"),
    json_out: Path | None = typer.Option(None, "--json"),
    protocol_match_level: str = typer.Option("contextual_only", "--protocol-match-level"),
) -> None:
    """Run text prompts through a generator command and benchmark generated CIFs."""

    try:
        result = run_e2e_text_benchmark(
            prompts=prompts,
            generator_command=generator_command,
            out_dir=out_dir,
            num_attempts=num_attempts,
            protocols=protocols,
            summary=summary,
            markdown=markdown,
            results=results,
            json_out=json_out,
            protocol_match_level=protocol_match_level,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(
        f"[green]Ran {result['prompts']} prompts and collected {result['generated_cifs']} CIFs[/green]; "
        f"summary written to {result['summary_csv']}"
    )


@app.command("inspect-run-bundle")
def inspect_run_bundle_cli(
    run_dir: Path = typer.Option(..., "--run-dir", exists=True, file_okay=False, dir_okay=True, readable=True),
    out: Path = typer.Option(..., "--out", help="Output inspection CSV."),
    json_out: Path = typer.Option(..., "--json", help="Output inspection JSON."),
    markdown: Path = typer.Option(..., "--markdown", help="Output inspection Markdown report."),
) -> None:
    """Inspect a traceable text-to-crystal CSP run bundle."""

    try:
        inspection = inspect_run_bundle(run_dir)
        write_bundle_inspection_outputs([inspection], out, json_out, markdown)
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Inspected run bundle[/green] {run_dir}; valid={inspection.bundle_valid}")


@app.command("convert-run-archive-to-bundle")
def convert_run_archive_to_bundle_cli(
    archive: Path = typer.Option(..., "--archive", exists=True, file_okay=False, dir_okay=True, readable=True),
    out_dir: Path = typer.Option(..., "--out-dir"),
    run_id: str | None = typer.Option(None, "--run-id"),
    markdown: Path | None = typer.Option(None, "--markdown", help="Optional inspection Markdown report."),
) -> None:
    """Convert one LLM-CSP/QLIP/evidence-pack archive into a traceable bundle."""

    try:
        if not detect_llm_csp_archive(archive):
            raise ValueError(f"Archive does not look like an LLM-CSP/QLIP run archive: {archive}")
        bundle = load_llm_csp_archive(archive, run_id=run_id)
        result = write_traceable_bundle(bundle, out_dir)
        inspection = inspect_run_bundle(out_dir)
        if markdown:
            write_bundle_inspection_outputs(
                [inspection],
                out_dir / "bundle_inspection.csv",
                out_dir / "bundle_inspection.json",
                markdown,
            )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(
        f"[green]Converted archive[/green] {archive} -> {result['out_dir']}; "
        f"valid={inspection.bundle_valid}"
    )


@app.command("convert-run-archives-to-bundles")
def convert_run_archives_to_bundles_cli(
    archives_root: Path = typer.Option(..., "--archives-root", exists=True, file_okay=False, dir_okay=True, readable=True),
    out_dir: Path = typer.Option(..., "--out-dir"),
    summary: Path = typer.Option(..., "--summary"),
) -> None:
    """Batch-convert child run archives into traceable bundles."""

    rows = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        child_archives = [
            path for path in sorted(archives_root.iterdir()) if path.is_dir() and detect_llm_csp_archive(path)
        ]
        candidates = child_archives or ([archives_root] if detect_llm_csp_archive(archives_root) else [])
        for archive in candidates:
            run_id = archive.name
            target = out_dir / run_id
            try:
                bundle = load_llm_csp_archive(archive, run_id=run_id)
                result = write_traceable_bundle(bundle, target)
                inspection = inspect_run_bundle(target)
                row = {
                    **result["manifest_row"],
                    "archive": str(archive),
                    "bundle_valid": inspection.bundle_valid,
                    "missing_artifacts": ";".join(inspection.missing_artifacts),
                    "parse_errors": ";".join(inspection.parse_errors),
                }
            except Exception as exc:
                row = {
                    "run_id": run_id,
                    "archive": str(archive),
                    "bundle_dir": str(target),
                    "bundle_valid": False,
                    "conversion_errors": str(exc),
                }
            rows.append(row)
        summary.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(summary, index=False)
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Converted {len(rows)} archives[/green]; summary written to {summary}")


@app.command("run-retrieval-ablation-benchmark")
def run_retrieval_ablation_benchmark_cli(
    prompts: Path = typer.Option(..., "--prompts", exists=True, file_okay=True, dir_okay=False, readable=True),
    generator_command: str = typer.Option(..., "--generator-command"),
    retrieval_modes: str = typer.Option("none,metadata,evidence_spp", "--retrieval-modes"),
    out_dir: Path = typer.Option(..., "--out-dir"),
    summary: Path = typer.Option(..., "--summary"),
    json_out: Path = typer.Option(..., "--json"),
    markdown: Path = typer.Option(..., "--markdown"),
) -> None:
    """Run a fake-or-real retrieval-mode ablation and summarize uplift metrics."""

    try:
        result = run_retrieval_ablation_benchmark(
            prompts=prompts,
            generator_command=generator_command,
            retrieval_modes=retrieval_modes,
            out_dir=out_dir,
            summary=summary,
            json_out=json_out,
            markdown=markdown,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Wrote retrieval ablation report[/green] with {result['rows']} rows")


@app.command("run-repairability-benchmark")
def run_repairability_benchmark_cli(
    cases: Path = typer.Option(..., "--cases", exists=True, file_okay=True, dir_okay=False, readable=True),
    repair_command: str = typer.Option(..., "--repair-command"),
    out_dir: Path = typer.Option(..., "--out-dir"),
    summary: Path = typer.Option(..., "--summary"),
    json_out: Path = typer.Option(..., "--json"),
    markdown: Path = typer.Option(..., "--markdown"),
) -> None:
    """Run repairability cases and write before/after repair metrics."""

    try:
        result = run_repairability_benchmark(
            cases=cases,
            repair_command=repair_command,
            out_dir=out_dir,
            summary=summary,
            json_out=json_out,
            markdown=markdown,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Wrote repairability report[/green] with {result['rows']} rows")


@app.command("unique-csp-benchmark-summary")
def unique_csp_benchmark_summary_cli(
    results: Path | None = typer.Option(None, "--results", file_okay=True, dir_okay=False, readable=True),
    bundles: Path = typer.Option(..., "--bundles", exists=True, file_okay=False, dir_okay=True, readable=True),
    out: Path = typer.Option(..., "--out", help="Output unique benchmark summary CSV."),
    json_out: Path = typer.Option(..., "--json", help="Output unique benchmark summary JSON."),
    markdown: Path = typer.Option(..., "--markdown", help="Output unique benchmark Markdown report."),
) -> None:
    """Build the unique traceable-constraint-grounded CSP composite report."""

    try:
        result = build_unique_csp_summary(
            results=results,
            bundles=bundles,
            out_csv=out,
            json_out=json_out,
            markdown=markdown,
        )
    except Exception as exc:
        raise ClickException(str(exc)) from exc
    console.print(f"[green]Wrote unique CSP benchmark summary[/green] with {result['rows']} rows")


@crystallm_app.command("one")
def crystallm_one(
    cif_path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    target_formula: str | None = typer.Option(None, "--target-formula"),
    target_space_group: str | None = typer.Option(None, "--target-space-group"),
    out: Path = typer.Option(..., "--out", help="Output JSON path."),
    require_spacegroup: str = typer.Option("false", "--require-spacegroup"),
    alignn: str = typer.Option("false", "--alignn"),
    novelty: str = typer.Option("false", "--novelty"),
    reference_folder: Path | None = typer.Option(None, "--reference-folder", exists=True, file_okay=False, dir_okay=True),
    reference_manifest: Path | None = typer.Option(None, "--reference-manifest", exists=True, file_okay=True, dir_okay=False),
    reference_path_col: str = typer.Option("cif_path", "--reference-path-col"),
    reference_id_col: str | None = typer.Option(None, "--reference-id-col"),
) -> None:
    """Evaluate one CIF with CrystaLLM-style pre-DFT checks."""

    reference_structures = _load_references_for_cli(
        novelty=_parse_bool(novelty),
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        reference_path_col=reference_path_col,
        reference_id_col=reference_id_col,
    )
    record, _ = evaluate_one_cif(
        cif_path,
        target_formula=target_formula,
        target_space_group=target_space_group,
        require_spacegroup=_parse_bool(require_spacegroup),
        run_alignn=_parse_bool(alignn),
        reference_structures=reference_structures,
    )
    write_single_json(record, out)
    console.print_json(record.model_dump_json())


@crystallm_app.command("folder")
def crystallm_folder(
    folder_path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    out: Path = typer.Option(..., "--out", help="Output CSV path."),
    jsonl: Path = typer.Option(..., "--jsonl", help="Output JSONL path."),
    target_formula: str | None = typer.Option(None, "--target-formula"),
    target_space_group: str | None = typer.Option(None, "--target-space-group"),
    require_spacegroup: str = typer.Option("false", "--require-spacegroup"),
    alignn: str = typer.Option("false", "--alignn"),
    novelty: str = typer.Option("false", "--novelty"),
    reference_folder: Path | None = typer.Option(None, "--reference-folder", exists=True, file_okay=False, dir_okay=True),
    reference_manifest: Path | None = typer.Option(None, "--reference-manifest", exists=True, file_okay=True, dir_okay=False),
    reference_path_col: str = typer.Option("cif_path", "--reference-path-col"),
    reference_id_col: str | None = typer.Option(None, "--reference-id-col"),
    recursive: str = typer.Option("true", "--recursive"),
) -> None:
    """Evaluate all CIF files in a folder and write CSV plus JSONL reports."""

    reference_structures = _load_references_for_cli(
        novelty=_parse_bool(novelty),
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        reference_path_col=reference_path_col,
        reference_id_col=reference_id_col,
    )
    records = evaluate_folder(
        folder_path,
        target_formula=target_formula,
        target_space_group=target_space_group,
        require_spacegroup=_parse_bool(require_spacegroup),
        run_alignn=_parse_bool(alignn),
        recursive=_parse_bool(recursive),
        reference_structures=reference_structures,
    )
    write_csv(records, out)
    write_jsonl(records, jsonl)
    console.print(f"[green]Wrote {len(records)} records[/green] to {out} and {jsonl}")


@crystallm_app.command("manifest")
def crystallm_manifest(
    manifest_csv: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    path_col: str = typer.Option("cif_path", "--path-col"),
    formula_col: str = typer.Option("target_formula", "--formula-col"),
    spacegroup_col: str = typer.Option("target_space_group", "--spacegroup-col"),
    method_col: str = typer.Option("method", "--method-col"),
    query_id_col: str = typer.Option("query_id", "--query-id-col"),
    out: Path = typer.Option(..., "--out", help="Output CSV path."),
    jsonl: Path = typer.Option(..., "--jsonl", help="Output JSONL path."),
    require_spacegroup: str = typer.Option("false", "--require-spacegroup"),
    alignn: str = typer.Option("false", "--alignn"),
    novelty: str = typer.Option("false", "--novelty"),
    reference_folder: Path | None = typer.Option(None, "--reference-folder", exists=True, file_okay=False, dir_okay=True),
    reference_manifest: Path | None = typer.Option(None, "--reference-manifest", exists=True, file_okay=True, dir_okay=False),
    reference_path_col: str = typer.Option("cif_path", "--reference-path-col"),
    reference_id_col: str | None = typer.Option(None, "--reference-id-col"),
) -> None:
    """Evaluate CIF paths listed in a manifest."""

    reference_structures = _load_references_for_cli(
        novelty=_parse_bool(novelty),
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        reference_path_col=reference_path_col,
        reference_id_col=reference_id_col,
    )
    records = evaluate_manifest(
        manifest_csv,
        path_col=path_col,
        formula_col=formula_col,
        spacegroup_col=spacegroup_col,
        method_col=method_col,
        query_id_col=query_id_col,
        require_spacegroup=_parse_bool(require_spacegroup),
        run_alignn=_parse_bool(alignn),
        reference_structures=reference_structures,
    )
    write_csv(records, out)
    write_jsonl(records, jsonl)
    console.print(f"[green]Wrote {len(records)} records[/green] to {out} and {jsonl}")


@app.command("select-top-k")
def select_top_k(
    eval_csv: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    group_cols: str = typer.Option("method,query_id", "--group-cols"),
    k: int = typer.Option(5, "--k", min=1),
    out: Path = typer.Option(..., "--out", help="Output CSV path."),
) -> None:
    """Select up to k records per group for later DFT."""

    frame = pd.read_csv(eval_csv)
    columns = [column.strip() for column in group_cols.split(",") if column.strip()]
    for column in columns + ["pre_dft_rank_score"]:
        if column not in frame.columns:
            raise typer.BadParameter(f"Column '{column}' not found in {eval_csv}")
    selected = (
        frame.sort_values(columns + ["pre_dft_rank_score"], ascending=True)
        .groupby(columns, dropna=False, as_index=False, group_keys=False)
        .head(k)
        .copy()
    )
    selected["selected_for_dft"] = True
    out.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(out, index=False)
    console.print(f"[green]Selected {len(selected)} records[/green] into {out}")


@app.command("summarize")
def summarize(
    eval_csv: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    group_col: str = typer.Option("method", "--group-col"),
    out: Path = typer.Option(..., "--out", help="Output summary CSV path."),
) -> None:
    """Summarize an evaluation CSV by group."""

    frame = pd.read_csv(eval_csv)
    if group_col not in frame.columns:
        frame[group_col] = None
    summaries = [_summarize_group(str(group), group_frame) for group, group_frame in frame.groupby(group_col, dropna=False)]
    write_summary_csv(summaries, out)
    console.print(f"[green]Wrote {len(summaries)} summary rows[/green] to {out}")


@app.command("benchmark-summary")
def benchmark_summary(
    benchmark_csv: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    group_col: str = typer.Option("method", "--group-col"),
    out: Path = typer.Option(..., "--out", help="Output benchmark summary CSV path."),
) -> None:
    """Summarize modular benchmark CSV output by a grouping column."""

    frame = pd.read_csv(benchmark_csv)
    if group_col not in frame.columns:
        frame = frame.copy()
        frame[group_col] = "all"
    rows = [
        _benchmark_summary_group(str(group), group_frame)
        for group, group_frame in frame.groupby(group_col, dropna=False)
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    console.print(f"[green]Wrote {len(rows)} benchmark summary rows[/green] to {out}")


@app.command("paper-benchmark-summary")
def paper_benchmark_summary(
    results_csv: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    manifest: Path = typer.Option(..., "--manifest", exists=True, file_okay=True, dir_okay=False, readable=True),
    out: Path = typer.Option(..., "--out", help="Output paper benchmark summary CSV."),
    json_out: Path = typer.Option(..., "--json", help="Output paper benchmark summary JSON."),
    markdown: Path | None = typer.Option(None, "--markdown", help="Optional Markdown report output."),
    group_col: str = typer.Option("benchmark_group", "--group-col"),
    id_col: str = typer.Option("benchmark_id", "--id-col"),
    attempt_col: str = typer.Option("attempt_id", "--attempt-col"),
    target_col: str = typer.Option("benchmark_id", "--target-col"),
    reference_required_policy: str = typer.Option("warn", "--reference-required-policy"),
    include_built_in_comparators: bool = typer.Option(False, "--include-built-in-comparators"),
    comparator_values: Path | None = typer.Option(None, "--comparator-values", exists=True, file_okay=True, dir_okay=False, readable=True),
) -> None:
    """Summarize SCA outputs against paper-comparable A-E benchmark metrics."""

    summary = build_paper_benchmark_summary(
        results_csv=results_csv,
        manifest_csv=manifest,
        comparator_values=comparator_values,
        include_built_in_comparators=include_built_in_comparators,
        group_col=group_col,
        id_col=target_col or id_col,
        attempt_col=attempt_col,
        reference_required_policy=reference_required_policy,
    )
    write_summary_outputs(summary, out_csv=out, out_json=json_out, markdown=markdown)
    console.print(f"[green]Wrote {len(summary.rows)} paper benchmark summary rows[/green] to {out} and {json_out}")


@app.command("build-paper-run-manifest")
def build_paper_run_manifest_cli(
    targets: Path = typer.Option(..., "--targets", exists=True, file_okay=True, dir_okay=False, readable=True),
    generated_folder: Path = typer.Option(..., "--generated-folder", exists=True, file_okay=False, dir_okay=True, readable=True),
    out: Path = typer.Option(..., "--out", help="Output generated benchmark manifest CSV."),
    filename_formula_mode: str = typer.Option("infer", "--filename-formula-mode"),
    default_method: str = typer.Option("qlip_generated", "--default-method"),
    attempt_id_mode: str = typer.Option("filename", "--attempt-id-mode"),
    copy_reference_fields: bool = typer.Option(True, "--copy-reference-fields/--no-copy-reference-fields"),
    unmatched_out: Path | None = typer.Option(None, "--unmatched-out", help="Optional CSV for unmatched or ambiguous CIFs."),
    strict: bool = typer.Option(False, "--strict", help="Fail if any generated CIF is unmatched or ambiguous."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
) -> None:
    """Map generated CIF files onto paper benchmark target rows."""

    frame = build_paper_run_manifest(
        targets_csv=targets,
        generated_folder=generated_folder,
        out_csv=out,
        recursive=recursive,
        filename_formula_mode=filename_formula_mode,
        default_method=default_method,
        attempt_id_mode=attempt_id_mode,
        copy_reference_fields=copy_reference_fields,
        unmatched_out=unmatched_out,
        strict=strict,
    )
    mapped = int((frame["mapping_status"] == "matched").sum()) if "mapping_status" in frame else 0
    ambiguous = int((frame["mapping_status"] == "ambiguous").sum()) if "mapping_status" in frame else 0
    console.print(
        f"[green]Wrote {len(frame)} manifest rows[/green] to {out} "
        f"({mapped} matched, {ambiguous} ambiguous, {len(frame) - mapped - ambiguous} unmatched)"
    )


@app.command("paper-target-diagnostics")
def paper_target_diagnostics(
    results: Path = typer.Option(..., "--results", exists=True, file_okay=True, dir_okay=False, readable=True),
    manifest: Path = typer.Option(..., "--manifest", exists=True, file_okay=True, dir_okay=False, readable=True),
    references: Path = typer.Option(..., "--references", exists=True, file_okay=True, dir_okay=False, readable=True),
    out: Path = typer.Option(..., "--out", help="Output per-target diagnostics CSV."),
    json_out: Path = typer.Option(..., "--json", help="Output per-target diagnostics JSON."),
    markdown: Path | None = typer.Option(None, "--markdown", help="Optional Markdown diagnostics report."),
) -> None:
    """Classify per-target paper benchmark failures without changing metrics."""

    rows = build_paper_target_diagnostics(
        results_csv=results,
        manifest_csv=manifest,
        references_csv=references,
    )
    write_diagnostics_outputs(rows, out_csv=out, out_json=json_out, markdown=markdown)
    console.print(f"[green]Wrote {len(rows)} target diagnostics rows[/green] to {out} and {json_out}")


def _benchmark_summary_group(group_value: str, frame: pd.DataFrame) -> dict:
    alignn_values = _numeric(frame, "formation_energy_per_atom").dropna()
    if alignn_values.empty:
        alignn_values = _numeric(frame, "alignn_formation_energy_per_atom").dropna()
    chgnet_values = _numeric(frame, "chgnet_energy_per_atom").dropna()
    hull_values = _numeric(frame, "predicted_energy_above_hull").dropna()
    property_error_values = _numeric(frame, "property_error").dropna()
    return {
        "group_value": group_value,
        "num_generated": len(frame),
        "parse_valid_rate": _bool_rate(frame, "parse_ok"),
        "target_formula_match_rate": _bool_rate(frame, "target_formula_match"),
        "space_group_consistency_rate": _bool_rate(frame, "space_group_consistent"),
        "target_structure_match_rate": _bool_rate(frame, "structure_match"),
        "known_match_rate": _bool_rate(frame, "known_match"),
        "novel_rate": _bool_rate(frame, "novel_by_structure_matcher"),
        "duplicate_rate": _bool_rate(frame, "is_duplicate"),
        "median_alignn_formation_energy": (
            float(alignn_values.median()) if not alignn_values.empty else None
        ),
        "median_chgnet_energy_per_atom": (
            float(chgnet_values.median()) if not chgnet_values.empty else None
        ),
        "predicted_hull_ok_rate": _bool_rate(frame, "hull_ok"),
        "median_predicted_energy_above_hull": (
            float(hull_values.median()) if not hull_values.empty else None
        ),
        "property_target_ok_rate": _bool_rate(frame, "property_target_ok"),
        "median_abs_property_error": (
            float(property_error_values.abs().median()) if not property_error_values.empty else None
        ),
    }


def _summarize_group(group_value: str, frame: pd.DataFrame) -> AggregateSummary:
    alignn_values = _numeric(frame, "formation_energy_per_atom").dropna()
    return AggregateSummary(
        group_value=group_value,
        num_generated=len(frame),
        parse_valid_rate=_bool_rate(frame, "parse_ok"),
        target_formula_match_rate=_bool_rate(frame, "target_formula_match"),
        space_group_consistency_rate=_bool_rate(frame, "space_group_consistent"),
        multiplicity_consistency_rate=_bool_rate(frame, "multiplicity_consistent"),
        bond_reasonable_rate=_bool_rate(frame, "bond_lengths_reasonable"),
        geometry_ok_rate=_bool_rate(frame, "geometry_ok"),
        pre_dft_valid_rate=_bool_rate(frame, "pre_dft_valid"),
        unique_valid_count=_unique_valid_count(frame),
        duplicate_rate=_bool_rate(frame, "is_duplicate"),
        novelty_checked_count=int(_bool_series(frame, "novelty_checked").sum()) if "novelty_checked" in frame else 0,
        novel_rate=_bool_rate(frame, "novel_by_structure_matcher"),
        known_match_rate=_bool_rate(frame, "known_match"),
        median_alignn_formation_energy=float(alignn_values.median()) if not alignn_values.empty else None,
        best_alignn_formation_energy=float(alignn_values.min()) if not alignn_values.empty else None,
    )


def _load_references_for_cli(
    novelty: bool,
    reference_folder: Path | None,
    reference_manifest: Path | None,
    reference_path_col: str,
    reference_id_col: str | None,
):
    if not novelty:
        return None
    if reference_folder is None and reference_manifest is None:
        raise ClickException(
            "--novelty true requires --reference-folder or --reference-manifest"
        )
    load_result = load_reference_structures_with_stats(
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        path_col=reference_path_col,
        id_col=reference_id_col,
    )
    console.print(
        "[cyan]Loaded reference structures:[/cyan] "
        f"{load_result.loaded_count} loaded, {load_result.failed_count} failed"
    )
    return load_result.structures


def _bool_rate(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    series = _bool_series(frame, column)
    non_null = series.dropna()
    if non_null.empty:
        return None
    return float(non_null.mean())


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].map(
        lambda value: None
        if pd.isna(value)
        else str(value).strip().lower() in {"true", "1", "yes"}
        if not isinstance(value, bool)
        else value
    )


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _unique_valid_count(frame: pd.DataFrame) -> int:
    if "pre_dft_valid" not in frame.columns:
        return 0
    valid = _bool_series(frame, "pre_dft_valid") == True  # noqa: E712
    if "is_unique_representative" not in frame.columns:
        return int(valid.sum())
    unique = _bool_series(frame, "is_unique_representative")
    return int((valid & (unique != False)).sum())  # noqa: E712


def _alignn(model: str) -> AlignnEvaluator:
    return AlignnEvaluator(model_name=model)


@benchmark_app.command("one")
def benchmark_cli_one(
    cif_path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    target_formula: str | None = typer.Option(None, "--target-formula"),
    target_space_group: str | None = typer.Option(None, "--target-space-group"),
    target_cif_path: Path | None = typer.Option(None, "--target-cif-path", exists=True, file_okay=True, dir_okay=False),
    reference_id: str | None = typer.Option(None, "--reference-id"),
    structure_match_mode: str = typer.Option("both", "--structure-match-mode"),
    spp_artifact: Path | None = typer.Option(None, "--spp-artifact", exists=True, file_okay=True, dir_okay=False),
    hull_reference: Path | None = typer.Option(None, "--hull-reference", exists=True, file_okay=True, dir_okay=False),
    target_formation_energy_per_atom: float | None = typer.Option(None, "--target-formation-energy-per-atom"),
    target_energy_above_hull: float | None = typer.Option(None, "--target-energy-above-hull"),
    target_band_gap: float | None = typer.Option(None, "--target-band-gap"),
    target_property_name: str | None = typer.Option(None, "--target-property-name"),
    target_property_value: float | None = typer.Option(None, "--target-property-value"),
    method: str | None = typer.Option(None, "--method"),
    query_id: str | None = typer.Option(None, "--query-id"),
    evaluators: str = typer.Option("pre_dft_validity", "--evaluators", help="Comma-separated evaluator names."),
    out: Path = typer.Option(..., "--out", help="Output benchmark JSON path, or CSV path when --jsonl is used."),
    jsonl: Path | None = typer.Option(None, "--jsonl", help="Optional output benchmark JSONL path."),
    require_spacegroup: str = typer.Option("false", "--require-spacegroup"),
    alignn: str = typer.Option("false", "--alignn", help="Run ALIGNN inside pre_dft_validity."),
    novelty: str = typer.Option("false", "--novelty"),
    reference_folder: Path | None = typer.Option(None, "--reference-folder", exists=True, file_okay=False, dir_okay=True),
    reference_manifest: Path | None = typer.Option(None, "--reference-manifest", exists=True, file_okay=True, dir_okay=False),
    reference_path_col: str = typer.Option("cif_path", "--reference-path-col"),
    reference_id_col: str | None = typer.Option(None, "--reference-id-col"),
) -> None:
    """Benchmark one CIF with registered evaluators."""

    reference_structures = _load_references_for_cli(
        novelty=_parse_bool(novelty),
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        reference_path_col=reference_path_col,
        reference_id_col=reference_id_col,
    )
    record = benchmark_one(
        cif_path,
        evaluator_names=_parse_evaluators(evaluators),
        target_formula=target_formula,
        target_space_group=target_space_group,
        target_cif_path=target_cif_path,
        reference_id=reference_id,
        structure_match_mode=structure_match_mode,
        spp_artifact=spp_artifact,
        hull_reference_path=hull_reference,
        target_formation_energy_per_atom=target_formation_energy_per_atom,
        target_energy_above_hull=target_energy_above_hull,
        target_band_gap=target_band_gap,
        target_property_name=target_property_name,
        target_property_value=target_property_value,
        method=method,
        query_id=query_id,
        require_spacegroup=_parse_bool(require_spacegroup),
        run_alignn=_parse_bool(alignn),
        reference_structures=reference_structures,
    )
    if jsonl is None:
        write_single_json(record, out)
        console.print_json(record.model_dump_json())
        return
    write_csv([record], out)
    write_jsonl([record], jsonl)
    console.print(f"[green]Wrote 1 benchmark record[/green] to {out} and {jsonl}")


@benchmark_app.command("folder")
def benchmark_cli_folder(
    folder_path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    out: Path = typer.Option(..., "--out", help="Output benchmark CSV path."),
    jsonl: Path = typer.Option(..., "--jsonl", help="Output benchmark JSONL path."),
    target_formula: str | None = typer.Option(None, "--target-formula"),
    target_space_group: str | None = typer.Option(None, "--target-space-group"),
    target_cif_path: Path | None = typer.Option(None, "--target-cif-path", exists=True, file_okay=True, dir_okay=False),
    reference_id: str | None = typer.Option(None, "--reference-id"),
    structure_match_mode: str = typer.Option("both", "--structure-match-mode"),
    spp_artifact: Path | None = typer.Option(None, "--spp-artifact", exists=True, file_okay=True, dir_okay=False),
    hull_reference: Path | None = typer.Option(None, "--hull-reference", exists=True, file_okay=True, dir_okay=False),
    target_formation_energy_per_atom: float | None = typer.Option(None, "--target-formation-energy-per-atom"),
    target_energy_above_hull: float | None = typer.Option(None, "--target-energy-above-hull"),
    target_band_gap: float | None = typer.Option(None, "--target-band-gap"),
    target_property_name: str | None = typer.Option(None, "--target-property-name"),
    target_property_value: float | None = typer.Option(None, "--target-property-value"),
    method: str | None = typer.Option(None, "--method"),
    query_id: str | None = typer.Option(None, "--query-id"),
    evaluators: str = typer.Option("pre_dft_validity", "--evaluators", help="Comma-separated evaluator names."),
    require_spacegroup: str = typer.Option("false", "--require-spacegroup"),
    alignn: str = typer.Option("false", "--alignn", help="Run ALIGNN inside pre_dft_validity."),
    novelty: str = typer.Option("false", "--novelty"),
    reference_folder: Path | None = typer.Option(None, "--reference-folder", exists=True, file_okay=False, dir_okay=True),
    reference_manifest: Path | None = typer.Option(None, "--reference-manifest", exists=True, file_okay=True, dir_okay=False),
    reference_path_col: str = typer.Option("cif_path", "--reference-path-col"),
    reference_id_col: str | None = typer.Option(None, "--reference-id-col"),
    recursive: str = typer.Option("true", "--recursive"),
) -> None:
    """Benchmark all CIF files in a folder."""

    reference_structures = _load_references_for_cli(
        novelty=_parse_bool(novelty),
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        reference_path_col=reference_path_col,
        reference_id_col=reference_id_col,
    )
    records = benchmark_folder(
        folder_path,
        evaluator_names=_parse_evaluators(evaluators),
        target_formula=target_formula,
        target_space_group=target_space_group,
        target_cif_path=target_cif_path,
        reference_id=reference_id,
        structure_match_mode=structure_match_mode,
        spp_artifact=spp_artifact,
        hull_reference_path=hull_reference,
        target_formation_energy_per_atom=target_formation_energy_per_atom,
        target_energy_above_hull=target_energy_above_hull,
        target_band_gap=target_band_gap,
        target_property_name=target_property_name,
        target_property_value=target_property_value,
        method=method,
        query_id=query_id,
        require_spacegroup=_parse_bool(require_spacegroup),
        run_alignn=_parse_bool(alignn),
        recursive=_parse_bool(recursive),
        reference_structures=reference_structures,
    )
    write_csv(records, out)
    write_jsonl(records, jsonl)
    console.print(f"[green]Wrote {len(records)} benchmark records[/green] to {out} and {jsonl}")


@benchmark_app.command("manifest")
def benchmark_cli_manifest(
    manifest_csv: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    path_col: str = typer.Option("cif_path", "--path-col"),
    formula_col: str = typer.Option("target_formula", "--formula-col"),
    spacegroup_col: str = typer.Option("target_space_group", "--spacegroup-col"),
    target_cif_col: str = typer.Option("target_cif_path", "--target-cif-col"),
    target_reference_id_col: str = typer.Option("reference_id", "--target-reference-id-col"),
    structure_match_mode: str = typer.Option("both", "--structure-match-mode"),
    spp_artifact: Path | None = typer.Option(None, "--spp-artifact", exists=True, file_okay=True, dir_okay=False),
    hull_reference: Path | None = typer.Option(None, "--hull-reference", exists=True, file_okay=True, dir_okay=False),
    target_formation_energy_col: str = typer.Option("target_formation_energy_per_atom", "--target-formation-energy-col"),
    target_energy_above_hull_col: str = typer.Option("target_energy_above_hull", "--target-energy-above-hull-col"),
    target_band_gap_col: str = typer.Option("target_band_gap", "--target-band-gap-col"),
    target_property_name_col: str = typer.Option("target_property_name", "--target-property-name-col"),
    target_property_value_col: str = typer.Option("target_property_value", "--target-property-value-col"),
    method_col: str = typer.Option("method", "--method-col"),
    query_id_col: str = typer.Option("query_id", "--query-id-col"),
    evaluators: str = typer.Option("pre_dft_validity", "--evaluators", help="Comma-separated evaluator names."),
    out: Path = typer.Option(..., "--out", help="Output benchmark CSV path."),
    jsonl: Path = typer.Option(..., "--jsonl", help="Output benchmark JSONL path."),
    require_spacegroup: str = typer.Option("false", "--require-spacegroup"),
    alignn: str = typer.Option("false", "--alignn", help="Run ALIGNN inside pre_dft_validity."),
    novelty: str = typer.Option("false", "--novelty"),
    reference_folder: Path | None = typer.Option(None, "--reference-folder", exists=True, file_okay=False, dir_okay=True),
    reference_manifest: Path | None = typer.Option(None, "--reference-manifest", exists=True, file_okay=True, dir_okay=False),
    reference_path_col: str = typer.Option("cif_path", "--reference-path-col"),
    reference_id_col: str | None = typer.Option(None, "--reference-id-col"),
) -> None:
    """Benchmark CIF paths listed in a manifest."""

    reference_structures = _load_references_for_cli(
        novelty=_parse_bool(novelty),
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        reference_path_col=reference_path_col,
        reference_id_col=reference_id_col,
    )
    records = benchmark_manifest(
        manifest_csv,
        evaluator_names=_parse_evaluators(evaluators),
        path_col=path_col,
        formula_col=formula_col,
        spacegroup_col=spacegroup_col,
        target_cif_col=target_cif_col,
        reference_id_col=target_reference_id_col,
        structure_match_mode=structure_match_mode,
        spp_artifact=spp_artifact,
        hull_reference_path=hull_reference,
        target_formation_energy_col=target_formation_energy_col,
        target_energy_above_hull_col=target_energy_above_hull_col,
        target_band_gap_col=target_band_gap_col,
        target_property_name_col=target_property_name_col,
        target_property_value_col=target_property_value_col,
        method_col=method_col,
        query_id_col=query_id_col,
        require_spacegroup=_parse_bool(require_spacegroup),
        run_alignn=_parse_bool(alignn),
        reference_structures=reference_structures,
    )
    write_csv(records, out)
    write_jsonl(records, jsonl)
    console.print(f"[green]Wrote {len(records)} benchmark records[/green] to {out} and {jsonl}")


@alignn_app.command("one")
def alignn_one(
    cif_path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    out: Path = typer.Option(..., "--out", help="Output JSON path."),
    model: str = typer.Option(DEFAULT_ALIGNN_MODEL, "--model", help="ALIGNN model name."),
) -> None:
    """Evaluate one CIF and write a JSON result."""

    result = evaluate_one(cif_path, _alignn(model))
    write_single_json(result, out)
    console.print_json(result.model_dump_json())


@alignn_app.command("folder")
def alignn_folder(
    folder_path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    out: Path = typer.Option(..., "--out", help="Output CSV path."),
    jsonl: Path = typer.Option(..., "--jsonl", help="Output JSONL path."),
    model: str = typer.Option(DEFAULT_ALIGNN_MODEL, "--model", help="ALIGNN model name."),
) -> None:
    """Evaluate all CIF files in a folder and write CSV plus JSONL outputs."""

    paths = discover_cif_files(folder_path)
    results = evaluate_many(paths, _alignn(model))
    write_csv(results, out)
    write_jsonl(results, jsonl)
    console.print(f"[green]Wrote {len(results)} results[/green] to {out} and {jsonl}")


@alignn_app.command("manifest")
def alignn_manifest(
    csv_path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    path_col: str = typer.Option("cif_path", "--path-col", help="Manifest column containing CIF paths."),
    out: Path = typer.Option(..., "--out", help="Output CSV path."),
    jsonl: Path = typer.Option(..., "--jsonl", help="Output JSONL path."),
    model: str = typer.Option(DEFAULT_ALIGNN_MODEL, "--model", help="ALIGNN model name."),
) -> None:
    """Evaluate CIF paths listed in a CSV manifest."""

    paths = load_manifest(csv_path, path_col)
    results = evaluate_many(paths, _alignn(model))
    write_csv(results, out)
    write_jsonl(results, jsonl)
    console.print(f"[green]Wrote {len(results)} results[/green] to {out} and {jsonl}")


if __name__ == "__main__":
    app()
