# Automatizaciones

Cada subcarpeta encapsula un flujo de navegador o de análisis independiente.

| Carpeta | Propósito |
| --- | --- |
| `generic_bot/` | Ejecución y grabación de pasos configurables. |
| `utel_inconcert/` | Flujo especializado UTEL → formulario → InConcert. |
| `weekly_auto/` | Apertura, captura y evidencia de URLs semanales. |
| `pdp_validation/` | Extracción, normalización y comparación de documentos y páginas. |

Los módulos de automatización no deben importar la capa HTTP ni acceder al DOM del frontend.
