from __future__ import annotations

import re
import unicodedata
from urllib.parse import SplitResult, urlsplit, urlunsplit


def normalize_country_slug(country: str, country_slugs: dict[str, str]) -> str:
    """Return a configured slug, with a deterministic accent-insensitive fallback."""

    key = " ".join(country.casefold().split())
    configured = country_slugs.get(key)
    if configured:
        return configured.strip("/").casefold()

    plain = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def add_country_to_canonical(
    canonical: str,
    country: str,
    country_slugs: dict[str, str],
    expected_host: str = "utel.edu.mx",
) -> str:
    if not canonical or not canonical.strip():
        raise ValueError("LinkCanonical esta vacio.")

    parsed = urlsplit(canonical.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("LinkCanonical no es una URL valida.")
    if parsed.hostname.casefold() != expected_host.casefold():
        raise ValueError(f"El host del canonical no es el esperado: {parsed.netloc}")

    country_slug = normalize_country_slug(country, country_slugs)
    if not country_slug:
        raise ValueError("No se pudo convertir el pais a un slug valido.")

    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and segments[0].casefold() == country_slug:
        return canonical.strip()

    updated = SplitResult(
        scheme=parsed.scheme,
        netloc=parsed.netloc,
        path="/" + "/".join([country_slug, *segments]),
        query=parsed.query,
        fragment=parsed.fragment,
    )
    return urlunsplit(updated)

