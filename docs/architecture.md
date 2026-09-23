# Arquitectura de la Fase 1

## Responsabilidades

### Electron

`frontend/src/main.js` crea la ventana y levanta FastAPI como un proceso hijo local. El proceso principal no ejecuta automatizaciones: su responsabilidad es coordinar la aplicación de escritorio.

`frontend/src/preload.js` expone únicamente la plataforma y la URL de la API. El renderer mantiene `nodeIntegration` desactivado para reducir la superficie de ataque.

`frontend/src/renderer/` contiene la interfaz y su navegación. `services/api.js` concentra las peticiones HTTP para que las pantallas no repitan código de comunicación.

### FastAPI

`backend/app/main.py` crea la aplicación, registra CORS local, inicializa carpetas, logs y SQLite.

`backend/app/api/routes.py` define el contrato HTTP.

`backend/app/services/` contiene reglas de aplicación.

`backend/app/database/` contiene SQL y conexión SQLite. Las rutas no ejecutan SQL directamente.

`backend/app/config/settings.py` centraliza rutas, puerto y variables de entorno.

## Flujo de una consulta del dashboard

```text
Usuario
  ↓
Renderer de Electron
  ↓ fetch /api/dashboard/summary
FastAPI / api/routes.py
  ↓
DashboardService
  ↓
ExecutionRepository
  ↓
SQLite en storage/qa_automation.db
```

La tabla `executions` ya soporta estados `SUCCESS`, `FAIL`, `WARNING`, `RUNNING` y `PENDING`. Las automatizaciones de las siguientes fases escribirán en ella y el dashboard podrá mostrar sus resultados sin cambiar la interfaz base.
