"""Native Ollama adapter using /api/chat (NDJSON)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import AIProvider
from .streaming import iter_ndjson
from .types import ChatMessage, ProviderConfig, ProviderError, TestResult, normalize_base_url

USER_AGENT = "Ailune/0.1.0"


class OllamaProvider(AIProvider):
    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        base = normalize_base_url(config.base_url)
        if base.endswith("/v1") or base.endswith("/api"):
            base = base.rsplit("/", 1)[0]
        self.base_url = base
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        timeout = max(1.0, float(self.config.timeout_seconds or 60.0))
        return httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            follow_redirects=False,
            transport=self._transport,
            headers={"User-Agent": USER_AGENT},
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/x-ndjson"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _body(self, messages: list[ChatMessage], stream: bool) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if self.config.temperature is not None:
            options["temperature"] = float(self.config.temperature)
        if self.config.max_tokens:
            options["num_predict"] = int(self.config.max_tokens)
        body: dict[str, Any] = {}
        body.update(self.config.extra_params or {})
        body.setdefault("options", {}).update(options)
        body.update(
            {
                "model": self.config.model_name,
                "messages": [m.as_dict() for m in messages],
                "stream": stream,
            }
        )
        return body

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        if not self.config.model_name:
            raise ProviderError("invalid_config", "model name is required")
        async with self._client() as client:
            try:
                async with client.stream(
                    "POST",
                    self.base_url + "/api/chat",
                    headers=self._headers(),
                    json=self._body(messages, stream=True),
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise ProviderError(
                            "http_error",
                            _ollama_error(body) or f"Ollama returned HTTP {response.status_code}",
                            status_code=response.status_code,
                        )
                    async for event in iter_ndjson(response):
                        error = event.get("error")
                        if error:
                            raise ProviderError("provider_error", str(error))
                        message = event.get("message")
                        if isinstance(message, dict):
                            content = message.get("content")
                            if isinstance(content, str) and content:
                                yield content
                        if event.get("done") is True:
                            return
            except httpx.TimeoutException as exc:
                raise ProviderError("timeout", "Ollama did not respond in time", retryable=True) from exc
            except httpx.RequestError as exc:
                raise ProviderError("network", f"cannot reach Ollama: {exc}") from exc

    async def list_models(self) -> list[str]:
        async with self._client() as client:
            try:
                response = await client.get(self.base_url + "/api/tags", headers=self._headers())
            except httpx.TimeoutException as exc:
                raise ProviderError("timeout", "Ollama did not respond in time", retryable=True) from exc
            except httpx.RequestError as exc:
                raise ProviderError("network", f"cannot reach Ollama: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(
                "http_error",
                f"Ollama returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        try:
            data = response.json()
        except Exception as exc:
            raise ProviderError("bad_response", "Ollama returned invalid JSON") from exc
        models = []
        for item in data.get("models", []) if isinstance(data, dict) else []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if isinstance(name, str):
                    models.append(name)
        return models

    async def test_connection(self) -> TestResult:
        started = time.monotonic()
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return TestResult(False, exc.message, int((time.monotonic() - started) * 1000))
        elapsed = int((time.monotonic() - started) * 1000)
        if models:
            return TestResult(True, f"Connected — {len(models)} local model(s)", elapsed, models)
        return TestResult(True, "Connected — no local models have been pulled yet", elapsed, [])


def _ollama_error(body: str) -> str:
    try:
        import json

        data = json.loads(body)
        if isinstance(data, dict) and isinstance(data.get("error"), str):
            return data["error"]
    except Exception:
        pass
    return ""
