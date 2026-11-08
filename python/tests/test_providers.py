from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ailune.ai.ollama import OllamaProvider
from ailune.ai.openai_compatible import OpenAICompatibleProvider
from ailune.ai.types import ChatMessage, ProviderConfig, ProviderError, normalize_base_url


def config(**overrides) -> ProviderConfig:
    values = {
        "id": "p1",
        "display_name": "Test",
        "provider_type": "custom",
        "base_url": "https://example.test/v1",
        "model_name": "model-1",
        "api_key": "sk-secret",
        "temperature": 0.4,
        "max_tokens": 128,
        "timeout_seconds": 5,
        "extra_params": {"top_p": 0.9},
    }
    values.update(overrides)
    return ProviderConfig(**values)


def collect(provider):
    async def run():
        return [chunk async for chunk in provider.stream_chat([ChatMessage("user", "Hi")])]

    return asyncio.run(run())


def test_openai_stream_and_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        payload = (
            'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=payload, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(config(), transport=transport)
    assert collect(provider) == ["Hel", "lo"]
    assert seen["auth"] == "Bearer sk-secret"
    body = seen["body"]
    assert body["model"] == "model-1"
    assert body["stream"] is True
    assert body["temperature"] == 0.4
    assert body["max_tokens"] == 128
    assert body["top_p"] == 0.9
    assert body["messages"] == [{"role": "user", "content": "Hi"}]


def test_openai_auth_error_does_not_leak_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad api key"}})

    provider = OpenAICompatibleProvider(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as info:
        collect(provider)
    assert info.value.code == "auth"
    assert "sk-secret" not in info.value.message


def test_openai_network_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    provider = OpenAICompatibleProvider(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as info:
        collect(provider)
    assert info.value.code == "network"


def test_openai_models_and_test_connection():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})

    async def run():
        provider = OpenAICompatibleProvider(config(), transport=httpx.MockTransport(handler))
        models = await provider.list_models()
        result = await provider.test_connection()
        return models, result

    models, result = asyncio.run(run())
    assert models == ["a", "b"]
    assert result.ok
    assert result.models == ["a", "b"]


def test_ollama_stream():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        body = (
            '{"message":{"content":"Hi "},"done":false}\n'
            '{"message":{"content":"there"},"done":true}\n'
        )
        return httpx.Response(200, text=body)

    provider = OllamaProvider(
        config(base_url="http://127.0.0.1:11434", api_key=None),
        transport=httpx.MockTransport(handler),
    )
    assert collect(provider) == ["Hi ", "there"]
    assert seen["path"] == "/api/chat"


def test_base_url_validation():
    assert normalize_base_url("https://example.test/v1/") == "https://example.test/v1"
    for value in ("", "ftp://example.test", "https://user:pass@example.test", "https://example.test/?a=1"):
        with pytest.raises(ProviderError):
            normalize_base_url(value)


def test_missing_model_is_rejected():
    provider = OpenAICompatibleProvider(config(model_name=""), transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ProviderError) as info:
        collect(provider)
    assert info.value.code == "invalid_config"
