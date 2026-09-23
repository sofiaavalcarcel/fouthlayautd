# Backend

Esta carpeta implementa la API FastAPI, las automatizaciones y la persistencia local. La capa web nunca accede directamente a SQLite, archivos de almacenamiento ni credenciales.

## Subcarpetas

| Ruta | Responsabilidad |
| --- | --- |
| `app/api/` | Endpoints HTTP y orquestación de solicitudes. |
| `app/automations/` | Ejecutores aislados de Playwright y lógica de cada automatización. |
| `app/config/` | Configuración tipada desde variables de entorno. |
| `app/database/` | Inicialización y repositorios de SQLite. |
| `app/schemas/` | Contratos Pydantic de entrada y salida de la API. |
| `app/services/` | Reglas de negocio, generación de reportes e integraciones. |
| `tests/` | Pruebas unitarias y de integración del backend. |

`app/main.py` es el único punto de entrada de FastAPI. Las rutas deben validar datos mediante esquemas y delegar la lógica de negocio a servicios o automatizaciones.
