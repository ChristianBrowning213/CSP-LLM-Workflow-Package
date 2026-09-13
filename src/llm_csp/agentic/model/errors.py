"""Provider-independent failures at the structured model boundary."""

from __future__ import annotations

from enum import Enum


class ModelErrorCode(str, Enum):
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_REQUEST_FAILED = "MODEL_REQUEST_FAILED"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    MODEL_OUTPUT_SCHEMA_MISMATCH = "MODEL_OUTPUT_SCHEMA_MISMATCH"
    MODEL_FORMAT_RETRY_EXHAUSTED = "MODEL_FORMAT_RETRY_EXHAUSTED"


class AgentModelError(RuntimeError):
    """A typed model failure containing no provider-specific state."""

    def __init__(self, code: ModelErrorCode, message: str, *, retryable_format: bool = False) -> None:
        self.code = ModelErrorCode(code)
        self.retryable_format = retryable_format
        super().__init__(message)


__all__ = ["AgentModelError", "ModelErrorCode"]
