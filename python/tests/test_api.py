from __future__ import annotations

import json
import stat
from pathlib import Path

from fastapi.testclient import TestClient

from ailune.service.secrets import FileSecretStore


def create_character(client: TestClient, headers: dict, tmp_path: Path) -> dict:
    response = client.post(
        "/api/v1/characters",
        headers=headers,
        json={
            "name": "Aria",
            "model_path": str(tmp_path / "Aria"),
            "model_entry": "Aria.model3.json",
            "reply_language": "auto",
            "scale": 1.0,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_provider(client: TestClient, headers: dict, key: str = "sk-test-secret") -> dict:
    response = client.post(
        "/api/v1/providers",
        headers=headers,
        json={
            "display_name": "Fake",
            "provider_type": "custom",
            "base_url": "https://example.test/v1",
            "model_name": "fake-model",
            "api_key": key,
            "temperature": 0.7,
            "max_tokens": 128,
            "timeout_seconds": 20,
            "is_default": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_requires_auth(client: TestClient):
    assert client.get("/api/v1/health").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/health", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_personality_and_character_crud(client: TestClient, headers: dict, tmp_path: Path):
    personality = client.post(
        "/api/v1/personalities", headers=headers, json={"name": "Yuki", "system_prompt": "Calm."}
    )
    assert personality.status_code == 201
    personality_id = personality.json()["id"]
    character = create_character(client, headers, tmp_path)
    updated = client.patch(
        f"/api/v1/characters/{character['id']}",
        headers=headers,
        json={"name": "Aria 2", "personality_id": personality_id},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Aria 2"
    assert updated.json()["personality_id"] == personality_id
    assert client.get("/api/v1/characters", headers=headers).json()[0]["name"] == "Aria 2"
    assert client.delete(f"/api/v1/characters/{character['id']}", headers=headers).status_code == 204
    assert client.get("/api/v1/characters", headers=headers).json() == []


def test_provider_secrets_are_write_only(client: TestClient, headers: dict, settings):
    provider = create_provider(client, headers)
    assert provider["has_api_key"] is True
    assert "secret_ref" not in provider
    listed = client.get("/api/v1/providers", headers=headers).json()
    assert listed[0]["has_api_key"] is True
    assert "sk-test-secret" not in json.dumps(listed)
    store = FileSecretStore(settings.secrets_path)
    assert store.get(provider["secret_ref"] if "secret_ref" in provider else f"provider:{provider['id']}") == "sk-test-secret"
    assert stat.S_IMODE(settings.secrets_path.stat().st_mode) == 0o600

    updated = client.patch(
        f"/api/v1/providers/{provider['id']}",
        headers=headers,
        json={"display_name": "Renamed"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Renamed"
    assert updated.json()["has_api_key"] is True

    cleared = client.patch(
        f"/api/v1/providers/{provider['id']}",
        headers=headers,
        json={"api_key": ""},
    )
    assert cleared.json()["has_api_key"] is False
    assert store.get(f"provider:{provider['id']}") is None

    assert client.delete(f"/api/v1/providers/{provider['id']}", headers=headers).status_code == 204
    assert client.get("/api/v1/providers", headers=headers).json() == []


def test_provider_test_endpoint(client: TestClient, headers: dict):
    response = client.post(
        "/api/v1/providers/test",
        headers=headers,
        json={
            "provider_type": "custom",
            "base_url": "https://example.test/v1",
            "model_name": "fake-model",
            "api_key": "sk-test",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["models"] == ["fake-model"]


def test_validation_errors_are_safe(client: TestClient, headers: dict):
    response = client.post(
        "/api/v1/providers",
        headers=headers,
        json={"display_name": "x", "provider_type": "custom", "base_url": "", "model_name": "m"},
    )
    assert response.status_code == 422
    assert "sk-" not in response.text
    assert client.post(
        "/api/v1/characters",
        headers=headers,
        json={"name": "x", "model_path": "relative", "model_entry": "a.model3.json"},
    ).status_code == 422


def test_chat_stream_and_persistence(client: TestClient, headers: dict, tmp_path: Path):
    create_provider(client, headers)
    character = create_character(client, headers, tmp_path)
    payload = {"character_id": character["id"], "message": "Hello"}
    with client.stream("POST", "/api/v1/chat/stream", headers=headers, json=payload) as response:
        assert response.status_code == 200, response.text
        body = "".join(response.iter_text())
    assert "event: start" in body
    assert "event: delta" in body
    assert "event: done" in body
    assert "fake provider" in body

    conversations = client.get(
        f"/api/v1/conversations?character_id={character['id']}", headers=headers
    ).json()
    assert len(conversations) == 1
    messages = client.get(
        f"/api/v1/conversations/{conversations[0]['id']}/messages", headers=headers
    ).json()
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert "fake provider" in messages[1]["content"]


def test_memory_and_chat_prompt(client: TestClient, headers: dict, tmp_path: Path, fake_factory):
    create_provider(client, headers)
    character = create_character(client, headers, tmp_path)
    response = client.post(
        "/api/v1/memories",
        headers=headers,
        json={"character_id": character["id"], "content": "The user likes jasmine tea."},
    )
    assert response.status_code == 201
    memories = client.get(
        f"/api/v1/memories?character_id={character['id']}", headers=headers
    ).json()
    assert len(memories) == 1
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        headers=headers,
        json={"character_id": character["id"], "message": "What should I drink?"},
    ) as response:
        "".join(response.iter_text())
    assert fake_factory.created, "provider factory was not used"
    system = fake_factory.created[-1].last_messages[0]
    assert system.role == "system"
    assert "jasmine tea" in system.content


def test_chat_requires_provider_or_character(client: TestClient, headers: dict, tmp_path: Path):
    character = create_character(client, headers, tmp_path)
    response = client.post(
        "/api/v1/chat/stream", headers=headers, json={"character_id": character["id"], "message": "Hi"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_provider"
    create_provider(client, headers)
    assert client.post(
        "/api/v1/chat/stream", headers=headers, json={"character_id": "missing", "message": "Hi"}
    ).status_code == 404


def test_cancel_unknown_request(client: TestClient, headers: dict):
    response = client.post("/api/v1/chat/cancel/req_missing", headers=headers)
    assert response.status_code == 404


def test_meta_and_health(client: TestClient, headers: dict):
    health = client.get("/api/v1/health", headers=headers).json()
    assert health["ok"] is True
    assert health["secret_backend"] == "file"
    meta = client.get("/api/v1/meta", headers=headers).json()
    assert meta["capabilities"]["streaming_chat"] is True
    assert len(meta["provider_presets"]) >= 8
