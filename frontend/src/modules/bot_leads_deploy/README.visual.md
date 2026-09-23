# Presentación de Bot Leads Deploy

Tema visual basado en la referencia de Bot de nuevos productos. Configuración y
diagnóstico a la izquierda; resultados, acciones, telemetría y detalle a la derecha.

## Archivos

- `visual.css`: tema independiente, iconos SVG locales y diseño responsive.
- `visual.js`: montaje, textos de presentación, calendario reflejado y guía.
- `../../renderer/gooey-buttons.js`: cinco líneas para cargar esta presentación
  mediante import dinámico con manejo de error, sin bloquear el inicio de los bots.
- `../../../tests/leads-deploy-visual.test.mjs`: pruebas de contratos y aislamiento.

No se importa el tema de Nuevos productos. Sus archivos no se modifican.
Las reglas internas comienzan con `#view-leads-deploy`; las del marco compartido
usan `body:has(#view-leads-deploy.active)` y dejan de aplicarse al cambiar de vista.
El calendario añadido tiene su propia clase `ldv-header-date`.

## Contratos conservados

No cambia `renderer/leads-deploy-module.js`, el backend, la configuración, los
validadores, la lectura de Excel, los reintentos, los envíos ni las consultas CRM.
El país, nivel, modalidad y formulario siguen resolviéndose como antes; no se
revela el selector de país ni se activa Dry run para imitar la captura.

Todos los controles conservan su nodo, ID, valor, listener y atributos
`hidden`/`disabled`. Los mensajes, resultados y enlaces de descarga dinámicos
permanecen a cargo del controlador original. Los textos de estado no se sustituyen.
La tarjeta hero redundante se oculta y el MISMO botón de guía se reubica dentro de
Opciones avanzadas, sin clonarlo ni volver a asociarle eventos.

`initializeLeadsDeployVisuals()` es idempotente. Su resultado ofrece `destroy()`
para retirar calendario/estilos propios, desconectar observadores y restaurar la
guía y los textos. Solo se observa el montaje de la vista y la fecha existente;
no hay solicitudes de red, temporizadores, lecturas de configuración ni escritura
en almacenamiento desde esta capa de presentación.

## Verificación

Desde la raíz del proyecto:

```sh
node --test frontend/tests/leads-deploy-visual.test.mjs
```

Se comprobó el aspecto en Chromium con una página aislada que reproduce la
estructura de la vista; no es una ejecución completa de la aplicación ni una
prueba de envío. Se verificaron montaje repetido, desmontaje, identidad y estado
de los controles, guía, opciones avanzadas, mapeo, botones de lote, mensajes largos
y ausencia de desbordamiento horizontal entre 320 y 1920 px.

A 1020 px o menos los paneles se apilan; a 700 px el menú pasa arriba. No se ocultan
acciones operativas para encajar en una captura. El país sigue viniendo de cada
fila del Excel, por eso la tarjeta de configuración no replica ese selector de
Nuevos productos. Los datos de prueba de las capturas no están fijados en el tema.
