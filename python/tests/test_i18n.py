from __future__ import annotations

import json
import re
from pathlib import Path

UI_DIR = Path(__file__).resolve().parents[1] / "ailune" / "ui"
I18N_DIR = UI_DIR / "i18n"

PATTERNS = [
    re.compile(r'\btr\(\s*"([^"]+)"'),
    re.compile(r'\bPageHeader\(\s*"([^"]+)"\s*,\s*"([^"]+)"'),
    re.compile(r'\bSectionTitle\(\s*"([^"]+)"'),
    re.compile(r'\bEmptyState\(\s*"([^"]+)"\s*,\s*"([^"]+)"'),
    re.compile(r'\bStatusPill\(\s*"([^"]+)"'),
]


def load(language: str) -> dict[str, str]:
    return json.loads((I18N_DIR / f"{language}.json").read_text(encoding="utf-8"))


def test_catalogs_have_the_same_keys():
    en = load("en")
    zh = load("zh_CN")
    assert set(en) == set(zh), f"missing zh keys: {set(en) - set(zh)}; missing en keys: {set(zh) - set(en)}"


def test_every_literal_key_exists():
    en = load("en")
    zh = load("zh_CN")
    missing: list[tuple[str, str]] = []
    for path in UI_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        keys: set[str] = set()
        for pattern in PATTERNS:
            for match in pattern.finditer(text):
                for group in match.groups():
                    keys.add(group)
        for key in keys:
            if key not in en or key not in zh:
                missing.append((str(path.relative_to(UI_DIR)), key))
    assert not missing, f"missing translation keys: {missing}"


def test_dynamic_error_keys_exist():
    en = load("en")
    codes = {
        "network", "api", "unauthorized", "service_unavailable", "no_provider",
        "empty_message", "character_not_found", "conversation_not_found",
        "personality_not_found", "not_found", "validation_error", "provider_test_failed",
        "auth", "rate_limit", "timeout", "network_provider", "server_error", "http_error",
        "bad_response", "empty_reply", "too_long", "secret_store_error", "internal",
        "invalid_config", "job_failed", "generic",
    }
    for code in codes:
        assert f"errors.{code}" in en, code
    for key in ("chat.open_characters", "chat.open_providers", "providers.remove_key"):
        assert key in en
