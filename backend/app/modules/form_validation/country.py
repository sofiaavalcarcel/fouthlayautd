"""Normalización segura de URLs QA e inferencia del país de una landing."""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


# Se permiten subdominios institucionales existentes sin abrir la automatización
# a dominios arbitrarios incluidos por accidente en un Excel.
ALLOWED_HOST_SUFFIXES = (
    "utel.edu.mx",
    "utlenlinea.com",
    "utel.mx",
)
TEST_HOSTS = {"example.com", "example.test"}

_COUNTRY_ALIASES = {
    "mexico": "México",
    "méxico": "México",
    "peru": "Perú",
    "perú": "Perú",
    "usa": "USA",
    "united states": "USA",
    "estados unidos": "USA",
    "philippines": "Filipinas",
    "filipinas": "Filipinas",
    "indonesia": "Indonesia",
    "colombia": "Colombia",
    "argentina": "Argentina",
    "ecuador": "Ecuador",
    # ISO-3166 y abreviaturas habituales de los reportes de landings.
    "mx": "México",
    "co": "Colombia",
    "ar": "Argentina",
    "pe": "Perú",
    "ec": "Ecuador",
    "bo": "Bolivia",
    "cl": "Chile",
    "py": "Paraguay",
    "do": "Dominicana",
    "gt": "Guatemala",
    "pa": "Panamá",
    "sv": "El Salvador",
    "us": "USA",
    "ph": "Filipinas",
    "id": "Indonesia",
    "in": "India",
    "vn": "Vietnam",
    "india": "India",
    "vietnam": "Vietnam",
}


def normalize_allowed_url(value: str) -> str:
    """Devuelve una URL HTTPS permitida o lanza ``ValueError``.

    Los espacios, fragmentos y esquemas ausentes se normalizan antes de validar.
    Esto evita que una fila mal formada abra un navegador fuera del alcance del
    módulo.
    """

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("La URL está vacía.")
    candidate = raw if re.match(r"^https?://", raw, re.I) else f"https://{raw}"
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("La URL no tiene un esquema HTTP válido.")
    if hostname not in TEST_HOSTS and not any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES):
        raise ValueError(
            "La URL no pertenece a un dominio UTEL permitido "
            "(utel.edu.mx, utlenlinea.com o utel.mx)."
        )
    # HTTPS evita redirecciones innecesarias en las landings institucionales.
    return urlunparse(("https", hostname, parsed.path or "/", "", parsed.query, ""))


def _provided_country(value: str) -> str:
    """Canonicaliza un país aportado por el Excel cuando no es ``Global``."""

    normalized = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
    return _COUNTRY_ALIASES.get(normalized, str(value or "").strip())


def infer_country(country: str | None, url: str, context: str | None = None) -> str:
    """Infiere el país desde la columna o desde la ruta institucional.

    La columna tiene prioridad salvo que esté vacía o indique ``Global``. Las
    rutas de Filipinas/Indonesia se conservan para las portadas donde vive el
    FooterBLC, y la raíz de UTEL se interpreta como México.
    """

    supplied = str(country or "").strip()
    if supplied and supplied.casefold() not in {"global", "world", "internacional"}:
        return _provided_country(supplied)
    normalized_url = normalize_allowed_url(url)
    parsed = urlparse(normalized_url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold().rstrip("/")

    if host == "utlenlinea.com" or host.endswith(".utlenlinea.com"):
        return "Perú"
    # Las matrices QA usan ``Global`` junto con niveles como
    # ``Filipinas Bachelor`` o ``India Master``. En esas filas el contexto del
    # nivel es la única evidencia de país disponible y debe ganar al valor
    # predeterminado México de la ruta /global.
    context_normalized = re.sub(r"\s+", " ", str(context or "")).casefold()
    for token, result in (
        ("filipinas", "Filipinas"),
        ("philippines", "Filipinas"),
        ("indonesia", "Indonesia"),
        ("india", "India"),
        ("vietnam", "Vietnam"),
    ):
        if re.search(rf"\b{re.escape(token)}\b", context_normalized):
            return result
    # El orden es importante: la ruta específica gana frente a la raíz México.
    for segment, result in (
        ("/colombia", "Colombia"),
        ("/argentina", "Argentina"),
        ("/usa", "USA"),
        ("/peru", "Perú"),
        ("/philippines", "Filipinas"),
        ("/indonesia", "Indonesia"),
        ("/ecuador", "Ecuador"),
    ):
        if path == segment or path.startswith(f"{segment}/"):
            return result
    return "México"
