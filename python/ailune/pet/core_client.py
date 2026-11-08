"""Authenticated client for the Go core's control API."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger("ailune.pet.core")

EventHandler = Callable[[str, Any], None]


class CoreClient:
    def __init__(self, base_url: str, token: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def get_state(self) -> dict[str, Any] | None:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/api/v1/state", headers=self._headers())
            if response.status_code != 200:
                logger.warning("core state returned HTTP %s", response.status_code)
                return None
            value = response.json()
            return value if isinstance(value, dict) else None
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.debug("core is not reachable yet: %s", exc)
            return None

    def patch_state(self, payload: dict[str, Any]) -> bool:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.patch(
                    f"{self.base_url}/api/v1/state",
                    headers=self._headers(),
                    json=payload,
                )
            if response.status_code >= 400:
                logger.warning("core state patch failed: HTTP %s", response.status_code)
                return False
            return True
        except httpx.HTTPError as exc:
            logger.debug("could not persist pet state: %s", exc)
            return False

    def action(self, name: str) -> bool:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/v1/actions/{name}",
                    headers=self._headers(),
                )
            if response.status_code >= 400:
                logger.warning("core action %s failed: HTTP %s", name, response.status_code)
                return False
            return True
        except httpx.HTTPError as exc:
            logger.warning("core action %s failed: %s", name, exc)
            return False

    def post_command(self, command: dict[str, Any]) -> bool:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/v1/pet/commands",
                    headers=self._headers(),
                    json=command,
                )
            return response.status_code < 400
        except httpx.HTTPError:
            return False

    def listen(self, on_event: EventHandler, stop: threading.Event) -> None:
        """Consume the core SSE stream until ``stop`` is set, reconnecting."""
        delay = 1.0
        while not stop.is_set():
            try:
                timeout = httpx.Timeout(self.timeout, read=None)
                with httpx.Client(timeout=timeout) as client:
                    with client.stream(
                        "GET",
                        f"{self.base_url}/api/v1/events",
                        headers=self._headers(),
                    ) as response:
                        if response.status_code != 200:
                            logger.warning("core event stream returned HTTP %s", response.status_code)
                            raise httpx.HTTPError("unexpected event stream status")
                        delay = 1.0
                        event_type = "message"
                        data_lines: list[str] = []
                        for line in response.iter_lines():
                            if stop.is_set():
                                return
                            if line == "":
                                if data_lines:
                                    self._dispatch(on_event, event_type, "\n".join(data_lines))
                                event_type = "message"
                                data_lines = []
                                continue
                            if line.startswith(":"):
                                continue
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].lstrip(" "))
            except (httpx.HTTPError, OSError) as exc:
                logger.debug("core event stream disconnected: %s", exc)
            except Exception:
                logger.exception("unexpected core event stream failure")
            if stop.wait(delay):
                return
            delay = min(delay * 2, 10.0)

    @staticmethod
    def _dispatch(on_event: EventHandler, event_type: str, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug("ignoring malformed core event")
            return
        try:
            on_event(event_type, data)
        except Exception:
            logger.exception("core event handler failed")


def wait_for_core(client: CoreClient, stop: threading.Event, timeout: float = 10.0) -> dict[str, Any] | None:
    """Poll briefly so a pet launched before the core settles still connects."""
    deadline = time.monotonic() + timeout
    while not stop.is_set() and time.monotonic() < deadline:
        state = client.get_state()
        if state is not None:
            return state
        if stop.wait(0.4):
            break
    return None
