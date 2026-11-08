"""Provider presets and adapter construction."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .base import AIProvider
from .ollama import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider
from .types import ProviderConfig, ProviderError


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    base_url: str
    default_model: str
    api_style: str
    needs_key: bool
    local: bool = False


PRESETS: dict[str, Preset] = {
    "openai": Preset(
        "openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini", "openai", True
    ),
    "deepseek": Preset(
        "deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat", "openai", True
    ),
    "zhipu": Preset(
        "zhipu",
        "Zhipu AI",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-4-flash",
        "openai",
        True,
    ),
    "dashscope": Preset(
        "dashscope",
        "Alibaba DashScope",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
        "openai",
        True,
    ),
    "moonshot": Preset(
        "moonshot", "Moonshot AI", "https://api.moonshot.cn/v1", "moonshot-v1-8k", "openai", True
    ),
    "ollama": Preset(
        "ollama", "Ollama (local)", "http://127.0.0.1:11434", "llama3.2", "ollama", False, True
    ),
    "lmstudio": Preset(
        "lmstudio", "LM Studio (local)", "http://127.0.0.1:1234/v1", "local-model", "openai", False, True
    ),
    "custom": Preset("custom", "OpenAI-compatible (custom)", "", "", "openai", False),
}

ALIASES = {
    "openai-compatible": "custom",
    "openai_compatible": "custom",
    "lm-studio": "lmstudio",
    "zhipuai": "zhipu",
    "qwen": "dashscope",
    "tongyi": "dashscope",
}

PROVIDER_TYPES = tuple(PRESETS.keys())


def normalize_provider_type(value: str) -> str:
    value = (value or "").strip().lower()
    value = ALIASES.get(value, value)
    if value not in PRESETS:
        raise ProviderError("invalid_config", f"unknown provider type: {value or '(empty)'}")
    return value


def make_provider(
    config: ProviderConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AIProvider:
    provider_type = normalize_provider_type(config.provider_type)
    preset = PRESETS[provider_type]
    if preset.api_style == "ollama":
        return OllamaProvider(config, transport=transport)
    if not config.base_url.strip():
        raise ProviderError("invalid_config", "base URL is required for this provider")
    return OpenAICompatibleProvider(config, transport=transport)


def public_presets() -> list[dict]:
    return [
        {
            "id": p.id,
            "label": p.label,
            "base_url": p.base_url,
            "default_model": p.default_model,
            "api_style": p.api_style,
            "needs_key": p.needs_key,
            "local": p.local,
        }
        for p in PRESETS.values()
    ]
