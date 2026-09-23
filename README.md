# UTEL QA Automation Web + Desktop

Aplicación web y desktop para centralizar automatizaciones de QA. La interfaz puede abrirse directamente desde un navegador o desde Electron; ambos modos comparten el mismo backend FastAPI, SQLite, logs y automatizaciones.

Las automatizaciones reales de formularios, monitoreo visual y Excel/Strapi se incorporarán en las fases siguientes. También se añadió el módulo **Bot de verificaciones**, que permite construir flujos y ejecutarlos con Playwright.

## Arquitectura

```text
Navegador web o Electron
    ↓ HTTP
FastAPI (backend)
    ↓
SQLite + logs organizados
```

Electron arranca FastAPI automáticamente cuando se inicia la aplicación desktop. En modo web, FastAPI también sirve la interfaz. El navegador nunca recibe las credenciales, que se leen únicamente desde `.env` en el backend.

## Requisitos

- Node.js 18 o superior y npm.
- Python 3.11 o superior.
- En Windows, el comando `python` debe estar disponible. Se puede usar otro con `PYTHON_COMMAND`.

## Instalación

En un equipo Windows nuevo, abre **Iniciar.cmd**. El asistente solicita autorización para instalar las dependencias faltantes y luego inicia el modo web. También se comprueba la preparación al ejecutar `npm run web` o `npm start`. Consulta [tecnologías, instalación y compatibilidad](docs/instalacion.md).

Desde la raíz del proyecto:

```powershell
npm install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
python -m playwright install chromium
```

Para usar Google Chrome con una sesión persistente de QA, abre el perfil aislado con:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\open_chrome_qa.ps1
```

Inicia sesión en las plataformas necesarias y cierra esa ventana. Luego selecciona **Google Chrome - Perfil QA** en el Bot de verificaciones y ejecuta el flujo. Las cookies se guardan en `storage/browser_profiles/chrome-qa`, que está excluida de Git.

No completes todavía las variables de CRM o Strapi con credenciales reales; esos módulos pertenecen a fases posteriores.

## Ejecución

### Opción web

```powershell
npm run web
```

Después abre `http://127.0.0.1:8000`. Esta primera fase web se ejecuta en la misma computadora para conservar el acceso a Chromium, los archivos locales, Ollama y las sesiones de QA. Electron continúa disponible mientras se completa la migración.

### Opción desktop: Electron + FastAPI

```powershell
npm run dev
```

El proceso principal de Electron intentará arrancar FastAPI en `http://127.0.0.1:8000` y abrirá `frontend/index.html`.

### Ejecutar FastAPI por separado

Es útil para revisar la API o depurar el backend:

```powershell
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

La documentación interactiva queda disponible en `http://127.0.0.1:8000/docs`.

## Endpoints de la Fase 1

| Método | Endpoint | Uso |
| --- | --- | --- |
| GET | `/api/health` | Comprueba que FastAPI está disponible. |
| GET | `/api/dashboard/summary` | Métricas del día y última ejecución. |
| GET | `/api/executions?limit=20` | Historial reciente. |
| POST | `/api/bots/run` | Ejecuta un flujo web con Playwright y guarda sus evidencias. |
| POST | `/api/bots/recorder/start` | Abre el navegador visible para grabar interacciones. |
| GET | `/api/bots/recorder/{id}/events` | Consulta clicks y campos capturados. |
| POST | `/api/bots/recorder/{id}/stop` | Cierra la grabación y devuelve los pasos. |

## Proveedores de IA

Las integraciones de Ollama Cloud, Groq y Gemini viven en `backend/app/services/ai_service.py`. Sus claves se configuran únicamente en `.env`; el renderer solo puede consultar el estado booleano mediante `GET /api/ai/providers`.

Para las automatizaciones futuras se dispone de `POST /api/ai/generate` con `provider`, `prompt`, `system_instruction` opcional y `model` opcional. La respuesta tiene el mismo formato para los tres proveedores.

Para activar Ollama local:

1. Instala Ollama y descarga el modelo definido en `OLLAMA_LOCAL_MODEL` (por defecto `gpt-oss:20b`).
2. Confirma que el servidor local esté disponible en `OLLAMA_LOCAL_BASE_URL` (por defecto `http://127.0.0.1:11434/api`).
3. No necesitas una clave para el servidor local.

Las respuestas directas de `/api/ai/generate` incluyen `usage` y `rate_limits` cuando el proveedor los informa.

## Tests

```powershell
python -m pytest backend/tests -q
```

Los tests usan archivos SQLite temporales y no modifican la base de datos local.

## Estructura importante

