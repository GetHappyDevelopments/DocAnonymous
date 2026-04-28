from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from doc_anonymizer.app.core.models import SUPPORTED_EXTENSIONS


@dataclass
class TextChunk:
    text: str
    part: str


class FormatHandler:
    def extract_text(self, path: Path) -> list[TextChunk]:
        raise NotImplementedError

    def anonymize(self, source: Path, target: Path, findings: list, job) -> dict[str, Path]:
        raise NotImplementedError


def get_handler(path: Path) -> FormatHandler:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}")
    if suffix == ".txt":
        from doc_anonymizer.app.formats.txt_handler import TxtHandler

        return TxtHandler()
    if suffix == ".docx":
        from doc_anonymizer.app.formats.docx_handler import DocxHandler

        return DocxHandler()
    if suffix == ".xlsx":
        from doc_anonymizer.app.formats.xlsx_handler import XlsxHandler

        return XlsxHandler()
    if suffix == ".pptx":
        from doc_anonymizer.app.formats.pptx_handler import PptxHandler

        return PptxHandler()
    if suffix == ".pdf":
        from doc_anonymizer.app.formats.pdf_handler import PdfHandler

        return PdfHandler()
    raise ValueError(f"Unsupported file type: {suffix}")
