from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ailune.ai.base import AIProvider
from ailune.ai.types import ChatMessage, ProviderConfig, TestResult
from ailune.service.app import create_app
from ailune.service.settings import settings_for_tests

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def write_sample_model(root: Path) -> Path:
    (root / "textures").mkdir(parents=True)
    (root / "motions").mkdir()
    (root / "expressions").mkdir()
    (root / "sounds").mkdir()
    (root / "textures" / "texture_00.png").write_bytes(TINY_PNG)
    (root / "Aria.moc3").write_bytes(b"MOC3" + b"\x00" * 64)
    (root / "Aria.physics3.json").write_text("{}", encoding="utf-8")
    (root / "Aria.pose3.json").write_text("{}", encoding="utf-8")
    (root / "expressions" / "smile.exp3.json").write_text("{}", encoding="utf-8")
    for name in ("idle", "happy"):
        (root / "motions" / f"{name}.motion3.json").write_text("{}", encoding="utf-8")
    (root / "sounds" / "pat.wav").write_bytes(b"RIFF")
    payload = {
        "Version": 3,
        "FileReferences": {
            "Moc": "Aria.moc3",
            "Textures": ["textures/texture_00.png"],
            "Physics": "Aria.physics3.json",
            "Pose": "Aria.pose3.json",
            "Expressions": [{"Name": "Smile", "File": "expressions/smile.exp3.json"}],
            "Motions": {
                "Idle": [{"File": "motions/idle.motion3.json"}],
                "Happy": [{"File": "motions/happy.motion3.json", "Sound": "sounds/pat.wav"}],
            },
        },
        "Groups": [
            {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen"]},
            {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
        ],
        "HitAreas": [{"Id": "Head", "Name": "Head"}],
    }
    (root / "Aria.model3.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


@pytest.fixture()
def sample_model(tmp_path: Path) -> Path:
    return write_sample_model(tmp_path / "Aria")


class FakeProvider(AIProvider):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.last_messages: list[ChatMessage] = []

    async def stream_chat(self, messages: list[ChatMessage]):
        self.last_messages = list(messages)
        for chunk in ("Hello", " from", " the", " fake", " provider."):
            yield chunk

    async def test_connection(self) -> TestResult:
        return TestResult(True, "fake provider is available", 3, ["fake-model"])

    async def list_models(self) -> list[str]:
        return ["fake-model"]


@pytest.fixture()
def settings(tmp_path: Path):
    return settings_for_tests(tmp_path)


@pytest.fixture()
def fake_factory():
    providers: list[FakeProvider] = []

    def factory(config: ProviderConfig) -> FakeProvider:
        provider = FakeProvider(config)
        providers.append(provider)
        return provider

    factory.created = providers  # type: ignore[attr-defined]
    return factory


@pytest.fixture()
def app(settings, fake_factory):
    return create_app(settings, provider_factory=fake_factory)


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def headers(settings):
    return {"Authorization": f"Bearer {settings.token}"}
