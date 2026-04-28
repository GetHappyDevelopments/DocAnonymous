from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


SUPPORTED_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".pdf", ".txt"}


@dataclass
class FindingLocation:
    part: str
    page: int | None = None
    paragraph: int | None = None
    row: int | None = None
    column: int | None = None
    slide: int | None = None
    character_start: int | None = None
    character_end: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FindingLocation":
        return cls(**data)


@dataclass
class Finding:
    original_text: str
    replacement_text: str
    category: str
    sub_category: str | None = None
    confidence: float = 1.0
    source: str = "manual"
    locations: list[FindingLocation] = field(default_factory=list)
    enabled: bool = True
    id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def occurrence_count(self) -> int:
        return max(1, len(self.locations))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        data = dict(data)
        data["locations"] = [FindingLocation.from_dict(item) for item in data.get("locations", [])]
        return cls(**data)


@dataclass
class ImageLocation:
    part: str
    page: int | None = None
    slide: int | None = None
    row: int | None = None
    column: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageLocation":
        return cls(**data)


@dataclass
class ImageReplacement:
    id: str
    original_file_name: str
    original_mime_type: str
    placeholder_text: str
    width: float | None = None
    height: float | None = None
    locations: list[ImageLocation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageReplacement":
        data = dict(data)
        data["locations"] = [ImageLocation.from_dict(item) for item in data.get("locations", [])]
        return cls(**data)


@dataclass
class DocumentJob:
    source_path: Path
    id: str = field(default_factory=lambda: str(uuid4()))
    output_path: Path | None = None
    restore_package_path: Path | None = None
    status: str = "Nicht gescannt"
    findings: list[Finding] = field(default_factory=list)
    image_replacements: list[ImageReplacement] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def format(self) -> str:
        return self.source_path.suffix.lower().lstrip(".")

    def to_jsonable(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_path"] = str(self.source_path)
        data["output_path"] = str(self.output_path) if self.output_path else None
        data["restore_package_path"] = (
            str(self.restore_package_path) if self.restore_package_path else None
        )
        data["format"] = self.format
        return data

    @classmethod
    def from_jsonable(cls, data: dict[str, Any]) -> "DocumentJob":
        job = cls(source_path=Path(data["source_path"]), id=data.get("id", str(uuid4())))
        job.output_path = Path(data["output_path"]) if data.get("output_path") else None
        job.restore_package_path = Path(data["restore_package_path"]) if data.get("restore_package_path") else None
        job.status = data.get("status", "Nicht gescannt")
        job.findings = [Finding.from_dict(item) for item in data.get("findings", [])]
        job.image_replacements = [
            ImageReplacement.from_dict(item) for item in data.get("image_replacements", [])
        ]
        job.errors = list(data.get("errors", []))
        return job
