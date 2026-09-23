"""Normalización conservadora para comparar sin perder evidencia."""

from __future__ import annotations

import html
import re
import unicodedata


def display_text(value: str) -> str:
    """Limpia espacios y entidades sin alterar el contenido visible."""

    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalized_text(value: str) -> str:
    """Normaliza mayúsculas, acentos, bullets y puntuación visual."""

    value = display_text(value).lower()
    value = "".join(character for character in unicodedata.normalize("NFKD", value) if not unicodedata.combining(character))
    value = re.sub(r"^\s*\d+\s*[.)]\s*", "", value)
    value = "".join(character if character.isalnum() or character in "?/:|" else " " for character in value)
    return re.sub(r"\s+", " ", value).strip(" .,:;-")


def token_set(value: str) -> set[str]:
    return {token for token in normalized_text(value).split() if len(token) > 2}
