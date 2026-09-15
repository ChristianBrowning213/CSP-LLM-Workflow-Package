from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.mcp.fake_lib import serve

TOOLS = [
    "spp.run_pipeline",
    "spp.check_compat",
    "spp.package_for_qlip",
    "spp.publish_to_qlip_outputs",
]

# Constants
RUN_ID = "spp-pkg"
TOOL_NAME = "SPP_Maker"
TOOL_VERSION = "shim"
OUTPUT_BYTES_ORIGINAL = 128

def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _qlip_package_from_spp_run(
    *,
    run_root: Path,
    calibration_json: Path,
    out_dir: Path,
    name: str,
    material_system: str | None = None,
    required_pairs: list[str] | None = None,
) -> dict[str, Any]:
    bundle_name = name if name else "_bundle"
    bundle_path = out_dir / f"{bundle_name}_bundle"
    package_json = bundle_path / "package.json"
    try:
        try:
            from src.spp_maker_qlip.qlip_package import create_spp_guidance_package
        except ModuleNotFoundError:
            from spp_maker_qlip.qlip_package import create_spp_guidance_package

        guidance_result = create_spp_guidance_package(
            run_root,
            calibration_json,
            out_dir,
            bundle_name,
            qlip_outputs_root=Path.cwd() / "QLIP_Outputs",
            material_system=material_system,
            required_pairs=required_pairs,
        )
        guidance_package_path = Path(str(guidance_result["guidance_package_path"]))
        compatibility = (
            guidance_result.get("compatibility")
            if isinstance(guidance_result.get("compatibility"), dict)
            else _read_json_file(guidance_package_path / "compatibility.json")
        )
        qlip_solve_compatible = bool(compatibility.get("qlip_solve_compatible"))
        missing = [
            str(item)
            for item in compatibility.get("missing", [])
            if isinstance(item, str) and item.strip()
        ] if isinstance(compatibility.get("missing"), list) else []
        warnings = []
        if not qlip_solve_compatible:
            reason = compatibility.get("reason")
            warnings.append(str(reason) if isinstance(reason, str) and reason.strip() else "QLIP solve compatibility is false.")
        package_json.parent.mkdir(parents=True, exist_ok=True)
        package_json.write_text(
            json.dumps(
                {
                    "name": bundle_name,
                    "spp_run_root": str(run_root),
                    "guidance_package_path": str(guidance_package_path),
                    "compatibility": compatibility,
                    "qlip_solve_compatible": qlip_solve_compatible,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "status": "ready" if qlip_solve_compatible else "partial",
            "guidance_package_path": str(guidance_package_path),
            "package_json_path": str(package_json),
            "final_bundle_path": str(bundle_path),
            "compatibility": compatibility,
            "qlip_solve_compatible": qlip_solve_compatible,
            "context": guidance_result.get("context") if isinstance(guidance_result.get("context"), dict) else {},
            "artifact_refs": guidance_result.get("artifact_refs") if isinstance(guidance_result.get("artifact_refs"), list) else [],
            "summary": guidance_result.get("summary") if isinstance(guidance_result.get("summary"), str) else "",
            "required_pairs": guidance_result.get("required_pairs") if isinstance(guidance_result.get("required_pairs"), list) else [],
            "missing_pairs": guidance_result.get("missing_pairs") if isinstance(guidance_result.get("missing_pairs"), list) else [],
            "available_pair_count": guidance_result.get("available_pair_count", 0),
            "missing": missing,
            "warnings": warnings,
            "errors": guidance_result.get("errors") if isinstance(guidance_result.get("errors"), list) else [],
        }
    except Exception as exc:
        return {
            "status": "failed",
            "guidance_package_path": None,
            "package_json_path": str(package_json),
            "final_bundle_path": str(bundle_path),
            "compatibility": {},
            "qlip_solve_compatible": False,
            "context": {},
            "artifact_refs": [],
            "summary": "QLIP packaging failed.",
            "missing": [],
            "warnings": [],
            "errors": [
                {
                    "code": "qlip_packaging_failed",
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
            ],
        }


def _ok(tool_name: str, result: dict[str, Any], trace_id: str | None = None, warnings: list | None = None) -> dict:
    return {
        "ok": True,
        "trace_id": trace_id or f"{tool_name}-trace",
        "tool_name": tool_name,
        "result": result,
        "error": None,
        "warnings": warnings or [],
    }

def _err(tool_name: str, code: str, message: str) -> dict:
    return {
        "ok": False,
        "trace_id": f"{tool_name}-trace",
        "tool_name": tool_name,
        "result": None,
        "error": {"type": "validation_error", "message": message, "code": code, "details": []},
        "warnings": [],
    }

def on_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "spp.run_pipeline":
        for required in ("cif_dir", "out_dir", "name"):
            if required not in args:
                return _err(name, "missing_required", required)
        out_dir = Path(args["out_dir"]).resolve()
        run_root = out_dir / f"{args['name']}_run"
        run_root.mkdir(parents=True, exist_ok=True)
        paths = {
            "fit_spp_root": str(run_root / "fit_spp"),
            "calibration_json": str(run_root / "calibration.json"),
            "scaled_spp_root": str(run_root / "scaled_spp"),
            "package_json": str(run_root / "package.json"),
        }
        for p in paths.values():
            path = Path(p)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix:
                path.write_text("{}", encoding="utf-8")
            else:
                path.mkdir(parents=True, exist_ok=True)
        cif_count = len(list(Path(args["cif_dir"]).glob("*.cif")))
        result = {
            "run_id": "spp-run",
            "run_root": str(run_root),
            "final_bundle": str(run_root / "final_bundle"),
            "content_hash": "abc123",
            "paths": paths,
            "published": None,
            "provenance": {
                "git_sha": None,
                "tool": "SPP_Maker",
                "tool_version": "shim",
                "params_hash": None,
                "content_hash": None,
            },
            "log_path": str(run_root / "run.log"),
            "dry_run": bool(args.get("dry_run", False)),
            "cif_count": cif_count,
            "output_bytes": 1024,
        }
        (run_root / "final_bundle").mkdir(exist_ok=True)
        qlip_package = _qlip_package_from_spp_run(
            run_root=run_root,
            calibration_json=Path(paths["calibration_json"]),
            out_dir=run_root / "qlip_package",
            name=str(args.get("name", "")),
            material_system=str(args.get("material_system") or args.get("formula") or ""),
            required_pairs=args.get("required_pairs") if isinstance(args.get("required_pairs"), list) else None,
        )
        result.update(
            {
                "spp_run_root": str(run_root),
                "calibration_json": paths["calibration_json"],
                "final_bundle_path": str(run_root / "final_bundle"),
                "guidance_package_path": qlip_package.get("guidance_package_path"),
                "package_json_path": qlip_package.get("package_json_path"),
                "compatibility": qlip_package.get("compatibility", {}),
                "qlip_solve_compatible": bool(qlip_package.get("qlip_solve_compatible")),
                "qlip_package": qlip_package,
            }
        )
        return _ok(name, result, args.get("trace_id"))

    if name == "spp.check_compat":
        result = {"ok": True, "files_checked": 1, "failed_count": 0, "failures": []}
        return _ok(name, result, args.get("trace_id"))

    if name == "spp.package_for_qlip":
        run_root = args.get("run_root")
        spp_root = args.get("spp_root")
        calibration_json = args.get("calibration_json")

        # Validate inputs
        if not run_root and not (spp_root and calibration_json):
            return _err(name, "validation_error", "Either run_root OR (spp_root + calibration_json)")

        out_dir = Path(args["out_dir"]).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        bundle_name = args["name"] if args["name"] else "_bundle"
        bundle_path = out_dir / f"{bundle_name}"
        bundle_path.mkdir(parents=True, exist_ok=True)

        if run_root:
            # Import create_spp_guidance_package here to avoid global import
            try:
                from src.spp_maker_qlip.qlip_package import create_spp_guidance_package
            except ModuleNotFoundError:
                from spp_maker_qlip.qlip_package import create_spp_guidance_package

            try:
                guidance_result = create_spp_guidance_package(run_root, calibration_json, out_dir, str(args["name"]))
            except Exception as e:
                return _err(name, "compilation_error", str(e))

            # Update package.json to include guidance_package_path
            guidance_package_path = Path(str(guidance_result["guidance_package_path"]))
            bundle_path = guidance_package_path.parent
            package_json = bundle_path / "package.json"
            package_data = {
                "name": bundle_name,
                "guidance_package_path": guidance_result["guidance_package_path"],
                "compatibility": guidance_result.get("compatibility", {}),
                "qlip_solve_compatible": bool(guidance_result.get("compatibility", {}).get("qlip_solve_compatible", False)),
            }
            package_json.write_text(json.dumps(package_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = {
                "run_id": RUN_ID,
                "final_bundle_path": str(bundle_path),
                "package_json_path": str(package_json),
                "contents": ["package.json", "guidance_package"],
                "guidance_package_path": guidance_result["guidance_package_path"],
                "provenance": guidance_result["provenance"],
                "output_bytes": guidance_result["output_bytes"],
            }
            return _ok(name, result, args.get("trace_id"))
        elif spp_root and calibration_json:
            # Original behavior when spp_root and calibration_json are provided
            package_json = bundle_path / "package.json"
            package_json.write_text(json.dumps({"name": bundle_name}), encoding="utf-8")
            result = {
                "run_id": RUN_ID,
                "final_bundle_path": str(bundle_path),
                "package_json_path": str(package_json),
                "contents": ["package.json"],
                "provenance": {
                    "git_sha": None,
                    "tool": TOOL_NAME,
                    "tool_version": TOOL_VERSION,
                    "params_hash": None,
                    "content_hash": None,
                },
                "output_bytes": OUTPUT_BYTES_ORIGINAL,
            }
            return _ok(name, result, args.get("trace_id"))
        else:
            # This should never be reached due to the validation above, but included for completeness
            return _err(name, "validation_error", "Either run_root OR (spp_root + calibration_json)")

    if name == "spp.publish_to_qlip_outputs":
        artifact_root = Path(args["artifact_root"]).resolve()
        qlip_outputs_path = Path(args["qlip_outputs_path"]).resolve()
        qlip_outputs_path.mkdir(parents=True, exist_ok=True)
        published = qlip_outputs_path / args["name"]
        if published.exists() and not args.get("overwrite", False):
            return _err(name, "already_exists", "Destination exists.")
        published.mkdir(parents=True, exist_ok=True)
        result = {
            "published_run_id": "published-1",
            "published_path": str(published),
            "index_json_path": str(qlip_outputs_path / "index.json"),
            "latest_pointer_path": str(qlip_outputs_path / "latest.txt"),
            "latest_pointer_value": str(published),
            "provenance": {
                "git_sha": None,
                "tool": TOOL_NAME,
                "tool_version": TOOL_VERSION,
                "params_hash": None,
                "content_hash": None,
            },
        }
        return _ok(name, result, args.get("trace_id"))

    return _err(name, "unknown_tool", name)


if __name__ == "__main__":
    serve(TOOLS, on_call)
