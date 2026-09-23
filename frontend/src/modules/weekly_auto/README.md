# Weekly Auto - Frontend

El coordinador `module.js` conecta cuatro submódulos independientes, cada uno con su propia vista en el menú lateral:

- `weekly_photos/`: controlador, API y estilos de la automatización existente.
- `weekly_forms/`: carga del Excel, ejecución en tandas y descarga del reporte.
- `weekly_leads/`: módulo principal Form Validation para envíos generales de leads.
- `weekly_performance/`: medición PageSpeed y descarga de resultados.

El archivo `frontend/src/renderer/weekly-auto-module.js` es únicamente un adaptador para conservar el import actual de la aplicación.
