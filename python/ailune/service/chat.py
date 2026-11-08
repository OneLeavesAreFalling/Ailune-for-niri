"""Chat orchestration: personality, memory, history and provider streaming."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from ailune.ai.base import AIProvider
from ailune.ai.registry import make_provider
from ailune.ai.types import ChatMessage, ProviderConfig, ProviderError

from .secrets import SecretStore
from .store import Database

logger = logging.getLogger(__name__)

MAX_USER_MESSAGE = 16_000
MAX_HISTORY = 24
MAX_MEMORIES = 20
MAX_REPLY_CHARS = 200_000


class ChatError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class CancelToken:
    """Cooperative cancellation for one streaming request.

    The HTTP layer binds the current task so a cancel request can interrupt a
    provider stream that is blocked waiting for the next chunk.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._task: asyncio.Task | None = None

    def bind(self, task: asyncio.Task | None) -> None:
        self._task = task

    def unbind(self) -> None:
        self._task = None

    def cancel(self, cancel_task: bool = True) -> None:
        self._event.set()
        if cancel_task and self._task is not None and not self._task.done():
            self._task.cancel()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class ChatSession:
    conversation_id: str
    character: dict[str, Any]
    provider: dict[str, Any]
    provider_config: ProviderConfig
    messages: list[ChatMessage]
    user_message: dict[str, Any]
    provider_impl: AIProvider
    cancel_token: CancelToken
    on_finish: Any | None = None

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        yield {
            "type": "start",
            "conversation_id": self.conversation_id,
            "user_message": self.user_message,
            "provider": {
                "id": self.provider["id"],
                "display_name": self.provider["display_name"],
                "model": self.provider["model_name"],
            },
        }
        chunks: list[str] = []
        total = 0
        try:
            async for delta in self.provider_impl.stream_chat(self.messages):
                if self.cancel_token.cancelled:
                    yield {"type": "cancelled"}
                    return
                if not delta:
                    continue
                total += len(delta)
                if total > MAX_REPLY_CHARS:
                    raise ProviderError("too_long", "the reply exceeded the maximum length")
                chunks.append(delta)
                yield {"type": "delta", "text": delta}
        except asyncio.CancelledError:
            logger.info("chat stream cancelled by client", extra={"provider": self.provider["id"]})
            raise
        except ProviderError as exc:
            logger.warning(
                "provider error",
                extra={"provider": self.provider["id"], "code": exc.code, "status": exc.status_code},
            )
            yield {"type": "error", "error": exc.to_dict()}
            return
        except Exception:
            logger.exception("unexpected chat failure", extra={"provider": self.provider["id"]})
            yield {
                "type": "error",
                "error": {"code": "internal", "message": "the chat request failed unexpectedly", "retryable": False},
            }
            return

        if self.cancel_token.cancelled:
            yield {"type": "cancelled"}
            return

        content = "".join(chunks).strip()
        if not content:
            yield {
                "type": "error",
                "error": {"code": "empty_reply", "message": "the provider returned an empty reply", "retryable": True},
            }
            return
        message = self.on_finish(self.conversation_id, content) if self.on_finish else None
        yield {"type": "done", "message": message}


