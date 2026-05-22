from __future__ import annotations

import re
import shutil
import tempfile
import warnings
import zipfile
from io import BytesIO
from posixpath import dirname, normpath
from pathlib import Path

from lxml import etree
from PIL import Image

from doc_anonymizer.app.core.models import Finding, ImageLocation, ImageReplacement


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf", ".svg", ".wdp"}
RELATIONSHIP_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
IMAGE_RELATIONSHIP_TYPES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/image",
    "http://schemas.microsoft.com/office/2007/relationships/hdphoto",
}
IMAGE_REFERENCE_LOCAL_NAMES = {"blip", "svgBlip", "imagedata"}
IMAGE_CONTAINER_LOCAL_NAMES = {
    "AlternateContent",
    "drawing",
    "pict",
    "pic",
    "object",
    "shape",
    "sp",
}
TEXT_XML_DIRS = (
    "word/",
    "docProps/",
    "xl/",
    "ppt/",
)
VISIBLE_ATTRIBUTE_LOCAL_NAMES = {
    "descr",
    "name",
    "title",
    "tooltip",
}
GUID_VALUE_RE = re.compile(r"^\{?[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}?$")


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
                    changed = replace_in_split_openxml_text(root, findings)
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
                            if not _should_replace_openxml_attribute(attr, value, node):
                                continue
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


def replace_in_split_openxml_text(root: etree._Element, findings: list[Finding]) -> bool:
    changed = False
    for block in root.iter():
        if _local_name(block.tag) != "p":
            continue
        text_nodes = [
            node
            for node in block.iter()
            if _local_name(node.tag) == "t" and node.text is not None
        ]
        if len(text_nodes) < 2:
            continue
        changed = _replace_across_text_nodes(text_nodes, findings) or changed
    return changed


def _replace_across_text_nodes(text_nodes: list[etree._Element], findings: list[Finding]) -> bool:
    changed = False
    for finding in findings:
        if not finding.original_text:
            continue
        while True:
            spans: list[tuple[etree._Element, int, int]] = []
            offset = 0
            for node in text_nodes:
                text = node.text or ""
                spans.append((node, offset, offset + len(text)))
                offset += len(text)
            joined = "".join(node.text or "" for node in text_nodes)
            start = joined.find(finding.original_text)
            if start < 0:
                break
            end = start + len(finding.original_text)
            touched = [(node, node_start, node_end) for node, node_start, node_end in spans if node_start < end and node_end > start]
            if not touched:
                break
            first, first_start, _ = touched[0]
            last, _, last_end = touched[-1]
            before = (first.text or "")[: max(0, start - first_start)]
            after = (last.text or "")[max(0, end - (last_end - len(last.text or ""))) :]
            first.text = before + finding.replacement_text + after
            for node, _, _ in touched[1:]:
                node.text = ""
            changed = True
    return changed


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
                for attr, value in node.attrib.items():
                    if _should_replace_openxml_attribute(attr, value, node) and value and value.strip():
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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _should_replace_openxml_attribute(attr: str, value: str, node: etree._Element | None = None) -> bool:
    if GUID_VALUE_RE.match(value.strip()):
        return False
    attr_name = _local_name(attr)
    if attr_name not in VISIBLE_ATTRIBUTE_LOCAL_NAMES:
        return False
    if node is None:
        return True
    node_name = _local_name(node.tag)
    if attr_name == "name":
        return node_name in {"author", "cNvPr", "section"}
    return True


