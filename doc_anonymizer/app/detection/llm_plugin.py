from __future__ import annotations

from dataclasses import dataclass

from doc_anonymizer.app.core.models import Finding


@dataclass
class LocalLlmConfig:
    enabled: bool = False
    endpoint: str = "http://localhost:11434"
    model: str = ""


class LocalLlmAnalyzer:
    """Prepared extension point. It intentionally performs no network calls by default."""

    def __init__(self, config: LocalLlmConfig | None = None) -> None:
        self.config = config or LocalLlmConfig()

    def is_available(self) -> bool:
        return bool(self.config.enabled and self.config.endpoint and self.config.model)

    def analyze_text(self, text: str, context: dict) -> list[Finding]:
        if not self.is_available():
            return []
        # Future implementation: call a local-only backend such as Ollama or LM Studio.
        return []
