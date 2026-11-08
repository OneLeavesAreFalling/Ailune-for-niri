"""Chat page with streaming replies and pet speech-bubble forwarding."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

import httpx
from PyQt6.QtCore import QEvent, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ailune.ui.clients import AIServiceClient, ControlClient, friendly_error
from ailune.ui.i18n import tr
from ailune.ui.widgets import EmptyState, MessageBubble, PageHeader, run_async


class ChatStreamWorker(QThread):
    started = pyqtSignal(dict)
    delta = pyqtSignal(str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(dict)
    cancelled = pyqtSignal()

    def __init__(
        self,
        client: AIServiceClient,
        payload: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.payload = payload
        self._cancel_requested = False
        self._response: httpx.Response | None = None
        self.request_id: str | None = None

    def cancel(self) -> None:
        self._cancel_requested = True
        response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def run(self) -> None:
        headers = {**self.client.headers(), "Accept": "text/event-stream"}
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=False) as http:
                with http.stream(
                    "POST", self.client.stream_url, headers=headers, json=self.payload
                ) as response:
                    self._response = response
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", "replace")
                        self.failed.emit(self._error_from_body(body, response.status_code))
                        return
                    event_type = "message"
                    data_lines: list[str] = []
                    for line in response.iter_lines():
                        if self._cancel_requested:
                            self.cancelled.emit()
                            return
                        if line == "":
                            if data_lines:
                                self._dispatch(event_type, "\n".join(data_lines))
                            event_type = "message"
                            data_lines = []
                            continue
                        if line.startswith(":"):
                            continue
                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip(" "))
                    if self._cancel_requested:
                        self.cancelled.emit()
                    return
        except httpx.HTTPError as exc:
            if self._cancel_requested:
                self.cancelled.emit()
            else:
                self.failed.emit(
                    {
                        "code": "network",
                        "message": tr("chat.connection_lost"),
                        "detail": str(exc),
                    }
                )
        finally:
            self._response = None

    def _dispatch(self, event_type: str, data: str) -> None:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        request_id = payload.get("request_id")
        if isinstance(request_id, str):
            self.request_id = request_id
        if event_type == "start":
            self.started.emit(payload)
        elif event_type == "delta":
            self.delta.emit(str(payload.get("text") or ""))
        elif event_type == "done":
            self.done.emit(payload)
        elif event_type == "error":
            self.failed.emit(dict(payload.get("error") or {}))
        elif event_type == "cancelled":
            self.cancelled.emit()

    @staticmethod
    def _error_from_body(body: str, status: int) -> dict[str, Any]:
        try:
            data = json.loads(body)
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict):
                return error
        except json.JSONDecodeError:
            pass
        return {"code": "http_error", "message": f"HTTP {status}"}


class ChatPage(QWidget):
    def __init__(
        self,
        services: dict[str, Any],
        navigate: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.control: ControlClient = services["control"]
        self.ai: AIServiceClient = services["ai"]
        self.notify: Callable[[str, str], None] = services["notify"]
        self.navigate = navigate
        self._workers: list[Any] = []
        self.characters: list[dict[str, Any]] = []
        self.conversations: list[dict[str, Any]] = []
        self.providers: list[dict[str, Any]] = []
        self.current_character: dict[str, Any] | None = None
        self.current_conversation_id: str | None = None
        self.worker: ChatStreamWorker | None = None
        self.assistant_bubble: MessageBubble | None = None
        self.accumulated = ""
        self.request_id: str | None = None
        self.cancelling = False
        self._last_caption = 0.0
        self._loaded_once = False

        self._build()
        self._refresh()

    # ------------------------------------------------------------------ ui

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)

        self.header = PageHeader("chat.title", "chat.subtitle")
        self.refresh_button = QPushButton(tr("common.refresh"))
        self.refresh_button.clicked.connect(self._refresh)
        self.new_button = QPushButton(tr("chat.new_chat"))
        self.new_button.clicked.connect(self._new_chat)
        self.header.add_action(self.refresh_button)
        self.header.add_action(self.new_button)
        root.addWidget(self.header)

        controls = QFrame()
        controls.setObjectName("Card")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(14, 10, 14, 10)
        controls_layout.setSpacing(10)
        self.character_label = QLabel()
        self.character_label.setObjectName("Muted")
        self.character_combo = QComboBox()
        self.character_combo.setMinimumWidth(190)
        self.character_combo.currentIndexChanged.connect(self._character_changed)
        self.conversation_label = QLabel()
        self.conversation_label.setObjectName("Muted")
        self.conversation_combo = QComboBox()
        self.conversation_combo.setMinimumWidth(220)
        self.conversation_combo.currentIndexChanged.connect(self._conversation_changed)
        self.delete_chat_button = QPushButton("×")
        self.delete_chat_button.setObjectName("Ghost")
        self.delete_chat_button.setToolTip(tr("chat.delete_chat"))
        self.delete_chat_button.clicked.connect(self._delete_conversation)
        self.provider_label = QLabel()
        self.provider_label.setObjectName("Muted")
        self.character_label.setText(tr("chat.character") + ":")
        self.conversation_label.setText(tr("chat.conversation") + ":")
        controls_layout.addWidget(self.character_label)
        controls_layout.addWidget(self.character_combo)
        controls_layout.addSpacing(8)
        controls_layout.addWidget(self.conversation_label)
        controls_layout.addWidget(self.conversation_combo)
        controls_layout.addWidget(self.delete_chat_button)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.provider_label)
        root.addWidget(controls)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("ChatScroll")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.messages_host = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_host)
        self.messages_layout.setContentsMargins(2, 8, 2, 8)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch(1)
        self.scroll.setWidget(self.messages_host)
        root.addWidget(self.scroll, 1)

        self.empty = EmptyState("chat.empty_title", "chat.empty_hint", "chat.open_characters")
        self.empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._empty_target = "characters"
        self.empty.button.clicked.connect(self._empty_action)
        self.empty.layout().addWidget(self.empty.button, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty, 1)

        input_card = QFrame()
        input_card.setObjectName("Card")
        input_layout = QVBoxLayout(input_card)
        input_layout.setContentsMargins(12, 10, 12, 10)
        input_layout.setSpacing(8)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(tr("chat.input_hint"))
        self.input.setFixedHeight(82)
        self.input.installEventFilter(self)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        self.status_label.setMinimumWidth(160)
        self.send_button = QPushButton(tr("chat.send"))
        self.send_button.setObjectName("Primary")
        self.send_button.clicked.connect(self._send)
        self.stop_button = QPushButton(tr("chat.cancel"))
        self.stop_button.setObjectName("Danger")
        self.stop_button.setVisible(False)
        self.stop_button.clicked.connect(self._stop)
        row = QHBoxLayout()
        row.addWidget(self.status_label, 1)
        row.addWidget(self.stop_button)
        row.addWidget(self.send_button)
        input_layout.addWidget(self.input)
        input_layout.addLayout(row)
        root.addWidget(input_card)
        self._show_empty_keys("chat.empty_title", "chat.empty_hint")

    def _empty_action(self) -> None:
        self.navigate(self._empty_target)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.input and event.type() == QEvent.Type.KeyPress:
            key = event  # type: ignore[assignment]
            if isinstance(key, QKeyEvent) and key.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not key.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self._send()
                    return True
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------ data

    def _refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self.status_label.setText(tr("common.loading"))

        def work() -> dict[str, Any]:
            state = self.control.state()
            characters = self.ai.list_characters()
            providers = self.ai.list_providers()
            return {"state": state, "characters": characters, "providers": providers}

        def done(data: dict[str, Any]) -> None:
            self.characters = data["characters"]
            self.providers = data["providers"]
            active = (data["state"] or {}).get("active_character") or {}
            self._fill_characters(active.get("id"))
            self._update_provider_label()
            self._show_empty_keys("chat.empty_title", "chat.empty_hint")
            self.refresh_button.setEnabled(True)
            self.status_label.setText("")
            if not self.characters:
                self._show_no_character()
            elif not self.providers:
                self._show_no_provider()
            elif self.current_conversation_id is None and not self._has_messages():
                self._show_empty_keys("chat.empty_title", "chat.empty_hint")
            self._loaded_once = True

        def fail(message: str) -> None:
            self.refresh_button.setEnabled(True)
            self.status_label.setText("")
            self._show_empty_keys("chat.no_provider_title", "chat.empty_hint")
            self._show_error(message)

        run_async(self, work, done, fail)

    def _fill_characters(self, preferred_id: str | None = None) -> None:
        previous = preferred_id or (self.current_character or {}).get("id")
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        for character in self.characters:
            self.character_combo.addItem(character.get("name") or character.get("id"), character.get("id"))
        if self.characters:
            index = 0
            if previous:
                for i in range(self.character_combo.count()):
                    if self.character_combo.itemData(i) == previous:
                        index = i
                        break
            self.character_combo.setCurrentIndex(index)
            self.current_character = self.characters[index]
        else:
            self.character_combo.addItem("—", None)
            self.current_character = None
        self.character_combo.setEnabled(bool(self.characters))
        self.character_combo.blockSignals(False)
        if self.current_character:
            self._load_conversations()

    def _character_changed(self, index: int) -> None:
        if 0 <= index < len(self.characters):
            self.current_character = self.characters[index]
            self.current_conversation_id = None
            self._clear_messages()
            self._load_conversations()
            self._update_header_state()

    def _load_conversations(self) -> None:
        character = self.current_character
        if not character:
            self._fill_conversations([])
            return

        def work() -> list[dict[str, Any]]:
            return self.ai.list_conversations(character["id"])

        def done(items: list[dict[str, Any]]) -> None:
            self.conversations = items
            self._fill_conversations(items)
            if items:
                self.conversation_combo.blockSignals(True)
                self.conversation_combo.setCurrentIndex(1)
                self.conversation_combo.blockSignals(False)
                self.current_conversation_id = items[0]["id"]
                self._load_messages(items[0]["id"])
            else:
                self.current_conversation_id = None
                self._clear_messages()
                self._show_empty_keys("chat.empty_title", "chat.empty_hint")
            self._update_header_state()

        run_async(self, work, done, self._show_error)

    def _fill_conversations(self, items: list[dict[str, Any]]) -> None:
        self.conversation_combo.blockSignals(True)
        self.conversation_combo.clear()
        self.conversation_combo.addItem(tr("chat.new_conversation"), None)
        for conversation in items:
            title = conversation.get("title") or tr("chat.conversation_untitled")
            self.conversation_combo.addItem(title, conversation["id"])
        if items:
            self.conversation_combo.setCurrentIndex(1)
        self.conversation_combo.blockSignals(False)

    def _conversation_changed(self, index: int) -> None:
        conversation_id = self.conversation_combo.itemData(index)
        if not conversation_id:
            self.current_conversation_id = None
            self._clear_messages()
            self._show_empty_keys("chat.empty_title", "chat.empty_hint")
            self._update_header_state()
            return
        self.current_conversation_id = str(conversation_id)
        self._load_messages(self.current_conversation_id)

    def _load_messages(self, conversation_id: str) -> None:
        self.status_label.setText(tr("chat.loading_history"))

        def work() -> list[dict[str, Any]]:
            return self.ai.list_messages(conversation_id)

        def done(messages: list[dict[str, Any]]) -> None:
            self._clear_messages()
            for message in messages:
                if message.get("role") in ("user", "assistant"):
                    self._add_bubble(
                        message["role"],
                        message.get("content") or "",
                        author=self._author_for(message["role"]),
                    )
            self.status_label.setText("")
            self._update_header_state()

        run_async(self, work, done, self._show_error)

    def _update_provider_label(self) -> None:
        if not self.providers:
            self.provider_label.setText(tr("chat.no_provider_title"))
            return
        default = next((p for p in self.providers if p.get("is_default")), self.providers[0])
        self.provider_label.setText(f"{tr('chat.default_provider')}: {default.get('display_name')} · {default.get('model_name')}")

    def _update_header_state(self) -> None:
        if not self.current_character:
            return
        self.header.subtitle.setText(
            tr("chat.current_character", name=self.current_character.get("name") or "")
        )
        self._update_provider_label()

    # ------------------------------------------------------------------ message rendering

    def _clear_messages(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.assistant_bubble = None
        self.accumulated = ""

    def _add_bubble(self, role: str, text: str, author: str = "") -> MessageBubble:
        bubble = MessageBubble(role, text, author=author)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
        wrapper = QWidget()
        wrapper.setLayout(row)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, wrapper)
        self.empty.setVisible(False)
        self.scroll.setVisible(True)
        self._scroll_to_bottom()
        return bubble

    def _show_empty_keys(self, title_key: str, hint_key: str) -> None:
        if self._has_messages():
            return
        self._empty_target = "characters"
        self.empty.set_keys(title_key, hint_key, "chat.open_characters")
        self.empty.setVisible(True)
        self.scroll.setVisible(False)

    def _show_no_character(self) -> None:
        self._empty_target = "characters"
        self.empty.set_keys("chat.no_character_title", "chat.no_character_hint", "chat.open_characters")
        self.empty.setVisible(True)
        self.scroll.setVisible(False)

    def _show_no_provider(self) -> None:
        self._empty_target = "providers"
        self.empty.set_keys("chat.no_provider_title", "chat.no_provider_hint", "chat.open_providers")
        self.empty.setVisible(True)
        self.scroll.setVisible(False)

    def _has_messages(self) -> bool:
        return self.messages_layout.count() > 1

    def _author_for(self, role: str) -> str:
        if role == "user":
            return tr("chat.you")
        if role == "assistant":
            return self.current_character.get("name") if self.current_character else tr("chat.assistant")
        return role

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))

    # ------------------------------------------------------------------ sending

    def _send(self) -> None:
        if self.worker is not None:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        if not self.current_character:
            self._show_no_character()
            return
        if not self.providers:
            self._show_no_provider()
            self.notify(tr("errors.no_provider"), "error")
            return
        self.input.clear()
        self._add_bubble("user", text, author=tr("chat.you"))
        self.assistant_bubble = self._add_bubble("assistant", "", author=self._author_for("assistant"))
        self.accumulated = ""
        self.assistant_bubble.set_text("…")
        self.status_label.setText(tr("chat.streaming"))
        self.send_button.setEnabled(False)
        self.stop_button.setVisible(True)
        self.cancelling = False
        self.request_id = None
        self._pet({"type": "speaking", "value": True})
        self._pet({"type": "expression", "name": "thinking"})

        payload: dict[str, Any] = {
            "character_id": self.current_character["id"],
            "message": text,
        }
        if self.current_conversation_id:
            payload["conversation_id"] = self.current_conversation_id

        worker = ChatStreamWorker(self.ai, payload, self)
        self.worker = worker
        worker.started.connect(self._on_started)
        worker.delta.connect(self._on_delta)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _on_started(self, payload: dict[str, Any]) -> None:
        conversation_id = payload.get("conversation_id")
        if isinstance(conversation_id, str) and conversation_id:
            self.current_conversation_id = conversation_id
            if self.conversation_combo.findData(conversation_id) < 0:
                self.conversation_combo.blockSignals(True)
                index = self.conversation_combo.count()
                self.conversation_combo.addItem(tr("chat.conversation_untitled"), conversation_id)
                self.conversation_combo.setCurrentIndex(index)
                self.conversation_combo.blockSignals(False)
        if self.worker is not None:
            self.request_id = self.worker.request_id

    def _on_delta(self, text: str) -> None:
        if not text or self.assistant_bubble is None:
            return
        self.accumulated += text
        self.assistant_bubble.set_text(self.accumulated)
        self._scroll_to_bottom()
        now = time.monotonic()
        if now - self._last_caption > 0.45:
            self._last_caption = now
            self._pet({"type": "caption", "text": self.accumulated[-600:], "sticky": True})

    def _on_done(self, payload: dict[str, Any]) -> None:
        message = payload.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and content:
            self.accumulated = content
        if self.assistant_bubble is not None:
            self.assistant_bubble.set_text(self.accumulated or "…")
        self._pet({"type": "speaking", "value": False})
        self._pet({"type": "caption", "text": self.accumulated[-600:], "sticky": False})
        self._pet({"type": "expression", "name": "happy"})
        self._pet({"type": "motion", "group": "happy", "index": 0})
        self.status_label.setText("")
        self._reload_conversation_titles()

    def _on_failed(self, error: dict[str, Any]) -> None:
        if self.cancelling:
            self._on_cancelled()
            return
        code = str(error.get("code") or "internal")
        message = str(error.get("message") or tr("chat.failed"))
        key = f"errors.{code}"
        friendly = tr(key) if tr(key) != key else message
        if self.assistant_bubble is not None:
            self.assistant_bubble.role = "error"
            self.assistant_bubble.setObjectName("ErrorBubble")
            self.assistant_bubble.style().unpolish(self.assistant_bubble)
            self.assistant_bubble.style().polish(self.assistant_bubble)
            self.assistant_bubble.set_text(f"{tr('chat.failed')}\n{friendly}")
        self.status_label.setText("")
        self._pet({"type": "speaking", "value": False})
        self._pet({"type": "expression", "name": "sad"})
        self.notify(friendly, "error")

    def _on_cancelled(self) -> None:
        if self.assistant_bubble is not None and not self.accumulated:
            self.assistant_bubble.set_text(tr("chat.cancelled"))
        self.status_label.setText(tr("chat.cancelled"))
        self._pet({"type": "speaking", "value": False})
        self._pet({"type": "expression", "name": "neutral"})

    def _on_worker_finished(self) -> None:
        worker = self.worker
        if worker is not None:
            worker.deleteLater()
        self.worker = None
        self.send_button.setEnabled(True)
        self.stop_button.setVisible(False)
        self.cancelling = False
        self.request_id = None
        self._pet({"type": "speaking", "value": False})

    def _stop(self) -> None:
        if self.worker is None:
            return
        self.cancelling = True
        self.status_label.setText(tr("chat.cancelled"))
        request_id = self.request_id
        self.worker.cancel()
        if request_id:
            run_async(self, lambda: self.ai.cancel_chat(request_id), on_error=lambda _m: None)

    def _new_chat(self) -> None:
        if self.worker is not None:
            self._stop()
        self.current_conversation_id = None
        self.conversation_combo.blockSignals(True)
        if self.conversation_combo.count() > 0:
            self.conversation_combo.setCurrentIndex(0)
        self.conversation_combo.blockSignals(False)
        self._clear_messages()
        self._show_empty_keys("chat.empty_title", "chat.empty_hint")

    def _delete_conversation(self) -> None:
        conversation_id = self.current_conversation_id
        if not conversation_id:
            return
        answer = QMessageBox.question(self, tr("chat.delete_chat"), tr("chat.delete_confirm"))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.conversation_combo.blockSignals(True)
        self.conversation_combo.setCurrentIndex(0)
        self.conversation_combo.blockSignals(False)
        self.current_conversation_id = None
        self._clear_messages()
        self._show_empty_keys("chat.empty_title", "chat.empty_hint")

        def done(_result: Any) -> None:
            self.notify(tr("common.deleted"), "success")
            self._load_conversations()

        run_async(self, lambda: self.ai.delete_conversation(conversation_id), done, self._show_error)

    def _reload_conversation_titles(self) -> None:
        if not self.current_character:
            return
        character_id = self.current_character["id"]
        run_async(self, lambda: self.ai.list_conversations(character_id), self._update_conversation_titles)

    def _update_conversation_titles(self, items: list[dict[str, Any]]) -> None:
        self.conversations = items
        current = self.current_conversation_id
        self.conversation_combo.blockSignals(True)
        self.conversation_combo.clear()
        self.conversation_combo.addItem(tr("chat.new_conversation"), None)
        for conversation in items:
            title = conversation.get("title") or tr("chat.conversation_untitled")
            self.conversation_combo.addItem(title, conversation["id"])
        if current:
            index = self.conversation_combo.findData(current)
            if index >= 0:
                self.conversation_combo.setCurrentIndex(index)
        self.conversation_combo.blockSignals(False)

    # ------------------------------------------------------------------ pet / errors

    def _pet(self, command: dict[str, Any]) -> None:
        def send() -> None:
            try:
                self.control.pet_command(command)
            except Exception:
                pass

        threading.Thread(target=send, daemon=True, name="ailune-pet-command").start()

    def _show_error(self, message: str) -> None:
        if not isinstance(message, str):
            message = friendly_error(message)
        self.notify(message, "error")

    def retranslate(self) -> None:
        self.header.retranslate()
        self.refresh_button.setText(tr("common.refresh"))
        self.new_button.setText(tr("chat.new_chat"))
        self.character_label.setText(tr("chat.character") + ":")
        self.conversation_label.setText(tr("chat.conversation") + ":")
        self.input.setPlaceholderText(tr("chat.input_hint"))
        self.send_button.setText(tr("chat.send"))
        self.stop_button.setText(tr("chat.cancel"))
        self.delete_chat_button.setToolTip(tr("chat.delete_chat"))
        self.empty.retranslate()
        for i in range(self.conversation_combo.count()):
            if self.conversation_combo.itemData(i) is None:
                self.conversation_combo.setItemText(i, tr("chat.new_conversation"))
        self._update_provider_label()
        self._update_header_state()
        # Update authors of existing bubbles without touching message content.
        for index in range(self.messages_layout.count() - 1):
            wrapper = self.messages_layout.itemAt(index).widget()
            if wrapper is None:
                continue
            layout = wrapper.layout()
            if layout is None:
                continue
            for j in range(layout.count()):
                widget = layout.itemAt(j).widget()
                if isinstance(widget, MessageBubble):
                    widget.set_author(self._author_for(widget.role))

    def on_show(self) -> None:
        if self.worker is None:
            self._refresh()
        self.input.setFocus()

    def on_hidden(self) -> None:
        if self.worker is not None:
            self._stop()
            self.worker.wait(2000)