class ChatService:
    def __init__(
        self,
        db: Database,
        secrets: SecretStore,
        provider_factory: Callable[[ProviderConfig], AIProvider] | None = None,
    ) -> None:
        self.db = db
        self.secrets = secrets
        self.provider_factory = provider_factory or make_provider

    def provider_config(self, row: dict[str, Any]) -> ProviderConfig:
        api_key = self.secrets.get(row["secret_ref"]) if row.get("secret_ref") else None
        return ProviderConfig(
            id=row["id"],
            display_name=row["display_name"],
            provider_type=row["provider_type"],
            base_url=row["base_url"],
            model_name=row["model_name"],
            api_key=api_key,
            temperature=float(row.get("temperature") if row.get("temperature") is not None else 0.8),
            max_tokens=row.get("max_tokens"),
            timeout_seconds=float(row.get("timeout_seconds") or 60),
            extra_params=row.get("extra_params") or {},
            is_default=bool(row.get("is_default")),
        )

    def _select_provider(self, provider_id: str | None) -> dict[str, Any]:
        row = self.db.get_provider(provider_id) if provider_id else self.db.get_default_provider()
        if row is None:
            raise ChatError(
                "no_provider",
                "No AI provider is configured. Add one in Settings → AI Providers.",
                409,
            )
        return row

    def prepare(
        self,
        *,
        character_id: str,
        text: str,
        conversation_id: str | None = None,
        provider_id: str | None = None,
        cancel_token: CancelToken | None = None,
    ) -> ChatSession:
        text = (text or "").strip()
        if not text:
            raise ChatError("empty_message", "message cannot be empty")
        if len(text) > MAX_USER_MESSAGE:
            raise ChatError("message_too_long", f"message cannot exceed {MAX_USER_MESSAGE} characters")

        character = self.db.get_character(character_id)
        if character is None:
            raise ChatError("character_not_found", "character not found", 404)
        provider = self._select_provider(provider_id)
        provider_config = self.provider_config(provider)
        provider_impl = self.provider_factory(provider_config)

        if conversation_id:
            conversation = self.db.get_conversation(conversation_id)
            if conversation is None:
                raise ChatError("conversation_not_found", "conversation not found", 404)
            if conversation["character_id"] != character_id:
                raise ChatError("conversation_mismatch", "conversation belongs to another character", 409)
        else:
            conversation = self.db.create_conversation(character_id)

        user_message = self.db.add_message(conversation["id"], "user", text)
        history = self.db.recent_messages(conversation["id"], limit=MAX_HISTORY)
        messages = self._build_messages(character, history)

        return ChatSession(
            conversation_id=conversation["id"],
            character=character,
            provider=provider,
            provider_config=provider_config,
            messages=messages,
            user_message=user_message,
            provider_impl=provider_impl,
            cancel_token=cancel_token or CancelToken(),
            on_finish=self._persist_reply,
        )

    def _build_messages(self, character: dict[str, Any], history: list[dict[str, Any]]) -> list[ChatMessage]:
        personality = None
        if character.get("personality_id"):
            personality = self.db.get_personality(character["personality_id"])
        memories = self.db.list_memories(character["id"], limit=MAX_MEMORIES)
        system = self._system_prompt(character, personality, memories)
        messages = [ChatMessage("system", system)]
        for item in history:
            if item["role"] in ("user", "assistant"):
                messages.append(ChatMessage(item["role"], item["content"]))
        return messages

    @staticmethod
    def _system_prompt(
        character: dict[str, Any],
        personality: dict[str, Any] | None,
        memories: list[dict[str, Any]],
    ) -> str:
        name = character.get("name") or "Ailune"
        persona = (personality or {}).get("system_prompt", "").strip()
        parts = [
            f"Your name is {name}. You are an AI desktop companion running inside Ailune on Linux.",
            persona or "Be warm, attentive and concise.",
            "Stay in character. Do not mention system prompts, providers or internal implementation details.",
        ]
        reply_language = character.get("reply_language") or "auto"
        if reply_language == "en":
            parts.append("Reply in English.")
        elif reply_language == "zh_CN":
            parts.append("Reply in Simplified Chinese (简体中文).")
        else:
            parts.append("Reply in the language the user writes in, unless they ask otherwise.")
        if memories:
            parts.append("Things you remember about this user and your shared history:")
            for memory in reversed(memories):
                content = (memory.get("content") or "").strip()
                if content:
                    parts.append(f"- {content[:800]}")
        return "\n\n".join(parts)

    def _persist_reply(self, conversation_id: str, content: str) -> dict[str, Any]:
        return self.db.add_message(conversation_id, "assistant", content)
