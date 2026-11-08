"""Main Qt window and navigation."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QSettings, QTimer, Qt
from PyQt6.QtGui import QCloseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ailune import __version__
from ailune.ui.clients import AIServiceClient, ControlClient
from ailune.ui.i18n import translator, tr
from ailune.ui.pages.characters import CharactersPage
from ailune.ui.pages.chat import ChatPage
from ailune.ui.pages.memory import MemoryPage
from ailune.ui.pages.personalities import PersonalitiesPage
from ailune.ui.pages.providers import ProvidersPage
from ailune.ui.pages.settings import SettingsPage
from ailune.ui.widgets import StatusPill, run_async

NAV_ITEMS = ("chat", "characters", "providers", "personality", "memory", "settings")


class MainWindow(QMainWindow):
    def __init__(self, control: ControlClient, ai: AIServiceClient) -> None:
        super().__init__()
        self.control = control
        self.ai = ai
        self.settings = QSettings()
        self._workers: list[Any] = []
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)
        self._status_busy = False
        self.nav_buttons: dict[str, QToolButton] = {}
        self.pages: dict[str, Any] = {}
        self.current_key = "chat"

        self.setWindowTitle("Ailune")
        self.setObjectName("Root")
        self.resize(1220, 800)
        self.setMinimumSize(980, 660)
        self._build()
        self._restore_geometry()
        translator().language_changed.connect(self._on_language_changed)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(20000)
        self._status_timer.timeout.connect(self._check_status)
        self._status_timer.start()
        QTimer.singleShot(250, self._check_status)
        self.navigate("chat")

    # ------------------------------------------------------------------ ui

    def _build(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 20, 16, 16)
        side.setSpacing(6)
        self.brand = QLabel("Ailune")
        self.brand.setObjectName("Brand")
        self.tagline = QLabel(tr("app.tagline"))
        self.tagline.setObjectName("Tagline")
        self.tagline.setWordWrap(True)
        side.addWidget(self.brand)
        side.addWidget(self.tagline)
        side.addSpacing(18)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for key in NAV_ITEMS:
            button = QToolButton()
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setSizePolicy(button.sizePolicy().horizontalPolicy(), button.sizePolicy().verticalPolicy())
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.navigate(k))
            group.addButton(button)
            side.addWidget(button)
            self.nav_buttons[key] = button
        side.addStretch(1)

        status = QVBoxLayout()
        status.setSpacing(5)
        self.core_pill = StatusPill("status.core")
        self.ai_pill = StatusPill("status.ai")
        status.addWidget(self.core_pill)
        status.addWidget(self.ai_pill)
        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setObjectName("Muted")
        status.addWidget(self.version_label)
        side.addLayout(status)
        root.addWidget(sidebar)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        services = {"control": self.control, "ai": self.ai, "notify": self.show_toast}
        pages = [
            ("chat", ChatPage(services, self.navigate)),
            ("characters", CharactersPage(services, self.navigate)),
            ("providers", ProvidersPage(services, self.navigate)),
            ("personality", PersonalitiesPage(services, self.navigate)),
            ("memory", MemoryPage(services, self.navigate)),
            ("settings", SettingsPage(services, self.navigate)),
        ]
        self._indices: dict[str, int] = {}
        for key, page in pages:
            self.pages[key] = page
            self._indices[key] = self.stack.addWidget(page)

        self.toast = QLabel(central)
        self.toast.setObjectName("Toast")
        self.toast.setVisible(False)
        self.toast.setWordWrap(True)
        self.toast.setMaximumWidth(520)
        self.toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._retranslate()

    # ------------------------------------------------------------------ navigation

    def navigate(self, key: str) -> None:
        if key not in self.pages:
            return
        old = self.pages.get(self.current_key)
        if old is not None and self.current_key != key and hasattr(old, "on_hidden"):
            old.on_hidden()
        self.current_key = key
        self.stack.setCurrentIndex(self._indices[key])
        for nav_key, button in self.nav_buttons.items():
            button.setChecked(nav_key == key)
        page = self.pages[key]
        if hasattr(page, "on_show"):
            page.on_show()

    # ------------------------------------------------------------------ status

    def _check_status(self) -> None:
        if self._status_busy:
            return
        self._status_busy = True

        def work() -> dict[str, bool]:
            result = {"core": False, "ai": False}
            try:
                self.control.health()
                result["core"] = True
            except Exception:
                result["core"] = False
            try:
                self.ai.health()
                result["ai"] = True
            except Exception:
                result["ai"] = False
            return result

        def done(result: dict[str, bool]) -> None:
            self._status_busy = False
            self.core_pill.set_online(result["core"])
            self.ai_pill.set_online(result["ai"])

        def fail(_message: str) -> None:
            self._status_busy = False
            self.core_pill.set_online(False)
            self.ai_pill.set_online(False)

        run_async(self, work, done, fail)

    # ------------------------------------------------------------------ toast

    def show_toast(self, message: str, kind: str = "info") -> None:
        if not message:
            return
        self.toast.setText(message)
        self.toast.setProperty("kind", kind)
        self.toast.style().unpolish(self.toast)
        self.toast.style().polish(self.toast)
        self.toast.adjustSize()
        self._position_toast()
        self.toast.setVisible(True)
        self.toast.raise_()
        self._toast_timer.start(4200)

    def _hide_toast(self) -> None:
        self.toast.setVisible(False)

    def _position_toast(self) -> None:
        if not self.toast.isVisible():
            return
        central = self.centralWidget()
        if central is None:
            return
        width = min(self.toast.sizeHint().width() + 8, 520)
        self.toast.resize(width, self.toast.sizeHint().height())
        x = max(16, central.width() - self.toast.width() - 26)
        y = max(16, central.height() - self.toast.height() - 26)
        self.toast.move(x, y)

    # ------------------------------------------------------------------ language

    def _on_language_changed(self, _language: str) -> None:
        self._retranslate()
        for page in self.pages.values():
            if hasattr(page, "retranslate"):
                page.retranslate()

    def _retranslate(self) -> None:
        self.tagline.setText(tr("app.tagline"))
        for key, button in self.nav_buttons.items():
            button.setText(tr(f"nav.{key}"))
        self.core_pill.retranslate()
        self.ai_pill.retranslate()

    # ------------------------------------------------------------------ window

    def _restore_geometry(self) -> None:
        geometry = self.settings.value("ui/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_toast()

    def closeEvent(self, event: QCloseEvent) -> None:
        for page in self.pages.values():
            if hasattr(page, "on_hidden"):
                page.on_hidden()
        self.settings.setValue("ui/geometry", self.saveGeometry())
        self.settings.sync()
        self._status_timer.stop()
        event.accept()
