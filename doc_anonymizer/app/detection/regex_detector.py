from __future__ import annotations

import re

from doc_anonymizer.app.core.models import Finding, FindingLocation
from doc_anonymizer.app.core.placeholder_factory import PlaceholderFactory


class RegexDetector:
    def __init__(self) -> None:
        self._patterns: list[tuple[str, str | None, float, re.Pattern[str]]] = [
            ("email", None, 0.99, re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
            ("url", None, 0.95, re.compile(r"\bhttps?://[^\s<>\"]+", re.I)),
            ("iban", None, 0.98, re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b")),
            ("phone", None, 0.78, re.compile(r"(?<!\w)(?:\+49|0049|0)[\d\s()/.-]{7,}\d(?!\w)")),
            (
                "address",
                None,
                0.82,
                re.compile(
                    r"\b[A-ZÄÖÜ][\wÄÖÜäöüß.-]+(?:strasse|straße|str\.|weg|platz|allee|gasse|ring|ufer|damm|chaussee)\s+\d+[a-zA-Z]?"
                    r"(?:\s*,?\s*\d{5}\s+[A-ZÄÖÜ][\wÄÖÜäöüß.-]+)?\b"
                ),
            ),
            (
                "company",
                None,
                0.88,
                re.compile(
                    r"\b[A-ZÄÖÜ][\wÄÖÜäöüß&+.-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß&+.-]*){0,5}\s+"
                    r"(?:GmbH|AG|UG|KG|OHG|GbR|e\.?\s?V\.?)\b"
                ),
            ),
            (
                "company",
                "AG",
                0.86,
                re.compile(
                    r"\b[A-ZÄÖÜ][\wÄÖÜäöüß&+.-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß&+.-]*){0,5}\s+"
                    r"Aktiengesellschaft\b"
                ),
            ),
            (
                "authority",
                None,
                0.82,
                re.compile(
                    r"\b(?:Amtsgericht|Landgericht|Oberlandesgericht|Finanzamt|Stadt|Gemeinde|Landkreis|Ministerium|Behörde|Behoerde)\s+"
                    r"[A-ZÄÖÜ][\wÄÖÜäöüß.-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.-]+)?\b"
                ),
            ),
            (
                "association",
                None,
                0.78,
                re.compile(
                    r"\b(?:Verein|Verband|Initiative|Stiftung)\s+"
                    r"[A-ZÄÖÜ][\wÄÖÜäöüß.-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.-]+){0,3}\b"
                ),
            ),
            (
                "group",
                None,
                0.68,
                re.compile(
                    r"\b(?:Projektteam|Arbeitsgruppe|Team|Gruppe|Teilnehmerkreis)\s+"
                    r"[A-ZÄÖÜ][\wÄÖÜäöüß.-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.-]+){0,2}\b"
                ),
            ),
            (
                "person",
                None,
                0.64,
                re.compile(
                    r"\b(?:Herr|Frau|Dr\.|Prof\.|Professor)\s+"
                    r"[A-ZÄÖÜ][a-zäöüß-]+(?:\s+[A-ZÄÖÜ][a-zäöüß-]+)?\b"
                ),
            ),
            (
                "person",
                None,
                0.58,
                re.compile(
                    r"\b[A-ZÄÖÜ][a-zäöüß-]{2,}\s+[A-ZÄÖÜ][a-zäöüß-]{2,}\b"
                ),
            ),
            ("reference", None, 0.7, re.compile(r"\b(?:AZ|Az\.|Aktenzeichen|Vertrag|Kunde|KdNr)\s*[:#]?\s*[A-Z0-9/-]{3,}\b")),
        ]

    def scan(self, text: str, part: str = "body") -> list[Finding]:
        findings: list[Finding] = []
        for category, sub_category, confidence, pattern in self._patterns:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                if len(value) < 3:
                    continue
                effective_sub = sub_category
                if category == "company":
                    effective_sub = sub_category or PlaceholderFactory.infer_company_sub_category(value)
                findings.append(
                    Finding(
                        original_text=value,
                        replacement_text="",
                        category=category,
                        sub_category=effective_sub,
                        confidence=confidence,
                        source="rule",
                        locations=[
                            FindingLocation(
                                part=part,
                                character_start=match.start(),
                                character_end=match.end(),
                            )
                        ],
                    )
                )
        return findings
