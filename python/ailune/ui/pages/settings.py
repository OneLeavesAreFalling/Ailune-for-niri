"""Settings page: language, pet behaviour, services and about."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ailune import __version__
from ailune.common.paths import resolve_paths
from ailune.ui.clients import AIServiceClient, ControlClient
from ailune.ui.i18n import translator, tr
from ailune.ui.widgets import Card, PageHeader, SectionTitle, StatusPill, separator, run_async

LANGUAGE_OPTIONS = (("en", "lang.en"), ("zh_CN", "lang.zh_CN"))


class SettingsPage(QWidget):
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
        self._updating = False
        self._build()
        self._load_language()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)
        self.header = PageHeader("settings.title", "settings.subtitle")
        root.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)

        # ---------------------------------------------------------- language
        language_card = Card()
        self.language_title = SectionTitle("settings.language")
        language_card.layout.addWidget(self.language_title)
        self.language_hint = QLabel(tr("settings.language_hint"))
        self.language_hint.setObjectName("Muted")
        self.language_hint.setWordWrap(True)
        language_card.layout.addWidget(self.language_hint)
        lang_row = QHBoxLayout()
        self.language_combo = QComboBox()
        self.language_combo.setMinimumWidth(220)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        lang_row.addWidget(self.language_combo)
        lang_row.addStretch(1)
        language_card.layout.addLayout(lang_row)
        layout.addWidget(language_card)

        # ---------------------------------------------------------- pet
        pet_card = Card()
        self.pet_title = SectionTitle("settings.pet")
        pet_card.layout.addWidget(self.pet_title)
        self.pet_hint = QLabel(tr("settings.pet_section_hint"))
        self.pet_hint.setObjectName("Muted")
        self.pet_hint.setWordWrap(True)
        pet_card.layout.addWidget(self.pet_hint)
        self.pet_visible = QCheckBox(tr("settings.pet_visible"))
        self.pet_click = QCheckBox(tr("settings.pet_click_through"))
        self.pet_click_hint = QLabel(tr("settings.pet_click_hint"))
        self.pet_click_hint.setObjectName("Muted")
        self.pet_click_hint.setWordWrap(True)
        pet_scale_row = QHBoxLayout()
        self.pet_scale_label = QLabel(tr("settings.pet_scale"))
        self.pet_scale_label.setObjectName("Muted")
        self.pet_scale = QDoubleSpinBox()
        self.pet_scale.setRange(0.5, 2.0)
        self.pet_scale.setSingleStep(0.05)
        self.pet_scale.setSuffix(" ×")
        pet_scale_row.addWidget(self.pet_scale_label)
        pet_scale_row.addWidget(self.pet_scale)
        pet_scale_row.addStretch(1)
        self.pet_save = QPushButton(tr("common.save"))
        self.pet_save.setObjectName("Primary")
        self.pet_save.clicked.connect(self._save_pet)
        self.pet_reset = QPushButton(tr("settings.pet_reset"))
        self.pet_reset.setObjectName("Ghost")
        self.pet_reset.clicked.connect(self._reset_pet)
        pet_buttons = QHBoxLayout()
        pet_buttons.addWidget(self.pet_save)
        pet_buttons.addWidget(self.pet_reset)
        pet_buttons.addStretch(1)
        pet_card.layout.addWidget(self.pet_visible)
        pet_card.layout.addLayout(pet_scale_row)
        pet_card.layout.addWidget(self.pet_click)
        pet_card.layout.addWidget(self.pet_click_hint)
        pet_card.layout.addLayout(pet_buttons)
        layout.addWidget(pet_card)

        # ---------------------------------------------------------- services
        service_card = Card()
        self.services_title = SectionTitle("settings.services")
        service_card.layout.addWidget(self.services_title)
        status_row = QHBoxLayout()
        self.core_pill = StatusPill("status.core")
        self.ai_pill = StatusPill("status.ai")
        self.check_button = QPushButton(tr("settings.check_services"))
        self.check_button.clicked.connect(self._check_services)
        status_row.addWidget(self.core_pill)
        status_row.addWidget(self.ai_pill)
        status_row.addStretch(1)
        status_row.addWidget(self.check_button)
        service_card.layout.addLayout(status_row)

        self.core_url = self._path_row(service_card, "settings.core_url", self.control.base_url)
        self.ai_url = self._path_row(service_card, "settings.ai_url", self.ai.base_url)
        paths = resolve_paths()
        self.data_dir = self._path_row(service_card, "settings.data_dir", str(paths.data_dir))
        self.token_file = self._path_row(service_card, "settings.token_file", str(paths.token_file))
        self.open_data_button = QPushButton(tr("settings.open_data"))
        self.open_data_button.clicked.connect(self._open_data)
        service_card.layout.addWidget(self.open_data_button, alignment=Qt.AlignmentFlag.AlignLeft)

        service_card.layout.addWidget(separator())
        self.niri_title = SectionTitle("settings.niri")
        service_card.layout.addWidget(self.niri_title)
        self.niri_label = QLabel(tr("status.checking"))
        self.niri_label.setObjectName("Muted")
        self.niri_label.setWordWrap(True)
        service_card.layout.addWidget(self.niri_label)
        layout.addWidget(service_card)

        # ---------------------------------------------------------- about
        about_card = Card()
        self.about_title = SectionTitle("settings.about")
        about_card.layout.addWidget(self.about_title)
        self.about_text = QLabel(tr("settings.about_text"))
        self.about_text.setWordWrap(True)
        about_card.layout.addWidget(self.about_text)
        self.version_label = QLabel()
        self.version_label.setObjectName("Muted")
        about_card.layout.addWidget(self.version_label)
        self.license_label = QLabel()
        self.license_label.setObjectName("Muted")
        self.license_label.setWordWrap(True)
        about_card.layout.addWidget(self.license_label)
        self.third_party = QLabel(tr("settings.third_party"))
        self.third_party.setObjectName("Muted")
        self.third_party.setWordWrap(True)
        about_card.layout.addWidget(self.third_party)
        self.project_note = QLabel(tr("settings.about_project"))
        self.project_note.setObjectName("Muted")
        self.project_note.setWordWrap(True)
        about_card.layout.addWidget(self.project_note)
        links = QLabel(
            '<a href="https://www.live2d.com/en/sdk/about/">Live2D Cubism SDK</a> · '
            '<a href="https://doc.qt.io/qt-6/">Qt</a> · '
            '<a href="https://webkitgtk.org/">WebKitGTK</a> · '
            '<a href="https://github.com/YaLTeR/niri">Niri</a>'
        )
        links.setOpenExternalLinks(True)
        links.setWordWrap(True)
        about_card.layout.addWidget(links)
        layout.addWidget(about_card)
        layout.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self._update_about_labels()
        self._populate_language_combo()

    def _path_row(self, card: Card, key: str, value: str) -> QLabel:
        row = QHBoxLayout()
        label = QLabel(tr(key))
        label.setObjectName("Muted")
        label.setMinimumWidth(110)
        text = QLabel(value)
        text.setObjectName("Mono")
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setWordWrap(True)
        row.addWidget(label)
        row.addWidget(text, 1)
        card.layout.addLayout(row)
        return text

    def _populate_language_combo(self) -> None:
        current = translator().language
        self._updating = True
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for language, key in LANGUAGE_OPTIONS:
            self.language_combo.addItem(tr(key), language)
        index = self.language_combo.findData(current)
        self.language_combo.setCurrentIndex(max(0, index))
        self.language_combo.blockSignals(False)
        self._updating = False

    def _load_language(self) -> None:
        self._populate_language_combo()

    def _language_changed(self, _index: int) -> None:
        if self._updating:
            return
        language = self.language_combo.currentData()
        if language == translator().language:
            return
        translator().set_language(str(language))
        self._populate_language_combo()

        def patch() -> Any:
            try:
                return self.control.patch_state({"language": language})
            except Exception:
                return None

        run_async(self, patch, on_error=lambda _m: None)
        self.notify(tr("toast.lang_changed"), "success")

    def _update_about_labels(self) -> None:
        self.version_label.setText(f"{tr('settings.version')}: {__version__}")
        self.license_label.setText(f"{tr('settings.license')}: {tr('about.license_value')}")

    def _save_pet(self) -> None:
        payload = {
            "pet": {
                "visible": self.pet_visible.isChecked(),
                "scale": self.pet_scale.value(),
                "click_through": self.pet_click.isChecked(),
            }
        }

        def done(_state: Any) -> None:
            self.notify(tr("settings.pet_saved"), "success")

        run_async(self, lambda: self.control.patch_state(payload), done, lambda m: self.notify(m, "error"))

    def _reset_pet(self) -> None:
        def done(_state: Any) -> None:
            self.notify(tr("settings.pet_reset_done"), "success")

        run_async(
            self,
            lambda: self.control.patch_state({"pet": {"x": -1, "y": -1}}),
            done,
            lambda m: self.notify(m, "error"),
        )

    def _open_data(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolve_paths().data_dir)))

    def _load_pet_state(self) -> None:
        def done(state: dict[str, Any]) -> None:
            pet = (state or {}).get("pet") or {}
            self._updating = True
            self.pet_visible.setChecked(pet.get("visible", True) is not False)
            self.pet_click.setChecked(bool(pet.get("click_through")))
            try:
                scale = float(pet.get("scale") or 1.0)
            except (TypeError, ValueError):
                scale = 1.0
            self.pet_scale.setValue(min(2.0, max(0.5, scale)))
            self._updating = False

        run_async(self, self.control.state, done, lambda _m: None)

    def _check_services(self) -> None:
        self.check_button.setEnabled(False)
        self.core_pill.set_online(None)
        self.ai_pill.set_online(None)

        def work() -> dict[str, Any]:
            result: dict[str, Any] = {
                "core": False,
                "ai": False,
                "info": None,
                "ai_version": "",
            }
            try:
                self.control.health()
                result["core"] = True
            except Exception:
                result["core"] = False
            try:
                health = self.ai.health()
                result["ai"] = True
                result["ai_version"] = health.get("version") or ""
            except Exception:
                result["ai"] = False
            try:
                result["info"] = self.control.info()
            except Exception:
                result["info"] = None
            return result

        def done(result: dict[str, Any]) -> None:
            self.check_button.setEnabled(True)
            self.core_pill.set_online(bool(result["core"]))
            self.ai_pill.set_online(bool(result["ai"]))
            info = result.get("info") or {}
            niri = info.get("niri") or {}
            if niri.get("available"):
                outputs = niri.get("outputs") or {}
                workspaces = niri.get("workspaces") or []
                output_names = ", ".join(outputs.keys()) if isinstance(outputs, dict) else ""
                self.niri_label.setText(
                    f"{tr('settings.niri_available')} · "
                    f"{tr('settings.outputs')}: {len(outputs) if isinstance(outputs, dict) else 0}"
                    + (f" ({output_names})" if output_names else "")
                    + f" · {tr('settings.workspaces')}: {len(workspaces) if isinstance(workspaces, list) else 0}"
                )
            else:
                self.niri_label.setText(tr("settings.niri_unavailable"))
            if not result["core"] and not result["ai"]:
                self.notify(tr("settings.no_services"), "error")

        def fail(message: str) -> None:
            self.check_button.setEnabled(True)
            self.core_pill.set_online(False)
            self.ai_pill.set_online(False)
            self.notify(message, "error")

        run_async(self, work, done, fail)

    def on_show(self) -> None:
        self._load_pet_state()
        self._check_services()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.language_title.retranslate()
        self.language_hint.setText(tr("settings.language_hint"))
        self.pet_title.retranslate()
        self.pet_hint.setText(tr("settings.pet_section_hint"))
        self.pet_visible.setText(tr("settings.pet_visible"))
        self.pet_scale_label.setText(tr("settings.pet_scale"))
        self.pet_click.setText(tr("settings.pet_click_through"))
        self.pet_click_hint.setText(tr("settings.pet_click_hint"))
        self.pet_save.setText(tr("common.save"))
        self.pet_reset.setText(tr("settings.pet_reset"))
        self.services_title.retranslate()
        self.check_button.setText(tr("settings.check_services"))
        self.open_data_button.setText(tr("settings.open_data"))
        self.niri_title.retranslate()
        self.about_title.retranslate()
        self.about_text.setText(tr("settings.about_text"))
        self.third_party.setText(tr("settings.third_party"))
        self.project_note.setText(tr("settings.about_project"))
        self._update_about_labels()
        self._populate_language_combo()
        self.core_pill.retranslate()
        self.ai_pill.retranslate()
