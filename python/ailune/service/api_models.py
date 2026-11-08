"""Pydantic request models for the local AI service API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PersonalityCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    system_prompt: str = Field(default="", max_length=20_000)


class PersonalityUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    system_prompt: str | None = Field(default=None, max_length=20_000)


class CharacterCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    model_path: str = Field(min_length=1, max_length=4096)
    model_entry: str = Field(min_length=1, max_length=1024)
    personality_id: str | None = None
    reply_language: Literal["auto", "en", "zh_CN"] = "auto"
    scale: float = Field(default=1.0, ge=0.25, le=4.0)

    @field_validator("model_path")
    @classmethod
    def absolute_model_path(cls, value: str) -> str:
        from pathlib import Path

        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("model_path must be an absolute path")
        return str(path)

    @field_validator("model_entry")
    @classmethod
    def safe_entry(cls, value: str) -> str:
        from pathlib import Path, PurePosixPath

        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("model_entry must be a relative path inside the model directory")
        if not value.lower().endswith(".model3.json"):
            raise ValueError("model_entry must end with .model3.json")
        return str(Path(*path.parts))


class CharacterUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    model_path: str | None = Field(default=None, min_length=1, max_length=4096)
    model_entry: str | None = Field(default=None, min_length=1, max_length=1024)
    personality_id: str | None = None
    reply_language: Literal["auto", "en", "zh_CN"] | None = None
    scale: float | None = Field(default=None, ge=0.25, le=4.0)


class ProviderCreate(ApiModel):
    display_name: str = Field(min_length=1, max_length=100)
    provider_type: str = Field(min_length=1, max_length=50)
    base_url: str = Field(min_length=1, max_length=2048)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=8192)
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    extra_params: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class ProviderUpdate(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    provider_type: str | None = Field(default=None, min_length=1, max_length=50)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=8192)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    timeout_seconds: float | None = Field(default=None, ge=1.0, le=600.0)
    extra_params: dict[str, Any] | None = None
    is_default: bool | None = None


class ProviderTest(ApiModel):
    display_name: str = "connection test"
    provider_type: str = Field(min_length=1, max_length=50)
    base_url: str = Field(min_length=1, max_length=2048)
    model_name: str = Field(default="test", max_length=200)
    api_key: str | None = Field(default=None, max_length=8192)
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    extra_params: dict[str, Any] = Field(default_factory=dict)
    provider_id: str | None = None


class ChatRequest(ApiModel):
    character_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=16_000)
    conversation_id: str | None = None
    provider_id: str | None = None
    request_id: str | None = Field(default=None, max_length=100)


class MemoryCreate(ApiModel):
    character_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)


class ConversationCreate(ApiModel):
    character_id: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=200)
