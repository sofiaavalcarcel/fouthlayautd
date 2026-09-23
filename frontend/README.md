# Frontend

Esta carpeta contiene exclusivamente la aplicación que ve y utiliza el equipo QA.

## Subcarpetas

| Ruta | Responsabilidad |
| --- | --- |
| `src/renderer/` | Pantallas, navegación, estilos y comportamiento de cada módulo visual. |
| `src/services/` | Cliente HTTP y comunicación con la API; las pantallas no hacen `fetch` directo. |
| `tests/` | Pruebas unitarias de los procesos y módulos del frontend. |

## Archivos de entrada

- `index.html`: punto de entrada de la versión web servida por FastAPI.
- `src/main.js`: proceso principal de Electron.
- `src/preload.js`: API mínima y segura expuesta a la ventana de Electron.
- `src/backend-process.js`: arranque y comprobación del backend cuando se usa Electron.

Las pantallas deben delegar toda llamada de red a `src/services/api.js` y no deben contener credenciales ni secretos.
