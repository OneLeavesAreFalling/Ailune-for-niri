"""Import dialog and model report rendering."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ailune.models.manifest import ModelManifest, validate_model
from ailune.ui.i18n import tr
from ailune.ui.widgets import format_bytes


def issue_text(issue: dict[str, Any]) -> str:
    code = str(issue.get("code") or "")
    path = str(issue.get("path") or "")
    if code in {
        "no_motions",
        "no_expressions",
        "no_eyeblink",
        "no_lipsync",
        "too_large",
    }:
        key = "model.issue.too_large" if code == "too_large" else f"model.issue.{code}"
        return tr(key)
    if code in {"entry_json"} or code.endswith("_json"):
        return tr("model.issue.json")
    if code in {"references_missing", "entry_shape", "expressions_shape", "expression_shape", "motions_shape", "motion_group_shape", "motion_shape"}:
        return tr("model.issue.shape") + (f" ({code})" if code else "")
    if code.endswith("_file_missing"):
        return tr("model.issue.file_missing", path=path or code)
    if code.endswith("_outside_root"):
        return tr("model.issue.outside_root", path=path or code)
    if code.endswith("_extension"):
        return tr("model.issue.extension", path=path or code)
    if code.endswith("_missing"):
        return tr("model.issue.missing", path=path or code)
    return tr("model.issue.other", message=str(issue.get("message") or code))


def report_html(report: ModelManifest | dict[str, Any]) -> str:
    data = report.to_dict() if isinstance(report, ModelManifest) else report
    ok = bool(data.get("ok"))
    counts = data.get("counts") or {}
    errors = data.get("errors") or []
    warnings = data.get("warnings") or []
    title = tr("characters.valid") if ok else tr("characters.invalid")
    color = "#8fe3b0" if ok else "#ff9fb7"
    pieces = [
        f'<div style="color:{color};font-weight:600;font-size:14px;">{html.escape(title)}</div>',
        "<p style='color:#9b90ba;margin:6px 0;'>"
        f"{tr('characters.textures')}: {counts.get('textures', 0)} · "
        f"{tr('characters.motions')}: {counts.get('motions', 0)} · "
        f"{tr('characters.expressions')}: {counts.get('expressions', 0)} · "
        f"{tr('characters.model_size')}: {format_bytes(int(data.get('total_bytes') or 0))}"
        "</p>",
    ]
    if errors:
        pieces.append(f'<div style="color:#ff9fb7;font-weight:600;">{html.escape(tr("characters.errors"))}</div><ul>')
        for issue in errors[:12]:
            pieces.append(f"<li>{html.escape(issue_text(issue))}</li>")
        pieces.append("</ul>")
    if warnings:
        pieces.append(f'<div style="color:#f0c674;font-weight:600;">{html.escape(tr("characters.warnings"))}</div><ul>')
        for issue in warnings[:12]:
            pieces.append(f"<li>{html.escape(issue_text(issue))}</li>")
        pieces.append("</ul>")
    if ok and not warnings:
        pieces.append(f'<p style="color:#8fe3b0;">{html.escape(tr("dialog.import_valid"))}</p>')
    return "".join(pieces)


class ImportDialog(QDialog):
    def __init__(
        self,
        entries: list[Path],
        personalities: list[dict[str, Any]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.import_title"))
        self.setMinimumWidth(680)
        self.entries = entries
        self.report: ModelManifest | None = None
        self._personalities = personalities
        self.result_data: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel(tr("dialog.import_title"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(16)
        self.preview = QLabel()
        self.preview.setFixedSize(176, 176)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "background:#151121;border:1px solid #332a4c;border-radius:12px;color:#7f739c;"
        )
        self.preview.setText(tr("characters.no_preview"))
        top.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)

        form = QFormLayout()
        form.setSpacing(9)
        self.entry_combo = QComboBox()
        for entry in entries:
            try:
                label = entry.relative_to(entries[0].parent).as_posix()
            except ValueError:
                label = entry.name
            self.entry_combo.addItem(label, str(entry))
        self.entry_combo.currentIndexChanged.connect(self._scan)
        self.name_edit = QLineEdit()
        self.personality_combo = QComboBox()
        self.personality_combo.addItem(tr("characters.unknown_personality"), None)
        for personality in personalities:
            self.personality_combo.addItem(personality.get("name") or "—", personality.get("id"))
        self.reply_combo = QComboBox()
        self.reply_combo.addItem(tr("characters.replies_auto"), "auto")
        self.reply_combo.addItem(tr("characters.replies_en"), "en")
        self.reply_combo.addItem(tr("characters.replies_zh"), "zh_CN")
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.5, 2.0)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setValue(1.0)
        self.copy_check = QCheckBox(tr("characters.copy_library"))
        self.copy_check.setChecked(False)
        copy_hint = QLabel(tr("characters.copy_hint"))
        copy_hint.setObjectName("Muted")
        copy_hint.setWordWrap(True)
        form.addRow(tr("dialog.import_summary"), self.entry_combo)
        form.addRow(tr("dialog.import_name"), self.name_edit)
        form.addRow(tr("dialog.import_personality"), self.personality_combo)
        form.addRow(tr("dialog.import_reply"), self.reply_combo)
        form.addRow(tr("dialog.import_scale"), self.scale_spin)
        form.addRow(self.copy_check)
        form.addRow(copy_hint)
        top.addLayout(form, 1)
        layout.addLayout(top)

        self.report_view = QTextBrowser()
        self.report_view.setMinimumHeight(150)
        self.report_view.setMaximumHeight(230)
        self.report_view.setOpenExternalLinks(False)
        self.report_view.setStyleSheet(
            "QTextBrowser{background:#151121;border:1px solid #332a4c;border-radius:10px;"
            "color:#d9d0ef;padding:8px;}"
        )
        layout.addWidget(self.report_view)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("characters.import"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)

        self._scan()

    def _scan(self) -> None:
        entry = self.entry_combo.currentData()
        if not entry:
            return
        entry_path = Path(str(entry))
        self.report = validate_model(entry_path.parent, entry_path)
        self.report_view.setHtml(report_html(self.report))
        if not self.name_edit.text().strip():
            self.name_edit.setText(self.report.name)
        if self.report.thumbnail:
            pixmap = QPixmap(str(self.report.thumbnail))
            if not pixmap.isNull():
                self.preview.setPixmap(
                    pixmap.scaled(
                        166,
                        166,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.preview.setText("")
        else:
            self.preview.clear()
            self.preview.setText(tr("characters.no_preview"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.report.ok)

    def accept(self) -> None:
        if self.report is None or not self.report.ok:
            return
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, tr("common.required"), tr("dialog.import_name"))
            return
        self.result_data = {
            "name": name,
            "report": self.report,
            "personality_id": self.personality_combo.currentData(),
            "reply_language": self.reply_combo.currentData(),
            "scale": self.scale_spin.value(),
            "copy": self.copy_check.isChecked(),
        }
        super().accept()
