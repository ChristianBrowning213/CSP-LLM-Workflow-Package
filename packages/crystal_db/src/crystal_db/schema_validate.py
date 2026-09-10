import json
from pathlib import Path
from typing import Any, Dict, Optional


SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


class _ValidationError(Exception):
    def __init__(self, path: str, message: str):
        super().__init__(message)
        self.path = path
        self.message = message


def _schema_path(schema_name: str) -> Path:
    if schema_name.endswith(".schema.json"):
        filename = schema_name
    else:
        filename = f"{schema_name}.schema.json"
    path = SCHEMAS_DIR / filename
    if not path.exists():
        raise ValueError(json.dumps({"schema": schema_name, "path": "$", "message": "schema_not_found"}))
    return path


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    return True


def _ensure_type(value: Any, expected: Any, path: str) -> None:
    if isinstance(expected, str):
        types = [expected]
    elif isinstance(expected, list):
        types = expected
    else:
        return
    if not any(_is_type(value, item) for item in types):
        raise _ValidationError(path, f"type_mismatch expected={types}")


def _validate_node(value: Any, schema: Dict[str, Any], path: str) -> None:
    if "anyOf" in schema:
        last_error: Optional[_ValidationError] = None
        for option in schema["anyOf"]:
            try:
                _validate_node(value, option, path)
                return
            except _ValidationError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
    if "type" in schema:
        _ensure_type(value, schema["type"], path)
    if "enum" in schema and value not in schema["enum"]:
        raise _ValidationError(path, "enum_mismatch")
    if "const" in schema and value != schema["const"]:
        raise _ValidationError(path, "const_mismatch")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise _ValidationError(path, f"missing_required:{key}")
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value:
                _validate_node(value[key], child_schema, f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    raise _ValidationError(path, f"unexpected_property:{key}")

    if isinstance(value, list) and "items" in schema:
        item_schema = schema["items"]
        for idx, item in enumerate(value):
            _validate_node(item, item_schema, f"{path}[{idx}]")


def validate(payload: Dict[str, Any], schema_name: str) -> None:
    path = _schema_path(schema_name)
    with open(path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)

    try:
        import jsonschema  # type: ignore
    except Exception:  # pylint: disable=broad-except
        jsonschema = None

    if jsonschema is not None:
        try:
            jsonschema.validate(instance=payload, schema=schema)
        except Exception as exc:  # pylint: disable=broad-except
            detail = {
                "schema": schema_name,
                "path": "$",
                "message": str(exc),
            }
            raise ValueError(json.dumps(detail)) from exc
        return

    try:
        _validate_node(payload, schema, "$")
    except _ValidationError as exc:
        detail = {"schema": schema_name, "path": exc.path, "message": exc.message}
        raise ValueError(json.dumps(detail)) from exc
