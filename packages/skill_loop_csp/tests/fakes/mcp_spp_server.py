from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp_fake_lib import serve

TOOLS = [
    "spp.run_pipeline",
    "spp.check_compat",
    "spp.package_for_qlip",
    "spp.publish_to_qlip_outputs",
]


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


def _compatibility(*, qlip_solve_compatible: bool = True) -> dict[str, Any]:
    return {
        "qlip_version": "1.0",
        "spp_maker_version": "stub",
        "qlip_solve_compatible": qlip_solve_compatible,
        "reason": "Real published SPP POT root found and validated." if qlip_solve_compatible else "SPP outputs are statistical guidance artifacts; no native QLIP POT root is produced.",
        "missing": [] if qlip_solve_compatible else ["context.pot_root"],
        "pot_compat": {"checked": 1, "passed": 1, "failed": 0, "strict": True} if qlip_solve_compatible else {},
        "recommended_next": "Add QLIP native SPP guidance mode or implement real POT export.",
        "accepted_parameters": ["spp_package_path"],
        "removed_parameters": [],
    }


def _required_pairs(material_system: str) -> list[str]:
    elements: list[str] = []
    for match in re.finditer(r"([A-Z][a-z]?)(?:\d*)", material_system):
        symbol = match.group(1)
        if symbol not in elements:
            elements.append(symbol)
    pairs: list[str] = []
    for left_index, left in enumerate(elements):
        for right in elements[left_index:]:
            pairs.append(f"{left}-{right}")
    return pairs


def _write_guidance_package(
    run_root: Path,
    calibration_json: Path,
    out_dir: Path,
    name: str,
    material_system: str = "CoAs2",
) -> dict[str, Any]:
    bundle_path = out_dir / f"{name}_bundle"
    guidance_package_path = bundle_path / "guidance_package"
    guidance_package_path.mkdir(parents=True, exist_ok=True)
    pot_root = run_root / "published_spp_root"
    pot_root.mkdir(parents=True, exist_ok=True)
    manifest_path = pot_root / "manifest.json"
    pairs = _required_pairs(material_system)
    manifest_path.write_text(json.dumps({"pairs": pairs}), encoding="utf-8")
    for pair in pairs:
        (pot_root / f"{pair}.POT").write_text("fake pot\n", encoding="utf-8")
    compat_report = pot_root / "compat_report.txt"
    compat_report.write_text("POT files checked: 1\nPassed: 1\nFailed: 0\n", encoding="utf-8")
    publish_meta = pot_root / "publish_meta.json"
    publish_meta.write_text(json.dumps({"checks": {"compat": {"checked": 1, "passed": 1, "failed": 0, "strict": True}}}), encoding="utf-8")
    compatibility = _compatibility()
    (guidance_package_path / "package_manifest.json").write_text(
        json.dumps(
            {
                "spp_run_root": str(run_root),
                "calibration_json": str(calibration_json),
                "final_bundle": str(run_root / "final_bundle"),
                "package_json": str(run_root / "package.json"),
                "log_path": str(run_root / "run.log"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (guidance_package_path / "compatibility.json").write_text(
        json.dumps(compatibility, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    package_json = bundle_path / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "name": name,
                "guidance_package_path": str(guidance_package_path),
                "compatibility": compatibility,
                "qlip_solve_compatible": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "status": "ready",
        "guidance_package_path": str(guidance_package_path),
        "package_json_path": str(package_json),
        "final_bundle_path": str(bundle_path),
        "compatibility": compatibility,
        "qlip_solve_compatible": True,
        "context": {"pot_root": str(pot_root)},
        "material_system": material_system,
        "formula": material_system,
        "required_pairs": pairs,
        "missing_pairs": [],
        "artifact_refs": [
            {"ref_name": "pot_root", "value": str(pot_root), "kind": "directory"},
            {"ref_name": "spp_manifest_json", "value": str(manifest_path), "kind": "file"},
            {"ref_name": "spp_compat_report_txt", "value": str(compat_report), "kind": "file"},
            {"ref_name": "spp_publish_meta_json", "value": str(publish_meta), "kind": "file"},
        ],
        "summary": "Real published SPP POT root found with 1 .POT files.",
        "missing": [],
        "warnings": [compatibility["reason"]],
        "errors": [],
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
                "tool_version": "stub",
                "params_hash": None,
                "content_hash": None,
            },
            "log_path": str(run_root / "run.log"),
            "dry_run": bool(args.get("dry_run", False)),
            "cif_count": cif_count,
            "output_bytes": 1024,
        }
        (run_root / "final_bundle").mkdir(exist_ok=True)
        qlip_package = _write_guidance_package(
            run_root,
            Path(paths["calibration_json"]),
            run_root / "qlip_package",
            str(args["name"]),
            str(args.get("material_system") or "CoAs2"),
        )
        result.update(
            {
                "spp_run_root": str(run_root),
                "calibration_json": paths["calibration_json"],
                "final_bundle_path": str(run_root / "final_bundle"),
                "guidance_package_path": qlip_package["guidance_package_path"],
                "package_json_path": qlip_package["package_json_path"],
                "compatibility": qlip_package["compatibility"],
                "qlip_solve_compatible": True,
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
        if not run_root and not (spp_root and calibration_json):
            return _err(name, "validation_error", "Either run_root OR (spp_root + calibration_json)")
        out_dir = Path(args["out_dir"]).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = out_dir / f"{args['name']}_bundle"
        bundle_path.mkdir(parents=True, exist_ok=True)
        package_json = out_dir / "package.json"
        package_json.write_text(json.dumps({"name": args["name"]}), encoding="utf-8")
        result = {
            "run_id": "spp-pkg",
            "final_bundle_path": str(bundle_path),
            "package_json_path": str(package_json),
            "contents": ["package.json"],
            "provenance": {
                "git_sha": None,
                "tool": "SPP_Maker",
                "tool_version": "stub",
                "params_hash": None,
                "content_hash": None,
            },
            "output_bytes": 128,
        }
        return _ok(name, result, args.get("trace_id"))

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
                "tool": "SPP_Maker",
                "tool_version": "stub",
                "params_hash": None,
                "content_hash": None,
            },
        }
        _ = artifact_root
        return _ok(name, result, args.get("trace_id"))

    return _err(name, "unknown_tool", name)


if __name__ == "__main__":
    serve(TOOLS, on_call)
