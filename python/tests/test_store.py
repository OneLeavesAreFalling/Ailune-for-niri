from __future__ import annotations

from pathlib import Path

from ailune.service.store import DEFAULT_PERSONALITY_ID, Database


def make_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.db")
    db.initialize()
    return db


def test_default_personality(tmp_path: Path):
    db = make_db(tmp_path)
    personalities = db.list_personalities()
    assert len(personalities) == 1
    assert personalities[0]["id"] == DEFAULT_PERSONALITY_ID
    assert db.delete_personality(DEFAULT_PERSONALITY_ID) is False


def test_character_conversation_and_memory_cascade(tmp_path: Path):
    db = make_db(tmp_path)
    character = db.create_character(
        {
            "name": "Aria",
            "model_path": "/models/Aria",
            "model_entry": "Aria.model3.json",
            "personality_id": DEFAULT_PERSONALITY_ID,
            "reply_language": "auto",
            "scale": 1.0,
        }
    )
    assert db.get_character(character["id"])["name"] == "Aria"
    conversation = db.create_conversation(character["id"])
    user = db.add_message(conversation["id"], "user", "Hello there")
    assert user["role"] == "user"
    assert db.get_conversation(conversation["id"])["title"] == "Hello there"
    db.add_message(conversation["id"], "assistant", "Hi!")
    messages = db.list_messages(conversation["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert [m["role"] for m in db.recent_messages(conversation["id"], 1)] == ["assistant"]
    memory = db.add_memory(character["id"], "Likes tea")
    assert db.list_memories(character["id"])[0]["content"] == "Likes tea"

    assert db.delete_character(character["id"]) is True
    assert db.get_conversation(conversation["id"]) is None
    assert db.list_messages(conversation["id"]) == []
    assert db.list_memories(character["id"]) == []
    assert db.delete_memory(memory["id"]) is False


def test_provider_default_and_secret_reference(tmp_path: Path):
    db = make_db(tmp_path)
    first = db.create_provider(
        {
            "display_name": "First",
            "provider_type": "custom",
            "base_url": "http://127.0.0.1:1/v1",
            "model_name": "a",
            "temperature": 0.5,
        },
        "provider:first",
        provider_id="prov_first",
    )
    assert first["is_default"] is True
    second = db.create_provider(
        {
            "display_name": "Second",
            "provider_type": "custom",
            "base_url": "http://127.0.0.1:2/v1",
            "model_name": "b",
            "is_default": True,
        },
        "provider:second",
        provider_id="prov_second",
    )
    assert second["is_default"] is True
    assert db.get_provider("prov_first")["is_default"] is False
    assert db.get_default_provider()["id"] == "prov_second"
    assert db.delete_provider("prov_second") is True
    remaining = db.get_default_provider()
    assert remaining is not None and remaining["id"] == "prov_first"
    assert remaining["secret_ref"] == "provider:first"


def test_extra_params_roundtrip(tmp_path: Path):
    db = make_db(tmp_path)
    row = db.create_provider(
        {
            "display_name": "Extra",
            "provider_type": "openai",
            "base_url": "https://example.test/v1",
            "model_name": "m",
            "extra_params": {"top_p": 0.3, "nested": {"a": 1}},
        },
        "provider:x",
    )
    assert row["extra_params"]["top_p"] == 0.3
    assert row["extra_params"]["nested"]["a"] == 1


def test_personality_update(tmp_path: Path):
    db = make_db(tmp_path)
    personality = db.create_personality("Yuki", "Calm and precise.")
    updated = db.update_personality(personality["id"], {"name": "Yuki 2", "system_prompt": "Still calm."})
    assert updated["name"] == "Yuki 2"
    assert updated["system_prompt"] == "Still calm."
    assert db.delete_personality(personality["id"]) is True
