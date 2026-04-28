from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from doc_anonymizer.app.core.models import Finding
from doc_anonymizer.app.formats.common import replace_text


class DocumentRestorer:
    def restore(self, anonymized_path: Path, restore_package_path: Path, output_path: Path | None = None) -> Path:
        output_path = output_path or anonymized_path.with_name(
            f"{anonymized_path.stem}.restored{anonymized_path.suffix}"
        )
        with zipfile.ZipFile(restore_package_path, "r") as zf:
            restore = json.loads(zf.read("restore.json").decode("utf-8"))
            replacements = [
                Finding(
                    original_text=item.get("replacementText", item.get("replacement_text", "")),
                    replacement_text=item.get("originalText", item.get("original_text", "")),
                    category=item.get("category", "custom"),
                    sub_category=item.get("subCategory", item.get("sub_category")),
                    source="restore",
                )
                for item in restore.get("textReplacements", [])
            ]
            suffix = anonymized_path.suffix.lower()
            if suffix == ".txt":
                text = anonymized_path.read_text(encoding="utf-8", errors="replace")
                output_path.write_text(replace_text(text, replacements), encoding="utf-8", newline="")
                return output_path
            if suffix in {".docx", ".xlsx", ".pptx"}:
                shutil.copyfile(anonymized_path, output_path)
                self._restore_openxml_text_and_images(output_path, replacements, restore, zf)
                return output_path
            if suffix == ".pdf":
                shutil.copyfile(anonymized_path, output_path)
                return output_path
        return output_path

    def _restore_openxml_text_and_images(
        self,
        output_path: Path,
        replacements: list[Finding],
        restore: dict,
        restore_zip: zipfile.ZipFile,
    ) -> None:
        from doc_anonymizer.app.formats.common import replace_in_openxml_text_nodes

        replace_in_openxml_text_nodes(output_path, replacements)
        tmp_target = output_path.with_suffix(output_path.suffix + ".restoretmp")
        shutil.copyfile(output_path, tmp_target)
        image_map: dict[str, bytes] = {}
        for image in restore.get("imageReplacements", []):
            image_id = image.get("id")
            for name in restore_zip.namelist():
                if name.startswith(f"images/{image_id}."):
                    image_map[image_id] = restore_zip.read(name)
                    break
        with zipfile.ZipFile(tmp_target, "r") as zin, zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                for image in restore.get("imageReplacements", []):
                    for location in image.get("locations", []):
                        if location.get("extra", {}).get("package_path") == item.filename:
                            data = image_map.get(image.get("id"), data)
                zout.writestr(item, data)
        tmp_target.unlink(missing_ok=True)
