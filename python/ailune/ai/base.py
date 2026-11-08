"""Abstract provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .types import ChatMessage, ProviderConfig, TestResult


class AIProvider(ABC):
    config: ProviderConfig

    @abstractmethod
    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield assistant text deltas. Raises ProviderError on failure."""
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self) -> TestResult:
        """Perform a cheap, non-generative connectivity check."""
        raise NotImplementedError

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return model identifiers advertised by the service."""
        raise NotImplementedError