```text
frontend/                 Interfaz Electron y renderer.
frontend/src/renderer/bot-module.js Constructor y controles del Bot de verificaciones.
backend/app/automations/generic_bot/runner.py Ejecutor de pasos web con Playwright.
storage/browser_profiles/chrome-qa Perfil persistente usado por Google Chrome para QA.
backend/app/automations/generic_bot/recorder.py Grabador visual de clicks y campos.
backend/app/api/          Rutas HTTP.
backend/app/config/       Variables y rutas centralizadas.
backend/app/database/     Conexión y consultas SQLite.
backend/app/services/     Reglas del dashboard y logging.
backend/tests/            Pruebas del backend.
storage/logs/             Logs organizados por fecha.
storage/reports/          Reportes futuros.
storage/screenshots/      Evidencias futuras.
storage/visual_comparisons/ Comparaciones futuras.
docs/                     Decisiones de arquitectura.
```

## Prueba manual de la Fase 1

1. Ejecuta `npm run dev`.
2. Comprueba que la ventana muestra el dashboard y el indicador **Backend conectado**.
3. Confirma que las tarjetas comienzan en cero y que aparece el estado de SQLite.
4. Navega entre Formularios, Monitoreo visual, Excel vs Web, Historial y Configuración.
5. Pulsa el botón de actualizar y confirma que el timestamp cambia.
6. Abre `/docs` en un navegador si quieres inspeccionar el contrato de FastAPI.
7. Revisa `storage/logs/YYYY-MM-DD/backend.log` para comprobar el log de inicio y las consultas.

## Configuración y seguridad

`.env.example` documenta las variables esperadas. `.env` está ignorado por Git y nunca debe subirse. El token de Strapi y la contraseña del CRM nunca se expondrán al frontend: FastAPI será el único componente que hablará con esos servicios.

### Carga de descripciones PDP desde Google Drive

Para leer documentos PDP privados, el backend necesita OAuth de Google Drive con permiso de solo lectura. En Google Cloud habilita Google Drive API, crea un cliente OAuth de tipo **Desktop app** y descarga su JSON. Ejecuta `python scripts/configure_google_drive_oauth.py "RUTA\AL\CLIENTE_OAUTH.json"` y autoriza la cuenta que tiene acceso a los documentos. El asistente guarda `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET` y `GOOGLE_DRIVE_REFRESH_TOKEN` directamente en `.env`; después reinicia FastAPI. No envíes estas credenciales por chat ni las subas a Git.

El backend renueva el access token automáticamente y solo exporta los Google Docs a DOCX para extraer la descripción. Solicita el alcance `https://www.googleapis.com/auth/drive.readonly`; no requiere permiso para editar Drive. Si el proyecto OAuth es externo y sigue en modo de pruebas, Google puede hacer expirar el refresh token a los 7 días para alcances de Drive; para uso continuo configura la audiencia interna de Workspace si aplica o completa la publicación/verificación correspondiente.

La búsqueda de productos en Strapi elimina el prefijo académico inicial (`Licenciatura en`, `Maestría en` o `Doctorado en`) para encontrar el nombre base de la carrera. Los reportes mantienen el nombre completo que viene en el Excel y las actualizaciones se hacen sobre el registro encontrado, incluso si está en estado `draft`.

## Cómo añadir una automatización después

Cada automatización tendrá su propio módulo dentro de `backend/app/automations/`, sus esquemas y su servicio. El servicio guardará una fila en `executions` y la interfaz podrá consumir su resultado mediante un endpoint específico. La Fase 2 comenzará con `forms/`; la Fase 3 con `visual_monitoring/`; la Fase 4 con `excel_strapi/`.

## Problemas frecuentes

- **Backend desconectado:** instala `backend/requirements.txt`, verifica que Python está en el PATH y revisa la consola de Electron.
- **El puerto 8000 está ocupado:** inicia FastAPI en otro puerto y ajusta `API_PORT` y `API_URL` de forma coherente; en una mejora posterior se automatizará esta negociación.
- **La ventana no abre:** ejecuta `npm install` y comprueba la versión de Node.
- **No aparecen logs:** verifica que el proceso tenga permisos de escritura en `storage/`.

## Bot UTEL + InConcert

El modulo **Bot de verificaciones** ejecuta ahora un flujo especializado de QA:

UTEL -> modalidad/nivel/programa -> formulario BLC -> envio del lead -> InConcert -> Contactos -> busqueda por email -> Gestionar -> Actividad -> Conversion.

En envíos reales, el bot valida primero el acceso a cada CRM regional, los campos y el país; después escucha la respuesta de `POST /api/forms` y espera hasta 65 segundos por portales lentos. Desde el instante del clic, cualquier toast de error o ausencia de confirmación queda **pendiente de conciliación**: el formulario no se vuelve a enviar y el resultado final se decide buscando el mismo email en InConcert y, como respaldo, en el Balanceador. El Excel conserva un checkpoint preventivo, el aviso de UTEL, la evidencia y el enlace del lead confirmado. El botón de reintento automático solo incluye fallos confirmados antes del clic; al detener un lote, termina y concilia la fila activa antes de cerrarse.

