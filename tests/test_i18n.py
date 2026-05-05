import json

from doc_anonymizer.app.i18n import LOCALES_PATH, Translator, normalize_locale, translation_placeholders


def _locale_data(locale_name: str) -> dict[str, str]:
    return json.loads((LOCALES_PATH / f"{locale_name}.json").read_text(encoding="utf-8"))


def test_locale_normalization_uses_german_english_and_english_fallback() -> None:
    assert normalize_locale("de_DE") == "de"
    assert normalize_locale("en_GB") == "en-US"
    assert normalize_locale("fr_FR") == "fr"
    assert normalize_locale("es_ES") == "es"
    assert normalize_locale("it_IT") == "en-US"


def test_translator_falls_back_to_english_for_unsupported_system_languages() -> None:
    translator = Translator("it-IT")

    assert translator.locale == "en-US"
    assert translator.text("action.add_files") == "Files"


def test_locale_files_have_matching_keys_and_placeholders() -> None:
    english = _locale_data("en-US")

    for locale_name in ("de", "fr", "es"):
        translated = _locale_data(locale_name)
        assert set(translated) == set(english)
        for key, english_text in english.items():
            assert translation_placeholders(translated[key]) == translation_placeholders(english_text)


def test_french_translator_loads_french_texts() -> None:
    translator = Translator("fr-FR")

    assert translator.locale == "fr"
    assert translator.text("action.add_files") == "Fichiers"


def test_spanish_translator_loads_spanish_texts() -> None:
    translator = Translator("es-ES")

    assert translator.locale == "es"
    assert translator.text("action.add_files") == "Archivos"
