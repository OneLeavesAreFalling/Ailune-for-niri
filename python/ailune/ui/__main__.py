"""Launch the Ailune PyQt6 interface."""

from __future__ import annotations

import logging
import signal
import sys

from PyQt6.QtCore import QCoreApplication, QTimer, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QApplication

from ailune import __version__
from ailune.ui.clients import AIServiceClient, ControlClient
from ailune.ui.i18n import translator
from ailune.ui.main_window import MainWindow
from ailune.ui.styles import STYLESHEET


def _make_icon() -> QIcon:
    pixmap = QPixmap(96, 96)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QRadialGradient(48, 40, 54)
    gradient.setColorAt(0.0, QColor("#d8c6ff"))
    gradient.setColorAt(0.6, QColor("#9d7bf0"))
    gradient.setColorAt(1.0, QColor("#5a4794"))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor("#2c2542"), 2))
    painter.drawEllipse(10, 10, 76, 76)
    painter.setBrush(QColor("#ffd479"))
    painter.setPen(QPen(QColor("#7a5bd0"), 1.5))
    from PyQt6.QtCore import QPointF

    star = []
    import math

    for index in range(10):
        radius = 19 if index % 2 == 0 else 8
        angle = math.pi / 5 * index - math.pi / 2
        star.append(QPointF(48 + math.cos(angle) * radius, 48 + math.sin(angle) * radius))
    from PyQt6.QtGui import QPolygonF

    painter.drawPolygon(QPolygonF(star))
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    QCoreApplication.setOrganizationName("Ailune")
    QCoreApplication.setOrganizationDomain("ailune.dev")
    QCoreApplication.setApplicationName("Ailune")
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("Ailune")
    app.setDesktopFileName("dev.ailune.Ailune")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(_make_icon())

    # QSettings and the translator need the application identity above.
    translator()

    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    signal.signal(signal.SIGTERM, lambda *_args: app.quit())
    # Python signal handlers only run while the interpreter has control.
    pulse = QTimer()
    pulse.start(250)
    pulse.timeout.connect(lambda: None)

    control = ControlClient()
    ai = AIServiceClient()
    window = MainWindow(control, ai)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
