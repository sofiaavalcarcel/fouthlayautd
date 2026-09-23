# Instalación y tecnologías

La interfaz usa HTML, CSS y JavaScript con módulos ES nativos; no necesita React ni un compilador frontend. Consume la API mediante fetch. FastAPI sirve la interfaz en modo web. Electron 36 es la envoltura de escritorio y Node.js ejecuta los lanzadores.

El backend utiliza Python, FastAPI, Uvicorn, Pydantic Settings, HTTPX, cloudscraper y python-multipart. SQLite viene incluido con Python y no necesita un servidor separado. Playwright controla los navegadores, openpyxl procesa Excel y phonenumbers valida teléfonos. pytest ejecuta pruebas. Las versiones admitidas están en backend/requirements.txt y package.json; npm ci respeta package-lock.json.

## Nuevo equipo Windows

1. Copiar o clonar el proyecto sin .venv, node_modules, .env ni perfiles privados de storage.
2. Abrir Iniciar.cmd. No necesita Node ni Python para mostrar el asistente.
3. Leer la lista de instalaciones y escribir SI para autorizarlas. Cancelar no instala nada y no inicia la app.
4. El asistente instala los runtimes faltantes mediante winget, crea .venv, instala los requisitos Python y Chromium, y comprueba dependencias. Electron se requiere únicamente al iniciar el modo escritorio con npm start. Puede aparecer el aviso de permisos de Windows. Si winget falta, muestra instrucciones y se detiene.
5. Configurar las credenciales propias en .env e iniciar sesión en los CRM cuando corresponda. Las claves, sesiones y permisos externos no se pueden crear instalando librerías.
6. Cuando la consola indique que el servidor está listo, abrir http://127.0.0.1:8000.

Cada arranque con Iniciar.cmd, npm run web o npm start comprueba las dependencias instaladas, sus versiones admitidas y Chromium. El modo web no exige Electron. Un registro ausente, antiguo o con distinta firma no provoca una reinstalación si las dependencias funcionan. Sólo solicita autorización cuando falla la comprobación de un requisito. Ejecutar Uvicorn directamente omite este asistente.

Diagnóstico sin instalaciones: powershell -NoProfile -File scripts/setup-windows.ps1 -CheckOnly. Código 0: listo; 2: preparación pendiente; 1: error.

Ollama local es opcional: requiere instalar Ollama y descargar un modelo adecuado al hardware. Los proveedores remotos necesitan claves y conexión. El asistente no descarga modelos grandes ni configura cuentas automáticamente. No instala Brave ni navegadores adicionales opcionales.

## Otros sistemas y dispositivos

### Recursos y teléfonos en un equipo nuevo

Iniciar.cmd comprueba el catálogo `backend/data/Programas_UTEL_Todos_los_Paises.xlsx`, los catálogos auxiliares de los módulos y las listas de URLs incluidas en el proyecto. Es necesario compartir la carpeta completa o el ZIP del repositorio: el lanzador solo no contiene estos archivos. Si falta un recurso, informa su ruta antes del arranque.

El equipo original no tiene un banco privado cargado: utiliza generación local de teléfonos sintéticos. Si el nuevo equipo tiene el banco vacío y la generación desactivada, el asistente solicita autorización una vez para habilitarla y guarda `UTEL_ALLOW_SYNTHETIC_REAL_PHONES=true` en `.env`. También repara este caso en instalaciones anteriores y conserva el resto de la configuración. Los teléfonos tienen formato nacional validado, pero no garantizan una línea activa ni que el número no esté asignado.

Si ya existe un banco en `UTEL_TEST_PHONES_JSON`, se conserva y debe cubrir los países de las pruebas. Las credenciales, claves de API y sesiones de navegador no se distribuyen; se configuran por equipo. Ollama local y sus modelos siguen siendo opcionales y no están incluidos en este asistente. La generación local de teléfonos funciona sin una clave de IA.

El asistente incluido es para Windows con winget. No se ha certificado la automatización completa en macOS o Linux: existen rutas y funciones específicas de Windows. Estos sistemas requieren preparar Python, Node y los navegadores manualmente y validar cada módulo; en Linux Playwright puede necesitar bibliotecas del sistema.

Un móvil o una tableta puede actuar como cliente de una instalación web accesible, pero no ejecutar este instalador ni los bots locales. El navegador no puede instalar Python, Electron o programas del sistema. Publicar la app para acceso remoto requiere configurar alojamiento y autenticación antes de exponer el backend; este cambio no la publica ni cambia sus permisos de red.

## Alcance de verificación

El 7 de septiembre de 2026 se ejecutó Iniciar.cmd en una copia temporal sin .venv, node_modules ni .env. Se autorizó la instalación, se instalaron las librerías Python y Electron, se comprobó Chromium y se inició la app en el puerto de prueba 8017. La interfaz, /api/health y /api/dashboard/summary respondieron HTTP 200; Chromium cargó el dashboard sin errores JavaScript. El diagnóstico posterior devolvió código 0 sin volver a solicitar instalación.

La prueba detectó y corrigió el uso de Get-FileHash no disponible en ese arranque, una extracción incompleta de Electron y una comprobación de Playwright que cerraba su conexión demasiado pronto. El asistente ahora comprueba la apertura real de Chromium y la presencia del ejecutable de Electron antes de guardar la preparación.

Python, Node.js y Chrome ya estaban instalados en el computador anfitrión; Chromium estaba en la caché del usuario. Sus instalaciones iniciales mediante winget y la descarga de Chromium en un Windows completamente vacío aún requieren una máquina virtual o un equipo nuevo. npm también reportó dos vulnerabilidades de severidad alta en el árbol existente; no se actualizaron versiones como parte de esta prueba del instalador.
