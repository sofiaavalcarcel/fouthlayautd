# Weekly Auto - Backend

Cada automatización semanal vive en su propia subcarpeta:

- `weekly_photos/`: implementación actual de capturas y validaciones de páginas.
- `weekly_forms/`: importación QA, detección semántica, envío y verificación CRM.
- `weekly_leads/`: adaptador independiente para envíos generales con la misma matriz y reglas.
- `weekly_performance/`: medición PageSpeed y descarga de resultados.

`runner.py` se conserva como adaptador para no romper imports existentes.
