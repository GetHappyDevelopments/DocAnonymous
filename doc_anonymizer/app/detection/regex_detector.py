from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

from doc_anonymizer.app.core.models import Finding, FindingLocation
from doc_anonymizer.app.core.placeholder_factory import PlaceholderFactory


WORD = r"[\wÄÖÜäöüß&+.'-]+"
NAME_WORD = r"[A-ZÄÖÜ][a-zäöüß]+(?:[-'][A-ZÄÖÜ]?[a-zäöüß]+)?"
COMPANY_WORD = r"[A-ZÄÖÜ0-9][\wÄÖÜäöüß&+.'-]*"
COMPANY_TOKEN = rf"(?:{COMPANY_WORD}|&)"
HSPACE = r"[ \t\u00a0]"
CONTROL_WHITESPACE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
PLZ_CITY = rf"\d{{5}}{HSPACE}+[A-ZÄÖÜ][\wÄÖÜäöüß.'-]+(?:{HSPACE}+[A-ZÄÖÜ][\wÄÖÜäöüß.'-]+){{0,2}}"


FIRST_NAMES = {
    "anna",
    "ben",
    "christian",
    "claudia",
    "daniel",
    "david",
    "elena",
    "emilia",
    "erik",
    "felix",
    "frank",
    "hans",
    "johanna",
    "julia",
    "karl",
    "katharina",
    "laura",
    "lena",
    "lisa",
    "maria",
    "markus",
    "martin",
    "max",
    "michael",
    "monika",
    "paul",
    "peter",
    "sabine",
    "sarah",
    "stefan",
    "thomas",
    "uwe",
}

COMMON_LAST_NAMES = {
    "becker",
    "fischer",
    "hofmann",
    "koch",
    "krause",
    "lange",
    "lehmann",
    "meyer",
    "mueller",
    "müller",
    "mustermann",
    "neumann",
    "richter",
    "schäfer",
    "schmidt",
    "schneider",
    "schulz",
    "schwarz",
    "weber",
    "wagner",
    "wolf",
}

CITY_NAMES = {
    "berlin",
    "bielefeld",
    "bonn",
    "bremen",
    "dortmund",
    "dresden",
    "duesseldorf",
    "düsseldorf",
    "essen",
    "frankfurt",
    "hamburg",
    "hannover",
    "koeln",
    "köln",
    "leipzig",
    "muenchen",
    "münchen",
    "nuernberg",
    "nürnberg",
    "stuttgart",
}

COMPANY_TRIGGERS = {
    "auftraggeber",
    "auftragnehmer",
    "dienstleister",
    "firma",
    "gesellschaft",
    "kunde",
    "lieferant",
    "unternehmen",
    "vertragspartner",
}

PERSON_TRIGGERS = {
    "ansprechpartner",
    "bearbeiter",
    "geschäftsführer",
    "geschaeftsfuehrer",
    "inhaber",
    "kontakt",
    "mitarbeiter",
    "sachbearbeiter",
    "vertreten",
}

LEGAL_FORM_REGEX = (
    r"GmbH|AG|UG|KG|OHG|GbR|SE|e\.?\s?K\.?|e\.?\s?V\.?|mbH|GmbH\s*&\s*Co\.?\s*KG|"
    r"UG\s*\(haftungsbeschränkt\)|UG\s*\(haftungsbeschraenkt\)|Aktiengesellschaft|"
    r"Gesellschaft\s+mit\s+beschränkter\s+Haftung|Gesellschaft\s+mit\s+beschraenkter\s+Haftung"
)


@dataclass(frozen=True)
class DetectionRule:
    category: str
    sub_category: str | None
    confidence: float
    pattern: re.Pattern[str]


