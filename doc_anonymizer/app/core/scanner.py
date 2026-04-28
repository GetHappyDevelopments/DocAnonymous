from __future__ import annotations

from collections import OrderedDict

from doc_anonymizer.app.core.models import DocumentJob, Finding
from doc_anonymizer.app.core.placeholder_factory import PlaceholderFactory
from doc_anonymizer.app.detection.llm_plugin import LocalLlmAnalyzer
from doc_anonymizer.app.detection.regex_detector import RegexDetector
from doc_anonymizer.app.formats import get_handler


class DocumentScanner:
    def __init__(self, llm_analyzer: LocalLlmAnalyzer | None = None) -> None:
        self.regex_detector = RegexDetector()
        self.llm_analyzer = llm_analyzer or LocalLlmAnalyzer()

    def scan(self, job: DocumentJob) -> list[Finding]:
        handler = get_handler(job.source_path)
        chunks = handler.extract_text(job.source_path)
        raw_findings: list[Finding] = []
        for chunk in chunks:
            raw_findings.extend(self.regex_detector.scan(chunk.text, chunk.part))
            raw_findings.extend(self.llm_analyzer.analyze_text(chunk.text, {"part": chunk.part}))

        job.findings = self._merge_and_assign_placeholders(raw_findings)
        job.status = "Scan abgeschlossen"
        return job.findings

    def _merge_and_assign_placeholders(self, findings: list[Finding]) -> list[Finding]:
        factory = PlaceholderFactory()
        merged: OrderedDict[tuple[str, str | None, str], Finding] = OrderedDict()
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
            canonical = PlaceholderFactory.canonical_entity_text(
                finding.original_text, finding.category, finding.sub_category
            )
            key = (
                finding.category,
                finding.sub_category,
                canonical,
            )
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
