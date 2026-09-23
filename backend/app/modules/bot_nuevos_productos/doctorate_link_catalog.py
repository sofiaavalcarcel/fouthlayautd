"""Catálogo validado de enlaces directos a doctorados por país."""

from pathlib import Path
from urllib.parse import urlparse

from .program_rotation_service import normalize


# Fuente QA: "enlazes directos  (1).xlsx", Hoja 1, rango A1:C79.
# Estos enlaces evitan depender del clic desde los listados, que puede activar
# el bloqueo de acceso antes de llegar a la página del programa.
_COUNTRY_ROUTES: dict[str, tuple[str, str]] = {
    "usa": ("utel.edu.mx", "/usa"),
    "bolivia": ("utel.edu.mx", "/bolivia"),
    "chile": ("utel.edu.mx", "/chile"),
    "paraguay": ("utel.edu.mx", "/paraguay"),
    "dominicana": ("utel.edu.mx", "/dominicana"),
    "guatemala": ("utel.edu.mx", "/guatemala"),
    "panama": ("utel.edu.mx", "/panama"),
    "el salvador": ("utel.edu.mx", "/elsalvador"),
    "argentina": ("utel.edu.mx", "/argentina"),
    "mexico": ("utel.edu.mx", ""),
    "colombia": ("utel.edu.mx", "/colombia"),
    "peru": ("utlenlinea.com", ""),
}

_PROGRAM_NAMES = {
    "administracion-estrategica-empresarial": "Doctorado en Administración Estratégica Empresarial",
    "educacion": "Doctorado en Educación",
    "gestion-e-innovacion-tecnologica": "Doctorado en Gestión e Innovación Tecnológica",
    "finanzas": "Doctorado en Finanzas",
    "estudios-interdisciplinarios-sobre-america-latina": "Doctorado en Estudios Interdisciplinarios sobre América Latina",
    "estudios-interculturales-y-diversidad-humana": "Doctorado en Estudios Interculturales y Diversidad Humana",
    "desarrollo-sostenible-y-gestion-ambiental": "Doctorado en Desarrollo Sostenible y Gestión Ambiental",
    "desarrollo-humano": "Doctorado en Desarrollo Humano",
    "calidad-y-sostenibilidad-organizacional": "Doctorado en Calidad y Sostenibilidad Organizacional",
    "ciencia-de-datos-e-inteligencia-artificial": "Doctorado en Ciencia de Datos e Inteligencia Artificial",
    "ciberseguridad-de-sistemas-autonomos": "Doctorado en Ciberseguridad de Sistemas Autónomos",
    "ciberseguridad-y-gestion-de-riesgos-digitales": "Doctorado en Ciberseguridad y Gestión de Riesgos Digitales",
    "tecnologia-educativa-e-innovacion-didactica": "Doctorado en Tecnología Educativa e Innovación Didáctica",
    "liderazgo-educativo-y-gestion-escolar": "Doctorado en Liderazgo Educativo y Gestión Escolar",
    "justicia-digital-y-ciberderecho": "Doctorado en Justicia Digital y Ciberderecho",
    "derecho": "Doctorado en Derecho",
    "transformacion-digital-organizacional": "Doctorado en Transformación Digital Organizacional",
    "urbanismo": "Doctorado en Urbanismo",
    "economia-publica-fiscalidad-y-gobernanza-financiera": "Doctorado en Economía Pública, Fiscalidad y Gobernanza Financiera",
    "evaluacion-de-politicas-sociales-y-programas-publicos": "Doctorado en Evaluación de Políticas Sociales y Programas Públicos",
    "politicas-publicas-y-gobernanza": "Doctorado en Políticas Públicas y Gobernanza",
    "alta-direccion-y-gobierno-corporativo": "Doctorado en Alta Dirección y Gobierno Corporativo",
}


def _entries(country: str, *slugs: str) -> tuple[tuple[str, str], ...]:
    host, prefix = _COUNTRY_ROUTES[country]
    return tuple(
        (_PROGRAM_NAMES[slug], f"https://{host}{prefix}/doctorado-en-{slug}")
        for slug in slugs
    )


