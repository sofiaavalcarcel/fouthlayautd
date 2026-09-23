"""Modelos intermedios para comparar fuentes heterogéneas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SemanticNode:
    """Unidad semántica comparable, independiente de HTML o estilos."""

    node_id: str
    type: str
    text: str = ""
    section: str = ""
    order: int = 0
    source: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list["SemanticNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticDocument:
    """Representación normalizada de un documento o una página."""

    source_kind: str
    title: str = ""
    nodes: list[SemanticNode] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "title": self.title,
            "nodes": [node.to_dict() for node in self.nodes],
            "metadata": self.metadata,
        }


@dataclass
class ComparisonFinding:
    """Hallazgo trazable producido por el comparador."""

    finding_id: str
    status: str
    section: str
    expected: str
    actual: str = ""
    confidence: float = 1.0
    comparison_type: str = "normalized"
    reason: str = ""
    document_source: dict[str, Any] = field(default_factory=dict)
    page_source: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    expected_id: str = ""
    actual_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
