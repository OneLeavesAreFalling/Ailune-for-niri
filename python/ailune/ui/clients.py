"""Thin HTTP clients for the Go core and the Python AI service."""

from __future__ import annotations

from typing import Any

import httpx

from ailune.common.paths import ai_url, core_url, load_token
from ailune.ui.i18n import tr


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, ApiError):
        key = f"errors.{exc.code}"
        if tr(key) != key:
            return tr(key)
        return tr("errors.generic", message=exc.message)
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return tr("errors.network")
    if isinstance(exc, httpx.HTTPError):
        return tr("errors.network")
    return tr("errors.generic", message=str(exc) or tr("common.error"))


def _parse_error(response: httpx.Response) -> ApiError:
    try:
        data = response.json()
    except Exception:
        data = {}
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return ApiError(
            str(error.get("code") or "http_error"),
            str(error.get("message") or tr("errors.api")),
            response.status_code,
        )
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, list):
        detail = "; ".join(str(item) for item in detail)
    return ApiError("http_error", str(detail or tr("errors.api")), response.status_code)


class _BaseClient:
    def __init__(self, base_url: str, token: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        auth: bool = True,
    ) -> Any:
        headers = self.headers() if auth else {}
        try:
            with httpx.Client(timeout=timeout or self.timeout, follow_redirects=False) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise ApiError("network", tr("errors.network")) from exc
        if response.status_code >= 400:
            raise _parse_error(response)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("bad_response", tr("errors.bad_response")) from exc


class ControlClient(_BaseClient):
    def __init__(self) -> None:
        super().__init__(core_url(), load_token(), timeout=5.0)

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/health", auth=False, timeout=3.0)

    def state(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/state")

    def patch_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", "/api/v1/state", json=payload)

    def info(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/info", timeout=7.0)

    def action(self, name: str) -> dict[str, Any]:
        return self.request("POST", f"/api/v1/actions/{name}")

    def pet_command(self, command: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v1/pet/commands", json=command, timeout=3.0)


class AIServiceClient(_BaseClient):
    def __init__(self) -> None:
        super().__init__(ai_url(), load_token(), timeout=8.0)

    # ------------------------------------------------------------------ health

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/health", timeout=4.0)

    def meta(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/meta", timeout=5.0)

    # ------------------------------------------------------------------ personalities

    def list_personalities(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v1/personalities") or []

    def create_personality(self, name: str, system_prompt: str) -> dict[str, Any]:
        return self.request(
            "POST", "/api/v1/personalities", json={"name": name, "system_prompt": system_prompt}
        )

    def update_personality(self, personality_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", f"/api/v1/personalities/{personality_id}", json=payload)

    def delete_personality(self, personality_id: str) -> None:
        self.request("DELETE", f"/api/v1/personalities/{personality_id}")

    # ------------------------------------------------------------------ characters

    def list_characters(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v1/characters") or []

    def create_character(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v1/characters", json=payload)

    def update_character(self, character_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", f"/api/v1/characters/{character_id}", json=payload)

    def delete_character(self, character_id: str) -> None:
        self.request("DELETE", f"/api/v1/characters/{character_id}")

    # ------------------------------------------------------------------ providers

    def list_providers(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v1/providers") or []

    def create_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v1/providers", json=payload)

    def update_provider(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", f"/api/v1/providers/{provider_id}", json=payload)

    def delete_provider(self, provider_id: str) -> None:
        self.request("DELETE", f"/api/v1/providers/{provider_id}")

    def test_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v1/providers/test", json=payload, timeout=30.0)

    def provider_models(self, provider_id: str) -> list[str]:
        data = self.request("GET", f"/api/v1/providers/{provider_id}/models", timeout=20.0) or {}
        return list(data.get("models") or [])

    # ------------------------------------------------------------------ conversations

    def list_conversations(self, character_id: str) -> list[dict[str, Any]]:
        return self.request(
            "GET", "/api/v1/conversations", params={"character_id": character_id}
        ) or []

    def list_messages(self, conversation_id: str, limit: int = 300) -> list[dict[str, Any]]:
        return self.request(
            "GET",
            f"/api/v1/conversations/{conversation_id}/messages",
            params={"limit": limit},
        ) or []

    def delete_conversation(self, conversation_id: str) -> None:
        self.request("DELETE", f"/api/v1/conversations/{conversation_id}")

    def cancel_chat(self, request_id: str) -> None:
        self.request("POST", f"/api/v1/chat/cancel/{request_id}", timeout=3.0)

    # ------------------------------------------------------------------ memory

    def list_memories(self, character_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.request(
            "GET", "/api/v1/memories", params={"character_id": character_id, "limit": limit}
        ) or []

    def create_memory(self, character_id: str, content: str) -> dict[str, Any]:
        return self.request(
            "POST", "/api/v1/memories", json={"character_id": character_id, "content": content}
        )

    def delete_memory(self, memory_id: str, character_id: str) -> None:
        self.request(
            "DELETE", f"/api/v1/memories/{memory_id}", params={"character_id": character_id}
        )

    # ------------------------------------------------------------------ chat

    @property
    def stream_url(self) -> str:
        return f"{self.base_url}/api/v1/chat/stream"
