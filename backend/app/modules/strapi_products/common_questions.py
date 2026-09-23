from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO

from docx import Document


FAQ_HEADING = re.compile(r"^(?:12\s*[.)]\s*)?.*preguntas\s+frecuentes.*(?:faq)?.*$", re.IGNORECASE)
QUESTION = re.compile(r"^\s*\d+\s*[.)]\s*(.+?)\s*$")


@dataclass(frozen=True)
class CommonQuestion:
    question: str
    answer: str


def extract_common_questions(filename: str, content: bytes) -> tuple[CommonQuestion, ...] | None:
    """Extract numbered FAQ questions and their following answer paragraphs from a DOCX."""
    try:
        paragraphs = Document(BytesIO(content)).paragraphs
    except Exception as error:
        raise ValueError(f"No se pudieron leer las preguntas frecuentes en {filename}.") from error

    start = next((index for index, paragraph in enumerate(paragraphs) if FAQ_HEADING.fullmatch(_text(paragraph.text))), None)
    if start is None:
        return None

    entries: list[CommonQuestion] = []
    current_question: str | None = None
    answer_paragraphs: list[str] = []
    for paragraph in paragraphs[start + 1:]:
        text = _text(paragraph.text)
        if not text:
            continue
        question_match = QUESTION.match(text)
        question_text = question_match.group(1) if question_match else text
        if "?" in question_text and (question_match or text.endswith("?")):
            if current_question is not None:
                if not answer_paragraphs:
                    raise ValueError(f"La pregunta {current_question!r} no tiene respuesta en {filename}.")
                entries.append(CommonQuestion(current_question, "\n\n".join(answer_paragraphs)))
            current_question = question_text.strip()
            answer_paragraphs = []
            continue

        if paragraph.style and paragraph.style.name.casefold().startswith("heading"):
            break
        if current_question is None:
            continue
        answer_paragraphs.append(text)

    if current_question is not None:
        if not answer_paragraphs:
            raise ValueError(f"La pregunta {current_question!r} no tiene respuesta en {filename}.")
        entries.append(CommonQuestion(current_question, "\n\n".join(answer_paragraphs)))
    if not entries:
        raise ValueError(f"La sección 12. Preguntas frecuentes (FAQ) no contiene preguntas en {filename}.")
    return tuple(entries)


def _text(value: str) -> str:
    return value.replace("\u00a0", " ").strip()


def build_common_questions_payload(entries: tuple[CommonQuestion, ...], existing: dict | None) -> dict:
    """Keep section styling and component IDs while replacing FAQ copy with document text."""
    section = deepcopy((existing or {}).get("attributes", existing or {}))
    current = section.get("dropdowns") or []
    dropdowns = []
    for index, entry in enumerate(entries):
        item = {}
        if index < len(current):
            item = {key: deepcopy(current[index][key]) for key in ("id", "iconPosition") if key in current[index]}
        item.update({"dropdownTitle": entry.question, "richText": entry.answer})
        item.setdefault("iconPosition", "Left")
        dropdowns.append(item)
    section["dropdowns"] = dropdowns
    container = deepcopy(section.get("containerConfig") or {})
    background = deepcopy(container.get("background") or {})
    background["color"] = "#EDF2FA"
    background["size"] = "contain"
    container["background"] = background
    section["containerConfig"] = container
    section.setdefault("idForScrolling", "commonQuestions")
    section.setdefault("dropdownInitialOpen", True)
    section.setdefault("hideSection", False)
    return section


def common_questions_match(entries: tuple[CommonQuestion, ...], existing: dict | None) -> bool:
    section = (existing or {}).get("attributes", existing or {})
    current = section.get("dropdowns") or []
    return len(current) == len(entries) and all(
        item.get("dropdownTitle") == expected.question and item.get("richText") == expected.answer
        for item, expected in zip(current, entries)
    )
