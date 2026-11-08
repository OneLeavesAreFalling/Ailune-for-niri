"""Small, dependency-free parsers for streaming provider responses."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx


async def iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Yield the payload of each Server-Sent Event ``data:`` field."""
    buffer: list[str] = []
    async for raw in response.aiter_lines():
        line = raw.rstrip("\r")
        if line == "":
            if buffer:
                yield "\n".join(buffer)
                buffer.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip(" "))
        # Other fields (event:, id:, retry:) are irrelevant for chat deltas.
    if buffer:
        yield "\n".join(buffer)


async def iter_ndjson(response: httpx.Response) -> AsyncIterator[dict]:
    """Yield JSON objects from a newline-delimited JSON stream (Ollama)."""
    async for line in response.aiter_lines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value
