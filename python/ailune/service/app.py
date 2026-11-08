"""FastAPI application for Ailune's local AI service."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from ailune import __version__
from ailune.ai.registry import make_provider, normalize_provider_type, public_presets
from ailune.ai.types import ProviderConfig, ProviderError, normalize_base_url

from .api_models import (
    CharacterCreate,
    CharacterUpdate,
    ChatRequest,
    ConversationCreate,
    MemoryCreate,
    PersonalityCreate,
    PersonalityUpdate,
    ProviderCreate,
    ProviderTest,
    ProviderUpdate,
)
from .chat import CancelToken, ChatError, ChatService
from .secrets import SecretError, SecretStore, make_secret_store
from .settings import Settings
from .store import Database, DEFAULT_PERSONALITY_ID, new_id

logger = logging.getLogger("ailune.service")

ProviderFactory = Callable[[ProviderConfig], Any]


class CancelRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, CancelToken] = {}

    def add(self, request_id: str, token: CancelToken) -> None:
        with self._lock:
            self._tokens[request_id] = token

    def remove(self, request_id: str) -> None:
        with self._lock:
            self._tokens.pop(request_id, None)

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(request_id)
        if token is None:
            return False
        token.cancel()
        return True


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(settings: Settings | None = None, provider_factory: ProviderFactory | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.database_path)
    db.initialize()
    secret_store: SecretStore = make_secret_store(settings.secrets_path, settings.secret_backend)
    factory = provider_factory or (lambda config: make_provider(config))
    chat = ChatService(db, secret_store, provider_factory=factory)
    registry = CancelRegistry()

    app = FastAPI(
        title="Ailune AI Service",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.secrets = secret_store
    app.state.chat = chat
    app.state.registry = registry

    @app.exception_handler(ChatError)
    async def chat_error_handler(_request: Request, exc: ChatError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(ProviderError)
    async def provider_error_handler(_request: Request, exc: ProviderError) -> JSONResponse:
        return _error(502, exc.code, exc.message)

    @app.exception_handler(SecretError)
    async def secret_error_handler(_request: Request, exc: SecretError) -> JSONResponse:
        logger.warning("secret store failure: %s", exc)
        return _error(500, "secret_store_error", str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for error in exc.errors():
            location = ".".join(str(item) for item in error.get("loc", ()) if item != "body")
            parts.append(f"{location}: {error.get('msg', 'invalid value')}" if location else error.get("msg", "invalid value"))
        return _error(422, "validation_error", "; ".join(parts) or "invalid request")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "internal", "an unexpected error occurred")

    async def require_auth(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = request.app.state.settings.token
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        supplied = authorization.removeprefix("Bearer ").strip()
        if not expected or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid token")

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return _error(exc.status_code, "http_error", message)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    async def root() -> PlainTextResponse:
        return PlainTextResponse(f"Ailune AI service {__version__}\n")

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])

    # ------------------------------------------------------------------ health / meta

    @api.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "secret_backend": secret_store.backend_name,
            "stats": db.stats(),
        }

    @api.get("/meta")
    async def meta() -> dict[str, Any]:
        return {
            "version": __version__,
            "secret_backend": secret_store.backend_name,
            "provider_presets": public_presets(),
            "capabilities": {
                "live2d_runtime": False,
                "asr": False,
                "tts": False,
                "streaming_chat": True,
            },
            "stats": db.stats(),
        }

    # ------------------------------------------------------------------ personalities

    @api.get("/personalities")
    async def list_personalities() -> list[dict[str, Any]]:
        return db.list_personalities()

    @api.post("/personalities", status_code=201)
    async def create_personality(body: PersonalityCreate) -> dict[str, Any]:
        return db.create_personality(body.name.strip(), body.system_prompt)

    @api.patch("/personalities/{personality_id}")
    async def update_personality(personality_id: str, body: PersonalityUpdate) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True, exclude_none=True)
        if "name" in fields:
            fields["name"] = fields["name"].strip()
        updated = db.update_personality(personality_id, fields)
        if updated is None:
            raise ChatError("not_found", "personality not found", 404)
        return updated

    @api.delete("/personalities/{personality_id}", status_code=204)
    async def delete_personality(personality_id: str) -> None:
        if personality_id == DEFAULT_PERSONALITY_ID:
            raise ChatError("protected", "the default personality cannot be deleted", 409)
        if not db.delete_personality(personality_id):
            raise ChatError("not_found", "personality not found", 404)

    # ------------------------------------------------------------------ characters

    def check_personality(personality_id: str | None) -> None:
        if personality_id and db.get_personality(personality_id) is None:
            raise ChatError("personality_not_found", "personality not found", 404)

    @api.get("/characters")
    async def list_characters() -> list[dict[str, Any]]:
        return db.list_characters()

    @api.post("/characters", status_code=201)
    async def create_character(body: CharacterCreate) -> dict[str, Any]:
        check_personality(body.personality_id)
        return db.create_character(body.model_dump())

    @api.get("/characters/{character_id}")
    async def get_character(character_id: str) -> dict[str, Any]:
        character = db.get_character(character_id)
        if character is None:
            raise ChatError("not_found", "character not found", 404)
        return character

    @api.patch("/characters/{character_id}")
    async def update_character(character_id: str, body: CharacterUpdate) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        for required in ("name", "model_path", "model_entry", "reply_language", "scale"):
            if fields.get(required) is None:
                fields.pop(required, None)
        if "personality_id" in fields:
            check_personality(fields["personality_id"])
        if "name" in fields and fields["name"] is not None:
            fields["name"] = fields["name"].strip()
        updated = db.update_character(character_id, fields)
        if updated is None:
            raise ChatError("not_found", "character not found", 404)
        return updated

    @api.delete("/characters/{character_id}", status_code=204)
    async def delete_character(character_id: str) -> None:
        if not db.delete_character(character_id):
            raise ChatError("not_found", "character not found", 404)

    # ------------------------------------------------------------------ providers

    def public_provider(row: dict[str, Any]) -> dict[str, Any]:
        value = {k: row[k] for k in (
            "id",
            "display_name",
            "provider_type",
            "base_url",
            "model_name",
            "temperature",
            "max_tokens",
            "timeout_seconds",
            "extra_params",
            "is_default",
            "created_at",
            "updated_at",
        )}
        ref = row.get("secret_ref") or ""
        value["has_api_key"] = bool(ref and secret_store.get(ref))
        return value

    def validate_provider_fields(provider_type: str, base_url: str) -> tuple[str, str]:
        try:
            canonical = normalize_provider_type(provider_type)
            normalized_url = normalize_base_url(base_url)
        except ProviderError as exc:
            raise ChatError("invalid_config", exc.message, 400) from exc
        return canonical, normalized_url

    @api.get("/providers")
    async def list_providers() -> list[dict[str, Any]]:
        return [public_provider(row) for row in db.list_providers()]

    @api.post("/providers", status_code=201)
    async def create_provider(body: ProviderCreate) -> dict[str, Any]:
        provider_type, base_url = validate_provider_fields(body.provider_type, body.base_url)
        provider_id = new_id("prov")
        secret_ref = f"provider:{provider_id}"
        api_key = (body.api_key or "").strip()
        if api_key:
            secret_store.set(secret_ref, api_key)
        data = body.model_dump(exclude={"api_key"})
        data["provider_type"] = provider_type
        data["base_url"] = base_url
        try:
            row = db.create_provider(data, secret_ref, provider_id=provider_id)
        except Exception:
            if api_key:
                secret_store.delete(secret_ref)
            raise
        return public_provider(row)

    @api.patch("/providers/{provider_id}")
    async def update_provider(provider_id: str, body: ProviderUpdate) -> dict[str, Any]:
        existing = db.get_provider(provider_id)
        if existing is None:
            raise ChatError("not_found", "provider not found", 404)
        fields = body.model_dump(exclude_unset=True, exclude={"api_key"})
        for required in ("display_name", "provider_type", "base_url", "model_name", "temperature", "timeout_seconds"):
            if fields.get(required) is None:
                fields.pop(required, None)
        if "provider_type" in fields and fields["provider_type"] is not None:
            try:
                fields["provider_type"] = normalize_provider_type(fields["provider_type"])
            except ProviderError as exc:
                raise ChatError("invalid_config", exc.message, 400) from exc
        if "base_url" in fields and fields["base_url"] is not None:
            try:
                fields["base_url"] = normalize_base_url(fields["base_url"])
            except ProviderError as exc:
                raise ChatError("invalid_config", exc.message, 400) from exc
        if body.api_key is not None:
            ref = existing.get("secret_ref") or f"provider:{provider_id}"
            key = body.api_key.strip()
            if key:
                secret_store.set(ref, key)
            else:
                secret_store.delete(ref)
        updated = db.update_provider(provider_id, fields)
        if updated is None:
            raise ChatError("not_found", "provider not found", 404)
        return public_provider(updated)

    @api.delete("/providers/{provider_id}", status_code=204)
    async def delete_provider(provider_id: str) -> None:
        row = db.get_provider(provider_id)
        if row is None:
            raise ChatError("not_found", "provider not found", 404)
        ref = row.get("secret_ref")
        if ref:
            secret_store.delete(ref)
        db.delete_provider(provider_id)

    def config_for_test(body: ProviderTest) -> ProviderConfig:
        provider_type, base_url = validate_provider_fields(body.provider_type, body.base_url)
        api_key = body.api_key
        if api_key is None and body.provider_id:
            saved = db.get_provider(body.provider_id)
            if saved and saved.get("secret_ref"):
                api_key = secret_store.get(saved["secret_ref"])
        return ProviderConfig(
            id=body.provider_id or "test",
            display_name=body.display_name,
            provider_type=provider_type,
            base_url=base_url,
            model_name=body.model_name or "test",
            api_key=(api_key or "").strip() or None,
            timeout_seconds=body.timeout_seconds,
            extra_params=body.extra_params,
        )

    @api.post("/providers/test")
    async def test_provider(body: ProviderTest) -> dict[str, Any]:
        config = config_for_test(body)
        try:
            impl = factory(config)
            result = await impl.test_connection()
        except ProviderError as exc:
            raise ChatError("provider_test_failed", exc.message, 502) from exc
        return {
            "ok": result.ok,
            "message": result.message,
            "latency_ms": result.latency_ms,
            "models": result.models,
        }

    @api.get("/providers/{provider_id}/models")
    async def provider_models(provider_id: str) -> dict[str, Any]:
        row = db.get_provider(provider_id)
        if row is None:
            raise ChatError("not_found", "provider not found", 404)
        try:
            impl = factory(chat.provider_config(row))
            models = await impl.list_models()
        except ProviderError as exc:
            raise ChatError("provider_error", exc.message, 502) from exc
        return {"models": models}

    # ------------------------------------------------------------------ conversations

    @api.get("/conversations")
    async def list_conversations(character_id: str | None = None) -> list[dict[str, Any]]:
        return db.list_conversations(character_id)

    @api.post("/conversations", status_code=201)
    async def create_conversation(body: ConversationCreate) -> dict[str, Any]:
        if db.get_character(body.character_id) is None:
            raise ChatError("not_found", "character not found", 404)
        return db.create_conversation(body.character_id, body.title)

    @api.get("/conversations/{conversation_id}/messages")
    async def list_messages(conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
        if db.get_conversation(conversation_id) is None:
            raise ChatError("not_found", "conversation not found", 404)
        return db.list_messages(conversation_id, limit=limit)

    @api.delete("/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(conversation_id: str) -> None:
        if not db.delete_conversation(conversation_id):
            raise ChatError("not_found", "conversation not found", 404)

    # ------------------------------------------------------------------ memory

    @api.get("/memories")
    async def list_memories(character_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if db.get_character(character_id) is None:
            raise ChatError("not_found", "character not found", 404)
        return db.list_memories(character_id, limit=limit)

    @api.post("/memories", status_code=201)
    async def create_memory(body: MemoryCreate) -> dict[str, Any]:
        if db.get_character(body.character_id) is None:
            raise ChatError("not_found", "character not found", 404)
        return db.add_memory(body.character_id, body.content.strip())

    @api.delete("/memories/{memory_id}", status_code=204)
    async def delete_memory(memory_id: str, character_id: str | None = None) -> None:
        if not db.delete_memory(memory_id, character_id):
            raise ChatError("not_found", "memory not found", 404)

    # ------------------------------------------------------------------ chat

    @api.post("/chat/stream")
    async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
        token = CancelToken()
        request_id = (body.request_id or "").strip() or new_id("req")
        registry.add(request_id, token)
        try:
            session = chat.prepare(
                character_id=body.character_id,
                text=body.message,
                conversation_id=body.conversation_id,
                provider_id=body.provider_id,
                cancel_token=token,
            )
        except Exception:
            registry.remove(request_id)
            raise

        async def event_stream() -> AsyncIterator[str]:
            token.bind(asyncio.current_task())
            agen = session.events()
            try:
                async for event in agen:
                    event["request_id"] = request_id
                    if await request.is_disconnected():
                        token.cancel(cancel_task=False)
                        break
                    yield _sse(event.get("type", "message"), event)
            finally:
                token.cancel(cancel_task=False)
                await agen.aclose()
                token.unbind()
                registry.remove(request_id)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @api.post("/chat/cancel/{request_id}")
    async def cancel_chat(request_id: str) -> dict[str, Any]:
        if not registry.cancel(request_id):
            raise ChatError("not_found", "no active request with that id", 404)
        return {"ok": True}

    app.include_router(api)

    logger.info(
        "AI service initialised: db=%s secrets=%s providers=%d",
        settings.database_path,
        secret_store.backend_name,
        db.count_providers(),
    )
    return app


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n"


