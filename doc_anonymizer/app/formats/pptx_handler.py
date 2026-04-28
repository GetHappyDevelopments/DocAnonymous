from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from doc_anonymizer.app.formats import FormatHandler, TextChunk
from doc_anonymizer.app.formats.common import (
    extract_openxml_text,
    neutralize_openxml_media,
    replace_in_openxml_text_nodes,
    replace_text,
)


class PptxHandler(FormatHandler):
    def extract_text(self, path: Path) -> list[TextChunk]:
        prs = Presentation(str(path))
        chunks: list[TextChunk] = []
        for slide_idx, slide in enumerate(prs.slides, start=1):
            for shape_idx, shape in enumerate(slide.shapes):
                if hasattr(shape, "text") and shape.text:
                    chunks.append(TextChunk(shape.text, f"slide:{slide_idx}:shape:{shape_idx}"))
        for text, part in extract_openxml_text(path):
            chunks.append(TextChunk(text, part))
        return chunks

    def anonymize(self, source: Path, target: Path, findings: list, job) -> dict[str, Path]:
        prs = Presentation(str(source))
        for slide in prs.slides:
            for shape in slide.shapes:
                if not hasattr(shape, "text_frame") or shape.text_frame is None:
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    current = "".join(run.text for run in paragraph.runs)
                    new_text = replace_text(current, findings)
                    if new_text == current:
                        continue
                    for run in paragraph.runs:
                        run.text = ""
                    if paragraph.runs:
                        paragraph.runs[0].text = new_text
        prs.save(str(target))
        replace_in_openxml_text_nodes(target, findings)
        return neutralize_openxml_media(source, target, job)
