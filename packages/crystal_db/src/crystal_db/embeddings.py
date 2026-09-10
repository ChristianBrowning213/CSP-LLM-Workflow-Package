import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .utils import stable_hash

DEFAULT_MODEL_NAME = "hash-embed"
DEFAULT_MODEL_VERSION = "v1"
DEFAULT_DIM = 64
DEFAULT_EMBED_ENGINE = "auto"

LMSTUDIO_PROVIDER = "lmstudio"
LMSTUDIO_MODEL_NAME = "text-embedding-bge-m3"
LMSTUDIO_MODEL_VERSION = "lmstudio_v1"

ENV_BASE_URL = "CRYSTALDB_EMBED_BASE_URL"
ENV_API_KEY = "CRYSTALDB_EMBED_API_KEY"
ENV_TIMEOUT_S = "CRYSTALDB_EMBED_TIMEOUT_S"
ENV_BATCH = "CRYSTALDB_EMBED_BATCH"
ENV_RETRIES = "CRYSTALDB_EMBED_RETRIES"
ENV_BACKOFF_S = "CRYSTALDB_EMBED_BACKOFF_S"
ENV_MAX_CTX_TOKENS = "CRYSTALDB_EMBED_MAX_CTX_TOKENS"
ENV_CHUNK_OVERLAP_TOKENS = "CRYSTALDB_EMBED_CHUNK_OVERLAP_TOKENS"
ENV_MAX_ITEMS_PER_REQUEST = "CRYSTALDB_EMBED_MAX_ITEMS_PER_REQUEST"
ENV_MAX_TOTAL_TOKENS_PER_REQUEST = "CRYSTALDB_EMBED_MAX_TOTAL_TOKENS_PER_REQUEST"
ENV_CHUNKING = "CRYSTALDB_EMBED_CHUNKING"

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"
DEFAULT_TIMEOUT_S = 60
DEFAULT_BATCH = 64
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_S = 0.5
DEFAULT_MAX_CTX_TOKENS = 4096
DEFAULT_CHUNK_OVERLAP_TOKENS = 128
DEFAULT_MAX_ITEMS_PER_REQUEST = 8
DEFAULT_MAX_TOTAL_TOKENS_PER_REQUEST = 12000
DEFAULT_CHUNKING = True
TOKEN_ESTIMATE_SAFETY = 1.2
TOKEN_CHAR_RATIO = 4.0
CTX_MARGIN_TOKENS = 64
SENTENCE_SEP_PATTERN = re.compile(r"(?<=[\.;\?!])\s+")


