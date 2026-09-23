# Automatizaciones

Cada subcarpeta encapsula un flujo de navegador o de análisis independiente.

| Carpeta | Propósito |
| --- | --- |
| `generic_bot/` | Ejecución y grabación de pasos configurables. |
| `utel_inconcert/` | Flujo especializado UTEL → formulario → InConcert. |
| `weekly_auto/` | Adaptadores `weekly_photos/`, `weekly_forms/`, `weekly_leads/` y `weekly_performance/` hacia sus módulos canónicos. |

Los módulos de automatización no deben importar la capa HTTP ni acceder al DOM del frontend.