def _is_media_part(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return "/media/" in normalized and Path(normalized).suffix.lower() in IMAGE_SUFFIXES


def _content_type_for_suffix(suffix: str) -> str:
    normalized = suffix.lower().lstrip(".")
    if normalized == "jpg":
        normalized = "jpeg"
    if normalized == "tif":
        normalized = "tiff"
    if normalized == "svg":
        return "image/svg+xml"
    if normalized == "wdp":
        return "image/vnd.ms-photo"
    return f"image/{normalized or 'unknown'}"


def _image_dimensions(original: bytes, suffix: str) -> tuple[int | None, int | None]:
    if suffix.lower() == ".svg":
        try:
            root = etree.fromstring(original, etree.XMLParser(resolve_entities=False))
            width = _svg_length_to_int(root.get("width"))
            height = _svg_length_to_int(root.get("height"))
            if width and height:
                return width, height
            view_box = root.get("viewBox")
            if view_box:
                parts = [float(part) for part in re.split(r"[\s,]+", view_box.strip()) if part]
                if len(parts) == 4:
                    return int(parts[2]), int(parts[3])
        except Exception:
            return None, None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(BytesIO(original)) as img:
                return img.size
    except Exception:
        return None, None


def _svg_length_to_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", value)
    return int(float(match.group(1))) if match else None


def _source_part_for_relationship_part(name: str) -> str | None:
    normalized = name.replace("\\", "/")
    if "/_rels/" not in normalized or not normalized.endswith(".rels"):
        return None
    prefix, rel_name = normalized.rsplit("/_rels/", 1)
    return f"{prefix}/{rel_name[:-5]}"


def _relationship_target_part(relationship_part: str, target: str) -> str:
    normalized_target = target.replace("\\", "/")
    if normalized_target.startswith("/"):
        return normalized_target.lstrip("/")
    source_part = _source_part_for_relationship_part(relationship_part)
    base = dirname(source_part) if source_part else dirname(relationship_part)
    return normpath(f"{base}/{normalized_target}")


def _is_image_relationship(target: str, relationship_type: str) -> bool:
    normalized_target = target.replace("\\", "/").lower()
    return (
        relationship_type in IMAGE_RELATIONSHIP_TYPES
        or "/media/" in normalized_target
        or normalized_target.startswith("../media/")
        or Path(normalized_target).suffix.lower() in IMAGE_SUFFIXES
    )


def _remove_element(element: etree._Element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _image_container_for(element: etree._Element) -> etree._Element:
    current = element
    container = element
    while current.getparent() is not None:
        if _local_name(current.tag) in IMAGE_CONTAINER_LOCAL_NAMES:
            container = current
        current = current.getparent()
    return container


def _node_references_removed_image(node: etree._Element, relationship_ids: set[str]) -> bool:
    if not relationship_ids:
        return False
    for attr, value in node.attrib.items():
        if _local_name(attr) in {"embed", "link", "id"} and value in relationship_ids:
            return True
    return False


def _strip_image_markup(data: bytes, relationship_ids: set[str] | None = None) -> tuple[bytes, bool]:
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    root = etree.fromstring(data, parser)
    containers: list[etree._Element] = []
    remove_all_images = relationship_ids is None
    relationship_ids = relationship_ids or set()
    for node in root.iter():
        if _local_name(node.tag) in IMAGE_REFERENCE_LOCAL_NAMES and (
            remove_all_images or _node_references_removed_image(node, relationship_ids)
        ):
            containers.append(_image_container_for(node))
    changed = False
    for container in containers:
        if container.getparent() is not None:
            _remove_element(container)
            changed = True
    if not changed:
        return data, False
    return (
        etree.tostring(
            root,
            xml_declaration=data.lstrip().startswith(b"<?xml"),
            encoding="UTF-8",
            standalone=None,
        ),
        True,
    )


def _strip_image_relationships(data: bytes, relationship_part: str, removed_media_parts: set[str]) -> tuple[bytes, bool, set[str]]:
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    root = etree.fromstring(data, parser)
    changed = False
    removed_ids: set[str] = set()
    for relationship in list(root.findall(f"{{{RELATIONSHIP_NS}}}Relationship")):
        target = relationship.get("Target", "")
        relationship_type = relationship.get("Type", "")
        target_part = _relationship_target_part(relationship_part, target)
        if _is_image_relationship(target, relationship_type) and target_part in removed_media_parts:
            relationship_id = relationship.get("Id")
            if relationship_id:
                removed_ids.add(relationship_id)
            root.remove(relationship)
            changed = True
    if not changed:
        return data, False, removed_ids
    return (
        etree.tostring(
            root,
            xml_declaration=data.lstrip().startswith(b"<?xml"),
            encoding="UTF-8",
            standalone=None,
        ),
        True,
        removed_ids,
    )


def _strip_content_type_overrides(data: bytes, removed_parts: set[str]) -> tuple[bytes, bool]:
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False))
    changed = False
    for override in list(root.findall(f"{{{CONTENT_TYPES_NS}}}Override")):
        part_name = (override.get("PartName") or "").lstrip("/")
        if part_name in removed_parts:
            root.remove(override)
            changed = True
    if not changed:
        return data, False
    return (
        etree.tostring(
            root,
            xml_declaration=data.lstrip().startswith(b"<?xml"),
            encoding="UTF-8",
            standalone=None,
        ),
        True,
    )


