"""Small JSON-backed translation layer for the Qt interface.

Qt's .qm pipeline would require lrelease during packaging. A JSON catalog keeps
translation edits reviewable and lets the UI switch language at runtime without
rebuilding resources. The language manager is the single entry point for all
user-facing text.
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

DEFAULT_LANGUAGE = "en"
LANGUAGES = ("en", "zh_CN")


class Translator(QObject):
    language_changed = pyqtSignal(str)

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self._settings = settings or QSettings()
        self._catalogs: dict[str, dict[str, str]] = {}
        directory = Path(__file__).parent / "i18n"
        for language in LANGUAGES:
            path = directory / f"{language}.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            self._catalogs[language] = {str(k): str(v) for k, v in data.items()}
        saved = str(self._settings.value("ui/language", DEFAULT_LANGUAGE))
        self._language = saved if saved in LANGUAGES else DEFAULT_LANGUAGE

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str, persist: bool = True) -> None:
        if language not in LANGUAGES:
            language = DEFAULT_LANGUAGE
        if language == self._language:
            return
        self._language = language
        if persist:
            self._settings.setValue("ui/language", language)
            self._settings.sync()
        self.language_changed.emit(language)

    def has(self, key: str) -> bool:
        return key in self._catalogs.get(self._language, {}) or key in self._catalogs[DEFAULT_LANGUAGE]

    def text(self, key: str, **kwargs: object) -> str:
        value = self._catalogs.get(self._language, {}).get(key)
        if value is None:
            value = self._catalogs[DEFAULT_LANGUAGE].get(key, key)
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, ValueError):
                return value
        return value

    def language_label(self, language: str) -> str:
        return self.text(f"lang.{language}" if language in LANGUAGES else "lang.en")


_translator: Translator | None = None


def translator() -> Translator:
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def tr(key: str, **kwargs: object) -> str:
    return translator().text(key, **kwargs)


def set_language(language: str) -> None:
    translator().set_language(language)
