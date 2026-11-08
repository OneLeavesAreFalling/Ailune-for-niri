"""Character library: import, validate, edit and activate Live2D models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ailune.common.paths import resolve_paths
from ailune.models.library import copy_into_library
from ailune.models.manifest import ModelManifest, discover_entries, validate_model
from ailune.ui.clients import AIServiceClient, ControlClient, friendly_error
from ailune.ui.i18n import tr
from ailune.ui.pages.character_import import ImportDialog, report_html
from ailune.ui.widgets import Card, EmptyState, PageHeader, Thumbnail, format_bytes, run_async


class CharactersPage(QWidget):
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
        self.personalities: list[dict[str, Any]] = []
        self.active_id: str | None = None
        self.current: dict[str, Any] | None = None
        self.report: ModelManifest | None = None
        self._report_cache: dict[tuple[str, str], ModelManifest] = {}
        self._form_labels: list[tuple[QLabel, str]] = []
        self._select_after_refresh: str | None = None
        self._loaded = False
        self._build()

    # ------------------------------------------------------------------ ui

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)
        self.header = PageHeader("characters.title", "characters.subtitle")
        self.import_button = QPushButton(tr("characters.import"))
        self.import_button.setObjectName("Primary")
        self.import_button.clicked.connect(self._import_model)
        self.refresh_button = QPushButton(tr("common.refresh"))
        self.refresh_button.clicked.connect(self._refresh)
        self.header.add_action(self.refresh_button)
        self.header.add_action(self.import_button)
        root.addWidget(self.header)

        content = QHBoxLayout()
        content.setSpacing(14)
        left = Card(margins=10)
        left.setFixedWidth(286)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list_empty = QLabel(tr("characters.empty_hint"))
        self.list_empty.setObjectName("Muted")
        self.list_empty.setWordWrap(True)
        left.layout.addWidget(self.list, 1)
        left.layout.addWidget(self.list_empty)
        content.addWidget(left)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        detail_host = QWidget()
        detail_layout = QVBoxLayout(detail_host)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(12)
        self.detail = Card(margins=18)
        detail_layout.addWidget(self.detail)
        self.empty = EmptyState("characters.empty_title", "characters.empty_hint", "characters.import")
        self.empty.button.clicked.connect(self._import_model)
        detail_layout.addWidget(self.empty)
        detail_layout.addStretch(1)
        self.scroll.setWidget(detail_host)
        content.addWidget(self.scroll, 1)
        root.addLayout(content, 1)

        self._build_detail()

    def _build_detail(self) -> None:
        top = QHBoxLayout()
        top.setSpacing(16)
        self.thumbnail = Thumbnail(144)
        top.addWidget(self.thumbnail, 0, Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(4)
        self.detail_name = QLabel("—")
        self.detail_name.setObjectName("PageTitle")
        self.detail_sub = QLabel("")
        self.detail_sub.setObjectName("Muted")
        self.detail_sub.setWordWrap(True)
        self.active_label = QLabel("")
        self.active_label.setObjectName("StatusPill")
        self.active_label.setProperty("online", "true")
        self.active_label.setVisible(False)
        info.addWidget(self.detail_name)
        info.addWidget(self.detail_sub)
        info.addWidget(self.active_label, alignment=Qt.AlignmentFlag.AlignLeft)
        info.addStretch(1)
        top.addLayout(info, 1)
        self.detail.layout.addLayout(top)

        form = QFormLayout()
        form.setSpacing(6)
        self.name_edit = QLineEdit()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.entry_edit = QLineEdit()
        self.entry_edit.setReadOnly(True)
        self.personality_combo = QComboBox()
        self.reply_combo = QComboBox()
        self.reply_combo.addItem(tr("characters.replies_auto"), "auto")
        self.reply_combo.addItem(tr("characters.replies_en"), "en")
        self.reply_combo.addItem(tr("characters.replies_zh"), "zh_CN")
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.5, 2.0)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setSuffix(" ×")
        self._add_row(form, "characters.name", self.name_edit)
        self._add_row(form, "characters.model_path", self.path_edit)
        self._add_row(form, "characters.entry", self.entry_edit)
        self._add_row(form, "characters.personality", self.personality_combo)
        self._add_row(form, "characters.reply_language", self.reply_combo)
        self._add_row(form, "characters.scale", self.scale_spin)
        self.detail.layout.addLayout(form)

        self.report_view = QTextBrowser()
        self.report_view.setMinimumHeight(96)
        self.report_view.setMaximumHeight(150)
        self.report_view.setStyleSheet(
            "QTextBrowser{background:#151121;border:1px solid #332a4c;border-radius:10px;"
            "color:#d9d0ef;padding:8px;}"
        )
        self.detail.layout.addWidget(self.report_view)

        buttons = QHBoxLayout()
        self.activate_button = QPushButton(tr("characters.use"))
        self.activate_button.setObjectName("Primary")
        self.activate_button.clicked.connect(self._activate)
        self.save_button = QPushButton(tr("characters.save"))
        self.save_button.clicked.connect(self._save)
        self.revalidate_button = QPushButton(tr("characters.revalidate"))
        self.revalidate_button.clicked.connect(self._revalidate)
        buttons.addWidget(self.activate_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.revalidate_button)
        buttons.addStretch(1)
        self.detail.layout.addLayout(buttons)

        secondary = QHBoxLayout()
        self.open_button = QPushButton(tr("characters.open_folder"))
        self.open_button.setObjectName("Ghost")
        self.open_button.clicked.connect(self._open_folder)
        self.delete_button = QPushButton(tr("characters.delete"))
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete)
        secondary.addWidget(self.open_button)
        secondary.addStretch(1)
        secondary.addWidget(self.delete_button)
        self.detail.layout.addLayout(secondary)
        self.detail.setVisible(False)

    def _add_row(self, form: QFormLayout, key: str, widget: QWidget) -> None:
        label = QLabel(tr(key))
        label.setObjectName("Muted")
        self._form_labels.append((label, key))
        form.addRow(label, widget)

    # ------------------------------------------------------------------ data

    def _refresh(self) -> None:
        self.refresh_button.setEnabled(False)

        def work() -> dict[str, Any]:
            state = self.control.state()
            return {
                "state": state,
                "characters": self.ai.list_characters(),
                "personalities": self.ai.list_personalities(),
            }

        def done(data: dict[str, Any]) -> None:
            self.refresh_button.setEnabled(True)
            self.characters = data["characters"]
            self.personalities = data["personalities"]
            active = (data["state"] or {}).get("active_character") or {}
            self.active_id = active.get("id")
            self._fill_list(self._select_after_refresh)
            self._select_after_refresh = None
            self._loaded = True
            self._fill_personality_combo()
            self._update_layout_state()

        def fail(message: str) -> None:
            self.refresh_button.setEnabled(True)
            self.notify(message, "error")
            self.list_empty.setText(message)
            self.list_empty.setVisible(True)
            self.empty.setVisible(True)
            self.detail.setVisible(False)

        run_async(self, work, done, fail)

    def _fill_list(self, preferred: str | None = None) -> None:
        current = preferred or (self.current or {}).get("id")
        if self.active_id and not current:
            current = self.active_id
        self.list.blockSignals(True)
        self.list.clear()
        for character in self.characters:
            label = character.get("name") or character.get("id") or "—"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, character.get("id"))
            item.setToolTip(character.get("model_path") or "")
            if character.get("id") == self.active_id:
                item.setText(f"{label}  ●")
            if not character.get("personality_id"):
                item.setToolTip((character.get("model_path") or "") + "\n" + tr("characters.unknown_personality"))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.list_empty.setVisible(not self.characters)
        if self.characters:
            index = 0
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == current:
                    index = i
                    break
            self.list.setCurrentRow(index)
            self._set_current(self.characters[index])
        else:
            self.current = None
            self.detail.setVisible(False)
            self.empty.setVisible(True)
        self._update_layout_state()

    def _update_layout_state(self) -> None:
        has_characters = bool(self.characters)
        self.list.setVisible(has_characters)
        self.list_empty.setVisible(not has_characters)
        self.empty.setVisible(not has_characters)
        self.detail.setVisible(bool(self.current))

    def _selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        character_id = current.data(Qt.ItemDataRole.UserRole)
        for character in self.characters:
            if character.get("id") == character_id:
                self._set_current(character)
                return

    def _set_current(self, character: dict[str, Any]) -> None:
        self.current = character
        self.detail.setVisible(True)
        self.empty.setVisible(False)
        self.detail_name.setText(character.get("name") or "—")
        self.path_edit.setText(character.get("model_path") or "")
        self.entry_edit.setText(character.get("model_entry") or "")
        self.name_edit.setText(character.get("name") or "")
        self.scale_spin.setValue(float(character.get("scale") or 1.0))
        reply = character.get("reply_language") or "auto"
        index = self.reply_combo.findData(reply)
        self.reply_combo.setCurrentIndex(max(0, index))
        self._fill_personality_combo(character.get("personality_id"))
        is_active = character.get("id") == self.active_id
        self.active_label.setVisible(is_active)
        self.active_label.setText(tr("characters.active_badge"))
        self.activate_button.setEnabled(not is_active)
        self.activate_button.setText(tr("characters.active") if is_active else tr("characters.use"))
        self._validate(character)

    def _validate(self, character: dict[str, Any], force: bool = False) -> None:
        model_path = character.get("model_path") or ""
        entry = character.get("model_entry") or ""
        key = (model_path, entry)
        report = None if force else self._report_cache.get(key)
        if report is None:
            try:
                report = validate_model(model_path, entry)
            except Exception as exc:  # noqa: BLE001
                self.report = None
                self.report_view.setHtml(
                    f"<p style='color:#ff9fb7'>{friendly_error(exc)}</p>"
                )
                self.thumbnail.set_image(None)
                self.activate_button.setEnabled(False)
                return
            self._report_cache[key] = report
        self.report = report
        self.report_view.setHtml(report_html(report))
        self.thumbnail.set_image(str(report.thumbnail) if report.thumbnail else None)
        self.detail_sub.setText(
            f"{tr('characters.textures')}: {len(report.textures)} · "
            f"{tr('characters.motions')}: {sum(len(v) for v in report.motions.values())} · "
            f"{tr('characters.expressions')}: {len(report.expressions)} · "
            f"{tr('characters.model_size')}: {format_bytes(report.total_bytes)}"
        )
        if not report.ok:
            self.activate_button.setEnabled(False)
        elif character.get("id") != self.active_id:
            self.activate_button.setEnabled(True)

    def _fill_personality_combo(self, selected: str | None = None) -> None:
        selected = selected if selected is not None else (
            self.current.get("personality_id") if self.current else None
        )
        self.personality_combo.blockSignals(True)
        self.personality_combo.clear()
        self.personality_combo.addItem(tr("characters.unknown_personality"), None)
        for personality in self.personalities:
            self.personality_combo.addItem(personality.get("name") or "—", personality.get("id"))
        if selected:
            index = self.personality_combo.findData(selected)
            if index >= 0:
                self.personality_combo.setCurrentIndex(index)
        self.personality_combo.blockSignals(False)

    # ------------------------------------------------------------------ actions

    def _payload(self, character: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": character.get("name") or "Ailune",
            "model_path": character.get("model_path") or "",
            "model_entry": character.get("model_entry") or "",
            "personality_id": character.get("personality_id"),
            "scale": float(character.get("scale") or 1.0),
            "reply_language": character.get("reply_language") or "auto",
        }

    def _save(self) -> None:
        if not self.current:
            return
        name = self.name_edit.text().strip()
        if not name:
            self.notify(tr("common.required"), "error")
            return
        payload = {
            "name": name,
            "personality_id": self.personality_combo.currentData(),
            "reply_language": self.reply_combo.currentData(),
            "scale": self.scale_spin.value(),
        }
        character_id = self.current["id"]
        active = character_id == self.active_id

        def work() -> dict[str, Any]:
            updated = self.ai.update_character(character_id, payload)
            if active:
                self.control.patch_state(
                    {"active_character": self._payload(updated), "pet": {"visible": True}}
                )
            return updated

        def done(updated: dict[str, Any]) -> None:
            self.notify(tr("characters.saved"), "success")
            for index, character in enumerate(self.characters):
                if character.get("id") == updated.get("id"):
                    self.characters[index] = updated
                    break
            self._fill_list(updated.get("id"))

        run_async(self, work, done, lambda message: self.notify(message, "error"))

    def _activate(self) -> None:
        if not self.current or self.report is None or not self.report.ok:
            self.notify(tr("characters.import_failed"), "error")
            return
        character = dict(self.current)
        character["scale"] = self.scale_spin.value()
        character["name"] = self.name_edit.text().strip() or character.get("name")
        character["personality_id"] = self.personality_combo.currentData()
        character["reply_language"] = self.reply_combo.currentData()

        def work() -> dict[str, Any]:
            state = self.control.patch_state(
                {"active_character": self._payload(character), "pet": {"visible": True}}
            )
            return state

        def done(_state: dict[str, Any]) -> None:
            self.active_id = character.get("id")
            self.notify(tr("characters.activated", name=character.get("name") or ""), "success")
            self._fill_list(character.get("id"))

        def fail(message: str) -> None:
            self.notify(tr("characters.activation_failed") + " " + message, "error")

        run_async(self, work, done, fail)

    def _delete(self) -> None:
        if not self.current:
            return
        character = self.current
        answer = QMessageBox.question(
            self,
            tr("characters.delete_title"),
            tr("characters.delete_text", name=character.get("name") or ""),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def work() -> None:
            if character.get("id") == self.active_id:
                self.control.patch_state({"active_character": None})
            self.ai.delete_character(character["id"])

        def done(_result: Any) -> None:
            self.notify(tr("characters.deleted"), "success")
            self.current = None
            self._refresh()

        run_async(self, work, done, lambda message: self.notify(message, "error"))

    def _revalidate(self) -> None:
        if not self.current:
            return
        self._report_cache.clear()
        self._validate(self.current, force=True)
        self.notify(tr("characters.revalidated"), "success")

    def _open_folder(self) -> None:
        if not self.current:
            return
        path = Path(self.current.get("model_path") or "")
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _import_model(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, tr("characters.select_directory"), str(Path.home())
        )
        if not directory:
            return
        entries = discover_entries(Path(directory))
        if not entries:
            QMessageBox.warning(self, tr("characters.import"), tr("characters.no_entries"))
            return
        dialog = ImportDialog(entries, self.personalities, self)
        if dialog.exec() != dialog.DialogCode.Accepted or not dialog.result_data:
            return
        data = dialog.result_data
        progress = QProgressDialog(tr("characters.importing"), "", 0, 0, self)
        progress.setWindowTitle(tr("characters.import"))
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        library = resolve_paths().data_dir / "characters"

        def work() -> dict[str, Any]:
            report: ModelManifest = data["report"]
            if data["copy"]:
                result = copy_into_library(report, library)
                report = result.report
            root = report.root
            entry = report.entry.relative_to(root).as_posix()
            payload = {
                "name": data["name"],
                "model_path": str(root),
                "model_entry": entry,
                "personality_id": data["personality_id"],
                "reply_language": data["reply_language"],
                "scale": data["scale"],
            }
            return self.ai.create_character(payload)

        def done(created: dict[str, Any]) -> None:
            progress.close()
            self.notify(tr("dialog.import_done", name=created.get("name") or ""), "success")
            self._select_after_refresh = created.get("id")
            self.current = None
            self._refresh()

        def fail(message: str) -> None:
            progress.close()
            self.notify(tr("characters.import_failed") + " " + message, "error")

        run_async(self, work, done, fail)

    # ------------------------------------------------------------------ lifecycle

    def on_show(self) -> None:
        if not self._loaded:
            self._refresh()
        elif not self._workers:
            self._refresh()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.import_button.setText(tr("characters.import"))
        self.refresh_button.setText(tr("common.refresh"))
        for label, key in self._form_labels:
            label.setText(tr(key))
        self.activate_button.setText(
            tr("characters.active") if self.current and self.current.get("id") == self.active_id else tr("characters.use")
        )
        self.save_button.setText(tr("characters.save"))
        self.revalidate_button.setText(tr("characters.revalidate"))
        self.open_button.setText(tr("characters.open_folder"))
        self.delete_button.setText(tr("characters.delete"))
        self.empty.retranslate()
        self._fill_personality_combo(
            self.personality_combo.currentData() if self.personality_combo.count() else None
        )
        if self.report is not None:
            self.report_view.setHtml(report_html(self.report))
