"""Memory notes per character."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ailune.ui.clients import AIServiceClient, ControlClient
from ailune.ui.i18n import tr
from ailune.ui.widgets import Card, PageHeader, run_async


class MemoryPage(QWidget):
    def __init__(
        self,
        services: dict[str, Any],
        navigate: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ai: AIServiceClient = services["ai"]
        self.control: ControlClient = services["control"]
        self.notify: Callable[[str, str], None] = services["notify"]
        self.navigate = navigate
        self._workers: list[Any] = []
        self.characters: list[dict[str, Any]] = []
        self.memories: list[dict[str, Any]] = []
        self.current_character: dict[str, Any] | None = None
        self._loaded = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)
        self.header = PageHeader("memory.title", "memory.subtitle")
        self.refresh_button = QPushButton(tr("common.refresh"))
        self.refresh_button.clicked.connect(self._refresh)
        self.header.add_action(self.refresh_button)
        root.addWidget(self.header)

        selector = Card(margins=14)
        row = QHBoxLayout()
        selector.layout.addLayout(row)
        self.character_label = QLabel(tr("memory.character"))
        self.character_label.setObjectName("Muted")
        self.character_combo = QComboBox()
        self.character_combo.setMinimumWidth(240)
        self.character_combo.currentIndexChanged.connect(self._character_changed)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        row.addWidget(self.character_label)
        row.addWidget(self.character_combo)
        row.addStretch(1)
        row.addWidget(self.count_label)
        root.addWidget(selector)

        add_card = Card(margins=14)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(tr("memory.add_hint"))
        self.input.setFixedHeight(72)
        add_row = QHBoxLayout()
        self.add_button = QPushButton(tr("memory.add"))
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self._add)
        add_row.addWidget(self.input, 1)
        add_row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignBottom)
        add_card.layout.addLayout(add_row)
        root.addWidget(add_card)

        list_card = Card(margins=12)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda _item: self._delete())
        list_card.layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.note = QLabel(tr("memory.note"))
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        self.delete_button = QPushButton(tr("memory.delete"))
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete)
        buttons.addWidget(self.note, 1)
        buttons.addWidget(self.delete_button)
        list_card.layout.addLayout(buttons)
        root.addWidget(list_card, 1)
        self.empty = QLabel(tr("memory.empty"))
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        list_card.layout.insertWidget(0, self.empty)

    def _refresh(self) -> None:
        self.refresh_button.setEnabled(False)

        def work() -> dict[str, Any]:
            state = self.control.state()
            return {"characters": self.ai.list_characters(), "state": state}

        def done(data: dict[str, Any]) -> None:
            self.refresh_button.setEnabled(True)
            self.characters = data["characters"]
            active = (data["state"] or {}).get("active_character") or {}
            previous = (self.current_character or {}).get("id") or active.get("id")
            self.character_combo.blockSignals(True)
            self.character_combo.clear()
            for character in self.characters:
                self.character_combo.addItem(character.get("name") or "—", character.get("id"))
            index = 0
            for i in range(self.character_combo.count()):
                if self.character_combo.itemData(i) == previous:
                    index = i
                    break
            if self.character_combo.count():
                self.character_combo.setCurrentIndex(index)
            self.character_combo.blockSignals(False)
            self._loaded = True
            self._character_changed(index if self.characters else -1)

        def fail(message: str) -> None:
            self.refresh_button.setEnabled(True)
            self.notify(message, "error")
            self.empty.setText(message)
            self.empty.setVisible(True)

        run_async(self, work, done, fail)

    def _character_changed(self, index: int) -> None:
        if 0 <= index < len(self.characters):
            self.current_character = self.characters[index]
            self._load_memories()
        else:
            self.current_character = None
            self.memories = []
            self._fill_list()
            self.count_label.setText("")

    def _load_memories(self) -> None:
        character = self.current_character
        if not character:
            return

        def work() -> list[dict[str, Any]]:
            return self.ai.list_memories(character["id"])

        def done(items: list[dict[str, Any]]) -> None:
            self.memories = items
            self._fill_list()

        run_async(self, work, done, lambda message: self.notify(message, "error"))

    def _fill_list(self) -> None:
        self.list.clear()
        for memory in self.memories:
            item = QListWidgetItem(memory.get("content") or "")
            item.setData(Qt.ItemDataRole.UserRole, memory.get("id"))
            item.setToolTip(memory.get("created_at") or "")
            self.list.addItem(item)
        self.empty.setVisible(not self.memories)
        self.list.setVisible(bool(self.memories))
        self.count_label.setText(tr("memory.count", count=len(self.memories)))

    def _add(self) -> None:
        if not self.current_character:
            return
        content = self.input.toPlainText().strip()
        if not content:
            return
        character_id = self.current_character["id"]

        def done(_result: Any) -> None:
            self.input.clear()
            self.notify(tr("memory.saved"), "success")
            self._load_memories()

        run_async(self, lambda: self.ai.create_memory(character_id, content), done, lambda m: self.notify(m, "error"))

    def _delete(self) -> None:
        item = self.list.currentItem()
        if item is None or not self.current_character:
            return
        memory_id = item.data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self,
            tr("memory.delete_title"),
            tr("memory.delete_text"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        character_id = self.current_character["id"]

        def done(_result: Any) -> None:
            self.notify(tr("memory.deleted"), "success")
            self._load_memories()

        run_async(
            self,
            lambda: self.ai.delete_memory(memory_id, character_id),
            done,
            lambda m: self.notify(m, "error"),
        )

    def on_show(self) -> None:
        if not self._loaded or not self._workers:
            self._refresh()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.refresh_button.setText(tr("common.refresh"))
        self.character_label.setText(tr("memory.character"))
        self.input.setPlaceholderText(tr("memory.add_hint"))
        self.add_button.setText(tr("memory.add"))
        self.delete_button.setText(tr("memory.delete"))
        self.note.setText(tr("memory.note"))
        self.empty.setText(tr("memory.empty"))
        self.count_label.setText(tr("memory.count", count=len(self.memories)))
