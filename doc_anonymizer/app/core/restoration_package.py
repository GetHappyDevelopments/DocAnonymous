from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from doc_anonymizer.app.core.models import DocumentJob


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class RestorationPackageWriter:
    def write(self, job: DocumentJob, package_path: Path, image_files: dict[str, Path] | None = None) -> None:
        image_files = image_files or {}
        package_path.parent.mkdir(parents=True, exist_ok=True)
        restore = {
            "schemaVersion": "1.0",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "sourceDocument": {
                "fileName": job.source_path.name,
                "path": str(job.source_path),
                "sha256": sha256_file(job.source_path),
                "format": job.format,
            },
            "anonymizedDocument": {
                "fileName": job.output_path.name if job.output_path else None,
                "path": str(job.output_path) if job.output_path else None,
                "sha256": sha256_file(job.output_path) if job.output_path and job.output_path.exists() else None,
            },
            "textReplacements": [asdict(f) for f in job.findings if f.enabled],
            "imageReplacements": [asdict(img) for img in job.image_replacements],
            "securityNotice": "This package contains sensitive original data and must not be uploaded to public LLMs.",
        }
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("restore.json", json.dumps(restore, ensure_ascii=False, indent=2))
            for image_id, file_path in image_files.items():
                if file_path.exists():
                    zf.write(file_path, f"images/{image_id}{file_path.suffix}")
