from __future__ import annotations

from pathlib import Path

from doc_anonymizer.app.core.models import DocumentJob, Finding
from doc_anonymizer.app.core.restoration_package import RestorationPackageWriter
from doc_anonymizer.app.formats import get_handler


class DocumentAnonymizer:
    def anonymize(self, job: DocumentJob, output_dir: Path | None = None) -> DocumentJob:
        handler = get_handler(job.source_path)
        output_dir = output_dir or job.source_path.parent
        output_path = output_dir / f"{job.source_path.stem}.anonymized{job.source_path.suffix}"
        restore_path = output_dir / f"{job.source_path.stem}.restore.dam"
        enabled_findings = self._sort_findings(job.findings)
        job.image_replacements = []
        image_files = handler.anonymize(job.source_path, output_path, enabled_findings, job)
        job.output_path = output_path
        job.restore_package_path = restore_path
        RestorationPackageWriter().write(job, restore_path, image_files)
        job.status = "Anonymisiert"
        return job

    @staticmethod
    def _sort_findings(findings: list[Finding]) -> list[Finding]:
        return sorted(
            [f for f in findings if f.enabled and f.original_text and f.replacement_text],
            key=lambda f: len(f.original_text),
            reverse=True,
        )
