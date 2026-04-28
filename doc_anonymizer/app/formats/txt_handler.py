from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_bytes

from doc_anonymizer.app.formats import FormatHandler, TextChunk
from doc_anonymizer.app.formats.common import replace_text


class TxtHandler(FormatHandler):
    def extract_text(self, path: Path) -> list[TextChunk]:
        return [TextChunk(self._read(path)[0], "text")]

    def anonymize(self, source: Path, target: Path, findings: list, job) -> dict[str, Path]:
        text, encoding = self._read(source)
        target.write_text(replace_text(text, findings), encoding=encoding, newline="")
        return {}

    @staticmethod
    def _read(path: Path) -> tuple[str, str]:
        raw = path.read_bytes()
        best = from_bytes(raw).best()
        if best is None:
            return raw.decode("utf-8", errors="replace"), "utf-8"
        return str(best), best.encoding or "utf-8"
