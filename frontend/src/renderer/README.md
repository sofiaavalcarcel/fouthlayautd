# Renderer: interfaz de usuario

Los archivos de esta carpeta controlan la interfaz que se ejecuta en el navegador o en la ventana de Electron.

| Archivo | Sección de la aplicación |
| --- | --- |
| `app.js` | Estado global mínimo, navegación, dashboard e historial. |
| `bot-module.js` | Constructor, validación y ejecución del bot de verificaciones. |
| `weekly-auto-module.js` | Adaptador hacia los submódulos organizados en `src/modules/weekly_auto/`. |
| `styles.css` | Diseño visual compartido por todas las vistas. |

Cada módulo recibe por parámetro las funciones API que necesita. Así se evita acoplar la lógica visual con las URL de backend.