def collect_openxml_images(path: Path) -> list[ImageReplacement]:
    images: list[ImageReplacement] = []
    with zipfile.ZipFile(path, "r") as zf:
        for name in zf.namelist():
            normalized = name.replace("\\", "/")
            if not _is_media_part(normalized):
                continue
            data = zf.read(name)
            suffix = Path(normalized).suffix.lower()
            width, height = _image_dimensions(data, suffix)
            image_id = f"IMG-{len(images) + 1:06d}"
            images.append(
                ImageReplacement(
                    id=image_id,
                    original_file_name=Path(normalized).name,
                    original_mime_type=_content_type_for_suffix(suffix),
                    placeholder_text=image_id,
                    width=width,
                    height=height,
                    locations=[ImageLocation(part=normalized, extra={"package_path": normalized})],
                )
            )
    return images


def openxml_image_bytes(path: Path, package_path: str) -> bytes | None:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return zf.read(package_path)
    except Exception:
        return None


def neutralize_openxml_media(source: Path, target: Path, job) -> dict[str, Path]:
    """Remove media files and image references from an OpenXML package.

    The original media files are exported into a temporary directory and later
    embedded into the restoration ZIP.
    """
    image_files: dict[str, Path] = {}
    openxml_part_files: dict[str, Path] = {}
    keep_by_path = {
        location.extra.get("package_path"): image.keep
        for image in getattr(job, "image_replacements", [])
        for location in image.locations
        if location.extra.get("package_path")
    }
    job.image_replacements = []
    temp_dir = Path(tempfile.mkdtemp(prefix="docanonymous-media-"))
    part_temp_dir = Path(tempfile.mkdtemp(prefix="docanonymous-openxml-"))
    tmp_target = target.with_suffix(target.suffix + ".tmp")
    shutil.copyfile(target, tmp_target)
    removed_media_parts: set[str] = set()
    relationship_ids_by_part: dict[str, set[str]] = {}

    def store_original_part(part_name: str, data: bytes) -> None:
        if part_name in openxml_part_files:
            return
        part_path = part_temp_dir / f"part-{len(openxml_part_files) + 1:06d}.bin"
        part_path.write_bytes(data)
        openxml_part_files[part_name] = part_path

    with zipfile.ZipFile(tmp_target, "r") as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            normalized = item.filename.replace("\\", "/")
            if _is_media_part(normalized) and not keep_by_path.get(normalized, False):
                removed_media_parts.add(normalized)
        for item in zin.infolist():
            normalized = item.filename.replace("\\", "/")
            if not normalized.endswith(".rels"):
                continue
            try:
                _, _, removed_ids = _strip_image_relationships(zin.read(item.filename), normalized, removed_media_parts)
            except Exception:
                continue
            source_part = _source_part_for_relationship_part(normalized)
            if source_part and removed_ids:
                relationship_ids_by_part.setdefault(source_part, set()).update(removed_ids)
        for item in zin.infolist():
            data = zin.read(item.filename)
            suffix = Path(item.filename).suffix.lower()
            normalized = item.filename.replace("\\", "/")
            if normalized == "[Content_Types].xml":
                try:
                    new_data, changed = _strip_content_type_overrides(data, removed_media_parts)
                    if changed:
                        store_original_part(item.filename, data)
                        data = new_data
                except Exception:
                    pass
            if _is_media_part(normalized):
                image_id = f"IMG-{len(job.image_replacements) + 1:06d}"
                width, height = _image_dimensions(data, suffix)
                keep_image = keep_by_path.get(normalized, False)
                job.image_replacements.append(
                    ImageReplacement(
                        id=image_id,
                        original_file_name=Path(item.filename).name,
                        original_mime_type=_content_type_for_suffix(suffix),
                        placeholder_text=image_id,
                        width=width,
                        height=height,
                        locations=[ImageLocation(part=item.filename, extra={"package_path": item.filename})],
                        keep=keep_image,
                    )
                )
                if not keep_image:
                    original_path = temp_dir / f"{image_id}{suffix}"
                    original_path.write_bytes(data)
                    image_files[image_id] = original_path
                    continue
            if normalized.endswith(".rels"):
                try:
                    new_data, changed, removed_ids = _strip_image_relationships(data, normalized, removed_media_parts)
                    if changed:
                        store_original_part(item.filename, data)
                        data = new_data
                    source_part = _source_part_for_relationship_part(normalized)
                    if source_part and removed_ids:
                        relationship_ids_by_part.setdefault(source_part, set()).update(removed_ids)
                except Exception:
                    pass
            elif normalized.endswith(".xml"):
                try:
                    new_data, changed = _strip_image_markup(data, relationship_ids_by_part.get(normalized, set()))
                    if changed:
                        store_original_part(item.filename, data)
                        data = new_data
                except Exception:
                    pass
            zout.writestr(item, data)
    tmp_target.unlink(missing_ok=True)
    job.openxml_part_files = openxml_part_files
    return image_files