_BASIC_PROGRAMS = ("educacion",)
_MEXICO_PROGRAMS = (
    "estudios-interdisciplinarios-sobre-america-latina",
    "estudios-interculturales-y-diversidad-humana",
    "desarrollo-sostenible-y-gestion-ambiental",
    "desarrollo-humano",
    "calidad-y-sostenibilidad-organizacional",
    "ciencia-de-datos-e-inteligencia-artificial",
    "ciberseguridad-de-sistemas-autonomos",
    "ciberseguridad-y-gestion-de-riesgos-digitales",
    "educacion",
    "tecnologia-educativa-e-innovacion-didactica",
    "liderazgo-educativo-y-gestion-escolar",
    "justicia-digital-y-ciberderecho",
    "derecho",
    "transformacion-digital-organizacional",
    "urbanismo",
    "economia-publica-fiscalidad-y-gobernanza-financiera",
    "evaluacion-de-politicas-sociales-y-programas-publicos",
    "politicas-publicas-y-gobernanza",
    "alta-direccion-y-gobierno-corporativo",
    "gestion-e-innovacion-tecnologica",
)
_COLOMBIA_PROGRAMS = (
    "politicas-publicas-y-gobernanza",
    "evaluacion-de-politicas-sociales-y-programas-publicos",
    "urbanismo",
    "estudios-interdisciplinarios-sobre-america-latina",
    "estudios-interculturales-y-diversidad-humana",
    "justicia-digital-y-ciberderecho",
    "educacion",
    "calidad-y-sostenibilidad-organizacional",
    "desarrollo-sostenible-y-gestion-ambiental",
    "economia-publica-fiscalidad-y-gobernanza-financiera",
    "transformacion-digital-organizacional",
    "alta-direccion-y-gobierno-corporativo",
    "liderazgo-educativo-y-gestion-escolar",
    "ciencia-de-datos-e-inteligencia-artificial",
    "ciberseguridad-de-sistemas-autonomos",
    "ciberseguridad-y-gestion-de-riesgos-digitales",
    "tecnologia-educativa-e-innovacion-didactica",
    "gestion-e-innovacion-tecnologica",
    "finanzas",
)
_PERU_PROGRAMS = (
    "gestion-e-innovacion-tecnologica",
    "ciencia-de-datos-e-inteligencia-artificial",
    "ciberseguridad-de-sistemas-autonomos",
    "ciberseguridad-y-gestion-de-riesgos-digitales",
    "finanzas",
    "alta-direccion-y-gobierno-corporativo",
    "economia-publica-fiscalidad-y-gobernanza-financiera",
    "transformacion-digital-organizacional",
    "desarrollo-sostenible-y-gestion-ambiental",
    "calidad-y-sostenibilidad-organizacional",
    "educacion",
    "liderazgo-educativo-y-gestion-escolar",
    "tecnologia-educativa-e-innovacion-didactica",
    "justicia-digital-y-ciberderecho",
    "estudios-interculturales-y-diversidad-humana",
    "estudios-interdisciplinarios-sobre-america-latina",
)

_CATALOG: dict[str, tuple[tuple[str, str], ...]] = {
    "usa": _entries("usa", *_BASIC_PROGRAMS),
    "bolivia": _entries("bolivia", *_BASIC_PROGRAMS),
    "chile": _entries("chile", *_BASIC_PROGRAMS),
    "paraguay": _entries("paraguay", *_BASIC_PROGRAMS),
    "dominicana": _entries(
        "dominicana",
        "educacion",
        "gestion-e-innovacion-tecnologica",
        "finanzas",
    ),
    "guatemala": _entries("guatemala", *_BASIC_PROGRAMS),
    "panama": _entries("panama", *_BASIC_PROGRAMS),
    "el salvador": _entries("el salvador", *_BASIC_PROGRAMS),
    "argentina": _entries("argentina", *_BASIC_PROGRAMS),
    "mexico": _entries("mexico", *_MEXICO_PROGRAMS),
    "colombia": _entries("colombia", *_COLOMBIA_PROGRAMS),
    "peru": _entries("peru", *_PERU_PROGRAMS),
}

_COUNTRY_ALIASES = {
    "united states": "usa",
    "estados unidos": "usa",
    "republica dominicana": "dominicana",
    "rep dominicana": "dominicana",
}


class DoctorateLinkCatalog:
    """Resuelve enlaces directos sin depender del DOM de un listado."""

    @staticmethod
    def is_leads_deploy_file(filename: str) -> bool:
        """Reconoce Leads Deploy sin depender de mayúsculas o sufijos como (1)."""

        return "leads deploy" in normalize(Path(filename or "").stem)

    @staticmethod
    def canonical_country(country: str) -> str:
        key = normalize(country)
        return _COUNTRY_ALIASES.get(key, key)

    @classmethod
    def programs(cls, country: str) -> list[dict[str, str]]:
        key = cls.canonical_country(country)
        programs = [{"text": text, "url": url} for text, url in _CATALOG.get(key, ())]
        education = next((item for item in programs if cls._program_key(item["text"]) == "educacion"), None)
        if education:
            # Esta PDP es estable. Administración Estratégica Empresarial se
            # elige dentro de su TarjetaBLC, sin abrir su PDP propia, que ha
            # presentado bloqueos de acceso.
            programs.append(
                {
                    "text": _PROGRAM_NAMES["administracion-estrategica-empresarial"],
                    "url": education["url"],
                    "page_title": education["text"],
                }
            )
        return programs

    @classmethod
    def resolve(cls, country: str, program_name: str) -> dict[str, str] | None:
        expected = cls._program_key(program_name)
        return next(
            (candidate for candidate in cls.programs(country) if cls._program_key(candidate["text"]) == expected),
            None,
        )

    @staticmethod
    def _program_key(program_name: str) -> str:
        key = normalize(program_name)
        return key.removeprefix("doctorado en ")

    @classmethod
    def validate(cls) -> None:
        """Falla temprano si el catálogo contiene un enlace o nombre inválido."""

        for country, programs in _CATALOG.items():
            expected_host, expected_country_path = _COUNTRY_ROUTES[country]
            expected_prefix = f"{expected_country_path}/doctorado-en-"
            names: set[str] = set()
            for name, url in programs:
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.netloc != expected_host:
                    raise ValueError(f"Enlace directo inválido para {country}: {url}")
                if not parsed.path.startswith(expected_prefix) or parsed.query or parsed.fragment:
                    raise ValueError(f"La ruta no corresponde al país {country}: {url}")
                key = cls._program_key(name)
                if key in names:
                    raise ValueError(f"Programa duplicado para {country}: {name}")
                names.add(key)


DoctorateLinkCatalog.validate()
