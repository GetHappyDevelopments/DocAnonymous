from __future__ import annotations

import re
from collections import defaultdict


LEGAL_FORM_PATTERNS = [
    ("GmbH", re.compile(r"\bGmbH\b", re.IGNORECASE)),
    ("AG", re.compile(r"\bAG\b", re.IGNORECASE)),
    ("UG", re.compile(r"\bUG\b", re.IGNORECASE)),
    ("KG", re.compile(r"\bKG\b", re.IGNORECASE)),
    ("OHG", re.compile(r"\bOHG\b", re.IGNORECASE)),
    ("GbR", re.compile(r"\bGbR\b", re.IGNORECASE)),
    ("e.V.", re.compile(r"\be\.?\s?V\.?\b", re.IGNORECASE)),
]


class PlaceholderFactory:
    def __init__(self) -> None:
        self._known: dict[tuple[str, str | None, str], str] = {}
        self._counters: defaultdict[tuple[str, str | None], int] = defaultdict(int)

    def replacement_for(self, original: str, category: str, sub_category: str | None) -> str:
        normalized = self._normalize(original)
        key = (category, sub_category, normalized)
        if key in self._known:
            return self._known[key]

        counter_key = (category, sub_category)
        self._counters[counter_key] += 1
        label = self._label(category, sub_category)
        value = f"{label} {self._counters[counter_key]}"
        self._known[key] = value
        return value

    @staticmethod
    def infer_company_sub_category(text: str) -> str | None:
        for label, pattern in LEGAL_FORM_PATTERNS:
            if pattern.search(text):
                return label
        return None

    @staticmethod
    def canonical_entity_text(text: str, category: str, sub_category: str | None = None) -> str:
        value = re.sub(r"\s+", " ", text).strip()
        value = value.replace("Aktiengesellschaft", "AG")
        value = re.sub(r"\bGesellschaft mit beschraenkter Haftung\b", "GmbH", value, flags=re.I)
        value = re.sub(r"\bGesellschaft mit beschränkter Haftung\b", "GmbH", value, flags=re.I)
        value = re.sub(r"\be\.?\s?V\.?\b", "e.V.", value, flags=re.I)
        if category == "company" and sub_category:
            # Keep the legal form for the sub-category bucket, but normalize name variants.
            value = re.sub(rf"\b{re.escape(sub_category)}\b\.?", sub_category, value, flags=re.I)
        if category == "person":
            value = re.sub(r"\b(?:Herr|Frau|Dr\.|Prof\.|Professor)\s+", "", value, flags=re.I)
        return value.casefold()

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().casefold()

    @staticmethod
    def _label(category: str, sub_category: str | None) -> str:
        labels = {
            "person": "Person",
            "company": "Firma",
            "authority": "Behoerde",
            "association": "Verein",
            "group": "Gruppe",
            "address": "Adresse",
            "email": "E-Mail",
            "phone": "Telefon",
            "url": "URL",
            "iban": "IBAN",
            "reference": "Aktenzeichen",
            "custom": "Wert",
        }
        base = labels.get(category, "Wert")
        if category == "company" and sub_category:
            return f"{base} {sub_category}"
        return base
