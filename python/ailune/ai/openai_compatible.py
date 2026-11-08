"""OpenAI-compatible chat completions adapter.

Used for OpenAI, DeepSeek, Zhipu, DashScope, Moonshot, LM Studio, and custom
endpoints. The adapter intentionally avoids vendor SDKs so that every request,
timeout, redirect and stream is under our control.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import AIProvider
from .streaming import iter_sse_data
from .types import ChatMessage, ProviderConfig, ProviderError, TestResult, error_from_status, normalize_base_url

USER_AGENT = "Ailune/0.1.0"


class OpenAICompatibleProvider(AIProvider):
    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.base_url = normalize_base_url(config.base_url)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        timeout = max(1.0, float(self.config.timeout_seconds or 60.0))
        return httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            follow_redirects=False,
            transport=self._transport,
            headers={"User-Agent": USER_AGENT},
        )

    def _root(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        return base

    def _chat_url(self) -> str:
        return self._root() + "/chat/completions"

    def _models_url(self) -> str:
        return self._root() + "/models"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _body(self, messages: list[ChatMessage], stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {}
        body.update(self.config.extra_params or {})
        body.update(
            {
                "model": self.config.model_name,
                "messages": [m.as_dict() for m in messages],
                "stream": stream,
            }
        )
        if self.config.temperature is not None:
            body["temperature"] = float(self.config.temperature)
        if self.config.max_tokens:
            body["max_tokens"] = int(self.config.max_tokens)
        return body

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        if not self.config.model_name:
            raise ProviderError("invalid_config", "model name is required")
        async with self._client() as client:
            try:
                async with client.stream(
                    "POST",
                    self._chat_url(),
                    headers=self._headers(),
                    json=self._body(messages, stream=True),
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise error_from_status(response.status_code, body)
                    async for data in iter_sse_data(response):
                        if data.strip() == "[DONE]":
                            return
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        error = event.get("error")
                        if error:
                            message = error.get("message") if isinstance(error, dict) else str(error)
                            raise ProviderError("provider_error", message or "provider returned an error")
                        choices = event.get("choices")
                        if not isinstance(choices, list) or not choices:
                            continue
                        choice = choices[0]
                        if not isinstance(choice, dict):
                            continue
                        delta = choice.get("delta") or {}
                        if not isinstance(delta, dict):
                            continue
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            yield content
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and isinstance(part.get("text"), str):
                                    yield part["text"]
            except httpx.TimeoutException as exc:
                raise ProviderError("timeout", "the provider did not respond in time", retryable=True) from exc
            except httpx.RequestError as exc:
                raise ProviderError("network", f"cannot reach the provider: {exc}") from exc

    async def list_models(self) -> list[str]:
        async with self._client() as client:
            try:
                response = await client.get(self._models_url(), headers=self._headers())
            except httpx.TimeoutException as exc:
                raise ProviderError("timeout", "the provider did not respond in time", retryable=True) from exc
            except httpx.RequestError as exc:
                raise ProviderError("network", f"cannot reach the provider: {exc}") from exc
        if response.status_code >= 400:
            raise error_from_status(response.status_code, response.text)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("bad_response", "the provider returned invalid JSON") from exc
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        models = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                models.append(item["id"])
        return models

    async def test_connection(self) -> TestResult:
        started = time.monotonic()
        try:
            models = await self.list_models()
        except ProviderError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            return TestResult(False, exc.message, elapsed)
        elapsed = int((time.monotonic() - started) * 1000)
        if models:
            return TestResult(True, f"Connected — {len(models)} model(s) available", elapsed, models)
        return TestResult(True, "Connected — the service did not advertise any models", elapsed, [])