Los envíos reales usan por defecto un banco privado de números activos y expresamente autorizados por país. Configura `UTEL_TEST_PHONES_JSON` en `.env`; el backend valida país y formato, elimina el código internacional porque el formulario ya lo agrega y reserva un número distinto por fila. Si falta un país, el número pertenece a otra región o el banco no alcanza, el proceso se detiene antes del primer envío. Para formularios de prueba que acepten teléfonos inventados, activa explícitamente `UTEL_ALLOW_SYNTHETIC_REAL_PHONES=true`: genera números sintéticos con plan nacional válido, sin usar números de terceros, pero no garantiza que la línea exista o esté activa. Si UTEL devuelve explícitamente “Error al enviar / Contacta a soporte”, el bot prueba hasta tres teléfonos distintos; si los tres son rechazados, deja la fila marcada para ejecución manual. Los estados “Envío no confirmado” siguen conciliándose en CRM sin reenviar.

Para las filas de **Doctorado** cuyo formulario está en **tarjeta**, los países USA, Bolivia, Chile, Paraguay, República Dominicana, Guatemala, Panamá, El Salvador y Argentina usan un catálogo validado de enlaces PDP directos. El bot rota los programas disponibles por país y abre directamente la página seleccionada, evitando el clic desde el listado que puede activar el bloqueo de acceso. Los demás niveles, países y ubicaciones de formulario conservan su navegación anterior.

Para usarlo:

1. Configura en `.env` las credenciales `INCONCERT_USERNAME` e `INCONCERT_PASSWORD`. Tambien se aceptan `CRM_USERNAME` y `CRM_PASSWORD`.
2. Abre **Bot de verificaciones** en la app.
3. Completa pais, URL de UTEL, URL de InConcert, modalidad, nivel, tipo de formulario y datos del lead de prueba.
4. Usa **Programa opcional** solo si quieres seleccionar un programa concreto; si queda vacio, el bot intenta elegir el primer programa visible.
5. Pulsa **Validar** y luego **Ejecutar flujo**.

FastAPI crea la ejecucion en segundo plano con `POST /api/bots/utel-inconcert/run`, y la interfaz consulta el estado con `GET /api/bots/utel-inconcert/runs/{job_id}`. El flujo guarda screenshots en `storage/screenshots/utel_inconcert/` al abrir UTEL, antes y despues del envio, despues del login, al encontrar el lead, al abrir Gestionar, al encontrar Conversion y cuando ocurre un error. El modo debug visible desactiva headless y deja el navegador abierto al final para revision manual.

## Próxima fase

Antes de avanzar hay que verificar esta base con los tests y la prueba manual. El Bot de verificaciones ya tiene el primer ejecutor; el siguiente trabajo será añadir acciones como hover, teclas, selección de opciones, descarga de archivos y manejo de sesiones, sin asumir selectores, CRM o URLs reales.

## Grabar pasos visualmente

1. Selecciona **Google Chrome - Perfil QA** y escribe la URL inicial.
2. Pulsa **Grabar pasos**.
3. Interactúa con la ventana de Chrome que se abre; los elementos se resaltan al pasar el cursor.
4. Haz click en botones o enlaces y selecciona los campos de formulario que el bot deberá rellenar. Los pasos aparecerán automáticamente en la aplicación.
5. Pulsa **Detener grabación** para convertir la interacción en pasos editables.
6. En cada paso **Rellenar campo**, escribe dentro de la caja **Valor a enviar** el dato que el bot deberá introducir.
7. Revisa el flujo, guarda la configuración y pulsa **Ejecutar bot**.

### Ejecución en segundo plano

El Bot ejecuta los pasos con Playwright en modo headless por defecto. Al pulsar **Ejecutar bot**, FastAPI crea una ejecución en segundo plano y devuelve el control inmediatamente; la interfaz consulta su estado mediante `GET /api/bots/runs/{job_id}`. Puedes cambiar de módulo o continuar trabajando mientras el flujo navega, rellena campos, valida resultados y guarda sus evidencias.

La opción **Abrir navegador para revisión manual** desactiva el modo headless únicamente cuando necesites observar la sesión.

El grabador no conserva el texto que escribes en el navegador: guarda únicamente el localizador del campo. El valor se define después dentro de Electron, y los campos de contraseña no se capturan. También registra el scroll como una posición vertical y reemplaza los movimientos consecutivos por un único paso. Evita guardar tokens o datos sensibles en la configuración.