def replace_openxml_media_with_placeholders(source: Path, target: Path, job) -> dict[str, Path]:
    """Replace media payloads in-place while preserving OpenXML relationships.

    PowerPoint is stricter than the OpenXML SDK about removing picture markup,
    especially for extension image types such as HDPhoto. Keeping the package
    graph intact avoids repair prompts while still removing the original image
    bytes from the anonymized copy.
    """
    image_files: dict[str, Path] = {}
    keep_by_path = {
        location.extra.get("package_path"): image.keep
        for image in getattr(job, "image_replacements", [])
        for location in image.locations
        if location.extra.get("package_path")
    }
    job.image_replacements = []
    temp_dir = Path(tempfile.mkdtemp(prefix="docanonymous-media-"))
    tmp_target = target.with_suffix(target.suffix + ".tmp")
    shutil.copyfile(target, tmp_target)

    with zipfile.ZipFile(tmp_target, "r") as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            normalized = item.filename.replace("\\", "/")
            suffix = Path(item.filename).suffix.lower()
            if _is_media_part(normalized):
                image_id = f"IMG-{len(job.image_replacements) + 1:06d}"
                width, height = _image_dimensions(data, suffix)
                keep_image = keep_by_path.get(normalized, False)
                job.image_replacements.append(
                    ImageReplacement(
                        id=image_id,
                        original_file_name=Path(item.filename).name,
                        original_mime_type=_content_type_for_suffix(suffix),
                        placeholder_text=image_id,
                        width=width,
                        height=height,
                        locations=[ImageLocation(part=item.filename, extra={"package_path": item.filename})],
                        keep=keep_image,
                    )
                )
                if not keep_image:
                    original_path = temp_dir / f"{image_id}{suffix}"
                    original_path.write_bytes(data)
                    image_files[image_id] = original_path
                    data, _, _ = placeholder_for_image(data, suffix)
            zout.writestr(item, data)
    tmp_target.unlink(missing_ok=True)
    job.openxml_part_files = {}
    return image_files
