"""Reusable Qt widgets and async helpers."""

from __future__ import annotations

import html
from typing import Any, Callable

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ailune.ui.clients import friendly_error
from ailune.ui.i18n import tr


class _FunctionThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            self.failed.emit(friendly_error(exc))
            return
        self.succeeded.emit(result)


def run_async(
    owner: QWidget,
    fn: Callable[[], Any],
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Run a blocking callable and deliver its result on the UI thread."""
    workers: list[_FunctionThread] = getattr(owner, "_workers", [])
    owner._workers = workers  # type: ignore[attr-defined]
    worker = _FunctionThread(fn, owner)
    workers.append(worker)

    if on_success is not None:
        worker.succeeded.connect(on_success)
    if on_error is not None:
        worker.failed.connect(on_error)
    elif hasattr(owner, "show_error"):
        worker.failed.connect(owner.show_error)  # type: ignore[attr-defined]

    def cleanup() -> None:
        if worker in workers:
            workers.remove(worker)
        if on_done is not None:
            on_done()
        worker.deleteLater()

    worker.finished.connect(cleanup)
    worker.start()


class PageHeader(QWidget):
    def __init__(
        self,
        title_key: str,
        subtitle_key: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.title_key = title_key
        self.subtitle_key = subtitle_key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(3)
        row = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        row.addWidget(self.title)
        row.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        row.addLayout(self.actions)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        layout.addLayout(row)
        layout.addWidget(self.subtitle)
        self.retranslate()

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def retranslate(self) -> None:
        self.title.setText(tr(self.title_key))
        self.subtitle.setText(tr(self.subtitle_key))


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, margins: int = 16) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(margins, margins, margins, margins)
        self.layout.setSpacing(10)


class SectionTitle(QLabel):
    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SectionTitle")
        self.key = key
        self.retranslate()

    def retranslate(self) -> None:
        self.setText(tr(self.key))


class EmptyState(QWidget):
    def __init__(
        self,
        title_key: str,
        hint_key: str,
        button_key: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.title_key = title_key
        self.hint_key = hint_key
        self.button_key = button_key
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(9)
        self.title = QLabel()
        self.title.setObjectName("SectionTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint = QLabel()
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setMaximumWidth(460)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        self.button = QPushButton() if button_key else None
        if self.button is not None:
            self.button.setObjectName("Primary")
            self.button.setFixedWidth(180)
            layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.retranslate()

    def set_keys(self, title_key: str, hint_key: str, button_key: str | None = None) -> None:
        self.title_key = title_key
        self.hint_key = hint_key
        if button_key is not None:
            self.button_key = button_key
        self.retranslate()

    def retranslate(self) -> None:
        self.title.setText(tr(self.title_key))
        self.hint.setText(tr(self.hint_key))
        if self.button is not None and self.button_key:
            self.button.setText(tr(self.button_key))


class StatusPill(QLabel):
    def __init__(self, label_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label_key = label_key
        self._online: bool | None = None
        self.setObjectName("StatusPill")
        self.setProperty("online", "false")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setMaximumWidth(170)
        self.retranslate()

    def retranslate(self) -> None:
        if self._online is True:
            state = tr("status.online")
        elif self._online is False:
            state = tr("status.offline")
        else:
            state = tr("status.checking")
        self.setText(f"{tr(self.label_key)} · {state}")

    def set_online(self, online: bool | None) -> None:
        self._online = online
        self.setProperty("online", "true" if online else "false")
        self.retranslate()
        self.style().unpolish(self)
        self.style().polish(self)


class MessageBubble(QFrame):
    def __init__(
        self,
        role: str,
        text: str = "",
        *,
        author: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.role = role
        if role == "user":
            self.setObjectName("UserBubble")
        elif role == "error":
            self.setObjectName("ErrorBubble")
        else:
            self.setObjectName("AssistantBubble")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.setMaximumWidth(720)
        self.setMinimumWidth(126 if role == "user" else 320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 11)
        layout.setSpacing(4)
        self.author = QLabel(author)
        self.author.setObjectName("BubbleRole")
        self.body = QLabel()
        self.body.setObjectName("BubbleBody")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.body.setOpenExternalLinks(True)
        self.body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.author)
        layout.addWidget(self.body)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        if self.role == "assistant":
            self.body.setTextFormat(Qt.TextFormat.MarkdownText)
            self.body.setText(text)
        else:
            self.body.setTextFormat(Qt.TextFormat.PlainText)
            self.body.setText(text)
        self.updateGeometry()

    def set_author(self, author: str) -> None:
        self.author.setText(author.upper())


class Thumbnail(QLabel):
    def __init__(self, size: int = 190, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background:#151121;border:1px solid #332a4c;border-radius:12px;color:#7f739c;"
        )
        self.setText(tr("characters.no_preview"))

    def retranslate(self) -> None:
        if self.pixmap() is None or self.pixmap().isNull():
            self.setText(tr("characters.no_preview"))

    def set_image(self, path: str | None) -> None:
        if not path:
            self.clear()
            self.setText(tr("characters.no_preview"))
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.clear()
            self.setText(tr("characters.no_preview"))
            return
        self.setText("")
        self.setPixmap(
            pixmap.scaled(
                self._size - 10,
                self._size - 10,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TiB"


def separator() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    line.setFrameShape(QFrame.Shape.HLine)
    return line


def escape(text: str) -> str:
    return html.escape(text, quote=False)