class EmbeddingDocumentError(RuntimeError):
    def __init__(self, *, code: str, message: str, diagnostics: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics or {}

    def to_payload(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "diagnostics": self.diagnostics,
        }


def _hash_embed(text: str, model_name: str, model_version: str, dim: int) -> List[float]:
    seed_hex = stable_hash({"text": text, "model_name": model_name, "model_version": model_version})[:16]
    seed = int(seed_hex, 16)
    rng = random.Random(seed)
    return [round(rng.uniform(-1.0, 1.0), 6) for _ in range(dim)]


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _get_env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    return default


def estimate_tokens(text: str) -> int:
    value = text or ""
    estimated = int(math.ceil((len(value) / TOKEN_CHAR_RATIO) * TOKEN_ESTIMATE_SAFETY))
    return max(1, estimated)


def _ctx_safe_token_limit(max_ctx_tokens: int) -> int:
    return max(1, int(max_ctx_tokens) - CTX_MARGIN_TOKENS)


def _estimate_chars_for_tokens(tokens: int) -> int:
    return max(1, int((float(tokens) / TOKEN_ESTIMATE_SAFETY) * TOKEN_CHAR_RATIO))


def _shrink_to_token_limit(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    if not text:
        return text
    low = 1
    high = len(text)
    best = text[:1]
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid]
        if estimate_tokens(candidate) <= max_tokens:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _split_into_segments(text: str) -> List[str]:
    paragraphs = [part for part in text.split("\n\n") if part]
    segments: List[str] = []
    for para in paragraphs:
        sentences = [seg for seg in SENTENCE_SEP_PATTERN.split(para) if seg]
        if sentences:
            segments.extend(sentences)
        else:
            segments.append(para)
    if not segments:
        return [text]
    return segments


def chunk_text_for_embedding(
    text: str,
    *,
    max_ctx_tokens: int,
    overlap_tokens: int,
) -> List[Dict[str, Any]]:
    safe_token_limit = _ctx_safe_token_limit(max_ctx_tokens)
    source = text or ""
    if estimate_tokens(source) <= safe_token_limit:
        return [{"text": source, "weight_tokens": estimate_tokens(source)}]

    overlap_chars = max(0, int(overlap_tokens) * int(TOKEN_CHAR_RATIO))
    chunks: List[Dict[str, Any]] = []
    current = ""
    for segment in _split_into_segments(source):
        proposed = segment if not current else (current + " " + segment)
        if estimate_tokens(proposed) <= safe_token_limit:
            current = proposed
            continue
        if current:
            fitted = _shrink_to_token_limit(current, safe_token_limit)
            if fitted:
                chunks.append({"text": fitted, "weight_tokens": estimate_tokens(fitted)})
            current = ""
        remaining = segment
        while remaining:
            fitted = _shrink_to_token_limit(remaining, safe_token_limit)
            if not fitted:
                fitted = remaining[:1]
            chunks.append({"text": fitted, "weight_tokens": estimate_tokens(fitted)})
            if len(fitted) >= len(remaining):
                remaining = ""
            else:
                start = max(0, len(fitted) - overlap_chars)
                remaining = remaining[start:]
    if current:
        fitted = _shrink_to_token_limit(current, safe_token_limit)
        if fitted:
            chunks.append({"text": fitted, "weight_tokens": estimate_tokens(fitted)})

    normalized: List[Dict[str, Any]] = []
    for item in chunks:
        value = str(item.get("text") or "")
        if not value:
            continue
        fitted = _shrink_to_token_limit(value, safe_token_limit)
        if not fitted:
            continue
        normalized.append({"text": fitted, "weight_tokens": estimate_tokens(fitted)})
    if not normalized:
        fitted = _shrink_to_token_limit(source, safe_token_limit)
        if not fitted:
            fitted = source[:1] if source else " "
        normalized = [{"text": fitted, "weight_tokens": estimate_tokens(fitted)}]
    return normalized


def _weighted_mean_pool(vectors: List[List[float]], weights: List[int]) -> List[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    for idx, vector in enumerate(vectors):
        if len(vector) != dim:
            raise EmbeddingDocumentError(
                code="chunk_dimension_mismatch",
                message="Chunk embeddings had inconsistent dimensions.",
                diagnostics={"expected_dim": dim, "failed_chunk_index": idx, "actual_dim": len(vector)},
            )
    total_weight = float(sum(max(1, int(w)) for w in weights))
    pooled = [0.0 for _ in range(dim)]
    for vector, weight in zip(vectors, weights):
        scalar = float(max(1, int(weight)))
        for idx, value in enumerate(vector):
            pooled[idx] += float(value) * scalar
    return [value / total_weight for value in pooled]


def _pack_by_limits(texts: List[str], *, max_items: int, max_total_tokens: int) -> List[List[str]]:
    if not texts:
        return []
    batches: List[List[str]] = []
    current: List[str] = []
    current_tokens = 0
    for text in texts:
        tokens = estimate_tokens(text)
        exceed_items = len(current) >= max_items
        exceed_tokens = (current_tokens + tokens > max_total_tokens) and bool(current)
        if exceed_items or exceed_tokens:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(text)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


def _lmstudio_config() -> tuple:
    base_url = os.getenv(ENV_BASE_URL, DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    api_key = os.getenv(ENV_API_KEY, DEFAULT_API_KEY).strip()
    timeout_s = _get_env_float(ENV_TIMEOUT_S, DEFAULT_TIMEOUT_S)
    batch_size = _get_env_int(ENV_BATCH, DEFAULT_BATCH)
    retries = _get_env_int(ENV_RETRIES, DEFAULT_RETRIES)
    backoff_s = _get_env_float(ENV_BACKOFF_S, DEFAULT_BACKOFF_S)
    max_ctx_tokens = _get_env_int(ENV_MAX_CTX_TOKENS, DEFAULT_MAX_CTX_TOKENS)
    overlap_tokens = _get_env_int(ENV_CHUNK_OVERLAP_TOKENS, DEFAULT_CHUNK_OVERLAP_TOKENS)
    max_items_per_request = _get_env_int(ENV_MAX_ITEMS_PER_REQUEST, DEFAULT_MAX_ITEMS_PER_REQUEST)
    max_total_tokens_per_request = _get_env_int(ENV_MAX_TOTAL_TOKENS_PER_REQUEST, DEFAULT_MAX_TOTAL_TOKENS_PER_REQUEST)
    chunking = _get_env_bool(ENV_CHUNKING, DEFAULT_CHUNKING)
    return (
        base_url,
        api_key,
        timeout_s,
        batch_size,
        retries,
        backoff_s,
        max_ctx_tokens,
        overlap_tokens,
        max_items_per_request,
        max_total_tokens_per_request,
        chunking,
    )


def _lmstudio_embed_batch(
    texts: List[str],
    model_name: str,
    base_url: str,
    api_key: str,
    timeout_s: float,
    retries: int,
    backoff_s: float,
) -> List[List[float]]:
    if not texts:
        return []
    url = base_url.rstrip("/") + "/embeddings"
    payload = {"model": model_name, "input": texts}
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8")
            try:
                response = json.loads(raw)
            except json.JSONDecodeError as exc:
                if attempt < retries:
                    time.sleep(backoff_s * (2 ** attempt))
                    attempt += 1
                    continue
                raise RuntimeError("LM Studio embeddings response was not valid JSON") from exc
            break
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if retryable and attempt < retries:
                time.sleep(backoff_s * (2 ** attempt))
                attempt += 1
                continue
            raise RuntimeError(f"LM Studio embeddings request failed: {exc}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < retries:
                time.sleep(backoff_s * (2 ** attempt))
                attempt += 1
                continue
            raise RuntimeError(f"LM Studio embeddings request failed: {exc}") from exc

    data_items = response.get("data")
    if not isinstance(data_items, list):
        raise RuntimeError("LM Studio embeddings response missing data array")
    if all(isinstance(item, dict) and "index" in item for item in data_items):
        embeddings: List[List[float]] = [None for _ in range(len(texts))]  # type: ignore[list-item]
        for item in data_items:
            idx = int(item.get("index", -1))
            if idx < 0 or idx >= len(texts):
                raise RuntimeError("LM Studio embeddings response index out of range")
            embeddings[idx] = item.get("embedding")  # type: ignore[index]
        if any(item is None for item in embeddings):
            raise RuntimeError("LM Studio embeddings response missing embeddings for some inputs")
        return embeddings  # type: ignore[return-value]
    embeddings = [item.get("embedding") for item in data_items if isinstance(item, dict)]
    if len(embeddings) != len(texts):
        raise RuntimeError("LM Studio embeddings response length mismatch")
    return embeddings  # type: ignore[return-value]


def resolve_embed_engine(embed_engine: Optional[str], model_name: str) -> str:
    engine = (embed_engine or DEFAULT_EMBED_ENGINE).strip().lower()
    if engine == DEFAULT_EMBED_ENGINE:
        return LMSTUDIO_PROVIDER if model_name == LMSTUDIO_MODEL_NAME else "hash"
    if engine in ("hash", "local"):
        return "hash"
    if engine == LMSTUDIO_PROVIDER:
        return LMSTUDIO_PROVIDER
    raise ValueError(f"unsupported embed engine: {embed_engine}")


def resolve_model_version(model_name: str, model_version: Optional[str], embed_engine: Optional[str] = None) -> str:
    backend = resolve_embed_engine(embed_engine, model_name)
    if backend == LMSTUDIO_PROVIDER:
        if not model_version or model_version == DEFAULT_MODEL_VERSION:
            return LMSTUDIO_MODEL_VERSION
        return model_version
    if model_version:
        return model_version
    return DEFAULT_MODEL_VERSION


def embed_texts(
    texts: List[str],
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: Optional[str] = DEFAULT_MODEL_VERSION,
    dim: int = DEFAULT_DIM,
    embed_engine: Optional[str] = None,
) -> List[List[float]]:
    if model_name is None:
        model_name = DEFAULT_MODEL_NAME
    backend = resolve_embed_engine(embed_engine, model_name)
    model_version = resolve_model_version(model_name, model_version, embed_engine=backend)
    if backend == LMSTUDIO_PROVIDER:
        (
            base_url,
            api_key,
            timeout_s,
            batch_size,
            retries,
            backoff_s,
            _max_ctx_tokens,
            _overlap_tokens,
            max_items_per_request,
            max_total_tokens_per_request,
            _chunking,
        ) = _lmstudio_config()
        effective_items = max(1, min(int(batch_size), int(max_items_per_request)))
        vectors: List[List[float]] = []
        raw_batches = _pack_by_limits(texts, max_items=effective_items, max_total_tokens=max_total_tokens_per_request)
        for batch in raw_batches:
            vectors.extend(_lmstudio_embed_batch(batch, model_name, base_url, api_key, timeout_s, retries, backoff_s))
        return vectors
    return [_hash_embed(text, model_name, model_version, dim) for text in texts]


def embed_document_text(
    text: str,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: Optional[str] = DEFAULT_MODEL_VERSION,
    dim: int = DEFAULT_DIM,
    embed_engine: Optional[str] = None,
) -> Tuple[List[float], Dict[str, Any]]:
    if model_name is None:
        model_name = DEFAULT_MODEL_NAME
    backend = resolve_embed_engine(embed_engine, model_name)
    resolved_model_version = resolve_model_version(model_name, model_version, embed_engine=backend)
    total_est_tokens = estimate_tokens(text)
    chunking_enabled = _get_env_bool(ENV_CHUNKING, DEFAULT_CHUNKING)
    max_ctx_tokens = _get_env_int(ENV_MAX_CTX_TOKENS, DEFAULT_MAX_CTX_TOKENS)
    overlap_tokens = _get_env_int(ENV_CHUNK_OVERLAP_TOKENS, DEFAULT_CHUNK_OVERLAP_TOKENS)

    if (not chunking_enabled) and total_est_tokens > max_ctx_tokens:
        raise EmbeddingDocumentError(
            code="text_too_long_for_context",
            message="Text exceeds embedding context and chunking is disabled.",
            diagnostics={
                "estimated_tokens": total_est_tokens,
                "max_ctx_tokens": max_ctx_tokens,
            },
        )

    if chunking_enabled:
        chunks = chunk_text_for_embedding(
            text,
            max_ctx_tokens=max_ctx_tokens,
            overlap_tokens=overlap_tokens,
        )
    else:
        chunks = [{"text": text, "weight_tokens": total_est_tokens}]

    chunk_texts = [str(item["text"]) for item in chunks]
    chunk_weights = [max(1, int(item.get("weight_tokens", 1))) for item in chunks]

    try:
        chunk_vectors = embed_texts(
            chunk_texts,
            model_name=model_name,
            model_version=resolved_model_version,
            dim=dim,
            embed_engine=backend,
        )
    except Exception as exc:  # pylint: disable=broad-except
        failed_chunk_index = 0
        for idx, chunk_text in enumerate(chunk_texts):
            try:
                single = embed_texts(
                    [chunk_text],
                    model_name=model_name,
                    model_version=resolved_model_version,
                    dim=dim,
                    embed_engine=backend,
                )
                if len(single) != 1:
                    failed_chunk_index = idx
                    break
            except Exception:  # pylint: disable=broad-except
                failed_chunk_index = idx
                break
        raise EmbeddingDocumentError(
            code="chunk_embedding_failed",
            message="Failed to embed one or more chunks.",
            diagnostics={
                "chunk_count": len(chunk_texts),
                "failed_chunk_index": failed_chunk_index,
                "error": str(exc),
            },
        ) from exc
    if len(chunk_vectors) != len(chunk_texts):
        raise EmbeddingDocumentError(
            code="chunk_embedding_failed",
            message="Chunk embedding count mismatch.",
            diagnostics={"chunk_count": len(chunk_texts), "received": len(chunk_vectors), "failed_chunk_index": 0},
        )

    pooled = _weighted_mean_pool(chunk_vectors, chunk_weights)
    meta = {
        "chunk_count": len(chunk_texts),
        "max_chunk_tokens": max(chunk_weights) if chunk_weights else 0,
        "total_est_tokens": total_est_tokens,
    }
    return pooled, meta


def embed_text(
    text: str,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: Optional[str] = DEFAULT_MODEL_VERSION,
    dim: int = DEFAULT_DIM,
    embed_engine: Optional[str] = None,
) -> List[float]:
    vectors = embed_texts(
        [text],
        model_name=model_name,
        model_version=model_version,
        dim=dim,
        embed_engine=embed_engine,
    )
    return vectors[0] if vectors else []


def l2_distance(vec_a: List[float], vec_b: List[float]) -> float:
    total = 0.0
    for a, b in zip(vec_a, vec_b):
        delta = a - b
        total += delta * delta
    return total ** 0.5


def vector_hash(vector: List[float]) -> str:
    return stable_hash({"vector": vector})
