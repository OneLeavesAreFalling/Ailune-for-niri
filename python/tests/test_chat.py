from __future__ import annotations

import asyncio
from pathlib import Path

from ailune.ai.types import ChatMessage, ProviderConfig
from ailune.ai.types import TestResult as ProviderTestResult
from ailune.service.chat import CancelToken, ChatError, ChatService
from ailune.service.secrets import FileSecretStore
from ailune.service.store import Database


class FakeProvider:
    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []

    async def stream_chat(self, messages):
        self.messages = list(messages)
        yield "First"
        yield " second"

    async def test_connection(self):
        return ProviderTestResult(True, "ok", 1, [])

    async def list_models(self):
        return []


def setup(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    secrets = FileSecretStore(tmp_path / "secrets.json")
    created: list[FakeProvider] = []

    def factory(_config: ProviderConfig) -> FakeProvider:
        provider = FakeProvider()
        created.append(provider)
        return provider

    service = ChatService(db, secrets, provider_factory=factory)
    personality = db.create_personality("Kind", "You are gentle and curious.")
    character = db.create_character(
        {
            "name": "Aria",
            "model_path": "/models/Aria",
            "model_entry": "Aria.model3.json",
            "personality_id": personality["id"],
            "reply_language": "zh_CN",
        }
    )
    db.add_memory(character["id"], "The user loves rainy days.")
    provider_row = db.create_provider(
        {
            "display_name": "Fake",
            "provider_type": "custom",
            "base_url": "https://example.test/v1",
            "model_name": "fake-model",
            "temperature": 0.6,
        },
        "provider:fake",
        provider_id="prov_fake",
    )
    return db, service, character, provider_row, created


def test_prepare_injects_personality_memory_and_language(tmp_path: Path):
    db, service, character, provider_row, created = setup(tmp_path)
    session = service.prepare(character_id=character["id"], text="Hello")
    system = session.messages[0]
    assert system.role == "system"
    assert "gentle and curious" in system.content
    assert "rainy days" in system.content
    assert "Simplified Chinese" in system.content
    assert session.messages[-1] == ChatMessage("user", "Hello")
    assert db.recent_messages(session.conversation_id)[0]["role"] == "user"


def test_stream_persists_reply_and_trims_history(tmp_path: Path):
    db, service, character, provider_row, created = setup(tmp_path)

    async def run():
        session = service.prepare(character_id=character["id"], text="Hello")
        events = []
        async for event in session.events():
            events.append(event)
        return session, events

    session, events = asyncio.run(run())
    types = [event["type"] for event in events]
    assert types[0] == "start"
    assert types[-1] == "done"
    assert "".join(event.get("text", "") for event in events) == "First second"
    messages = db.list_messages(session.conversation_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "First second"


def test_cancel_before_stream(tmp_path: Path):
    db, service, character, provider_row, created = setup(tmp_path)
    token = CancelToken()
    token.cancel(cancel_task=False)

    async def run():
        session = service.prepare(character_id=character["id"], text="Hello", cancel_token=token)
        return [event async for event in session.events()]

    events = asyncio.run(run())
    assert any(event["type"] == "cancelled" for event in events)
    assert len(db.list_messages(service.db.list_conversations(character["id"])[0]["id"])) == 1


def test_no_provider_raises(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    service = ChatService(db, FileSecretStore(tmp_path / "s.json"))
    character = db.create_character(
        {"name": "Aria", "model_path": "/models/Aria", "model_entry": "Aria.model3.json"}
    )
    try:
        service.prepare(character_id=character["id"], text="Hello")
    except ChatError as exc:
        assert exc.code == "no_provider"
        assert exc.status == 409
    else:
        raise AssertionError("expected no_provider")
