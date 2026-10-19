"""Error taxonomy (ARCHITECTURE §9). ``http_status`` drives API error mapping."""

from __future__ import annotations


class DocForgeError(Exception):
    http_status = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class UserInputError(DocForgeError):
    http_status = 400
    code = "invalid_input"


class NotFoundError(DocForgeError):
    http_status = 404
    code = "not_found"


class UnsupportedFileError(UserInputError):
    code = "unsupported_file"


class FileTooLargeError(UserInputError):
    http_status = 413
    code = "file_too_large"


class TemplateError(DocForgeError):
    code = "template_error"


class ResearchError(DocForgeError):
    code = "research_error"


class LLMError(DocForgeError):
    http_status = 502
    code = "llm_error"


class LLMTransient(LLMError):
    """Retryable provider failure (5xx, timeout, connection)."""

    http_status = 503
    code = "llm_unavailable"


class LLMRateLimited(LLMTransient):
    code = "llm_rate_limited"

    @property
    def retry_after_s(self) -> float | None:
        return self.details.get("retry_after_s")

    @property
    def daily(self) -> bool:
        return bool(self.details.get("daily"))


class LLMModelUnavailable(LLMError):
    """The model was retired or is unknown to this key (HTTP 404); the gateway moves to the next model."""

    code = "llm_model_unavailable"


class LLMSchemaRejected(LLMError):
    """The provider rejected a native JSON-schema constraint; the gateway retries without it."""

    code = "llm_schema_rejected"


class LLMRefused(LLMError):
    """The provider blocked the prompt or response (safety/policy)."""

    code = "llm_refused"

    def __init__(self, message: str, *, category: str | None = None, details: dict | None = None) -> None:
        super().__init__(message, details={**(details or {}), "category": category})
        self.category = category


class LLMOutputInvalid(LLMError):
    code = "llm_output_invalid"


class CassetteMissing(LLMError):
    code = "cassette_missing"


class RenderError(DocForgeError):
    code = "render_error"


class ValidationFailed(DocForgeError):
    code = "validation_failed"


class BudgetExceeded(DocForgeError):
    code = "budget_exceeded"


class StorageError(DocForgeError):
    code = "storage_error"
