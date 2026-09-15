from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse


def is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _http_get_json(url: str, timeout_s: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict, timeout_s: int = 20) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _origin(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def discover_model_id(base_url: str, timeout_s: int = 10) -> str | None:
    origin = _origin(base_url)
    path = urlparse(base_url).path.rstrip("/")
    openai_models_url = f"{origin}{path}/models" if path else f"{origin}/v1/models"
    api_models_url = f"{origin}/api/v1/models"

    # Prefer loaded LLM model from LM Studio style API.
    try:
        payload = _http_get_json(api_models_url, timeout_s=timeout_s)
        models = payload.get("models", [])
        llm_loaded = [
            model
            for model in models
            if model.get("type") == "llm" and isinstance(model.get("loaded_instances"), list) and model.get("loaded_instances")
        ]
        if llm_loaded:
            key = llm_loaded[0].get("key")
            if isinstance(key, str) and key:
                return key
        llm_models = [model for model in models if model.get("type") == "llm"]
        if llm_models:
            key = llm_models[0].get("key")
            if isinstance(key, str) and key:
                return key
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError):
        pass

    # Fallback to OpenAI-compatible model listing.
    try:
        payload = _http_get_json(openai_models_url, timeout_s=timeout_s)
        data = payload.get("data", [])
        if isinstance(data, list):
            non_embedding = [
                item.get("id")
                for item in data
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and "embedding" not in item.get("id", "").lower()
            ]
            if non_embedding:
                return non_embedding[0]
            any_ids = [item.get("id") for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]
            if any_ids:
                return any_ids[0]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError):
        pass
    return None


def resolve_llm_credentials(base_url: str, llm_api_key: str | None, llm_model: str | None) -> tuple[str | None, str | None, list[str]]:
    notes: list[str] = []
    model = llm_model
    api_key = llm_api_key
    if not model:
        model = discover_model_id(base_url)
        if model:
            notes.append(f"auto_discovered_model:{model}")
    if not api_key and is_local_base_url(base_url):
        api_key = "local-key"
        notes.append("auto_filled_api_key:local-key")
    return api_key, model, notes


def smoke_chat_api_v1(base_url: str, model: str, timeout_s: int = 20) -> tuple[bool, str]:
    origin = _origin(base_url)
    url = f"{origin}/api/v1/chat"
    payload = {
        "model": model,
        "system_prompt": "Reply with one short sentence.",
        "input": "Say OK.",
    }
    try:
        response = _http_post_json(url, payload, timeout_s=timeout_s)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return False, str(exc)
    output = response.get("output")
    if isinstance(output, list) and output:
        return True, "ok"
    return False, "missing_output"
