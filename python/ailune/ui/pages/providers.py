"""Provider configuration page."""

from __future__ import annotations

import json
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ailune.ui.clients import AIServiceClient
from ailune.ui.i18n import tr
from ailune.ui.widgets import Card, EmptyState, PageHeader, run_async

FALLBACK_PRESETS = [
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini", "needs_key": True, "local": False},
    {"id": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat", "needs_key": True, "local": False},
    {"id": "zhipu", "label": "Zhipu AI", "base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-4-flash", "needs_key": True, "local": False},
    {"id": "dashscope", "label": "Alibaba DashScope", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus", "needs_key": True, "local": False},
    {"id": "moonshot", "label": "Moonshot AI", "base_url": "https://api.moonshot.cn/v1", "default_model": "moonshot-v1-8k", "needs_key": True, "local": False},
    {"id": "ollama", "label": "Ollama (local)", "base_url": "http://127.0.0.1:11434", "default_model": "llama3.2", "needs_key": False, "local": True},
    {"id": "lmstudio", "label": "LM Studio (local)", "base_url": "http://127.0.0.1:1234/v1", "default_model": "local-model", "needs_key": False, "local": True},
    {"id": "custom", "label": "OpenAI-compatible (custom)", "base_url": "", "default_model": "", "needs_key": False, "local": False},
]


class ProvidersPage(QWidget):
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
        self.providers: list[dict[str, Any]] = []
        self.presets: list[dict[str, Any]] = FALLBACK_PRESETS
        self.current: dict[str, Any] | None = None
        self.is_new = False
        self._form_labels: list[tuple[QLabel, str]] = []
        self._loaded = False
        self._build()

    # ------------------------------------------------------------------ ui

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)
        self.header = PageHeader("providers.title", "providers.subtitle")
        self.refresh_button = QPushButton(tr("common.refresh"))
        self.refresh_button.clicked.connect(self._refresh)
        self.add_button = QPushButton(tr("providers.add"))
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self._new_provider)
        self.header.add_action(self.refresh_button)
        self.header.add_action(self.add_button)
        root.addWidget(self.header)

        content = QHBoxLayout()
        content.setSpacing(14)
        left = Card(margins=10)
        left.setFixedWidth(300)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list_empty = QLabel(tr("providers.empty_hint"))
        self.list_empty.setObjectName("Muted")
        self.list_empty.setWordWrap(True)
        left.layout.addWidget(self.list, 1)
        left.layout.addWidget(self.list_empty)
        content.addWidget(left)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(12)
        self.detail = Card(margins=18)
        host_layout.addWidget(self.detail)
        self.empty = EmptyState("providers.empty_title", "providers.empty_hint", "providers.add")
        self.empty.button.clicked.connect(self._new_provider)
        host_layout.addWidget(self.empty)
        host_layout.addStretch(1)
        self.scroll.setWidget(host)
        content.addWidget(self.scroll, 1)
        root.addLayout(content, 1)

        self._build_form()

    def _build_form(self) -> None:
        title = QLabel(tr("providers.details"))
        title.setObjectName("SectionTitle")
        self.detail.layout.addWidget(title)

        buttons = QHBoxLayout()
        self.save_button = QPushButton(tr("common.save"))
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self._save)
        self.test_button = QPushButton(tr("providers.test"))
        self.test_button.clicked.connect(self._test)
        self.delete_button = QPushButton(tr("providers.delete"))
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_button)
        self.detail.layout.addLayout(buttons)

        form = QFormLayout()
        form.setSpacing(8)
        self.type_combo = QComboBox()
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.display_edit = QLineEdit()
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("https://api.example.com/v1")
        self.model_edit = QLineEdit()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_hint = QLabel("")
        self.key_hint.setObjectName("Muted")
        self.key_hint.setWordWrap(True)
        self.clear_key_check = QCheckBox(tr("providers.remove_key"))
        self.clear_key_check.setVisible(False)
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.8)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(0, 200000)
        self.max_tokens_spin.setSingleStep(256)
        self.max_tokens_spin.setSpecialValueText("—")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setValue(60)
        self.timeout_spin.setSuffix(" s")
        self.extra_edit = QPlainTextEdit()
        self.extra_edit.setFixedHeight(74)
        self.extra_edit.setPlaceholderText("{}")
        self.default_check = QCheckBox(tr("providers.make_default"))
        self.needs_key_label = QLabel("")
        self.needs_key_label.setObjectName("Muted")
        self.base_hint = QLabel(tr("providers.base_url_hint"))
        self.base_hint.setObjectName("Muted")
        self.base_hint.setWordWrap(True)
        self.extra_hint = QLabel(tr("providers.extra_hint"))
        self.extra_hint.setObjectName("Muted")
        self._add_row(form, "providers.type", self.type_combo)
        self._add_row(form, "providers.display_name", self.display_edit)
        self._add_row(form, "providers.base_url", self.base_edit)
        form.addRow("", self.base_hint)
        self._add_row(form, "providers.model_name", self.model_edit)
        self._add_row(form, "providers.api_key", self.key_edit)
        form.addRow("", self.key_hint)
        form.addRow("", self.clear_key_check)
        self._add_row(form, "providers.temperature", self.temperature_spin)
        self._add_row(form, "providers.max_tokens", self.max_tokens_spin)
        self.max_tokens_hint = QLabel(tr("providers.max_tokens_hint"))
        self.max_tokens_hint.setObjectName("Muted")
        form.addRow("", self.max_tokens_hint)
        self._add_row(form, "providers.timeout", self.timeout_spin)
        self._add_row(form, "providers.extra_json", self.extra_edit)
        form.addRow("", self.extra_hint)
        form.addRow("", self.default_check)
        form.addRow("", self.needs_key_label)
        self.detail.layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        self.detail.layout.addWidget(self.status_label)

        self.security_label = QLabel("")
        self.security_label.setObjectName("Muted")
        self.security_label.setWordWrap(True)
        self.detail.layout.addWidget(self.security_label)
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
            meta = self.ai.meta()
            return {"providers": self.ai.list_providers(), "meta": meta}

        def done(data: dict[str, Any]) -> None:
            self.refresh_button.setEnabled(True)
            self.providers = data["providers"]
            self.presets = data["meta"].get("provider_presets") or FALLBACK_PRESETS
            self._fill_type_combo()
            self.security_label.setText(
                f"{tr('providers.secret_backend')}: {data['meta'].get('secret_backend', 'file')}. "
                + tr("providers.security_note")
            )
            self._fill_list()
            self.empty.setVisible(not self.providers and not self.is_new)
            self._loaded = True

        def fail(message: str) -> None:
            self.refresh_button.setEnabled(True)
            self.notify(message, "error")
            self.list_empty.setText(message)
            self.list_empty.setVisible(True)
            self.empty.setVisible(True)
            self.detail.setVisible(False)

        run_async(self, work, done, fail)

    def _fill_type_combo(self) -> None:
        previous = self.type_combo.currentData()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        for preset in self.presets:
            label = preset.get("label") or preset.get("id")
            self.type_combo.addItem(label, preset.get("id"))
        if previous:
            index = self.type_combo.findData(previous)
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
        self.type_combo.blockSignals(False)

    def _fill_list(self, preferred: str | None = None) -> None:
        current = preferred or (self.current or {}).get("id")
        self.list.blockSignals(True)
        self.list.clear()
        for provider in self.providers:
            label = provider.get("display_name") or provider.get("id") or "—"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, provider.get("id"))
            if provider.get("is_default"):
                item.setText(f"{label}  ●")
            item.setToolTip(f"{provider.get('provider_type')} · {provider.get('model_name')}")
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.list_empty.setVisible(not self.providers)
        if self.providers:
            index = 0
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == current:
                    index = i
                    break
            self.list.blockSignals(True)
            self.list.setCurrentRow(index)
            self.list.blockSignals(False)
            self._set_current(self.providers[index])
        elif not self.is_new:
            self.current = None
            self.detail.setVisible(False)
            self.empty.setVisible(True)

    def _selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        provider_id = current.data(Qt.ItemDataRole.UserRole)
        for provider in self.providers:
            if provider.get("id") == provider_id:
                self.is_new = False
                self.current = provider
                self._set_current(provider)
                return

    def _set_current(self, provider: dict[str, Any]) -> None:
        self.is_new = False
        self.current = provider
        self.detail.setVisible(True)
        self.empty.setVisible(False)
        self.delete_button.setEnabled(True)
        type_index = self.type_combo.findData(provider.get("provider_type"))
        self.type_combo.setCurrentIndex(max(0, type_index))
        self.display_edit.setText(provider.get("display_name") or "")
        self.base_edit.setText(provider.get("base_url") or "")
        self.model_edit.setText(provider.get("model_name") or "")
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(tr("providers.api_key_placeholder"))
        self.temperature_spin.setValue(float(provider.get("temperature") or 0.8))
        self.max_tokens_spin.setValue(int(provider.get("max_tokens") or 0))
        self.timeout_spin.setValue(int(provider.get("timeout_seconds") or 60))
        self.extra_edit.setPlainText(
            json.dumps(provider.get("extra_params") or {}, ensure_ascii=False, indent=2)
        )
        self.default_check.setChecked(bool(provider.get("is_default")))
        self.clear_key_check.setVisible(bool(provider.get("has_api_key")))
        self.clear_key_check.setChecked(False)
        if provider.get("has_api_key"):
            self.key_hint.setText(tr("providers.api_key_stored") + " " + tr("providers.api_key_keep"))
        else:
            self.key_hint.setText("")
        self._update_needs_key()
        self.status_label.setVisible(False)

    def _new_provider(self) -> None:
        self.is_new = True
        self.current = None
        self.detail.setVisible(True)
        self.empty.setVisible(False)
        self.delete_button.setEnabled(False)
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(tr("providers.api_key_placeholder"))
        self.key_hint.setText("")
        self.clear_key_check.setVisible(False)
        self.clear_key_check.setChecked(False)
        self.display_edit.clear()
        self.model_edit.clear()
        self.extra_edit.setPlainText("{}")
        self.default_check.setChecked(False)
        self.temperature_spin.setValue(0.8)
        self.max_tokens_spin.setValue(0)
        self.timeout_spin.setValue(60)
        self.status_label.setVisible(False)
        self.type_combo.setCurrentIndex(0)
        self._apply_preset()
        self.display_edit.setFocus()

    def _type_changed(self) -> None:
        if self.is_new:
            self._apply_preset()
        self._update_needs_key()

    def _update_needs_key(self) -> None:
        preset = self._preset()
        if preset is None:
            self.needs_key_label.setText("")
            return
        self.needs_key_label.setText(
            tr("providers.needs_key") if preset.get("needs_key") else tr("providers.local")
        )

    def _apply_preset(self) -> None:
        preset = self._preset()
        if not preset:
            return
        if not self.base_edit.text().strip() or self.is_new:
            self.base_edit.setText(preset.get("base_url") or "")
        if not self.model_edit.text().strip() or self.is_new:
            self.model_edit.setText(preset.get("default_model") or "")
        if self.is_new and not self.display_edit.text().strip():
            self.display_edit.setText(preset.get("label") or "")
        self._update_needs_key()

    def _preset(self) -> dict[str, Any] | None:
        provider_type = self.type_combo.currentData()
        for preset in self.presets:
            if preset.get("id") == provider_type:
                return preset
        return None

    # ------------------------------------------------------------------ actions

    def _form_payload(self, *, include_key: bool = True) -> dict[str, Any]:
        provider_type = self.type_combo.currentData()
        base_url = self.base_edit.text().strip().rstrip("/")
        model_name = self.model_edit.text().strip()
        display_name = self.display_edit.text().strip() or (self._preset() or {}).get("label") or provider_type
        if not base_url:
            raise ValueError(tr("providers.base_url"))
        if not model_name:
            raise ValueError(tr("providers.model_name"))
        try:
            extra = json.loads(self.extra_edit.toPlainText().strip() or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(tr("providers.invalid_extra")) from exc
        if not isinstance(extra, dict):
            raise ValueError(tr("providers.invalid_extra"))
        payload: dict[str, Any] = {
            "display_name": display_name,
            "provider_type": provider_type,
            "base_url": base_url,
            "model_name": model_name,
            "temperature": self.temperature_spin.value(),
            "max_tokens": self.max_tokens_spin.value() or None,
            "timeout_seconds": float(self.timeout_spin.value()),
            "extra_params": extra,
            "is_default": self.default_check.isChecked(),
        }
        if include_key:
            key = self.key_edit.text().strip()
            if key:
                payload["api_key"] = key
            elif self.clear_key_check.isChecked():
                payload["api_key"] = ""
        return payload

    def _save(self) -> None:
        try:
            payload = self._form_payload(include_key=True)
        except ValueError as exc:
            self.notify(str(exc), "error")
            return
        provider_id = self.current.get("id") if self.current else None
        self.save_button.setEnabled(False)

        def work() -> dict[str, Any]:
            if provider_id:
                return self.ai.update_provider(provider_id, payload)
            return self.ai.create_provider(payload)

        def done(provider: dict[str, Any]) -> None:
            self.save_button.setEnabled(True)
            self.notify(tr("providers.saved"), "success")
            self.current = provider
            self.is_new = False
            self._refresh()

        def fail(message: str) -> None:
            self.save_button.setEnabled(True)
            self.notify(message, "error")

        run_async(self, work, done, fail)

    def _test(self) -> None:
        try:
            form = self._form_payload(include_key=False)
        except ValueError as exc:
            self.notify(str(exc), "error")
            return
        payload: dict[str, Any] = {
            "display_name": "Ailune connection test",
            "provider_type": form["provider_type"],
            "base_url": form["base_url"],
            "model_name": form["model_name"],
            "timeout_seconds": min(60.0, float(self.timeout_spin.value())),
            "extra_params": form["extra_params"],
        }
        if self.current:
            payload["provider_id"] = self.current.get("id")
        key = self.key_edit.text().strip()
        if key:
            payload["api_key"] = key
        self.test_button.setEnabled(False)
        self.test_button.setText(tr("providers.testing"))
        self.status_label.setVisible(True)
        self.status_label.setObjectName("Muted")
        self.status_label.setText(tr("providers.testing"))

        def work() -> dict[str, Any]:
            return self.ai.test_provider(payload)

        def done(result: dict[str, Any]) -> None:
            self.test_button.setEnabled(True)
            self.test_button.setText(tr("providers.test"))
            ok = bool(result.get("ok"))
            models = result.get("models") or []
            latency = result.get("latency_ms") or 0
            self.status_label.setObjectName("SuccessText" if ok else "ErrorText")
            if ok:
                self.status_label.setText(
                    f"{tr('providers.test_success', models=len(models))} · {latency} ms"
                )
            else:
                self.status_label.setText(f"{tr('providers.test_failed')}: {result.get('message') or ''}")
            self.status_label.setVisible(True)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)

        def fail(message: str) -> None:
            self.test_button.setEnabled(True)
            self.test_button.setText(tr("providers.test"))
            self.status_label.setObjectName("ErrorText")
            self.status_label.setText(f"{tr('providers.test_failed')}: {message}")
            self.status_label.setVisible(True)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)

        run_async(self, work, done, fail)

    def _delete(self) -> None:
        if not self.current:
            return
        provider = self.current
        answer = QMessageBox.question(
            self,
            tr("providers.delete_title"),
            tr("providers.delete_text", name=provider.get("display_name") or ""),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def done(_result: Any) -> None:
            self.notify(tr("providers.deleted"), "success")
            self.current = None
            self._refresh()

        run_async(self, lambda: self.ai.delete_provider(provider["id"]), done, lambda m: self.notify(m, "error"))

    # ------------------------------------------------------------------ lifecycle

    def on_show(self) -> None:
        if not self._loaded:
            self._refresh()
        elif not self._workers:
            self._refresh()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.refresh_button.setText(tr("common.refresh"))
        self.add_button.setText(tr("providers.add"))
        for label, key in self._form_labels:
            label.setText(tr(key))
        self.save_button.setText(tr("common.save"))
        self.test_button.setText(tr("providers.test"))
        self.delete_button.setText(tr("providers.delete"))
        self.base_hint.setText(tr("providers.base_url_hint"))
        self.extra_hint.setText(tr("providers.extra_hint"))
        self.max_tokens_hint.setText(tr("providers.max_tokens_hint"))
        self.default_check.setText(tr("providers.make_default"))
        self.clear_key_check.setText(tr("providers.remove_key"))
        self.empty.retranslate()
        if self.current and self.current.get("has_api_key"):
            self.key_hint.setText(tr("providers.api_key_stored") + " " + tr("providers.api_key_keep"))
        self._fill_list(self.current.get("id") if self.current else None)
