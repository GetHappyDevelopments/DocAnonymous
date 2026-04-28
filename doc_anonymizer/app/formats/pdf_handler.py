from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from doc_anonymizer.app.core.models import ImageLocation, ImageReplacement
from doc_anonymizer.app.formats import FormatHandler, TextChunk


class PdfHandler(FormatHandler):
    def extract_text(self, path: Path) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        with fitz.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                text = page.get_text("text")
                if text:
                    chunks.append(TextChunk(text, f"page:{index}"))
        return chunks

    def anonymize(self, source: Path, target: Path, findings: list, job) -> dict[str, Path]:
        image_files: dict[str, Path] = {}
        temp_dir = Path(tempfile.mkdtemp(prefix="docanonymous-pdf-"))
        doc = fitz.open(source)
        for page_index, page in enumerate(doc, start=1):
            for finding in findings:
                for rect in page.search_for(finding.original_text):
                    page.add_redact_annot(rect, text=finding.replacement_text, fill=(1, 1, 1), text_color=(0, 0, 0))
            for img in page.get_images(full=True):
                xref = img[0]
                rects = page.get_image_rects(xref)
                image_id = f"IMG-{len(job.image_replacements) + 1:06d}"
                try:
                    extracted = doc.extract_image(xref)
                    suffix = "." + extracted.get("ext", "bin")
                    original_path = temp_dir / f"{image_id}{suffix}"
                    original_path.write_bytes(extracted["image"])
                    image_files[image_id] = original_path
                except Exception:
                    suffix = ".bin"
                width = rects[0].width if rects else None
                height = rects[0].height if rects else None
                job.image_replacements.append(
                    ImageReplacement(
                        id=image_id,
                        original_file_name=f"{image_id}{suffix}",
                        original_mime_type=f"image/{suffix.lstrip('.')}",
                        placeholder_text=image_id,
                        width=width,
                        height=height,
                        locations=[ImageLocation(part=f"page:{page_index}")],
                    )
                )
                for rect in rects:
                    page.add_redact_annot(rect, text=image_id, fill=(0.74, 0.74, 0.74), text_color=(0, 0, 0))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        doc.save(target, garbage=4, deflate=True)
        doc.close()
        return image_files
