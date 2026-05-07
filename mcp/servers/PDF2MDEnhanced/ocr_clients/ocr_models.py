from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class OcrElement:
    kind: str
    source: str
    text: str = ""
    title: str = ""
    markdown: str = ""
    latex: str = ""
    caption: str = ""
    description: str = ""
    context: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OcrResult:
    markdown: str = ""
    page_text: str = ""
    tables: List[OcrElement] = field(default_factory=list)
    formulas: List[OcrElement] = field(default_factory=list)
    figures: List[OcrElement] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (
            self.markdown.strip()
            or self.page_text.strip()
            or self.tables
            or self.formulas
            or self.figures
        )
