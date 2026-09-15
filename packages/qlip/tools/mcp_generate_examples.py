from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from jsonschema import Draft202012Validator, RefResolver


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "docs" / "mcp" / "MCP_SCHEMA.json"
TOOL_DEFS_PATH = REPO_ROOT / "docs" / "mcp" / "MCP_TOOL_DEFS.json"
EXAMPLES_DIR = REPO_ROOT / "examples" / "mcp"


def normalize_refs(obj: Any) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "$ref" and isinstance(value, str):
                if value.startswith("$defs/"):
                    obj[key] = "#/" + value
                elif value.startswith("/$defs/"):
                    obj[key] = "#" + value
            else:
                normalize_refs(value)
    elif isinstance(obj, list):
        for item in obj:
            normalize_refs(item)


def _collect_base_defs(schemas: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key in sorted(schemas.keys()):
        schema = schemas[key]
        if isinstance(schema, dict) and isinstance(schema.get("$defs"), dict):
            merged.update(schema["$defs"])
    return merged


def load_schemas() -> Dict[str, Any]:
    schemas = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for schema in schemas.values():
        normalize_refs(schema)
    return schemas


def load_tool_defs() -> Dict[str, Any]:
    tool_defs = json.loads(TOOL_DEFS_PATH.read_text(encoding="utf-8"))
    return {tool["name"]: tool for tool in tool_defs}


def build_schema_store(schemas: Dict[str, Any]) -> Dict[str, Any]:
    store: Dict[str, Any] = {}
    for schema in schemas.values():
        if isinstance(schema, dict) and "$id" in schema:
            store[schema["$id"]] = schema
    return store


def build_tool_schema(
    tool_name: str,
    schema_key: str,
    schemas: Dict[str, Any],
    tool_defs: Dict[str, Any],
) -> Dict[str, Any]:
    base_defs = schemas.get("$defs")
    if not isinstance(base_defs, dict):
        base_defs = _collect_base_defs(schemas)

    combined = copy.deepcopy(tool_defs[tool_name][schema_key])
    normalize_refs(combined)

    if not isinstance(combined.get("$defs"), dict):
        combined["$defs"] = dict(base_defs)
    else:
        merged_defs = dict(base_defs)
        merged_defs.update(combined["$defs"])
        combined["$defs"] = merged_defs
    return combined


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _join_pointer(parts: Iterable[str]) -> str:
    return "/" + "/".join(_escape_pointer_token(p) for p in parts)


def _resolve_pointer(root: Any, pointer: str) -> Any:
    if pointer in ("", "#"):
        return root
    if pointer.startswith("#"):
        pointer = pointer[1:]
    if not pointer:
        return root
    if not pointer.startswith("/"):
        raise ValueError(f"Unsupported pointer: {pointer}")
    current = root
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def resolve_ref(ref: str, root: Dict[str, Any], store: Dict[str, Any]) -> Dict[str, Any]:
    if ref.startswith("$defs/"):
        ref = "#/" + ref
    elif ref.startswith("/$defs/"):
        ref = "#" + ref

    if ref.startswith("#"):
        return _resolve_pointer(root, ref)
    if ref in store:
        return store[ref]
    raise KeyError(f"Unknown ref: {ref}")


def _matches_if(instance: Dict[str, Any], if_schema: Dict[str, Any]) -> bool:
    required = if_schema.get("required", [])
    for req in required:
        if req not in instance:
            return False
    props = if_schema.get("properties", {})
    for prop_name, prop_schema in props.items():
        if prop_name not in instance:
            return False
        value = instance[prop_name]
        if "const" in prop_schema and value != prop_schema["const"]:
            return False
        if "enum" in prop_schema and value not in prop_schema["enum"]:
            return False
    return True


def _default_for_string(pointer: str) -> str:
    if pointer.endswith("/formula"):
        return "SrTiO3"
    return "string"


def generate_instance(
    schema: Dict[str, Any],
    root: Dict[str, Any],
    store: Dict[str, Any],
    pointer: str = "",
    overrides: Optional[Mapping[str, Any]] = None,
    full_schema: Optional[Dict[str, Any]] = None,
) -> Any:
    if overrides and pointer in overrides:
        return copy.deepcopy(overrides[pointer])

    if "$ref" in schema:
        ref = schema["$ref"]
        resolved = resolve_ref(ref, root, store)
        next_root = root if ref.startswith("#") else resolved
        return generate_instance(
            resolved,
            next_root,
            store,
            pointer=pointer,
            overrides=overrides,
            full_schema=full_schema or resolved,
        )

    if "const" in schema:
        return copy.deepcopy(schema["const"])

    if "enum" in schema:
        return copy.deepcopy(schema["enum"][0])

    schema_type = schema.get("type")

    if "default" in schema:
        if schema_type == "object":
            if not schema.get("required"):
                return copy.deepcopy(schema["default"])
        elif schema_type == "array":
            return copy.deepcopy(schema["default"])
        else:
            return copy.deepcopy(schema["default"])

    if "anyOf" in schema or "oneOf" in schema:
        branches = schema.get("anyOf") or schema.get("oneOf") or []
        for branch in branches:
            candidate = generate_instance(
                branch,
                root,
                store,
                pointer=pointer,
                overrides=overrides,
                full_schema=full_schema or schema,
            )
            validator = Draft202012Validator(
                full_schema or schema,
                resolver=RefResolver.from_schema(root, store=store),
            )
            if not list(validator.iter_errors(candidate)):
                return candidate
        return generate_instance(
            branches[0],
            root,
            store,
            pointer=pointer,
            overrides=overrides,
            full_schema=full_schema or schema,
        )

    if schema_type == "object" or "properties" in schema:
        result: Dict[str, Any] = {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for prop_name in required:
            prop_schema = properties.get(prop_name)
            if prop_schema is None:
                continue
            result[prop_name] = generate_instance(
                prop_schema,
                root,
                store,
                pointer=f"{pointer}/{prop_name}" if pointer else _join_pointer([prop_name]),
                overrides=overrides,
                full_schema=full_schema or schema,
            )

        for subschema in schema.get("allOf", []):
            if "if" in subschema and "then" in subschema:
                if _matches_if(result, subschema["if"]):
                    then_required = subschema["then"].get("required", [])
                    for prop_name in then_required:
                        if prop_name in result:
                            continue
                        prop_schema = properties.get(prop_name)
                        if prop_schema is None:
                            continue
                        result[prop_name] = generate_instance(
                            prop_schema,
                            root,
                            store,
                            pointer=(
                                f"{pointer}/{prop_name}"
                                if pointer
                                else _join_pointer([prop_name])
                            ),
                            overrides=overrides,
                            full_schema=full_schema or schema,
                        )
        return result

    if schema_type == "array":
        items_schema = schema.get("items", {})
        min_items = schema.get("minItems")
        count = min_items if isinstance(min_items, int) and min_items > 0 else 1
        return [
            generate_instance(
                items_schema,
                root,
                store,
                pointer=f"{pointer}/0" if pointer else _join_pointer(["0"]),
                overrides=overrides,
                full_schema=full_schema or schema,
            )
            for _ in range(count)
        ]

    if schema_type == "integer":
        minimum = schema.get("minimum")
        return int(minimum if minimum is not None else 1)

    if schema_type == "number":
        minimum = schema.get("minimum")
        return float(minimum if minimum is not None else 1)

    if schema_type == "boolean":
        return False

    if schema_type == "string":
        return _default_for_string(pointer)

    return None


def generate_payload(
    tool_schema: Dict[str, Any],
    store: Dict[str, Any],
    overrides: Optional[Mapping[str, Any]] = None,
) -> Any:
    return generate_instance(tool_schema, tool_schema, store, overrides=overrides)


def validate_payload(payload: Any, tool_schema: Dict[str, Any], store: Dict[str, Any]) -> List[str]:
    resolver = RefResolver.from_schema(tool_schema, store=store)
    validator = Draft202012Validator(tool_schema, resolver=resolver)
    return [err.message for err in validator.iter_errors(payload)]


def generate_examples() -> List[Path]:
    schemas = load_schemas()
    tool_defs = load_tool_defs()
    store = build_schema_store(schemas)

    targets = {
        "qlip.validate_request": [
            (
                "uniform_grid",
                {"/problem/design_space/sites/mode": "uniform_grid"},
                EXAMPLES_DIR / "validate_request_uniform_grid.json",
            ),
            (
                "explicit_fractional_sites",
                {
                    "/problem/design_space/sites/mode": "explicit_fractional_sites"
                },
                EXAMPLES_DIR / "validate_request_explicit_fractional_sites.json",
            ),
        ],
        "qlip.solve": [
            (
                "uniform_grid",
                {"/problem/design_space/sites/mode": "uniform_grid"},
                EXAMPLES_DIR / "solve_uniform_grid.json",
            ),
            (
                "explicit_fractional_sites",
                {
                    "/problem/design_space/sites/mode": "explicit_fractional_sites"
                },
                EXAMPLES_DIR / "solve_explicit_fractional_sites.json",
            ),
        ],
    }

    written: List[Path] = []
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    for tool_name, variants in targets.items():
        tool_schema = build_tool_schema(tool_name, "inputSchema", schemas, tool_defs)
        for mode, overrides, output_path in variants:
            payload = generate_payload(tool_schema, store, overrides=overrides)
            errors = validate_payload(payload, tool_schema, store)
            if errors:
                formatted = "\n".join(errors)
                raise RuntimeError(
                    f"Generated payload for {tool_name} ({mode}) has schema errors:\n{formatted}"
                )
            output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(
                "OK: 0 schema errors for "
                f"{tool_name} {mode} -> {output_path} (copy/paste into MCP Inspector)"
            )
            written.append(output_path)

    return written


def main() -> None:
    generate_examples()


if __name__ == "__main__":
    main()
