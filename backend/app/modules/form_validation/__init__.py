"""Componentes compartidos del flujo Form Validation.

El módulo reutiliza el runner histórico de Weekly Forms, pero mantiene en este
paquete las reglas de entrada que son propias de URLs QA y reportes generales.
"""

from .country import infer_country, normalize_allowed_url

__all__ = ["infer_country", "normalize_allowed_url"]