class RegexDetector:
    def __init__(self) -> None:
        self._patterns: list[DetectionRule] = [
            DetectionRule("email", None, 0.99, re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
            DetectionRule("url", None, 0.95, re.compile(r"\bhttps?://[^\s<>\"]+", re.I)),
            DetectionRule("iban", None, 0.98, re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b")),
            DetectionRule("phone", None, 0.78, re.compile(r"(?<!\w)(?:\+49|0049|0)[\d\s()/.-]{7,}\d(?!\w)")),
            DetectionRule(
                "address",
                None,
                0.88,
                re.compile(
                    rf"\b[A-ZÄÖÜ][\wÄÖÜäöüß.'-]*(?:straße|strasse|str\.|weg|platz|allee|gasse|ring|ufer|damm|chaussee|hof|markt){HSPACE}+"
                    rf"\d+[a-zA-Z]?(?:{HSPACE}*,?{HSPACE}*{PLZ_CITY})?\b",
                ),
            ),
            DetectionRule(
                "company",
                None,
                0.91,
                re.compile(
                    rf"\b{COMPANY_WORD}(?:{HSPACE}+{COMPANY_TOKEN}){{0,8}}{HSPACE}+(?:{LEGAL_FORM_REGEX})\b",
                ),
            ),
            DetectionRule(
                "company",
                None,
                0.78,
                re.compile(
                    rf"\b(?:Firma|Unternehmen|Auftragnehmer|Auftraggeber|Lieferant|Kunde)\s+"
                    rf"{COMPANY_WORD}(?:{HSPACE}+{COMPANY_WORD}){{0,5}}\b",
                    re.I,
                ),
            ),
            DetectionRule(
                "authority",
                None,
                0.84,
                re.compile(
                    rf"\b(?:Amtsgericht|Landgericht|Oberlandesgericht|Finanzamt|Stadt|Gemeinde|Landkreis|Ministerium|Behörde|Behoerde)\s+"
                    rf"[A-ZÄÖÜ][\wÄÖÜäöüß.'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.'-]+)?\b"
                ),
            ),
            DetectionRule(
                "association",
                None,
                0.79,
                re.compile(
                    rf"\b(?:Verein|Verband|Initiative|Stiftung)\s+"
                    rf"[A-ZÄÖÜ][\wÄÖÜäöüß.'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.'-]+){{0,3}}\b"
                ),
            ),
            DetectionRule(
                "group",
                None,
                0.68,
                re.compile(
                    rf"\b(?:Projektteam|Arbeitsgruppe|Team|Gruppe|Teilnehmerkreis)\s+"
                    rf"[A-ZÄÖÜ][\wÄÖÜäöüß.'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.'-]+){{0,2}}\b"
                ),
            ),
            DetectionRule(
                "person",
                None,
                0.82,
                re.compile(
                    rf"\b(?:Herr|Frau|Dr\.|Prof\.|Professor|Rechtsanwalt|Rechtsanwältin|RA|RAin)\s+"
                    rf"(?:(?:Dr\.|Prof\.|Professor)\s+){{0,2}}{NAME_WORD}(?:\s+{NAME_WORD}){{0,2}}\b"
                ),
            ),
            DetectionRule(
                "person",
                None,
                0.67,
                re.compile(rf"\b{NAME_WORD}{HSPACE}+{NAME_WORD}(?:{HSPACE}+{NAME_WORD})?\b"),
            ),
            DetectionRule("reference", None, 0.7, re.compile(r"\b(?:AZ|Az\.|Aktenzeichen|Vertrag|Kunde|KdNr)\s*[:#]?\s*[A-Z0-9/-]{3,}\b")),
        ]

    def scan(self, text: str, part: str = "body") -> list[Finding]:
        findings: list[Finding] = []
        for rule in self._patterns:
            for match in rule.pattern.finditer(text):
                value = self._clean_value(match.group(0))
                start = match.start()
                end = match.end()
                if rule.category == "company":
                    value, start, end = self._trim_company_prefix(value, start, end)
                if len(value) < 3:
                    continue
                confidence = self._score(value, rule.category, rule.confidence, text, start, end)
                if not self._passes_threshold(value, rule.category, confidence):
                    continue
                findings.append(self._finding(value, rule.category, rule.sub_category, confidence, part, start, end, "rule"))

        findings.extend(self._scan_address_blocks(text, part))
        findings.extend(self._scan_spacy(text, part))
        return findings

    def _scan_address_blocks(self, text: str, part: str) -> list[Finding]:
        findings: list[Finding] = []
        lines = list(re.finditer(r"[^\r\n]+", text))
        street_pattern = re.compile(
            r"\b[A-ZÄÖÜ][\wÄÖÜäöüß.'-]*(?:straße|strasse|str\.|weg|platz|allee|gasse|ring|ufer|damm|chaussee|hof|markt)\s+\d+[a-zA-Z]?\b",
            re.I,
        )
        city_pattern = re.compile(rf"\b{PLZ_CITY}\b")
        for idx, line in enumerate(lines):
            street_match = street_pattern.search(line.group(0))
            if not street_match:
                continue
            start = line.start() + street_match.start()
            end = line.end()
            confidence = 0.88
            if idx + 1 < len(lines) and city_pattern.search(lines[idx + 1].group(0)):
                end = lines[idx + 1].end()
                confidence = 0.94
            if idx > 0 and self._looks_like_person_name(lines[idx - 1].group(0).strip()):
                start = lines[idx - 1].start()
                confidence = max(confidence, 0.9)
            value = self._clean_value(text[start:end])
            findings.append(self._finding(value, "address", None, confidence, part, start, end, "address-block"))
        return findings

    def _scan_spacy(self, text: str, part: str) -> list[Finding]:
        nlp = self._spacy_nlp
        if nlp is None:
            return []
        findings: list[Finding] = []
        for ent in nlp(text).ents:
            mapped = {"PER": "person", "PERSON": "person", "ORG": "company", "LOC": "address", "GPE": "address"}.get(ent.label_)
            if not mapped:
                continue
            value = self._clean_value(ent.text)
            confidence = self._score(value, mapped, 0.72, text, ent.start_char, ent.end_char)
            if self._passes_threshold(value, mapped, confidence):
                findings.append(self._finding(value, mapped, None, confidence, part, ent.start_char, ent.end_char, "ner"))
        return findings

    @cached_property
    def _spacy_nlp(self):
        try:
            import spacy
        except ImportError:
            return None
        for model_name in ("de_core_news_lg", "de_core_news_md", "de_core_news_sm"):
            try:
                return spacy.load(model_name)
            except OSError:
                continue
        return None

    def _score(self, value: str, category: str, base: float, text: str, start: int, end: int) -> float:
        context = text[max(0, start - 80) : min(len(text), end + 80)].casefold()
        score = base
        if category == "person":
            parts = self._name_parts(value)
            if any(part in FIRST_NAMES for part in parts):
                score += 0.14
            if any(part in COMMON_LAST_NAMES for part in parts):
                score += 0.08
            if any(trigger in context for trigger in PERSON_TRIGGERS):
                score += 0.12
            if re.search(r"\b(?:Herr|Frau|Dr\.|Prof\.|Professor|RA|RAin)\b", value):
                score += 0.1
        elif category == "company":
            if re.search(LEGAL_FORM_REGEX, value, re.I):
                score += 0.12
            if any(trigger in context for trigger in COMPANY_TRIGGERS):
                score += 0.08
        elif category == "address":
            if re.search(r"\b\d{5}\b", value):
                score += 0.08
            if any(city in value.casefold() for city in CITY_NAMES):
                score += 0.05
            if "\n" in value:
                score += 0.04
        return max(0.0, min(score, 0.99))

    def _passes_threshold(self, value: str, category: str, confidence: float) -> bool:
        if self._is_false_positive(value):
            return False
        thresholds = {"person": 0.7, "company": 0.74, "address": 0.78}
        if confidence < thresholds.get(category, 0.0):
            return False
        if category == "person" and not self._looks_like_person_name(value):
            return False
        return True

    @staticmethod
    def _is_false_positive(value: str) -> bool:
        words = {word.casefold().strip(".") for word in re.findall(r"\w+", value)}
        blocked = {
            "anlage",
            "april",
            "august",
            "betreff",
            "dezember",
            "dienstag",
            "donnerstag",
            "februar",
            "freitag",
            "januar",
            "juli",
            "juni",
            "mai",
            "märz",
            "maerz",
            "mittwoch",
            "montag",
            "november",
            "oktober",
            "rechnung",
            "samstag",
            "sonntag",
            "vertrag",
        }
        return bool(words & blocked)

    @classmethod
    def _looks_like_person_name(cls, value: str) -> bool:
        clean = re.sub(r"\b(?:Herr|Frau|Dr\.|Prof\.|Professor|Rechtsanwalt|Rechtsanwältin|RA|RAin)\s+", "", value).strip()
        parts = cls._name_parts(clean)
        if len(parts) < 2 or len(parts) > 3:
            return False
        if any(part in FIRST_NAMES for part in parts) or any(part in COMMON_LAST_NAMES for part in parts):
            return True
        return all(re.match(r"^[a-zäöüß]{3,}$", part) for part in parts)

    @staticmethod
    def _name_parts(value: str) -> list[str]:
        return [part.casefold() for part in re.findall(r"[A-ZÄÖÜ]?[a-zäöüß]{2,}", value)]

    @staticmethod
    def _clean_value(value: str) -> str:
        value = CONTROL_WHITESPACE_RE.sub(" ", value)
        return re.sub(r"[ \t\u00a0]+", " ", value).strip(" \t\r\n,;:.")

    @staticmethod
    def _trim_company_prefix(value: str, start: int, end: int) -> tuple[str, int, int]:
        match = re.match(r"^(?:Die|Der|Das)\s+", value)
        if not match:
            return value, start, end
        return value[match.end() :], start + match.end(), end

    @staticmethod
    def _finding(
        value: str,
        category: str,
        sub_category: str | None,
        confidence: float,
        part: str,
        start: int,
        end: int,
        source: str,
    ) -> Finding:
        effective_sub = sub_category
        if category == "company":
            effective_sub = sub_category or PlaceholderFactory.infer_company_sub_category(value)
        return Finding(
            original_text=value,
            replacement_text="",
            category=category,
            sub_category=effective_sub,
            confidence=confidence,
            source=source,
            locations=[FindingLocation(part=part, character_start=start, character_end=end)],
        )
