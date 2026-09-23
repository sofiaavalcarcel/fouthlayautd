from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CountryConfig:
    code: str
    label: str
    locale: str
    slug: str


COUNTRIES: dict[str, CountryConfig] = {
    "AR": CountryConfig("AR", "Argentina", "es-AR", "argentina"),
    "MX": CountryConfig("MX", "Mexico", "es-MX", "mexico"),
    "SV": CountryConfig("SV", "El Salvador", "es-SV", "elsalvador"),
    "US": CountryConfig("US", "USA", "es-US", "usa"),
    "DO": CountryConfig("DO", "Republica Dominicana", "es-DO", "dominicana"),
    "PA": CountryConfig("PA", "Panama", "es-PA", "panama"),
    "BO": CountryConfig("BO", "Bolivia", "es-BO", "bolivia"),
    "CL": CountryConfig("CL", "Chile", "es-CL", "chile"),
    "CO": CountryConfig("CO", "Colombia", "es-CO", "colombia"),
    "EC": CountryConfig("EC", "Ecuador", "es-EC", "ecuador"),
    "PE": CountryConfig("PE", "Peru", "es-PE", "peru"),
    "PY": CountryConfig("PY", "Paraguay", "es-PY", "paraguay"),
}


def detect_country_from_filename(filename: str) -> CountryConfig:
    """Detect a country code from '[AR] ...' or 'AR-...' filenames."""

    name = Path(filename).name
    match = re.match(r"^\s*(?:\[([A-Za-z]{2})\]|([A-Za-z]{2})(?=[-_ ]))", name)
    if not match:
        raise ValueError("El archivo debe comenzar con un codigo de pais, por ejemplo [AR].")

    code = (match.group(1) or match.group(2)).upper()
    country = COUNTRIES.get(code)
    if country is None:
        raise ValueError(f"El codigo de pais [{code}] no esta configurado.")
    return country

