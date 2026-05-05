from __future__ import annotations

import json
import locale
import os
from pathlib import Path
from string import Formatter
from typing import Any


DEFAULT_LOCALE = "en-US"
LOCALES_PATH = Path(__file__).resolve().parent / "locales"


def system_locale() -> str:
    override = os.environ.get("DOCANONYMIZER_LOCALE")
    if override:
        return override
    current, _encoding = locale.getlocale()
    return current or DEFAULT_LOCALE


def normalize_locale(value: str | None) -> str:
    if not value:
        return DEFAULT_LOCALE
    normalized = value.replace("_", "-")
    language = normalized.split("-", 1)[0].casefold()
    if language == "de":
        return "de"
    if language == "en":
        return "en-US"
    language_tag = _language_tag(normalized)
    if (LOCALES_PATH / f"{language_tag}.json").exists():
        return language_tag
    if (LOCALES_PATH / f"{language}.json").exists():
        return language
    return DEFAULT_LOCALE


def _language_tag(value: str) -> str:
    parts = value.split("-")
    if len(parts) == 1:
        return parts[0].casefold()
    return f"{parts[0].casefold()}-{parts[1].upper()}"


class Translator:
    def __init__(self, locale_name: str | None = None) -> None:
        self.locale = normalize_locale(locale_name or system_locale())
        self._fallback = self._load(DEFAULT_LOCALE)
        self._translations = self._load(self.locale)

    def text(self, key: str, **values: Any) -> str:
        template = self._translations.get(key) or self._fallback.get(key) or key
        if not values:
            return template
        return template.format_map(_SafeFormatValues(values))

    def _load(self, locale_name: str) -> dict[str, str]:
        path = LOCALES_PATH / f"{locale_name}.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return {str(key): str(value) for key, value in data.items()}


class _SafeFormatValues(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def translation_placeholders(template: str) -> set[str]:
    return {
        field_name
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(template)
        if field_name
    }
