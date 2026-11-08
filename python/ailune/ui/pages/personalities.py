"""Personality library page."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ailune.service.store import DEFAULT_PERSONALITY_ID
from ailune.ui.clients import AIServiceClient
from ailune.ui.i18n import tr
from ailune.ui.widgets import Card, PageHeader, run_async


class PersonalitiesPage(QWidget):
    def __init__(
        self,
        services: dict[str, Any],
        navigate: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ai: AIServiceClient = services["ai"]
        self.notify: Callable[[str, str], None] = services["notify"]
        self.navigate = navigate
        self._workers: list[Any] = []
        self.personalities: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.is_new = False
        self._loaded = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)
        self.header = PageHeader("personality.title", "personality.subtitle")
        self.refresh_button = QPushButton(tr("common.refresh"))
        self.refresh_button.clicked.connect(self._refresh)
        self.new_button = QPushButton(tr("personality.new"))
        self.new_button.setObjectName("Primary")
        self.new_button.clicked.connect(self._new)
        self.header.add_action(self.refresh_button)
        self.header.add_action(self.new_button)
        root.addWidget(self.header)

        content = QHBoxLayout()
        content.setSpacing(14)
        left = Card(margins=10)
        left.setFixedWidth(300)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selection_changed)
        self.empty_list = QLabel(tr("personality.empty"))
        self.empty_list.setObjectName("Muted")
        self.empty_list.setWordWrap(True)
        left.layout.addWidget(self.list, 1)
        left.layout.addWidget(self.empty_list)
        content.addWidget(left)

        self.detail = Card(margins=18)
        detail_layout = QVBoxLayout()
        self.detail.layout.addLayout(detail_layout)
        title_row = QHBoxLayout()
        self.detail_title = QLabel(tr("personality.title"))
        self.detail_title.setObjectName("SectionTitle")
        self.default_badge = QLabel(tr("personality.default_badge"))
        self.default_badge.setObjectName("StatusPill")
        self.default_badge.setProperty("online", "true")
        self.default_badge.setVisible(False)
        title_row.addWidget(self.detail_title)
        title_row.addWidget(self.default_badge)
        title_row.addStretch(1)
        detail_layout.addLayout(title_row)

        form = QFormLayout()
        form.setSpacing(9)
        self.name_label = QLabel(tr("personality.name"))
        self.name_label.setObjectName("Muted")
        self.name_edit = QLineEdit()
        form.addRow(self.name_label, self.name_edit)
        self.prompt_label = QLabel(tr("personality.system_prompt"))
        self.prompt_label.setObjectName("Muted")
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMinimumHeight(260)
        self.prompt_edit.setPlaceholderText(tr("personality.prompt_hint"))
        form.addRow(self.prompt_label, self.prompt_edit)
        detail_layout.addLayout(form)
        hint = QLabel(tr("personality.character_hint"))
        hint.setObjectName("Muted")
        detail_layout.addWidget(hint)
        detail_layout.addStretch(1)

        buttons = QHBoxLayout()
        self.save_button = QPushButton(tr("personality.save"))
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self._save)
        self.delete_button = QPushButton(tr("personality.delete"))
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_button)
        detail_layout.addLayout(buttons)

        content.addWidget(self.detail, 1)
        root.addLayout(content, 1)
        self._show_editor(False)

    def _show_editor(self, visible: bool) -> None:
        self.detail.setVisible(visible)

    def _refresh(self) -> None:
        self.refresh_button.setEnabled(False)

        def done(items: list[dict[str, Any]]) -> None:
            self.refresh_button.setEnabled(True)
            self.personalities = items
            self._fill_list(self.current.get("id") if self.current else None)
            self._loaded = True

        def fail(message: str) -> None:
            self.refresh_button.setEnabled(True)
            self.empty_list.setText(message)
            self.empty_list.setVisible(True)
            self.notify(message, "error")

        run_async(self, self.ai.list_personalities, done, fail)

    def _fill_list(self, preferred: str | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for personality in self.personalities:
            label = personality.get("name") or personality.get("id") or "—"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, personality.get("id"))
            if personality.get("id") == DEFAULT_PERSONALITY_ID:
                item.setText(f"{label}  ·  {tr('personality.default_badge')}")
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.empty_list.setVisible(not self.personalities)
        if self.personalities:
            index = 0
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == preferred:
                    index = i
                    break
            self.list.blockSignals(True)
            self.list.setCurrentRow(index)
            self.list.blockSignals(False)
            self._set_current(self.personalities[index])
        elif not self.is_new:
            self.current = None
            self._show_editor(False)

    def _selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        personality_id = current.data(Qt.ItemDataRole.UserRole)
        for personality in self.personalities:
            if personality.get("id") == personality_id:
                self.is_new = False
                self._set_current(personality)
                return

    def _set_current(self, personality: dict[str, Any]) -> None:
        self.is_new = False
        self.current = personality
        self._show_editor(True)
        self.name_edit.setText(personality.get("name") or "")
        self.prompt_edit.setPlainText(personality.get("system_prompt") or "")
        is_default = personality.get("id") == DEFAULT_PERSONALITY_ID
        self.default_badge.setVisible(is_default)
        self.delete_button.setEnabled(not is_default)
        self.delete_button.setToolTip(tr("personality.default_locked") if is_default else "")
        self.detail_title.setText(personality.get("name") or tr("personality.title"))

    def _new(self) -> None:
        self.is_new = True
        self.current = None
        self._show_editor(True)
        self.name_edit.clear()
        self.name_edit.setPlaceholderText(tr("personality.name"))
        self.prompt_edit.clear()
        self.default_badge.setVisible(False)
        self.delete_button.setEnabled(False)
        self.detail_title.setText(tr("personality.new"))
        self.name_edit.setFocus()

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        prompt = self.prompt_edit.toPlainText().strip()
        if not name:
            self.notify(tr("common.required"), "error")
            return
        if self.current and not self.is_new:
            personality_id = self.current["id"]
            work = lambda: self.ai.update_personality(personality_id, {"name": name, "system_prompt": prompt})
        else:
            work = lambda: self.ai.create_personality(name, prompt)
        self.save_button.setEnabled(False)

        def done(personality: dict[str, Any]) -> None:
            self.save_button.setEnabled(True)
            self.notify(tr("personality.saved"), "success")
            self.current = personality
            self.is_new = False
            self._refresh()

        def fail(message: str) -> None:
            self.save_button.setEnabled(True)
            self.notify(message, "error")

        run_async(self, work, done, fail)

    def _delete(self) -> None:
        if not self.current:
            return
        if self.current.get("id") == DEFAULT_PERSONALITY_ID:
            self.notify(tr("personality.default_locked"), "error")
            return
        answer = QMessageBox.question(
            self,
            tr("personality.delete_title"),
            tr("personality.delete_text", name=self.current.get("name") or ""),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        personality_id = self.current["id"]

        def done(_result: Any) -> None:
            self.notify(tr("personality.deleted"), "success")
            self.current = None
            self._refresh()

        run_async(self, lambda: self.ai.delete_personality(personality_id), done, lambda m: self.notify(m, "error"))

    def on_show(self) -> None:
        if not self._loaded or not self._workers:
            self._refresh()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.refresh_button.setText(tr("common.refresh"))
        self.new_button.setText(tr("personality.new"))
        self.name_label.setText(tr("personality.name"))
        self.prompt_label.setText(tr("personality.system_prompt"))
        self.prompt_edit.setPlaceholderText(tr("personality.prompt_hint"))
        self.save_button.setText(tr("personality.save"))
        self.delete_button.setText(tr("personality.delete"))
        self.default_badge.setText(tr("personality.default_badge"))
        if self.current:
            self.detail_title.setText(self.current.get("name") or tr("personality.title"))
        self._fill_list(self.current.get("id") if self.current else None)
