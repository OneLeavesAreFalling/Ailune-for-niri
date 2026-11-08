"""Provider-neutral types used by the chat engine and HTTP API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    display_name: str
    provider_type: str
    base_url: str
    model_name: str
    api_key: str | None = field(default=None, repr=False)
    temperature: float = 0.8
    max_tokens: int | None = None
    timeout_seconds: float = 60.0
    extra_params: dict[str, Any] = field(default_factory=dict)
    is_default: bool = False


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class TestResult:
    ok: bool
    message: str
    latency_ms: int
    models: list[str] = field(default_factory=list)


class ProviderError(Exception):
    """A safe-to-surface provider error. Never contains credentials."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        payload["retryable"] = self.retryable
        return payload


def error_from_status(status: int, body: str) -> ProviderError:
    message = _extract_error_message(body)
    if status in (401, 403):
        return ProviderError("auth", message or "authentication failed", status_code=status)
    if status == 404:
        return ProviderError(
            "not_found",
            message or "endpoint or model not found (check the base URL and model name)",
            status_code=status,
        )
    if status == 429:
        return ProviderError("rate_limit", message or "rate limit reached", status_code=status, retryable=True)
    if status in (408, 504):
        return ProviderError("timeout", message or "the provider timed out", status_code=status, retryable=True)
    if status >= 500:
        return ProviderError(
            "server_error", message or f"provider returned HTTP {status}", status_code=status, retryable=True
        )
    return ProviderError("http_error", message or f"provider returned HTTP {status}", status_code=status)


def _extract_error_message(body: str) -> str:
    body = (body or "").strip()
    if not body:
        return ""
    if len(body) > 800:
        body = body[:800] + "…"
    try:
        import json

        data = json.loads(body)
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"]
            if isinstance(error, str):
                return error
            if isinstance(data.get("message"), str):
                return data["message"]
            if isinstance(data.get("detail"), str):
                return data["detail"]
    except json.JSONDecodeError:
        pass
    return body


def normalize_base_url(value: str) -> str:
    """Validate an HTTP(S) base URL without credentials or fragments."""
    from urllib.parse import urlsplit

    value = (value or "").strip().rstrip("/")
    if not value:
        raise ProviderError("invalid_config", "base URL is required")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise ProviderError("invalid_config", "base URL must start with http:// or https://")
    if not parts.hostname:
        raise ProviderError("invalid_config", "base URL has no host")
    if parts.username or parts.password:
        raise ProviderError("invalid_config", "base URL must not contain credentials")
    if parts.query or parts.fragment:
        raise ProviderError("invalid_config", "base URL must not contain a query or fragment")
    return value
