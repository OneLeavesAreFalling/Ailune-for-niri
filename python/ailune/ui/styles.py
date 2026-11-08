"""Application-wide Qt stylesheet."""

from __future__ import annotations

STYLESHEET = """
* {
    font-family: "Noto Sans", "Noto Sans CJK SC", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow, QWidget#Root {
    background: #14111f;
    color: #ece7f7;
}
QWidget {
    color: #ece7f7;
}
QFrame#Sidebar {
    background: #191426;
    border-right: 1px solid #2a2340;
}
QLabel#Brand {
    font-size: 26px;
    font-weight: 700;
    color: #f4ecff;
    letter-spacing: 1px;
}
QLabel#Tagline {
    color: #9388b4;
    font-size: 12px;
}
QLabel#PageTitle {
    font-size: 24px;
    font-weight: 700;
    color: #f7f2ff;
}
QLabel#PageSubtitle {
    color: #9b90ba;
    font-size: 13px;
}
QLabel#SectionTitle {
    font-size: 15px;
    font-weight: 650;
    color: #ded3fa;
    margin-top: 6px;
}
QLabel#Muted, QLabel[role="muted"] {
    color: #968ab7;
    font-size: 12px;
}
QLabel#ErrorText {
    color: #ff9fb7;
}
QLabel#WarningText {
    color: #f0c674;
}
QLabel#SuccessText {
    color: #8fe3b0;
}
QLabel#Mono {
    font-family: "JetBrains Mono", "Noto Sans Mono", monospace;
    font-size: 11px;
    color: #b8abd9;
}
QLabel#StatusPill {
    padding: 3px 9px;
    border-radius: 9px;
    background: #2a2340;
    color: #b9add8;
    font-size: 11px;
}
QLabel#StatusPill[online="true"] {
    background: rgba(96, 214, 146, 0.14);
    color: #8fe3b0;
}
QLabel#StatusPill[online="false"] {
    background: rgba(255, 120, 150, 0.12);
    color: #ff9fb7;
}
QFrame#Card {
    background: #1c172b;
    border: 1px solid #2c2444;
    border-radius: 14px;
}
QFrame#Card QLabel {
    background: transparent;
}
QFrame#Separator {
    background: #2a2340;
    max-height: 1px;
    min-height: 1px;
}
QPushButton {
    background: #29213e;
    color: #ece7f7;
    border: 1px solid #3a3057;
    border-radius: 9px;
    padding: 7px 14px;
    min-height: 18px;
}
QPushButton:hover { background: #33294c; border-color: #4b3f70; }
QPushButton:pressed { background: #241d36; }
QPushButton:disabled { color: #6f658c; background: #1f1a2f; border-color: #2a2340; }
QPushButton#Primary {
    background: #8d6be6;
    border-color: #a487f3;
    color: #171126;
    font-weight: 650;
}
QPushButton#Primary:hover { background: #a084ef; }
QPushButton#Primary:pressed { background: #7a5bd0; }
QPushButton#Danger {
    background: rgba(255, 112, 150, 0.1);
    border-color: rgba(255, 130, 165, 0.35);
    color: #ffa8bf;
}
QPushButton#Danger:hover { background: rgba(255, 112, 150, 0.18); }
QPushButton#Ghost {
    background: transparent;
    border-color: transparent;
    color: #b8abd9;
    padding: 5px 9px;
}
QPushButton#Ghost:hover { background: #241d36; color: #f0eaff; }
QToolButton#Nav {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    color: #a99ec8;
    text-align: left;
    padding: 10px 14px;
    font-size: 13px;
    font-weight: 550;
}
QToolButton#Nav:hover { background: #221b34; color: #e9e1ff; }
QToolButton#Nav:checked {
    background: #2b2242;
    border-color: #40345f;
    color: #f6efff;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #151121;
    color: #ece7f7;
    border: 1px solid #332a4c;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: #6f54b8;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #9d7bf0;
}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {
    color: #746a90;
    background: #1a1527;
}
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox QAbstractItemView {
    background: #201a31;
    color: #ece7f7;
    border: 1px solid #3a3057;
    selection-background-color: #382c55;
    outline: 0;
}
QScrollArea { border: 0; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3b3059;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #4d3f73; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 10px; background: transparent; }
QScrollBar::handle:horizontal { background: #3b3059; border-radius: 4px; min-width: 24px; }
QListWidget {
    background: transparent;
    border: 0;
    outline: 0;
}
QListWidget::item {
    background: #1c172b;
    border: 1px solid #2c2444;
    border-radius: 10px;
    padding: 9px 11px;
    margin: 3px 0;
    color: #dcd2f4;
}
QListWidget::item:selected {
    background: #30264a;
    border-color: #6c55a8;
    color: #f8f3ff;
}
QListWidget::item:hover { border-color: #4a3c6c; }
QTabWidget::pane { border: 0; }
QTabBar::tab {
    background: transparent;
    color: #9b90ba;
    padding: 8px 14px;
    border-radius: 8px;
}
QTabBar::tab:selected { background: #2a2140; color: #f2eaff; }
QCheckBox, QRadioButton { spacing: 8px; color: #d9d0ef; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #4a3d6b; background: #171222;
}
QCheckBox::indicator:checked { background: #9d7bf0; border-color: #b99aff; }
QSlider::groove:horizontal {
    height: 4px; background: #332a4c; border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -7px 0; border-radius: 8px;
    background: #b99aff;
}
QProgressBar {
    background: #201a31; border: 0; border-radius: 4px; height: 6px;
    text-align: center; color: transparent;
}
QProgressBar::chunk { background: #9d7bf0; border-radius: 4px; }
QScrollArea#ChatScroll, QScrollArea#ChatScroll > QWidget > QWidget {
    background: transparent;
}
QFrame#UserBubble {
    background: #43346c;
    border: 1px solid #5b478e;
    border-radius: 14px;
}
QFrame#AssistantBubble {
    background: #1e192e;
    border: 1px solid #322947;
    border-radius: 14px;
}
QFrame#ErrorBubble {
    background: rgba(120, 30, 55, 0.35);
    border: 1px solid rgba(255, 130, 165, 0.4);
    border-radius: 14px;
}
QLabel#BubbleRole {
    color: #bcaee0;
    font-size: 10px;
    font-weight: 650;
    letter-spacing: 0.08em;
}
QLabel#BubbleBody {
    color: #f2ecff;
    font-size: 13px;
}
QLabel#Toast {
    background: #2a2340;
    border: 1px solid #4a3d6b;
    border-radius: 10px;
    color: #f2ecff;
    padding: 10px 14px;
    font-size: 12px;
}
QLabel#Toast[kind="success"] {
    background: rgba(39, 82, 62, 0.96);
    border-color: rgba(120, 224, 166, 0.45);
    color: #d8ffe8;
}
QLabel#Toast[kind="error"] {
    background: rgba(92, 38, 54, 0.96);
    border-color: rgba(255, 140, 170, 0.45);
    color: #ffe2ea;
}
QToolTip {
    background: #241d36;
    color: #f1eaff;
    border: 1px solid #4a3c6c;
    padding: 5px 7px;
    border-radius: 6px;
}
QDialog { background: #171222; color: #ece7f7; }
QMessageBox { background: #171222; }
QStatusBar { background: #171222; color: #9b90ba; }
QSplitter::handle { background: #2a2340; width: 1px; }
"""
