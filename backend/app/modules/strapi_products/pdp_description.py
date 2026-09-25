from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from dataclasses import dataclass


def _normalize(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", plain.casefold()).split())


def _clean(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split()).strip()


def _is_heading(text: str) -> bool:
    return len(text) <= 140 and (text.isupper() or re.match(r"^(?:\d+[.)]?|perfil|plan de estudios|competencias|informacion)\b", text, re.I))


def _extract_after_title(program: str, blocks: list[str], source: str) -> str:
    target = _normalize(program)
    title_index = next((index for index, block in enumerate(blocks) if _normalize(block) == target or target in _normalize(block)), None)
    if title_index is None:
        raise ValueError(f"No se encontro el titulo del programa en {source}.")

    for candidate in blocks[title_index + 1:]:
        text = _clean(candidate)
        if not text:
            continue
        if _is_heading(text):
            raise ValueError(f"No se encontro una descripcion debajo del titulo en {source}.")
        return text
    raise ValueError(f"No se encontro una descripcion debajo del titulo en {source}.")


def _docx_text_blocks(document: Document) -> list[str]:
    """Return paragraph and table-cell text from a DOCX.

    PDP duration options are commonly stored in a table rather than in body
    paragraphs, so duration extraction must inspect both structures.
    """
    blocks = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            blocks.extend(cell.text for cell in row.cells)
    return blocks


def _docx_ordered_blocks(document: Document) -> list[str]:
    """Read paragraph and table content in the document's visual order."""
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            blocks.append(Paragraph(child, document).text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            for row in table.rows:
                for cell in row.cells:
                    blocks.extend(paragraph.text for paragraph in cell.paragraphs)
    return blocks


def extract_benefits(filename: str, content: bytes) -> tuple[str, ...]:
    """Extract benefit texts from the PDP's Beneficios de estudiar en Utel block."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            blocks = _docx_ordered_blocks(Document(BytesIO(content)))
        elif extension == ".pdf":
            blocks = [
                line
                for page in PdfReader(BytesIO(content)).pages
                for line in (page.extract_text() or "").splitlines()
            ]
        else:
            raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo leer los beneficios de {filename}.") from error

    marker = _normalize("Beneficios de estudiar en Utel")
    values: list[str] = []
    active = False
    for block in blocks:
        for raw_line in block.splitlines():
            line = _clean(raw_line)
            if not line:
                continue
            normalized = _normalize(line)
            if marker in normalized:
                active = True
                continue
            if not active:
                continue
            if re.match(r"^\(?\s*(?:web|coms|pdp|ft|padron|pendiente)\s*\)?\s*(?:bloque|banner|cintillo|documentos|pasos)", normalized):
                active = False
                break
            if normalized in {"formulario", "header"}:
                active = False
                break
            value = re.sub(r"^[•·▪◦\-–*]\s*", "", line).strip()
            if value and _normalize(value) not in {_normalize(item) for item in values}:
                values.append(value)
    return tuple(values)


@dataclass(frozen=True)
class LaborFieldContent:
    areas: tuple[tuple[str, str], ...]
    positions: tuple[str, ...]
    market_description: str


def _docx_labor_blocks(document: Document) -> list[str]:
    """Return body and table-cell lines used by the labor-field sections."""
    # PDP exports frequently place the section content in tables. Reading all
    # paragraphs first and all tables afterward makes a later table (for
    # example, graduate testimonials) look like it belongs to an earlier
    # market section. Keep the document's visual order instead.
    return [block for block in _docx_ordered_blocks(document) if _clean(block)]


def _section_lines(blocks: list[str], marker: str) -> list[str]:
    """Extract the lines following a labeled FT/PDP block."""
    marker_normalized = _normalize(marker)
    section_markers = {
        "areas en las que vas a poder trabajar",
        "puestos que podrias ocupar",
        "datos de mercado laboral",
    }
    result: list[str] = []
    active = False
    for block in blocks:
        lines = [_clean(line) for line in block.splitlines() if _clean(line)]
        for line in lines:
            normalized = _normalize(line)
            if marker_normalized in normalized:
                active = True
                continue
            if not active:
                continue
            # A labor-field document contains three consecutive subsections.
            # Stop at the next subsection so areas, positions, and market copy
            # are not mixed into one another.
            if normalized in section_markers:
                active = False
                continue
            # Another labeled block marks the end of the requested section.
            if re.match(r"^\(?\s*(?:web|coms|pdp|ft|padron|pendiente)\s*\)?\b", normalized):
                active = False
                continue
            if normalized.startswith(("fuente", "source", "referencia", "http www", "https www")) or normalized.startswith("http"):
                active = False
                continue
            result.append(re.sub(r"^[•·▪◦\-–*]\s*", "", line).strip())
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean(value)
        key = _normalize(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _parse_area_items(lines: list[str]) -> list[tuple[str, str]]:
    """Group area titles with the descriptions that follow them.

    Some PDPs use ``Title: description`` on one line, while others place the
    four titles and their four descriptions on alternating lines. The latter
    must remain four area items, not eight separate items.
    """
    cleaned_lines = _dedupe(lines)
    areas: list[tuple[str, str]] = []
    index = 0
    while index < len(cleaned_lines):
        line = cleaned_lines[index]
        if ":" in line:
            title, description = line.split(":", 1)
            areas.append((_clean(title), _clean(description)))
            index += 1
            continue

        next_line = cleaned_lines[index + 1] if index + 1 < len(cleaned_lines) else ""
        next_word_count = len(next_line.split())
        looks_like_description = (
            bool(next_line)
            and (next_word_count >= 8 or next_line.endswith((".", ";")))
        )
        if looks_like_description:
            areas.append((line, next_line))
            index += 2
        else:
            areas.append((line, ""))
            index += 1
    return areas


def extract_labor_field_content(filename: str, content: bytes) -> LaborFieldContent:
    """Extract labor-field areas, positions and market copy from a source document."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            blocks = _docx_labor_blocks(Document(BytesIO(content)))
        elif extension == ".pdf":
            blocks = [line for page in PdfReader(BytesIO(content)).pages for line in (page.extract_text() or "").splitlines()]
        else:
            raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo abrir el contenido de oportunidades profesionales en {filename}.") from error

    areas_raw = _section_lines(blocks, "Áreas en las que vas a poder trabajar")
    positions_raw = _section_lines(blocks, "Puestos que podrías ocupar")
    market_raw = _section_lines(blocks, "Datos de mercado laboral")

    areas = _parse_area_items(areas_raw)
    market = "\n\n".join(_dedupe(market_raw))
    if not areas and not positions_raw and not market:
        raise ValueError(f"No se encontró contenido de oportunidades profesionales en {filename}.")
    return LaborFieldContent(tuple(areas), tuple(_dedupe(positions_raw)), market)


def extract_pdp_market_description(filename: str, content: bytes) -> str | None:
    """Extract only the PDP's ``(Coms) Datos de mercado laboral`` block."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            blocks = _docx_labor_blocks(Document(BytesIO(content)))
        elif extension == ".pdf":
            blocks = [
                line
                for page in PdfReader(BytesIO(content)).pages
                for line in (page.extract_text() or "").splitlines()
            ]
        else:
            raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo abrir los datos de mercado laboral en {filename}.") from error

    values: list[str] = []
    found_section = False
    active = False
    for block in blocks:
        for raw_line in block.splitlines():
            line = _clean(raw_line)
            if not line:
                continue
            normalized = _normalize(line)
            if re.match(r"^coms\b.*datos de mercado laboral\b", normalized):
                active = True
                found_section = True
                continue
            if not active:
                continue
            if re.match(r"^\(?\s*(?:web|coms|pdp|ft|padron|pendiente)\s*\)?\b", normalized):
                active = False
                continue
            if normalized in {
                "areas en las que vas a poder trabajar",
                "puestos que podrias ocupar",
                "datos de mercado laboral",
            }:
                active = False
                continue
            if normalized.startswith(("fuente", "source", "referencia", "http www", "https www")) or normalized.startswith("http"):
                active = False
                continue
            values.append(re.sub(r"^[•·▪◦\-–*]\s*", "", line).strip())
    return "\n\n".join(_dedupe(values)) if found_section else None


def _docx_subject_blocks(document: Document) -> list[tuple[str, str]]:
    """Return paragraph and table-cell lines with their optional style."""
    blocks: list[tuple[str, str]] = [
        (line, paragraph.style.name if paragraph.style else "")
        for paragraph in document.paragraphs
        for line in paragraph.text.splitlines()
    ]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for line in cell.text.splitlines():
                    blocks.append((line, ""))
    return blocks


def extract_content_description(filename: str, content: bytes) -> str:
    """Extract text after Asignaturas and before the first cuatrimestre block."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            document = Document(BytesIO(content))
            blocks = _docx_text_blocks(document)
        elif extension == ".pdf":
            reader = PdfReader(BytesIO(content))
            blocks = []
            for page in reader.pages:
                blocks.extend((page.extract_text() or "").splitlines())
        else:
            raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo abrir el Documento PDP {filename}.") from error
    heading_index = next(
        (
            index
            for index, block in enumerate(blocks)
            if _normalize(block) in {"asignaturas", "materias", "plan de estudios"}
            or "plan de estudios" in _normalize(block)
        ),
        None,
    )
    if heading_index is None:
        raise ValueError(f"No se encontro la seccion Plan de estudios en {filename}.")
    collected: list[str] = []
    for block in blocks[heading_index + 1:]:
        text = _clean(block)
        if not text:
            continue
        if re.match(r"^\d+\s*[°º.]?\s*(?:cuatrimestre|semestre)\b", _normalize(text), re.I):
            break
        if re.match(r"^\(?web\)?\s*bloque\b", _normalize(text), re.I):
            break
        collected.append(text)
    if not collected:
        raise ValueError(f"No se encontro contenido antes de las asignaturas en {filename}.")
    return "\n\n".join(collected)


def extract_description(program: str, filename: str, content: bytes) -> str:
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            document = Document(BytesIO(content))
            blocks = [paragraph.text for paragraph in document.paragraphs]
            return _extract_after_title(program, blocks, filename)
        if extension == ".pdf":
            reader = PdfReader(BytesIO(content))
            blocks = []
            for page in reader.pages:
                blocks.extend((page.extract_text() or "").splitlines())
            return _extract_after_title(program, blocks, filename)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo abrir el Documento PDP {filename}.") from error
    raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")


def extract_program_explanation(program: str, filename: str, content: bytes) -> str:
    """Extract the copy immediately below the PDP's Qué es... block."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            blocks = [paragraph.text for paragraph in Document(BytesIO(content)).paragraphs]
        elif extension == ".pdf":
            blocks = [line for page in PdfReader(BytesIO(content)).pages for line in (page.extract_text() or "").splitlines()]
        else:
            raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo abrir el Documento PDP {filename}.") from error

    target = _normalize(program)
    heading_index = next(
        (
            index for index, block in enumerate(blocks)
            if "que es" in _normalize(block) and target in _normalize(block)
        ),
        None,
    )
    if heading_index is None:
        raise ValueError(f"No se encontro el bloque Qué es de {program} en {filename}.")
    collected: list[str] = []
    for block in blocks[heading_index + 1:]:
        text = _clean(block)
        if not text:
            continue
        normalized = _normalize(text)
        if re.match(r"^(?:web|coms|padron|pendiente)\b.*\bbloque\b", normalized):
            break
        collected.append(text)
    if not collected:
        raise ValueError(f"El bloque Qué es de {filename} no tiene descripción.")
    return "\n\n".join(collected)


def extract_program_durations(filename: str, content: bytes) -> list[str]:
    """Return all distinct month durations from the PDP's Duración line.

    PDPs used to contain exactly two options. Newer PDPs can contain one,
    two, three or more, so the parser only requires at least one option and returns every
    distinct duration in ascending order.
    """
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            blocks = _docx_text_blocks(Document(BytesIO(content)))
        elif extension == ".pdf":
            blocks = []
            for page in PdfReader(BytesIO(content)).pages:
                blocks.extend((page.extract_text() or "").splitlines())
        else:
            raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo abrir el Documento PDP {filename}.") from error
    durations: list[str] = []
    for block in blocks:
        if not re.search(r"\b(?:duraci[oó]n|completa|intensivo|base|super\s+intensivo)\b", block, re.I):
            continue
        for months in re.findall(r"\b(\d+)\s*mes(?:es)?\b", block, re.I):
            value = f"{months} meses"
            if value not in durations:
                durations.append(value)
    if not durations:
        raise ValueError(
            f"El PDP {filename} debe contener al menos una duración; "
            f"se encontraron: {', '.join(durations) or 'ninguna'}."
        )
    return sorted(durations, key=lambda value: int(value.split()[0]))


def extract_rvoe_numbers(filename: str, content: bytes) -> list[str]:
    """Extract RVOE agreement numbers from a PDP or FT document."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            blocks = _docx_text_blocks(Document(BytesIO(content)))
        elif extension == ".pdf":
            blocks = [line for page in PdfReader(BytesIO(content)).pages for line in (page.extract_text() or "").splitlines()]
        else:
            raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo abrir el contenido de validez académica en {filename}.") from error
    found: list[str] = []
    for block in blocks:
        for number in re.findall(r"\bRVOE(?:\s+SEP)?\s*(?:[:|#-]\s*)?(\d{6,})\b", block, re.I):
            if number not in found:
                found.append(number)
    return found


def extract_graduate_testimonies(filename: str, content: bytes, program: str) -> list[tuple[str, str]]:
    """Extract graduate names and comments from the PDP testimony block."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    if extension != ".docx":
        return []
    try:
        document = Document(BytesIO(content))
    except Exception as error:
        raise ValueError(f"No se pudo abrir el contenido de egresados en {filename}.") from error

    target_program = _normalize(program)

    def program_matches(value: str) -> bool:
        candidate = _normalize(value)
        if not candidate or not target_program:
            return False
        if target_program in candidate or candidate in target_program:
            return True
        # Google Docs exports can replace accented characters with ``�``.
        # A close match is safe here because it is evaluated inside the
        # product-specific graduate section and against a full program title.
        compact_candidate = re.sub(r"[^a-z0-9]", "", candidate)
        compact_target = re.sub(r"[^a-z0-9]", "", target_program)
        return SequenceMatcher(None, compact_candidate, compact_target).ratio() >= 0.94

    target = _normalize(f"Egresados de {program}")
    # Google Docs exports the section heading either as a regular paragraph or
    # inside a table cell, depending on how the block was authored.  Check
    # both locations before parsing the testimony rows.
    section_texts = [paragraph.text for paragraph in document.paragraphs]
    section_texts.extend(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    has_section = any(
        target in _normalize(text)
        or ("egresados de" in _normalize(text) and program_matches(text))
        for text in section_texts
    )
    # Some DOCX exports replace accented characters with the replacement
    # character (for example ``Pol�ticas``).  In that case the heading cannot
    # be matched reliably even though the testimony table is intact.  The
    # table signature below is specific enough to serve as a safe fallback.

    testimonies: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_testimony(name: str, comment: str) -> None:
        name = _clean(name).strip('"“”')
        comment = _clean(comment).strip('"“”')
        if not name or not comment or len(name) < 3:
            return
        key = (_normalize(name), _normalize(comment))
        if key not in seen:
            seen.add(key)
            testimonies.append((name, comment))

    def label_index(lines: list[str], pattern: str) -> int | None:
        return next((index for index, line in enumerate(lines) if re.match(pattern, _normalize(line))), None)

    def value_after_label(line: str, label: str) -> str:
        match = re.match(rf"{label}\s*[:\-]\s*(.+)$", line, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    for table in document.tables:
        for row in table.rows:
            # Each Google Docs testimonial card is usually a separate cell.
            # Keeping cells separate prevents one card's name from being used
            # as the next card's comment when the row contains several cards.
            for cell in row.cells:
                cell_lines = [_clean(line) for line in cell.text.splitlines() if _clean(line)]
                cell_normalized = [_normalize(line) for line in cell_lines]
                if not cell_lines:
                    continue

                # Explicit Nombre/Comentario labels are supported as before.
                name_index = label_index(cell_lines, r"^nombre\b")
                comment_index = label_index(cell_lines, r"^(?:comentario|testimonio)\b")
                if name_index is not None and comment_index is not None:
                    name = value_after_label(cell_lines[name_index], r"nombre")
                    if not name and name_index + 1 < len(cell_lines):
                        name = cell_lines[name_index + 1]
                    comment = value_after_label(cell_lines[comment_index], r"(?:comentario|testimonio)")
                    if not comment and comment_index + 1 < len(cell_lines):
                        comment = "\n\n".join(cell_lines[comment_index + 1 :])
                    add_testimony(name, comment)

                marker_indexes = [
                    index for index, value in enumerate(cell_normalized)
                    if value.startswith("egresad")
                ]
                for marker_index in marker_indexes:
                    preceding = cell_lines[:marker_index]
                    if len(preceding) < 2:
                        continue
                    program_index = next(
                        (index for index, value in enumerate(preceding) if program_matches(value)),
                        None,
                    )
                    # The common card format is comment, name, program,
                    # Egresado/a, year. Older cards use comment, name,
                    # Carrera:, Egresado. Both have the name immediately
                    # before the program/career line.
                    if program_index is None:
                        program_index = len(preceding) - 1
                    if program_index < 1:
                        continue
                    name_index = program_index - 1
                    comment_lines = preceding[:name_index]
                    add_testimony(cell_lines[name_index], "\n\n".join(comment_lines))

        # A table without the PDP heading is only accepted when it has the
        # unambiguous card signature used by the existing documents. This
        # avoids interpreting unrelated tables as testimonials.

    if not has_section and not testimonies:
        return []
    return testimonies


def extract_active_graduates_percentage(filename: str, content: bytes) -> int | None:
    """Extract the percentage shown in the PDP `(Padron) Banner` block."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    if extension != ".docx":
        return None
    try:
        document = Document(BytesIO(content))
    except Exception as error:
        raise ValueError(f"No se pudo abrir el banner de egresados en {filename}.") from error

    document_blocks = _docx_ordered_blocks(document)
    has_banner = any(
        "padron" in _normalize(block) and "banner" in _normalize(block)
        for block in document_blocks
    )
    if not has_banner:
        return None

    # Some exports keep the percentage in a text block instead of the table.
    for block in document_blocks:
        normalized = _normalize(block)
        if "egresados" not in normalized and "activos" not in normalized:
            continue
        match = re.search(r"\b(\d{1,3})\s*%", block)
        if match:
            value = int(match.group(1))
            if 0 <= value <= 100:
                return value

    for table in document.tables:
        table_text = "\n".join(cell.text for row in table.rows for cell in row.cells)
        normalized = _normalize(table_text)
        if "egresados" not in normalized or "activos" not in normalized:
            continue
        match = re.search(r"\b(\d{1,3})\s*%", table_text)
        if match:
            value = int(match.group(1))
            if 0 <= value <= 100:
                return value
    return None


DEFAULT_ACTIVE_GRADUATES_PERCENTAGE = 90


def resolve_active_graduates_percentage(filename: str, content: bytes) -> int:
    """Return the PDP banner percentage, defaulting to 90 when it is absent."""
    extracted = extract_active_graduates_percentage(filename, content)
    return DEFAULT_ACTIVE_GRADUATES_PERCENTAGE if extracted is None else extracted


def extract_curriculum(filename: str, content: bytes) -> list[tuple[str, list[str]]]:
    """Extract subjects grouped by their semester/cuatrimestre heading."""
    extension = Path(urlparse(filename).path or filename).suffix.casefold()
    try:
        if extension == ".docx":
            document = Document(BytesIO(content))
            blocks = _docx_subject_blocks(document)
        elif extension == ".pdf":
            blocks = [line for page in PdfReader(BytesIO(content)).pages for line in (page.extract_text() or "").splitlines()]
        else:
            raise ValueError(f"Formato de Documento PDP no soportado: {filename}.")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"No se pudo abrir el Documento PDP {filename}.") from error
    curriculum: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_subjects: list[str] = []
    for item in blocks:
        text = _clean(item[0] if isinstance(item, tuple) else item)
        style = (item[1] if isinstance(item, tuple) else "").casefold()
        normalized = _normalize(text)
        if re.match(r"^\d+\s*[°º.]?\s*(cuatrimestre|semestre)\b", normalized):
            if current_title is not None:
                curriculum.append((current_title, current_subjects))
            current_title = text
            current_subjects = []
            continue
        if current_title is None or not text:
            continue
        if re.match(r"^(?:preguntas frecuentes|faq|que es|qué es|requisitos de admision|oportunidades profesionales|areas de concentracion|creditos totales|optativas)\b", normalized) or re.match(r"^(?:bandera|web|coms|padron|pendiente)\b", normalized) or text.startswith(("¿", "?")) or re.match(r"^\d+\.\s*", text):
            break
        if re.match(r"^(?:plan de estudios|asignaturas|materias|formacion|area)\b", normalized):
            continue
        clean = re.sub(r"^[•·\-–]\s*", "", text).strip()
        # PDP DOCX files commonly use plain paragraphs (Normal style) for
        # subjects, while PDFs and other files use bullets.
        if clean and clean not in current_subjects and not clean.endswith(":"):
            current_subjects.append(clean)
    if current_title is not None:
        curriculum.append((current_title, current_subjects))
    return [(title, items) for title, items in curriculum if items]


def extract_subjects(filename: str, content: bytes) -> list[str]:
    """Extract all subjects, preserving the legacy flat return shape."""
    return [subject for _, subjects in extract_curriculum(filename, content) for subject in subjects]

