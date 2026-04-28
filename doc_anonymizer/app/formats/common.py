from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from lxml import etree

from doc_anonymizer.app.core.models import Finding, ImageLocation, ImageReplacement


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf"}
TEXT_XML_DIRS = (
    "word/",
    "docProps/",
    "xl/",
    "ppt/",
)


def replace_text(text: str, findings: list[Finding]) -> str:
    result = text
    for finding in findings:
        result = result.replace(finding.original_text, finding.replacement_text)
    return result


def replace_text_regex_safe(text: str, findings: list[Finding]) -> str:
    result = text
    for finding in findings:
        result = re.sub(re.escape(finding.original_text), finding.replacement_text, result)
    return result


def replace_in_openxml_text_nodes(package_path: Path, findings: list[Finding]) -> None:
    tmp_target = package_path.with_suffix(package_path.suffix + ".xmltmp")
    shutil.copyfile(package_path, tmp_target)
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    with zipfile.ZipFile(tmp_target, "r") as zin, zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            normalized = item.filename.replace("\\", "/")
            if normalized.endswith(".xml") and normalized.startswith(TEXT_XML_DIRS):
                try:
                    root = etree.fromstring(data, parser)
                    changed = False
                    for node in root.iter():
                        if node.text:
                            new_text = replace_text(node.text, findings)
                            if new_text != node.text:
                                node.text = new_text
                                changed = True
                        if node.tail:
                            new_tail = replace_text(node.tail, findings)
                            if new_tail != node.tail:
                                node.tail = new_tail
                                changed = True
                        for attr, value in list(node.attrib.items()):
                            new_value = replace_text(value, findings)
                            if new_value != value:
                                node.attrib[attr] = new_value
                                changed = True
                    if changed:
                        data = etree.tostring(
                            root,
                            xml_declaration=data.lstrip().startswith(b"<?xml"),
                            encoding="UTF-8",
                            standalone=None,
                        )
                except Exception:
                    pass
            zout.writestr(item, data)
    tmp_target.unlink(missing_ok=True)


def extract_openxml_text(path: Path) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    with zipfile.ZipFile(path, "r") as zf:
        for name in zf.namelist():
            normalized = name.replace("\\", "/")
            if not (normalized.endswith(".xml") and normalized.startswith(TEXT_XML_DIRS)):
                continue
            try:
                root = etree.fromstring(zf.read(name), parser)
            except Exception:
                continue
            parts: list[str] = []
            for node in root.iter():
                if node.text and node.text.strip():
                    parts.append(node.text)
                for value in node.attrib.values():
                    if value and value.strip():
                        parts.append(value)
            if parts:
                chunks.append(("\n".join(parts), name))
    return chunks


def placeholder_png_bytes(width: int = 640, height: int = 360) -> bytes:
    try:
        from PIL import Image

        image = Image.new("RGB", (width, height), (190, 190, 190))
        out = BytesIO()
        image.save(out, "PNG")
        return out.getvalue()
    except Exception:
        # 1x1 gray PNG fallback.
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
            b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
        )


def placeholder_for_image(original: bytes, suffix: str) -> tuple[bytes, int | None, int | None]:
    try:
        from PIL import Image, ImageDraw

        with Image.open(BytesIO(original)) as img:
            width, height = img.size
            mode = "RGB" if suffix.lower() in {".jpg", ".jpeg", ".bmp"} else "RGBA"
            placeholder = Image.new(mode, (width, height), (190, 190, 190, 255) if mode == "RGBA" else (190, 190, 190))
            draw = ImageDraw.Draw(placeholder)
            text = "ANONYMIZED"
            box = draw.textbbox((0, 0), text)
            x = max(4, (width - (box[2] - box[0])) // 2)
            y = max(4, (height - (box[3] - box[1])) // 2)
            draw.text((x, y), text, fill=(70, 70, 70))
            out = BytesIO()
            fmt = img.format or "PNG"
            if suffix.lower() in {".jpg", ".jpeg"}:
                fmt = "JPEG"
            placeholder.save(out, format=fmt)
            return out.getvalue(), width, height
    except Exception:
        return placeholder_png_bytes(), None, None


def neutralize_openxml_media(source: Path, target: Path, job) -> dict[str, Path]:
    """Replace media files in an OpenXML package with gray PNG placeholders.

    The original media files are exported into a temporary directory and later
    embedded into the restoration ZIP.
    """
    image_files: dict[str, Path] = {}
    temp_dir = Path(tempfile.mkdtemp(prefix="docanonymous-media-"))
    tmp_target = target.with_suffix(target.suffix + ".tmp")
    shutil.copyfile(target, tmp_target)
    with zipfile.ZipFile(tmp_target, "r") as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            suffix = Path(item.filename).suffix.lower()
            if "/media/" in item.filename.replace("\\", "/") and suffix in IMAGE_SUFFIXES:
                image_id = f"IMG-{len(job.image_replacements) + 1:06d}"
                original_path = temp_dir / f"{image_id}{suffix}"
                original_path.write_bytes(data)
                image_files[image_id] = original_path
                placeholder, width, height = placeholder_for_image(data, suffix)
                job.image_replacements.append(
                    ImageReplacement(
                        id=image_id,
                        original_file_name=Path(item.filename).name,
                        original_mime_type=f"image/{suffix.lstrip('.')}",
                        placeholder_text=image_id,
                        width=width,
                        height=height,
                        locations=[ImageLocation(part=item.filename, extra={"package_path": item.filename})],
                    )
                )
                data = placeholder
            zout.writestr(item, data)
    tmp_target.unlink(missing_ok=True)
    return image_files
