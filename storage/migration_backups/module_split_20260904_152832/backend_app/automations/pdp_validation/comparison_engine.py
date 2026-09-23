"""Comparador determinista con trazabilidad y espacio para arbitraje semántico."""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Iterable

from .models import ComparisonFinding, SemanticDocument, SemanticNode
from .normalizer import normalized_text, token_set


CONTAINER_TYPES = {"table"}
NON_CONTENT_TYPES = {"section", "subsection"}
RELEVANT_EXTRA_TYPES = {"title", "section", "subsection", "paragraph", "list_item", "table_row", "table_cell", "label_value", "label", "value", "question", "cta"}


class ComparisonEngine:
    """Compara unidades y colecciones sin exigir la misma estructura visual."""

    def compare(self, expected: SemanticDocument, actual: SemanticDocument) -> dict:
        expected_nodes = self._atomic_nodes(expected.nodes, include_sections=True)
        actual_nodes = self._atomic_nodes(actual.nodes, include_sections=True)
        used_actual: set[str] = set()
        findings: list[ComparisonFinding] = []
        unresolved: list[dict] = []

        for expected_node in expected_nodes:
            related = self._label_value_candidate(expected_node, actual_nodes, used_actual)
            if related:
                candidate, consumed_ids = related
                used_actual.update(consumed_ids)
                findings.append(self._finding("MATCH_NORMALIZADO", expected_node, candidate, 0.98, "label_value_relation"))
                continue
            exact_candidates = [
                node for node in actual_nodes
                if node.node_id not in used_actual and normalized_text(node.text) == normalized_text(expected_node.text)
            ]
            candidate = self._best_section_candidate(expected_node, exact_candidates)
            if candidate:
                used_actual.add(candidate.node_id)
                findings.append(self._finding("MATCH_EXACTO" if expected_node.text == candidate.text else "MATCH_NORMALIZADO", expected_node, candidate, 1.0, "exact_or_normalized"))
                continue

            fuzzy_candidates = [
                (node, self._similarity(expected_node.text, node.text))
                for node in actual_nodes if node.node_id not in used_actual
            ]
            fuzzy_candidates.sort(key=lambda item: item[1], reverse=True)
            if fuzzy_candidates and fuzzy_candidates[0][1] >= 0.84:
                candidate, score = fuzzy_candidates[0]
                used_actual.add(candidate.node_id)
                findings.append(self._finding("DIFERENTE", expected_node, candidate, score, "text_similarity"))
                continue

            unresolved.append({
                "expected_id": expected_node.node_id,
                "expected": expected_node.text,
                "section": expected_node.section,
                "type": expected_node.type,
                "document_source": expected_node.source,
                "candidates": [
                    {"actual_id": node.node_id, "actual": node.text, "section": node.section, "type": node.type, "page_source": node.source}
                    for node, score in fuzzy_candidates[:8] if score >= 0.38
                ],
                "document_node": expected_node.to_dict(),
            })

        findings.extend(
            self._finding("FALTANTE", self._node_by_id(expected_nodes, item["expected_id"]), None, 1.0, "not_found")
            for item in unresolved
        )
        findings.extend(self._extra_findings(expected_nodes, actual_nodes, used_actual))
        return {
            "findings": [finding.to_dict() for finding in findings],
            "unresolved": unresolved,
            "expected_nodes": len(expected_nodes),
            "actual_nodes": len(actual_nodes),
            "sections": self._sections(expected_nodes),
        }

    def _label_value_candidate(self, expected: SemanticNode, actual_nodes: list[SemanticNode], used_actual: set[str]) -> tuple[SemanticNode, set[str]] | None:
        if expected.type != "label_value":
            return None
        label = normalized_text(str(expected.metadata.get("label") or expected.text.split(":", 1)[0]))
        value = normalized_text(str(expected.metadata.get("value") or expected.text.split(":", 1)[-1]))
        if not label or not value:
            return None
        for index, label_node in enumerate(actual_nodes):
            if label_node.node_id in used_actual or normalized_text(label_node.text) != label:
                continue
            for value_node in actual_nodes[index + 1 : index + 4]:
                if value_node.node_id in used_actual:
                    continue
                if normalized_text(value_node.text) == value:
                    return SemanticNode(
                        node_id=f"{label_node.node_id}+{value_node.node_id}", type="label_value",
                        text=f"{label_node.text}: {value_node.text}", section=label_node.section,
                        order=label_node.order, source={"label": label_node.source, "value": value_node.source},
                    ), {label_node.node_id, value_node.node_id}
        return None

    def apply_ai_findings(self, comparison: dict, ai_findings: Iterable[dict]) -> None:
        """Sustituye FALTANTE por equivalencia solo cuando la IA aporta evidencia."""

        findings = comparison["findings"]
        by_expected = {item["expected_id"]: item for item in findings if item["status"] == "FALTANTE"}
        for ai_finding in ai_findings:
            expected_id = ai_finding.get("expected_id")
            finding = by_expected.get(expected_id)
            if not finding:
                continue
            confidence = float(ai_finding.get("confidence", 0))
            actual = str(ai_finding.get("actual", "")).strip()
            if not actual or confidence < 0.8:
                finding["status"] = "REVISION_MANUAL"
                finding["comparison_type"] = "semantic_ambiguous"
                finding["confidence"] = confidence
                finding["reason"] = str(ai_finding.get("reason") or "La IA detectó una posible equivalencia, pero no hay evidencia suficiente.")
                finding["candidates"] = ai_finding.get("candidates") or []
            else:
                finding["status"] = "POSIBLE_COINCIDENCIA"
                finding["comparison_type"] = "semantic_candidate"
                finding["confidence"] = confidence
                finding["actual"] = actual
                finding["reason"] = str(ai_finding.get("reason") or "Posible equivalencia semántica; requiere confirmación.")
                finding["candidates"] = ai_finding.get("candidates") or []

    def summarize(self, comparison: dict) -> dict[str, int]:
        counts = Counter(item["status"] for item in comparison["findings"])
        return {
            "sections": comparison["sections"],
            "expected_elements": comparison["expected_nodes"],
            "page_elements": comparison["actual_nodes"],
            "exact_matches": counts["MATCH_EXACTO"],
            "normalized_matches": counts["MATCH_NORMALIZADO"],
            "different": counts["DIFERENTE"],
            "missing": counts["FALTANTE"],
            "extra": counts["EXTRA"],
            "duplicates": counts["DUPLICADO"],
            "possible_matches": counts["POSIBLE_COINCIDENCIA"],
            "manual_review": counts["REVISION_MANUAL"],
        }

    @staticmethod
    def _atomic_nodes(nodes: list[SemanticNode], include_sections: bool) -> list[SemanticNode]:
        result: list[SemanticNode] = []
        for node in nodes:
            if node.type in CONTAINER_TYPES and node.children:
                result.extend(ComparisonEngine._atomic_nodes(node.children, include_sections))
            elif node.type == "table_row" and node.metadata.get("cells"):
                cells = node.metadata["cells"]
                for index, cell in enumerate(cells):
                    text = str(cell).strip()
                    if not text or (index == 0 and len(cells) > 1 and re.match(r"^\s*(?:\d+|[ivxlcdm]+)(?:\D|$)", text, re.IGNORECASE)):
                        continue
                    result.append(SemanticNode(
                        node_id=f"{node.node_id}-cell-{index}", type="table_cell", text=text,
                        section=node.section, order=node.order, source={**node.source, "cell": index},
                        metadata={**node.metadata, "cell_index": index},
                    ))
            elif (include_sections or node.type not in NON_CONTENT_TYPES) and not ComparisonEngine._is_structural_heading(node) and normalized_text(node.text):
                result.append(node)
        return result

    @staticmethod
    def _is_structural_heading(node: SemanticNode) -> bool:
        """Omite rótulos editoriales numerados y grupos usados solo como contexto."""

        if node.type not in NON_CONTENT_TYPES:
            return False
        return node.metadata.get("ordered_group", False) or bool(re.match(r"^\s*\d+\s*[.)]\s*", node.text))

    @staticmethod
    def _node_by_id(nodes: list[SemanticNode], node_id: str) -> SemanticNode:
        return next(node for node in nodes if node.node_id == node_id)

    def _finding(self, status: str, expected: SemanticNode, actual: SemanticNode | None, confidence: float, comparison_type: str) -> ComparisonFinding:
        return ComparisonFinding(
            finding_id=f"finding-{expected.node_id}-{actual.node_id if actual else 'missing'}",
            status=status,
            section=expected.section,
            expected=expected.text,
            actual=actual.text if actual else "No encontrado",
            confidence=round(confidence, 3),
            comparison_type=comparison_type,
            reason="Coincidencia basada en contenido y contexto." if actual else "El elemento de la fuente de verdad no fue localizado.",
            document_source=expected.source,
            page_source=actual.source if actual else {},
            expected_id=expected.node_id,
            actual_id=actual.node_id if actual else "",
        )

    def _extra_findings(self, expected_nodes: list[SemanticNode], actual_nodes: list[SemanticNode], used_actual: set[str]) -> list[ComparisonFinding]:
        expected_counts = Counter(normalized_text(node.text) for node in expected_nodes)
        actual_counts = Counter(normalized_text(node.text) for node in actual_nodes)
        extras: list[ComparisonFinding] = []
        for node in actual_nodes:
            if node.node_id in used_actual or node.type not in RELEVANT_EXTRA_TYPES:
                continue
            normalized = normalized_text(node.text)
            same_context = any(self._section_similarity(node.section, expected.section) >= 0.55 for expected in expected_nodes)
            if node.type in {"list_item", "table_cell"}:
                same_context = same_context or any(expected.type in {"list_item", "table_cell"} for expected in expected_nodes)
            if node.type == "cta" and not any(expected.type == "cta" for expected in expected_nodes):
                continue
            if not same_context:
                continue
            expected_count = expected_counts.get(normalized, 0)
            actual_count = actual_counts.get(normalized, 0)
            status = "DUPLICADO" if expected_count and actual_count > expected_count else "EXTRA"
            extras.append(ComparisonFinding(
                finding_id=f"finding-extra-{node.node_id}", status=status, section=node.section,
                expected="No existe en el documento", actual=node.text, confidence=1.0,
                comparison_type="collection_difference", reason="El contenido aparece en la página fuera de los elementos emparejados.",
                page_source=node.source,
                actual_id=node.node_id,
            ))
        return extras

    @staticmethod
    def _sections(nodes: list[SemanticNode]) -> int:
        return len({normalized_text(node.section) for node in nodes if normalized_text(node.section)})

    def _best_section_candidate(self, expected: SemanticNode, candidates: list[SemanticNode]) -> SemanticNode | None:
        if not candidates:
            return None
        return max(candidates, key=lambda node: self._section_similarity(expected.section, node.section))

    def _similarity(self, expected: str, actual: str) -> float:
        left, right = normalized_text(expected), normalized_text(actual)
        if not left or not right:
            return 0.0
        return max(SequenceMatcher(None, left, right).ratio(), self._token_overlap(left, right))

    @staticmethod
    def _token_overlap(left: str, right: str) -> float:
        left_tokens, right_tokens = token_set(left), token_set(right)
        union = left_tokens | right_tokens
        return len(left_tokens & right_tokens) / max(len(union), 1)

    def _section_similarity(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        return self._similarity(left, right)
