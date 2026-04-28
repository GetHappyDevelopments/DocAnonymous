from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from doc_anonymizer import __version__
from doc_anonymizer.app.core.models import DocumentJob


class ProjectStateStore:
    def save(self, path: Path, jobs: list[DocumentJob]) -> None:
        payload = {
            "schemaVersion": "1.0",
            "appVersion": __version__,
            "savedAt": datetime.now(timezone.utc).isoformat(),
            "jobs": [job.to_jsonable() for job in jobs],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: Path) -> list[DocumentJob]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [DocumentJob.from_jsonable(item) for item in payload.get("jobs", [])]
