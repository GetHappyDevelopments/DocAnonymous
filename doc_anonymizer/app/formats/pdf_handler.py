from __future__ import annotations

import tempfile
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageDraw

from doc_anonymizer.app.core.models import ImageLocation, ImageReplacement
from doc_anonymizer.app.formats import FormatHandler, TextChunk


RENDER_SCALE = 2


class PdfHandler(FormatHandler):
    def extract_text(self, path: Path) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        pdf = pdfium.PdfDocument(path)
        try:
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_range()
                    finally:
                        text_page.close()
                    if text:
                        chunks.append(TextChunk(text, f"page:{index + 1}"))
                finally:
                    page.close()
        finally:
            pdf.close()
        return chunks

    def anonymize(self, source: Path, target: Path, findings: list, job) -> dict[str, Path]:
        image_files: dict[str, Path] = {}
        temp_dir = Path(tempfile.mkdtemp(prefix="docanonymous-pdf-"))
        rendered_pages: list[Image.Image] = []
        pdf = pdfium.PdfDocument(source)
        try:
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                try:
                    page_image = page.render(scale=RENDER_SCALE).to_pil().convert("RGB")
                    page_height = float(page.get_height())
                    draw = ImageDraw.Draw(page_image)
                    self._redact_text(page, page_height, draw, findings)
                    self._redact_images(page, page_index + 1, page_height, draw, temp_dir, image_files, job)
                    rendered_pages.append(page_image)
                finally:
                    page.close()
        finally:
            pdf.close()

        target.parent.mkdir(parents=True, exist_ok=True)
        if rendered_pages:
            first, rest = rendered_pages[0], rendered_pages[1:]
            first.save(
                target,
                "PDF",
                save_all=True,
                append_images=rest,
                resolution=72 * RENDER_SCALE,
            )
        else:
            Image.new("RGB", (1, 1), "white").save(target, "PDF", resolution=72)
        return image_files

    def _redact_text(self, page, page_height: float, draw: ImageDraw.ImageDraw, findings: list) -> None:
        text_page = page.get_textpage()
        try:
            for finding in findings:
                if not finding.original_text:
                    continue
                searcher = text_page.search(finding.original_text, match_case=False, match_whole_word=False)
                try:
                    while result := searcher.get_next():
                        start, count = result
                        rect_count = text_page.count_rects(start, count)
                        for rect_index in range(rect_count):
                            rect = text_page.get_rect(rect_index)
                            box = self._pdf_rect_to_image_box(rect, page_height)
                            draw.rectangle(box, fill="white")
                            draw.text((box[0] + 3, box[1] + 3), finding.replacement_text, fill="black")
                finally:
                    searcher.close()
        finally:
            text_page.close()

    def _redact_images(
        self,
        page,
        page_number: int,
        page_height: float,
        draw: ImageDraw.ImageDraw,
        temp_dir: Path,
        image_files: dict[str, Path],
        job,
    ) -> None:
        for image_obj in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE]):
            image_id = f"IMG-{len(job.image_replacements) + 1:06d}"
            suffix = ".png"
            original_path = temp_dir / f"{image_id}{suffix}"
            try:
                image_obj.extract(original_path)
                suffix = original_path.suffix or suffix
                image_files[image_id] = original_path
            except Exception:
                original_path.write_bytes(b"")

            left, bottom, right, top = image_obj.get_bounds()
            box = self._pdf_rect_to_image_box((left, bottom, right, top), page_height)
            width = max(0, right - left)
            height = max(0, top - bottom)
            job.image_replacements.append(
                ImageReplacement(
                    id=image_id,
                    original_file_name=f"{image_id}{suffix}",
                    original_mime_type=f"image/{suffix.lstrip('.')}",
                    placeholder_text=image_id,
                    width=width,
                    height=height,
                    locations=[ImageLocation(part=f"page:{page_number}")],
                )
            )
            draw.rectangle(box, fill=(190, 190, 190))
            draw.text((box[0] + 5, box[1] + 5), image_id, fill=(60, 60, 60))

    @staticmethod
    def _pdf_rect_to_image_box(rect: tuple[float, float, float, float], page_height: float) -> tuple[int, int, int, int]:
        left, bottom, right, top = rect
        x1 = int(left * RENDER_SCALE)
        y1 = int((page_height - top) * RENDER_SCALE)
        x2 = int(right * RENDER_SCALE)
        y2 = int((page_height - bottom) * RENDER_SCALE)
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
