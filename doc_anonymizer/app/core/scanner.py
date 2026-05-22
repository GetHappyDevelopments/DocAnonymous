from __future__ import annotations

import re
from collections import OrderedDict

from doc_anonymizer.app.core.models import DocumentJob, Finding
from doc_anonymizer.app.core.models import FindingLocation
from doc_anonymizer.app.core.placeholder_factory import PlaceholderFactory
from doc_anonymizer.app.detection.llm_plugin import LocalLlmAnalyzer
from doc_anonymizer.app.detection.regex_detector import RegexDetector
from doc_anonymizer.app.formats import get_handler


CONTROL_WHITESPACE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")


class DocumentScanner:
    def __init__(self, llm_analyzer: LocalLlmAnalyzer | None = None) -> None:
        self.regex_detector = RegexDetector()
        self.llm_analyzer = llm_analyzer or LocalLlmAnalyzer()

    def scan(self, job: DocumentJob) -> list[Finding]:
        review_state = {
            self._review_key(finding): (finding.correct, finding.incorrect)
            for finding in job.findings
            if finding.correct or finding.incorrect
        }
        handler = get_handler(job.source_path)
        chunks = handler.extract_text(job.source_path)
        raw_findings: list[Finding] = []
        learned_findings = [finding for finding in job.findings if finding.source in {"manual", "learned"}]
        for chunk in chunks:
            raw_findings.extend(self.regex_detector.scan(chunk.text, chunk.part))
            raw_findings.extend(self.llm_analyzer.analyze_text(chunk.text, {"part": chunk.part}))
            raw_findings.extend(self._find_learned_entities(chunk.text, chunk.part, learned_findings))

        raw_findings.extend(self._propagate_document_entities(raw_findings, chunks))

        raw_findings = [finding for finding in self._clean_findings(raw_findings) if finding.original_text]
        job.findings = self._apply_review_state(self._merge_and_assign_placeholders(raw_findings), review_state)
        job.status = "Scan abgeschlossen"
        return job.findings

    @staticmethod
    def _clean_findings(findings: list[Finding]) -> list[Finding]:
        for finding in findings:
            finding.original_text = CONTROL_WHITESPACE_RE.sub(" ", finding.original_text)
            finding.original_text = re.sub(r"[ \t\u00a0]+", " ", finding.original_text).strip(" \t\r\n,;:.")
        return findings

    @classmethod
    def _apply_review_state(
        cls,
        findings: list[Finding],
        review_state: dict[tuple[str, str, str], tuple[bool, bool]],
    ) -> list[Finding]:
        for finding in findings:
            correct, incorrect = review_state.get(cls._review_key(finding), (False, False))
            finding.correct = correct
            finding.incorrect = incorrect
            if finding.incorrect:
                finding.correct = False
                finding.enabled = False
        return sorted(findings, key=lambda finding: (finding.incorrect, finding.original_text.casefold()))

    @staticmethod
    def _review_key(finding: Finding) -> tuple[str, str, str]:
        original = re.sub(r"\s+", " ", finding.original_text).strip().casefold()
        return (original, finding.category, finding.sub_category or "")

    def _find_learned_entities(self, text: str, part: str, learned_findings: list[Finding]) -> list[Finding]:
        propagated: list[Finding] = []
        for learned in learned_findings:
            if not learned.original_text:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(learned.original_text)}(?!\w)", re.I)
            for match in pattern.finditer(text):
                propagated.append(
                    Finding(
                        original_text=match.group(0),
                        replacement_text="",
                        category=learned.category,
                        sub_category=learned.sub_category,
                        confidence=max(learned.confidence, 0.95),
                        source="learned",
                        locations=[
                            FindingLocation(
                                part=part,
                                character_start=match.start(),
                                character_end=match.end(),
                            )
                        ],
                    )
                )
        return propagated

    def _propagate_document_entities(self, findings: list[Finding], chunks) -> list[Finding]:
        propagated: list[Finding] = []
        variants = self._entity_variants(findings)
        for category, sub_category, variant, canonical in variants:
            if len(variant) < 4:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(variant)}(?!\w)", re.I)
            for chunk in chunks:
                for match in pattern.finditer(chunk.text):
                    propagated.append(
                        Finding(
                            original_text=match.group(0),
                            replacement_text="",
                            category=category,
                            sub_category=sub_category,
                            confidence=0.74 if category == "person" else 0.78,
                            source="propagated",
                            locations=[
                                FindingLocation(
                                    part=chunk.part,
                                    character_start=match.start(),
                                    character_end=match.end(),
                                    extra={"canonical_hint": canonical},
                                )
                            ],
                        )
                    )
        return propagated

    @staticmethod
    def _entity_variants(findings: list[Finding]) -> set[tuple[str, str | None, str, str]]:
        variants: set[tuple[str, str | None, str, str]] = set()
        for finding in findings:
            if finding.category == "person":
                clean = re.sub(
                    r"\b(?:Herr|Frau|Dr\.|Prof\.|Professor|Rechtsanwalt|Rechtsanwältin|RA|RAin)\s+",
                    "",
                    finding.original_text,
                    flags=re.I,
                ).strip()
                parts = clean.split()
                if len(parts) >= 2:
                    canonical = PlaceholderFactory.canonical_entity_text(finding.original_text, "person", None)
                    variants.add(("person", None, clean, canonical))
                    variants.add(("person", None, parts[-1], canonical))
            elif finding.category == "company":
                canonical = PlaceholderFactory.canonical_entity_text(
                    finding.original_text, "company", finding.sub_category
                )
                base = re.sub(
                    r"\b(?:GmbH\s*&\s*Co\.?\s*KG|GmbH|AG|UG|KG|OHG|GbR|SE|e\.?\s?K\.?|e\.?\s?V\.?|mbH|Aktiengesellschaft|Gesellschaft mit beschränkter Haftung|Gesellschaft mit beschraenkter Haftung)\b",
                    "",
                    finding.original_text,
                    flags=re.I,
                )
                base = re.sub(r"\s+", " ", base).strip(" ,;-")
                if len(base) >= 4 and len(base.split()) <= 5:
                    variants.add(("company", finding.sub_category, base, canonical))
        return variants

    def _merge_and_assign_placeholders(self, findings: list[Finding]) -> list[Finding]:
        factory = PlaceholderFactory()
        merged: OrderedDict[tuple[str, str | None, str, str], Finding] = OrderedDict()
        selected: list[Finding] = []
        occupied_by_part: dict[str, list[tuple[int, int]]] = {}
        for finding in sorted(findings, key=lambda f: (-len(f.original_text), -f.confidence)):
            if self._overlaps_existing(finding, occupied_by_part):
                continue
            selected.append(finding)
            for location in finding.locations:
                if location.character_start is None or location.character_end is None:
                    continue
                occupied_by_part.setdefault(location.part, []).append(
                    (location.character_start, location.character_end)
                )

        for finding in sorted(selected, key=lambda f: (-len(f.original_text), f.original_text.casefold())):
            canonical = finding.locations[0].extra.get("canonical_hint") if finding.locations else None
            canonical = canonical or PlaceholderFactory.canonical_entity_text(
                finding.original_text, finding.category, finding.sub_category
            )
            original_key = re.sub(r"\s+", " ", finding.original_text).strip().casefold()
            key = (finding.category, finding.sub_category, canonical, original_key)
            if key in merged:
                merged[key].locations.extend(finding.locations)
                merged[key].confidence = max(merged[key].confidence, finding.confidence)
                continue
            finding.replacement_text = factory.replacement_for(
                finding.original_text, finding.category, finding.sub_category
            )
            merged[key] = finding
        return list(merged.values())

    @staticmethod
    def _overlaps_existing(finding: Finding, occupied_by_part: dict[str, list[tuple[int, int]]]) -> bool:
        for location in finding.locations:
            if location.character_start is None or location.character_end is None:
                continue
            for start, end in occupied_by_part.get(location.part, []):
                if location.character_start < end and start < location.character_end:
                    return True
        return False
